"""NSE AI Platform — User Model"""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.dialects.sqlite import TEXT
from auth.database import Base
import uuid


class User(Base):
    __tablename__ = "users"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email           = Column(String, unique=True, index=True, nullable=False)
    name            = Column(String, nullable=False)
    avatar_url      = Column(String, nullable=True)
    provider        = Column(String, default="email")  # "email" | "google"
    hashed_password = Column(String, nullable=True)    # None for Google-only accounts
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    last_login      = Column(DateTime, nullable=True)
