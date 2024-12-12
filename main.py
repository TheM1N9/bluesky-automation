from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Request,
    Form,
    Response,
    status,
    Body,
)
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional, List
import os
from models import UserCreate, UserLogin, User, UserOnboarding
from database import db, Database
from bot_manager import bot_manager
from writing_analyzer import analyze_writing_style
import json
from web_search import research_topic
from bot import BlueskyBot

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


@app.on_event("startup")
async def startup_db_client():
    await db.connect_db()


@app.on_event("shutdown")
async def shutdown_db_client():
    await db.close_db()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await db.get_user(email)
    if user is None:
        raise credentials_exception
    return user


@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await db.get_user(form_data.username)  # form_data.username is email
    if not user or not db.verify_password(form_data.password, user["password"]):
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["email"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/start-bot")
async def start_bot(request: Request):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")

    # Pass user topics and auto_post setting to the bot
    success = await bot_manager.start_bot(
        user_email=user["email"],
        bluesky_handle=user["bluesky_handle"],
        bluesky_password=user["bluesky_password"],
        topics=user.get("topics", []),
        auto_post=user.get("auto_post", False),  # Pass auto_post setting
    )

    if success:
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
            headers={
                "messages": json.dumps(
                    [{"type": "success", "text": "Bot started successfully"}]
                )
            },
        )
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "is_running": user["email"] in bot_manager.bots,
            "messages": [{"type": "error", "text": "Failed to start bot"}],
        },
    )


@app.post("/stop-bot")
async def stop_bot(request: Request):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")

    success = await bot_manager.stop_bot(user["email"])

    if success:
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
            headers={
                "messages": json.dumps(
                    [{"type": "success", "text": "Bot stopped successfully"}]
                )
            },
        )
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "is_running": user["email"] in bot_manager.bots,
            "messages": [{"type": "error", "text": "Bot not running"}],
        },
    )


@app.get("/bot-status")
async def get_bot_status(request: Request):
    user = await get_current_user_from_session(request)
    if not user:
        return {"is_running": False}

    is_running = user["email"] in bot_manager.bots
    return {"is_running": is_running}


# Helper function to get current user from session
async def get_current_user_from_session(request: Request) -> Optional[dict]:
    user_email = request.session.get("user_email")
    if user_email:
        user = await db.get_user(user_email)
        return user
    return None


@app.get("/")
async def home(request: Request):
    user = await get_current_user_from_session(request)
    return templates.TemplateResponse("index.html", {"request": request, "user": user})


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login_post(
    request: Request, username: str = Form(...), password: str = Form(...)
) -> Response:
    user = await db.get_user(username)
    if not user or not db.verify_password(password, user["password"]):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "messages": [{"type": "error", "text": "Invalid credentials"}],
            },
        )

    request.session["user_email"] = user["email"]
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/signup")
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@app.post("/signup")
async def signup(request: Request, user_data: UserCreate):
    # Check if user exists
    existing_user = await db.get_user(user_data.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create user with basic info
    user = await db.create_user(user_data)

    # Create session immediately after signup
    request.session["user_email"] = user_data.email

    # Create access token as backup
    access_token = create_access_token(data={"sub": user_data.email})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "redirect": "/onboarding",
    }


@app.post("/complete-onboarding")
async def complete_onboarding(
    request: Request,
    onboarding_data: UserOnboarding,
    current_user: dict = Depends(get_current_user_from_session),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

    # Complete onboarding
    await db.complete_onboarding(current_user["email"], onboarding_data)

    # Ensure session is set
    request.session["user_email"] = current_user["email"]

    return {"success": True, "redirect": "/dashboard"}


@app.get("/onboarding")
async def onboarding_page(
    request: Request, current_user: dict = Depends(get_current_user_from_session)
):
    if not current_user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("onboarding.html", {"request": request})


@app.get("/dashboard")
async def dashboard(request: Request):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")

    # Check if onboarding is completed
    if not user.get("onboarding_completed", False):
        return RedirectResponse(url="/onboarding")

    is_running = user["email"] in bot_manager.bots
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "user": user, "is_running": is_running}
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")


@app.post("/post-tweet")
async def post_tweet(request: Request, tweet_text: str = Form(...)):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")

    success = await bot_manager.post_tweet(user["email"], tweet_text)

    if success:
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "user": user,
                "is_running": user["email"] in bot_manager.bots,
                "messages": [{"type": "success", "text": "Tweet posted successfully!"}],
            },
        )
    else:
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "user": user,
                "is_running": user["email"] in bot_manager.bots,
                "messages": [
                    {
                        "type": "error",
                        "text": "Failed to post tweet. Make sure your bot is running.",
                    }
                ],
            },
        )


@app.post("/update-topics")
async def update_topics(request: Request, topics: str = Form(...)):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")

    try:
        # Process topics
        topic_list = [topic.strip() for topic in topics.split(",") if topic.strip()]

        # Update user's topics in database
        await db.client.newsletter_bot.users.update_one(
            {"email": user["email"]}, {"$set": {"topics": topic_list}}
        )

        return RedirectResponse(
            url="/dashboard",
            status_code=303,
            headers={
                "messages": json.dumps(
                    [{"type": "success", "text": "Topics updated successfully"}]
                )
            },
        )
    except Exception as e:
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "user": user,
                "is_running": user["email"] in bot_manager.bots,
                "messages": [{"type": "error", "text": str(e)}],
            },
        )


