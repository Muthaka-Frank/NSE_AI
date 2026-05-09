"""
NSE AI Platform — SQLAlchemy Database Setup
Uses SQLite for zero-config local storage. Swappable to PostgreSQL via DATABASE_URL.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

# Default to local SQLite; override with DATABASE_URL for production
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./nse_users.db")

# SQLite needs check_same_thread=False; ignored for other DBs
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called once on startup."""
    from auth.models import User  # noqa: F401 — ensures model is registered
    Base.metadata.create_all(bind=engine)
