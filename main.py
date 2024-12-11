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
from models import UserCreate, UserLogin, User
from database import db, Database
from bot_manager import bot_manager
from writing_analyzer import analyze_writing_style
import json

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
async def get_current_user_from_session(request: Request):
    if "user_email" not in request.session or request.session["user_email"] is None:
        return None
    return await db.get_user(request.session["user_email"])


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
async def signup_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    bluesky_handle: str = Form(...),
    bluesky_password: str = Form(...),
    topics: str = Form(...),
):
    try:
        # Check if user already exists
        existing_user = await db.get_user(email)
        if existing_user:
            return templates.TemplateResponse(
                "signup.html",
                {
                    "request": request,
                    "messages": [{"type": "error", "text": "Email already registered"}],
                },
            )

        # Process topics
        topic_list = [topic.strip() for topic in topics.split(",") if topic.strip()]

        # Create user document
        user = {
            "email": email,
            "password": Database.pwd_context.hash(password),
            "bluesky_handle": bluesky_handle,
            "bluesky_password": bluesky_password,
            "topics": topic_list,
            "is_active": True,
            "created_at": datetime.utcnow(),
        }

        # Insert into MongoDB
        await db.client.newsletter_bot.users.insert_one(user)

        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "messages": [{"type": "error", "text": str(e)}]},
        )


@app.get("/dashboard")
async def dashboard(request: Request):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")

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
async def post_draft(request: Request, draft_id: str):
    user = await get_current_user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")

    draft = await db.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    if draft["user_email"] != user["email"]:
        raise HTTPException(status_code=403)

    bot = bot_manager.bots.get(user["email"])
    if bot:
        success = await bot.post_thread_to_bluesky(draft["tweets"])
        if success:
            await db.delete_draft(draft_id)
            return {"status": "success"}

    return {"status": "error"}


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
