"""
NSE AI Platform — Centralized Application Configuration
Provides strongly typed environment settings and defaults.
"""
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

_NAIROBI_TZ = ZoneInfo("Africa/Nairobi")


@dataclass(frozen=True)
class Settings:
    # Service Metadata
    SERVICE_NAME: str = "NSE AI Investment Intelligence API"
    VERSION: str = "1.0.0"

    # Timezone
    TIMEZONE_NAME: str = "Africa/Nairobi"

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./nse_users.db")

    # Authentication & Security
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "nse-ai-platform-super-secret-key-change-in-production-2026")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 7)))  # 7 days

    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")

    # Live Scraper (afx.kwayisi.org)
    KWAYISI_URL: str = os.getenv("KWAYISI_URL", "https://afx.kwayisi.org/nse/")
    SCRAPER_CACHE_TTL: int = int(os.getenv("SCRAPER_CACHE_TTL", "600"))  # 10 minutes
    SCRAPER_CIRCUIT_BREAKER_SECS: int = int(os.getenv("SCRAPER_CIRCUIT_BREAKER_SECS", "300"))  # 5 minutes

    # Market Trading Hours (EAT)
    MARKET_OPEN_HOUR: int = 8
    MARKET_OPEN_MINUTE: int = 55
    MARKET_CLOSE_HOUR: int = 15
    MARKET_CLOSE_MINUTE: int = 5

    # Daily Background Scraper Schedule (EAT)
    DAILY_SCRAPE_HOUR: int = 15
    DAILY_SCRAPE_MINUTE: int = 10

    # ML & Quantitative Signals
    ENABLE_ML_MODEL: bool = os.getenv("ENABLE_ML_MODEL", "false").lower() in ("true", "1", "yes")
    CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
    RECS_CACHE_TTL: float = float(os.getenv("RECS_CACHE_TTL", "60.0"))  # 60 seconds
    NEWS_CACHE_TTL: int = int(os.getenv("NEWS_CACHE_TTL", "600"))  # 10 minutes


settings = Settings()
