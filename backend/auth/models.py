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


class IPOListing(Base):
    __tablename__ = "ipo_listings"

    id                     = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_name           = Column(String, nullable=False, index=True)
    proposed_ticker        = Column(String, nullable=True, index=True)
    sector                 = Column(String, nullable=False)
    listing_type           = Column(String, default="IPO")  # "IPO", "Introduction", "Rights Issue", "Cross-Listing"
    offer_price            = Column(Float, nullable=True)     # e.g. 16.50
    offer_price_range      = Column(String, nullable=True)  # e.g. "KES 14.50 - 17.50"
    shares_offered         = Column(Integer, nullable=True) # e.g. 1,000,000,000
    target_capital         = Column(String, nullable=True)  # e.g. "KES 15.0 Billion"
    min_application_shares = Column(Integer, default=100)
    
    # Timeline
    announcement_date      = Column(String, nullable=True)  # YYYY-MM-DD
    offer_open_date        = Column(String, nullable=True)  # YYYY-MM-DD
    offer_close_date       = Column(String, nullable=True)  # YYYY-MM-DD
    allotment_date         = Column(String, nullable=True)  # YYYY-MM-DD
    listing_date           = Column(String, nullable=True)  # YYYY-MM-DD
    
    status                 = Column(String, default="UPCOMING")  # "UPCOMING", "OFFER_OPEN", "OFFER_CLOSED", "LISTED", "POSTPONED"
    cma_approval           = Column(Boolean, default=True)
    
    # Prospectus Analysis & Intelligence
    prospectus_url         = Column(String, nullable=True)
    ai_summary             = Column(String, nullable=True)
    ai_verdict             = Column(String, default="ATTRACTIVE")  # "ATTRACTIVE", "FAIR_VALUE", "CAUTION"
    ai_verdict_score       = Column(Float, default=0.85)
    highlights             = Column(String, nullable=True)  # Semicolon-delimited highlights
    risk_factors           = Column(String, nullable=True)  # Semicolon-delimited risk factors
    
    is_active_alert        = Column(Boolean, default=True)
    created_at             = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at             = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class IPOSubscriber(Base):
    __tablename__ = "ipo_subscribers"
    __table_args__ = (
        UniqueConstraint("phone_number", name="uq_ipo_subscriber_phone"),
    )

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id      = Column(String, nullable=True, index=True)
    phone_number = Column(String, nullable=False, index=True)
    email        = Column(String, nullable=True)
    sms_enabled  = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))


