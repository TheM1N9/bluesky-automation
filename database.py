from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta
from passlib.context import CryptContext
import os
from dotenv import load_dotenv
from typing import List
from bson import ObjectId

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")


class Database:
    client: AsyncIOMotorClient = None
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    async def connect_db(self):
        self.client = AsyncIOMotorClient(MONGO_URL)

    async def close_db(self):
        if self.client:
            self.client.close()  # Remove await as it's not an async method

    async def create_user(self, user_data):
        user = {
            "email": user_data.email,
            "password": self.pwd_context.hash(user_data.password),
            "bluesky_handle": user_data.bluesky_handle,
            "bluesky_password": user_data.bluesky_password,  # Consider encrypting this
            "is_active": True,
            "created_at": datetime.utcnow(),
        }
        await self.client.newsletter_bot.users.insert_one(user)
        return user

    async def get_user(self, email: str):
        return await self.client.newsletter_bot.users.find_one({"email": email})

    def verify_password(self, plain_password, hashed_password):
        return self.pwd_context.verify(plain_password, hashed_password)

    async def save_draft_thread(self, user_email: str, topic: str, tweets: List[str]):
        """Save a draft thread to the database"""
        draft = {
            "user_email": user_email,
            "topic": topic,
            "tweets": tweets,
            "created_at": datetime.utcnow(),
        }
        await self.client.newsletter_bot.draft_threads.insert_one(draft)

    async def get_user_drafts(self, user_email: str):
        cursor = self.client.newsletter_bot.draft_threads.find(
            {"user_email": user_email}
        )
        drafts = await cursor.to_list(length=None)
        print(f"Found {len(drafts)} drafts for user {user_email}")
        return drafts

    async def update_draft(self, draft_id: str, tweets: List[str]):
        await self.client.newsletter_bot.draft_threads.update_one(
            {"_id": ObjectId(draft_id)}, {"$set": {"tweets": tweets}}
        )

    async def delete_draft(self, draft_id: str):
        await self.client.newsletter_bot.draft_threads.delete_one(
            {"_id": ObjectId(draft_id)}
        )

    async def get_draft(self, draft_id: str):
        """Get a single draft by ID"""
        return await self.client.newsletter_bot.draft_threads.find_one(
            {"_id": ObjectId(draft_id)}
        )

    async def add_processed_message(self, user_email: str, message_id: str):
        """Store a processed message ID for a user"""
        await self.client.newsletter_bot.processed_messages.insert_one(
            {
                "user_email": user_email,
                "message_id": message_id,
                "processed_at": datetime.utcnow(),
            }
        )

    async def is_message_processed(self, user_email: str, message_id: str) -> bool:
        """Check if a message has been processed for a user"""
        result = await self.client.newsletter_bot.processed_messages.find_one(
            {"user_email": user_email, "message_id": message_id}
        )
        return bool(result)

    async def cleanup_old_processed_messages(self, days_old: int = 30):
        """Clean up processed message records older than specified days"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        await self.client.newsletter_bot.processed_messages.delete_many(
            {"processed_at": {"$lt": cutoff_date}}
        )

    async def add_writing_sample(self, user_email: str, sample_type: str, content: str):
        """Add a writing sample for a user"""
        sample = {
            "type": sample_type,
            "content": content,
            "created_at": datetime.utcnow(),
        }
        await self.client.newsletter_bot.users.update_one(
            {"email": user_email}, {"$push": {"writing_samples": sample}}
        )

    async def get_writing_samples(self, user_email: str):
        """Get all writing samples for a user"""
        user = await self.get_user(user_email)
        if user:
            return user.get("writing_samples", [])
        else:
            return []

    async def update_writing_style(
        self, user_email: str, thinking_style: str, narrative_style: str
    ):
        """Update user's writing style analysis"""
        style = {
            "thinking_style": thinking_style,
            "narrative_style": narrative_style,
            "last_updated": datetime.utcnow(),
        }
        await self.client.newsletter_bot.users.update_one(
            {"email": user_email}, {"$set": {"writing_style": style}}
        )


db = Database()
