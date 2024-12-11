from bot import BlueskyBot
import asyncio
from typing import Dict, List
import logging


class BotManager:
    def __init__(self):
        self.bots: Dict[str, BlueskyBot] = {}
        self.tasks: Dict[str, asyncio.Task] = {}

    async def start_bot(
        self,
        user_email: str,
        bluesky_handle: str,
        bluesky_password: str,
        topics: List[str] = [],
        auto_post: bool = False,
    ):
        if user_email in self.bots:
            return False

        # Create bot instance with user email and auto_post setting
        bot = BlueskyBot(
            handle=bluesky_handle,
            password=bluesky_password,
            topics=topics,
            user_email=user_email,
            auto_post=auto_post,
        )
        await bot.initialize()

        # Ensure bot is logged in to Bluesky
        if not await bot.login_to_bluesky():
            logging.error(f"Failed to login to Bluesky for user {user_email}")
            return False

        self.bots[user_email] = bot
        self.tasks[user_email] = asyncio.create_task(
            self._run_bot_with_error_handling(user_email, bot)
        )
        return True

    async def _run_bot_with_error_handling(self, user_email: str, bot: BlueskyBot):
        """Run bot with error handling to prevent one bot's failure affecting others"""
        try:
            await bot.run()
        except Exception as e:
            logging.error(f"Bot for user {user_email} crashed: {e}")
            # Cleanup
            if user_email in self.bots:
                await self.stop_bot(user_email)

    async def stop_bot(self, user_email: str):
        if user_email in self.tasks:
            self.tasks[user_email].cancel()
            if self.bots[user_email].db:
                await self.bots[user_email].db.close_db()
            del self.tasks[user_email]
            del self.bots[user_email]
            return True
        return False

    async def post_tweet(self, user_email: str, text: str) -> bool:
        """Post a tweet for a specific user's bot"""
        if user_email not in self.bots:
            return False

        try:
            bot = self.bots[user_email]
            if not bot.client.me:
                await bot.login_to_bluesky()

            response = bot.client.send_post(text=text)
            return bool(response)
        except Exception as e:
            logging.error(f"Error posting tweet for user {user_email}: {e}")
            return False


bot_manager = BotManager()
