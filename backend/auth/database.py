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

# Optimize SQLite performance with WAL mode to prevent concurrent write locks
if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()

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
    """Create all tables and composite unique indexes. Called once on startup."""
    from auth.models import User, StockHistory, WatchlistItem, PortfolioItem, StockIntraday  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Ensure composite unique indexes exist on SQLite database
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_history_ticker_date ON stock_history (ticker, date);"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlist_user_ticker ON watchlist (user_id, ticker);"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_intraday_ticker_time ON stock_intraday (ticker, date, time);"))
            conn.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Notice on unique index creation: %s", e)
