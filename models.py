from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class UserBase(BaseModel):
    email: EmailStr
    auto_post: bool = False


class UserCreate(UserBase):
    password: str
    bluesky_handle: str
    bluesky_password: str


class WritingSample(BaseModel):
    type: str  # "ESSAY" or "TWEET"
    content: str
    created_at: datetime = datetime.utcnow()


class UserWritingStyle(BaseModel):
    thinking_style: str
    narrative_style: str
    last_updated: datetime = datetime.utcnow()


class User(UserBase):
    id: str
    bluesky_handle: str
    is_active: bool
    created_at: datetime
    topics: List[str] = []
    auto_post: bool = False
    writing_samples: List[WritingSample] = []
    writing_style: Optional[UserWritingStyle] = None

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class DraftThread(BaseModel):
    user_email: EmailStr
    topic: str
    tweets: List[str]
    created_at: datetime

    class Config:
        from_attributes = True
