from atproto import Client
from dotenv import load_dotenv
import os
import random
import re
import google.generativeai as genai
import logging
from typing import List, Dict, Any
import email.utils
from datetime import datetime, timezone, timedelta
import json
import asyncio
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
import base64
from database import Database  # Add at top of file


class BlueskyBot:
    def __init__(
        self,
        handle: str,
        password: str = "",
        topics: List[str] = [],
        check_interval: int = 60,
        user_email: str = "",
        auto_post: bool = False,
    ):
        """Initialize Bluesky Bot with Gmail monitoring"""
        # Load environment variables
        load_dotenv()

        # Initialize Bluesky client
        self.client = Client()
        self.BLUESKY_USERNAME = handle
        self.BLUESKY_PASSWORD = password
        self.topics = topics
        self.check_interval = check_interval

        # Gmail API setup
        self.GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
        self.gmail_service = None

        self.start_time = datetime.now(timezone.utc)

        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler("bluesky_bot.log"),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger(__name__)

        # Initialize Gemini model
        self.model = self.setup_gemini()

        # Initialize database
        self.db = Database()

        self.user_email = user_email
        self.user_topics = topics
        self.auto_post = auto_post

    async def initialize(self):
        """Async initialization"""
        await self.db.connect_db()
        return self

    def authenticate_gmail(self):
        """Authenticate with Gmail API using OAuth 2.0"""
        try:
            creds = None
            # Check if token.pickle exists with stored credentials
            if os.path.exists("token.pickle"):
                with open("token.pickle", "rb") as token:
                    creds = pickle.load(token)

            # If credentials are invalid or don't exist, authenticate
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        "credentials.json", self.GMAIL_SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                # Save credentials for future use
                with open("token.pickle", "wb") as token:
                    pickle.dump(creds, token)

            self.gmail_service = build("gmail", "v1", credentials=creds)
            self.logger.info("Successfully authenticated with Gmail")

        except Exception as e:
            self.logger.error(f"Error authenticating with Gmail: {e}")
            raise Exception("Gmail authentication failed") from e

    def setup_gemini(self):
        """Setup Gemini model"""
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        genai.configure(api_key=GEMINI_API_KEY)
        return genai.GenerativeModel("gemini-1.5-flash")

    async def login_to_bluesky(self):
        """Login to Bluesky"""
        try:
            self.client.login(self.BLUESKY_USERNAME, self.BLUESKY_PASSWORD)
            return True
        except Exception as e:
            self.logger.error(f"Failed to login to Bluesky: {e}")
            return False

    def process_email(self, message_id: str) -> Dict[str, Any]:
        """Process a single email message"""
        try:
            if not self.gmail_service:
                raise Exception("Gmail service not initialized")

            msg = (
                self.gmail_service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            headers = msg["payload"]["headers"]
            subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                "No Subject",
            )
            sender = next(
                (h["value"] for h in headers if h["name"].lower() == "from"),
                "Unknown Sender",
            )
            date = next(
                (h["value"] for h in headers if h["name"].lower() == "date"), None
            )

            # Get message body
            if "parts" in msg["payload"]:
                parts = msg["payload"]["parts"]
                content = self._get_message_body(parts)
            else:
                content = base64.urlsafe_b64decode(
                    msg["payload"]["body"].get("data", "")
                ).decode("utf-8")

            return {
                "id": message_id,
                "subject": subject,
                "sender": sender,
                "date": date,
                "content": content,
            }
        except Exception as e:
            self.logger.error(f"Error processing email {message_id}: {e}")
            return {}

    def _get_message_body(self, parts: List[Dict]) -> str:
        """Extract message body from email parts"""
        body = ""
        for part in parts:
            if part["mimeType"] == "text/plain":
                if "data" in part["body"]:
                    body += base64.urlsafe_b64decode(part["body"]["data"]).decode(
                        "utf-8"
                    )
            elif "parts" in part:
                body += self._get_message_body(part["parts"])
        return body

    async def analyze_newsletter(self, email_data: Dict[str, Any]) -> bool:
        """Analyze newsletter and process relevant topics"""
        try:
            if not self.user_email:
                self.logger.error("No user email configured for bot")
                return False

            self.logger.info(f"Analyzing newsletter for user {self.user_email}")
            self.logger.info(f"Auto-post setting: {self.auto_post}")

            analysis = self.analyze_email_type(self.model, email_data, self.user_topics)

            if (
                not analysis
                or analysis["type"] != "NEWSLETTER"
                or not analysis["is_relevant"]
            ):
                self.logger.info(
                    "Newsletter analysis: not relevant or not a newsletter"
                )
                return False

            for topic in analysis["matching_topics"]:
                self.logger.info(f"Processing topic: {topic}")
                tweets = await self.create_topic_thread(topic, email_data["content"])
                if tweets:
                    if self.auto_post:
                        self.logger.info(
                            "Auto-post is enabled, attempting to post to Bluesky"
                        )
                        success = await self.post_thread_to_bluesky(tweets)
                        if success:
                            self.logger.info(
                                f"Successfully auto-posted thread for topic {topic}"
                            )
                        else:
                            self.logger.error(
                                f"Failed to auto-post thread for topic {topic}"
                            )
                    else:
                        self.logger.info("Auto-post is disabled, saving as draft")
                        await self.db.save_draft_thread(
                            user_email=self.user_email, topic=topic, tweets=tweets
                        )
                        self.logger.info(f"Saved draft for topic {topic}")

            return True
        except Exception as e:
            self.logger.error(
                f"Error analyzing newsletter for user {self.user_email}: {e}"
            )
            return False

    def is_new_email(self, date_str: str) -> bool:
        """Check if email is newer than bot start time"""
        try:
            # Parse email date string to datetime
            email_date_tuple = email.utils.parsedate_tz(date_str)
            if email_date_tuple is None:
                return False

            email_date = datetime.fromtimestamp(
                email.utils.mktime_tz(email_date_tuple), timezone.utc
            )

            # Compare with bot start time and ensure it's not too old
            max_age = timedelta(days=1)  # Only process emails up to 1 day old
            now = datetime.now(timezone.utc)

            return email_date > self.start_time and (now - email_date) <= max_age

        except Exception as e:
            self.logger.error(f"Error parsing date {date_str}: {e}")
            return False

    async def post_thread_to_bluesky(self, posts: List[str]) -> bool:
        """Post a thread of messages to Bluesky"""
        try:
            previous_post = None
            root_post = None

            for i, post in enumerate(posts):
                try:
                    if i == 0:
                        # First post in thread
                        response = self.client.send_post(text=post)
                        root_post = response
                        previous_post = response
                        self.logger.info(f"✅ Posted thread starter: {post[:50]}...")
                    else:
                        if root_post is None or previous_post is None:
                            self.logger.error(
                                "Root or previous post not found, skipping reply"
                            )
                            continue
                        # Reply to previous post with proper parent and root references
                        response = self.client.send_post(
                            text=post,
                            reply_to={  # type: ignore
                                "root": {"uri": root_post.uri, "cid": root_post.cid},
                                "parent": {
                                    "uri": previous_post.uri,
                                    "cid": previous_post.cid,
                                },
                            },
                        )
                        previous_post = response
                        self.logger.info(f"✅ Posted thread part {i+1}: {post[:50]}...")

                    # Wait briefly between posts
                    await asyncio.sleep(2)

                except Exception as e:
                    self.logger.error(f"Error posting part {i} of thread: {e}")
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Error posting thread: {e}")
            return False

    async def monitor_gmail(self):
        """Monitor Gmail for new newsletters"""
        self.logger.info(f"Starting Gmail monitor for user {self.user_email}")

        if not self.gmail_service:
            raise Exception("Gmail service not initialized")

        while True:
            try:
                self.logger.info(f"Checking emails for user {self.user_email}")

                # Clean up old processed messages periodically
                await self.db.cleanup_old_processed_messages()

                results = (
                    self.gmail_service.users()
                    .messages()
                    .list(userId="me", q="is:unread newer_than:1h", labelIds=["INBOX"])
                    .execute()
                )

                messages = results.get("messages", [])

                for message in messages:
                    # Check if message was already processed using database
                    is_processed = await self.db.is_message_processed(
                        self.user_email, message["id"]
                    )

                    if not is_processed:
                        email_data = self.process_email(message["id"])

                        if email_data and email_data.get("date"):
                            if self.is_new_email(email_data["date"]):
                                self.logger.info(
                                    f"Processing new email for user {self.user_email}: {email_data['subject']}"
                                )
                                success = await self.analyze_newsletter(email_data)

                                if success:
                                    # Store processed message ID in database
                                    await self.db.add_processed_message(
                                        self.user_email, message["id"]
                                    )
                                    # Mark as read in Gmail
                                    self.gmail_service.users().messages().modify(
                                        userId="me",
                                        id=message["id"],
                                        body={"removeLabelIds": ["UNREAD"]},
                                    ).execute()

                await asyncio.sleep(self.check_interval)

            except Exception as e:
                self.logger.error(
                    f"Error in Gmail monitor for user {self.user_email}: {e}"
                )
                await asyncio.sleep(10)

    async def run(self):
        """Main bot loop"""
        print("\n=== Starting Bluesky Newsletter Bot ===")

        # Authenticate with both services
        self.authenticate_gmail()
        if not await self.login_to_bluesky():
            return

        try:
            # Start monitoring Gmail
            await self.monitor_gmail()
        except KeyboardInterrupt:
            print("\nBot stopped by user")
        except Exception as e:
            print(f"Error in main loop: {e}")
            await asyncio.sleep(10)

    def analyze_email_type(self, model, email_data, user_topics: List[str]):
        """Analyze if an email is a newsletter and filter topics based on user preferences"""
        prompt = f"""
        Analyze this email and determine if it's a newsletter. Consider these aspects:
        - Subject: {email_data['subject']}
        - Sender: {email_data['sender']}
        - Content preview: {email_data['content']}
        
        User's preferred topics: {', '.join(user_topics)}
        
        Respond with 'NEWSLETTER' or 'NOT_NEWSLETTER' followed by a brief reason why. And if it's a newsletter, create a list of the topics discussed.
        The topics should be the main topics discussed in the email.

        If only a single topic was discussed in the newsletter then place only single topic in the list, don't break it down. 
        First determine if this is a newsletter. If it is, identify all topics discussed and filter them based on user's preferences.
        Only include topics that match or are closely related to the user's preferred topics.
        
        Output in the following format:
        ```json
        {{
            "type": "NEWSLETTER" | "NOT_NEWSLETTER",
            "reason": "reason why it's a newsletter or not",
            "all_topics": ["break newsletter into a list of topics make sure to break it down into the main topics without repeating the same topic"],
            "reason_all_topics": "reason why you broke it down into the main topics",
            "matching_topics": ["list of topics from all_topics that match user preferences"],
            "reason_matching_topics": "reason why matching_topics are relevant to user preferences",
            "is_relevant": true | false
        }}
        ```
        The 'is_relevant' field should be true if there's at least one matching topic.
        """

        try:
            response = model.generate_content(prompt)
            analysis = re.search("```json(.*)```", response.text, re.DOTALL)
            print(f"Analysis: {analysis}")
            if analysis:
                result = json.loads(analysis.group(1))

                # Log analysis results
                print(f"\n=== Email Analysis Results ===")
                print(f"Type: {result['type']}")
                print(f"Reason: {result['reason']}")
                print(f"All Topics: {', '.join(result['all_topics'])}")
                print(f"Matching Topics: {', '.join(result['matching_topics'])}")
                print(f"Reason Matching Topics: {result['reason_matching_topics']}")
                print(f"Is Relevant: {result['is_relevant']}")

                return result
            else:
                return {
                    "type": "ERROR",
                    "reason": "Could not parse JSON",
                    "all_topics": [],
                    "matching_topics": [],
                    "is_relevant": False,
                }
        except Exception as e:
            print(f"Error analyzing email: {e}")
            return {
                "type": "ERROR",
                "reason": str(e),
                "all_topics": [],
                "matching_topics": [],
                "is_relevant": False,
            }

    async def create_topic_thread(self, topic: str, content: str) -> List[str]:
        """Create a thread focusing on a specific topic from the newsletter content"""
        try:
            # Get user's writing style
            user = await self.db.get_user(self.user_email)
            if not user:
                raise Exception("User not found")

            writing_style = user.get("writing_style", {})

            # Default styles if not set
            DEFAULT_THINKING_STYLE = """
            Analytical and Research-Oriented: The writer examines topics critically, using data, historical context, and evidence to build arguments.
            Cause-and-Effect Reasoning: They explore how specific actions or methods lead to broader consequences.
            Skeptical and Insightful: They question motivations and outcomes, highlighting both the implications and the hidden strategies behind processes or phenomena.
            """

            DEFAULT_NARRATIVE_STYLE = """
            Engaging and Accessible: The writer uses conversational language to appeal to a broad audience.
            Descriptive and Vivid: They paint mental pictures with detailed imagery and anecdotes to make their points relatable and impactful.
            Emotionally Provocative: Language is charged to evoke curiosity or concern, making the topic feel urgent and relevant.
            Balanced Pacing: Quick transitions and comparisons maintain attention, mirroring the dynamic nature of the subject.
            Uses conversational language to maintain accessibility and engagement
            """

            thinking_style = writing_style.get("thinking_style", DEFAULT_THINKING_STYLE)
            narrative_style = writing_style.get(
                "narrative_style", DEFAULT_NARRATIVE_STYLE
            )

            chat = self.model.start_chat(history=[])
            prompt = f"""
            Create a engaging Twitter thread about: {topic}

            Context for the thread: {content}

            You are posting on behalf of human user. You are a human.
            You will be given his thinking style and narrative style.
            You should use this style to write the tweets.

            Use this thinking style:
            {thinking_style}

            Use this narrative style:
            {narrative_style}

            Requirements:
            - Each tweet MUST be under 300 characters (strict limit)
            - First tweet should hook readers
            - Use emojis sparingly (1-2 per tweet)
            - Do not use markdown or formatting
            - No URLs or placeholder links
            - Complete thoughts within each tweet
            - The post should not look like a spam post or a bot post
            - Only speak about the topic in the tweets
            - Narrate the tweets like a story
            - Separate tweets with [TWEET]

            You should focus on being concise yet informative.
            """

            response = chat.send_message(prompt)
            posts = response.text.split("[TWEET]")

            # Clean and validate posts
            valid_posts = []
            for post in posts:
                clean_post = post.strip()
                if clean_post:
                    clean_post = re.sub(r"\*\*|\[|\]|\(\)|\{\}|#", "", clean_post)
                    if len(clean_post) <= 300:
                        valid_posts.append(clean_post)
                    else:
                        # Split long posts
                        while clean_post and len(clean_post) > 300:
                            split_index = clean_post.rfind(". ", 0, 297)
                            if split_index == -1:
                                split_index = 297
                            valid_posts.append(clean_post[:split_index] + "...")
                            clean_post = clean_post[split_index:].strip()
                        if clean_post:
                            valid_posts.append(clean_post)

            return valid_posts

        except Exception as e:
            self.logger.error(f"Error creating topic thread: {e}")
            return []


async def main():
    # Load environment variables
    load_dotenv()

    # Get credentials from environment variables
    bluesky_handle = os.getenv("BLUESKY_HANDLE")
    bluesky_password = os.getenv("BLUESKY_PASSWORD")

    if not bluesky_handle or not bluesky_password:
        print("Error: Missing Bluesky credentials in environment variables")
        return

    bot = BlueskyBot(bluesky_handle, bluesky_password)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