@app.get("/drafts")
async def view_drafts(request: Request):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")

    drafts = await db.get_user_drafts(user["email"])
    print(f"User email: {user['email']}")
    print(f"Drafts found: {drafts}")

    return templates.TemplateResponse(
        "drafts.html", {"request": request, "user": user, "drafts": drafts}
    )


@app.post("/update-draft/{draft_id}")
async def update_draft(draft_id: str, tweets: dict = Body(...)):
    try:
        await db.update_draft(draft_id, tweets["tweets"])
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/delete-draft/{draft_id}")
async def delete_draft(draft_id: str):
    try:
        await db.delete_draft(draft_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/post-draft/{draft_id}")
async def post_draft(draft_id: str, request: Request):
    try:
        user = await get_current_user_from_session(request)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Get draft content
        draft = await db.get_draft(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        # Get the bot instance for this user
        if user["email"] not in bot_manager.bots:
            raise HTTPException(status_code=400, detail="Bot not running")

        bot = bot_manager.bots[user["email"]]

        # Post the thread
        success = await bot.post_thread_to_bluesky(draft["tweets"])

        if success:
            # Delete the draft after successful posting
            await db.delete_draft(draft_id)
            return {"success": True}
        else:
            raise HTTPException(status_code=500, detail="Failed to post thread")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/update-settings")
async def update_settings(
    request: Request,
    settings: dict = Body(...),
):
    user = await get_current_user_from_session(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        # Update user settings in database
        await db.client.newsletter_bot.users.update_one(
            {"email": user["email"]},
            {"$set": {"auto_post": settings.get("auto_post", False)}},
        )

        # If auto_post is being disabled, make sure any existing bot instance
        # is updated
        if user["email"] in bot_manager.bots:
            bot_manager.bots[user["email"]].auto_post = settings.get("auto_post", False)

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/writing-style")
async def writing_style_page(request: Request):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")

    samples = await db.get_writing_samples(user["email"])

    return templates.TemplateResponse(
        "writing_style.html",
        {
            "request": request,
            "user": user,
            "samples": samples,
            "writing_style": user.get("writing_style"),
        },
    )


@app.post("/submit-writing-sample")
async def submit_writing_sample(
    request: Request, sample_type: str = Form(...), content: str = Form(...)
):
    user = await get_current_user_from_session(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Validate sample
    if sample_type == "ESSAY" and len(content.split()) < 300:
        raise HTTPException(status_code=400, detail="Essays must be at least 300 words")
    elif sample_type == "TWEET" and len(content) > 300:
        raise HTTPException(
            status_code=400, detail="Tweets must be under 300 characters"
        )

    # Add sample to database
    await db.add_writing_sample(user["email"], sample_type, content)

    # If we have all 10 samples and no writing style yet, analyze it
    samples = await db.get_writing_samples(user["email"])
    if len(samples) == 10 and not user.get("writing_style"):
        thinking_style, narrative_style = await analyze_writing_style(
            samples, db, user["email"]
        )

    return RedirectResponse(url="/writing-style", status_code=303)


@app.post("/reanalyze-writing-style")
async def reanalyze_writing_style(request: Request):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")

    samples = await db.get_writing_samples(user["email"])
    if len(samples) == 10:
        # Force reanalysis by passing None as current style
        thinking_style, narrative_style = await analyze_writing_style(
            samples, db, user["email"]
        )

    return RedirectResponse(url="/writing-style", status_code=303)


@app.post("/generate-thread")
async def generate_thread(request: Request, topic: str = Form(...)):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")

    try:
        # Research the topic
        research_content = await research_topic(topic)

        # Get user's bot instance or create temporary one
        if user["email"] in bot_manager.bots:
            bot = bot_manager.bots[user["email"]]
        else:
            bot = BlueskyBot(
                handle=user["bluesky_handle"],
                password=user["bluesky_password"],
                user_email=user["email"],
            )

        # Generate thread using the research content
        tweets = await bot.create_topic_thread(topic, research_content)

        if tweets:
            # Save as draft
            draft_id = await db.save_draft_thread(
                user_email=user["email"], topic=topic, tweets=tweets
            )

            return RedirectResponse(
                url="/drafts",
                status_code=303,
                headers={
                    "messages": json.dumps(
                        [
                            {
                                "type": "success",
                                "text": "Thread generated successfully! Check your drafts.",
                            }
                        ]
                    )
                },
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to generate thread")

    except Exception as e:
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "user": user,
                "is_running": user["email"] in bot_manager.bots,
                "messages": [
                    {"type": "error", "text": f"Error generating thread: {str(e)}"}
                ],
            },
        )


@app.get("/settings")
async def settings_page(request: Request):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "settings.html", {"request": request, "user": user}
    )


@app.post("/update-bluesky-credentials")
async def update_bluesky_credentials(
    request: Request,
    credentials: dict,
    current_user: dict = Depends(get_current_user_from_session),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    await db.update_bluesky_credentials(
        current_user["email"],
        credentials["bluesky_handle"],
        credentials["bluesky_password"],
    )
    return {"message": "Credentials updated successfully"}


@app.post("/update-password")
async def update_password(
    request: Request,
    password_data: dict,
    current_user: dict = Depends(get_current_user_from_session),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    await db.update_password(current_user["email"], password_data["password"])
    return {"message": "Password updated successfully"}


@app.post("/delete-account")
async def delete_account(
    request: Request, current_user: dict = Depends(get_current_user_from_session)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    await db.delete_user(current_user["email"])
    request.session.clear()
    return {"message": "Account deleted successfully"}
