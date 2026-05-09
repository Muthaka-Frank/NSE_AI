"""
NSE AI Platform — Alpha Vantage Data Client
Used as a fallback when Yahoo Finance doesn't cover a stock.

Free tier: 25 requests/day, 500/month
Docs: https://www.alphavantage.co/documentation/

NSE Kenya symbols: SCOM.NR, EQTY.NR, KCB.NR etc.
(same format as Yahoo Finance, but AV has broader African coverage)
"""

import os
import json
import time
import requests
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
import logging

load_dotenv()
logger = logging.getLogger(__name__)

AV_BASE    = "https://www.alphavantage.co/query"
AV_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")

AV_DAILY_LIMIT  = 24   # stay 1 under 25 to be safe
_AV_COUNTER_FILE = os.path.join(os.path.dirname(__file__), "..", "tmp", "av_rate.json")


def is_configured() -> bool:
    """Check if a real API key has been provided."""
    return bool(AV_API_KEY) and AV_API_KEY != "your_key_here"


def _check_rate_limit() -> bool:
    """Persistent file-based counter — survives uvicorn --reload."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        os.makedirs(os.path.dirname(_AV_COUNTER_FILE), exist_ok=True)
        data = {}
        if os.path.exists(_AV_COUNTER_FILE):
            with open(_AV_COUNTER_FILE) as f:
                data = json.load(f)

        if data.get("date") != today:
            data = {"date": today, "count": 0}

        if data["count"] >= AV_DAILY_LIMIT:
            logger.warning(
                "Alpha Vantage daily limit reached (%d/%d). "
                "Falling back to Yahoo Finance / mock data. Resets tomorrow.",
                data["count"], AV_DAILY_LIMIT
            )
            return False

        data["count"] += 1
        with open(_AV_COUNTER_FILE, "w") as f:
            json.dump(data, f)
        return True
    except Exception:
        return False  # if file I/O fails, don't burn API calls


def get_quote(symbol: str) -> Optional[dict]:
    """
    Fetch the latest quote for a single symbol from Alpha Vantage.
    Returns a dict with price, change, change_pct or None on failure.

    AV symbol for NSE Kenya stocks: SCOM.NR, EQTY.NR, KCB.NR …
    """
    if not is_configured():
        return None
    if not _check_rate_limit():
        return None

    try:
        resp = requests.get(
            AV_BASE,
            params={
                "function": "GLOBAL_QUOTE",
                "symbol":   symbol,
                "apikey":   AV_API_KEY,
            },
            timeout=8,
        )
        data = resp.json()
        quote = data.get("Global Quote", {})

        if not quote or "05. price" not in quote:
            return None  # symbol not found or API error

        price      = float(quote["05. price"])
        change     = float(quote["09. change"])
        change_pct = float(quote["10. change percent"].replace("%", ""))
        volume     = int(quote.get("06. volume", 0))
        prev_close = float(quote.get("08. previous close", price))
        hi         = float(quote.get("03. high", price))
        lo         = float(quote.get("04. low", price))
        op         = float(quote.get("02. open", price))
        trade_date = quote.get("07. latest trading day", "")

        return {
            "price":      round(price, 2),
            "open":       round(op, 2),
            "high":       round(hi, 2),
            "low":        round(lo, 2),
            "volume":     volume,
            "change":     round(change, 2),
            "change_pct": round(change_pct, 2),
            "data_source": "alpha_vantage",
            "data_as_of":  trade_date,
        }
    except Exception:
        return None


def get_daily_history(symbol: str, outputsize: str = "compact") -> list[dict]:
    """
    Fetch daily OHLCV history from Alpha Vantage.
    outputsize: 'compact' = last 100 days, 'full' = up to 20 years
    """
    if not is_configured():
        return []
    if not _check_rate_limit():
        return []

    try:
        resp = requests.get(
            AV_BASE,
            params={
                "function":  "TIME_SERIES_DAILY",
                "symbol":    symbol,
                "outputsize": outputsize,
                "apikey":    AV_API_KEY,
            },
            timeout=12,
        )
        data   = resp.json()
        series = data.get("Time Series (Daily)", {})
        if not series:
            return []

        result = []
        for date_str, ohlcv in sorted(series.items()):
            result.append({
                "date":   date_str,
                "open":   round(float(ohlcv["1. open"]),  2),
                "high":   round(float(ohlcv["2. high"]),  2),
                "low":    round(float(ohlcv["3. low"]),   2),
                "close":  round(float(ohlcv["4. close"]), 2),
                "volume": int(ohlcv["5. volume"]),
            })
        return result
    except Exception:
        return []


def remaining_calls() -> dict:
    """Return how many AV calls are left today."""
    today = datetime.now().strftime("%Y-%m-%d")
    used  = _av_calls_today["count"] if _av_calls_today["date"] == today else 0
    return {
        "used":      used,
        "remaining": max(0, AV_DAILY_LIMIT - used),
        "limit":     AV_DAILY_LIMIT,
    }
