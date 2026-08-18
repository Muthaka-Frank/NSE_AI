from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Boolean, Float, Integer, UniqueConstraint
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
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login      = Column(DateTime, nullable=True)


class StockHistory(Base):
    __tablename__ = "stock_history"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_stock_history_ticker_date"),
    )

    id      = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ticker  = Column(String, index=True, nullable=False)
    date    = Column(String, index=True, nullable=False)  # YYYY-MM-DD
    open    = Column(Float, nullable=False)
    high    = Column(Float, nullable=False)
    low     = Column(Float, nullable=False)
    close   = Column(Float, nullable=False)
    volume  = Column(Integer, default=0)


class WatchlistItem(Base):
    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_watchlist_user_ticker"),
    )

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id     = Column(String, nullable=False, index=True)
    ticker      = Column(String, nullable=False)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PortfolioItem(Base):
    __tablename__ = "portfolio"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id     = Column(String, nullable=False, index=True)
    ticker      = Column(String, nullable=False)
    buy_price   = Column(Float, nullable=False)
    quantity    = Column(Integer, nullable=False)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class StockIntraday(Base):
    __tablename__ = "stock_intraday"
    __table_args__ = (
        UniqueConstraint("ticker", "date", "time", name="uq_stock_intraday_ticker_time"),
    )

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ticker     = Column(String, index=True, nullable=False)
    date       = Column(String, index=True, nullable=False)   # YYYY-MM-DD
    time       = Column(String, nullable=False)               # HH:MM:SS
    timestamp  = Column(Integer, index=True, nullable=False)  # UNIX Epoch seconds
    price      = Column(Float, nullable=False)
    change     = Column(Float, default=0.0)
    change_pct = Column(Float, default=0.0)
    volume     = Column(Integer, default=0)

