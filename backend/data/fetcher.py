"""
NSE AI Platform - Data Fetcher
Parallel fetching with in-memory TTL cache.
- Stock prices: fetched concurrently via ThreadPoolExecutor
- News: RSS feeds fetched concurrently
- Cache TTL: 5 min (stocks), 10 min (news), 15 min (history)
"""

import logging
import warnings
import feedparser
import pytz
import random
import time
from datetime import datetime, timedelta
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import data.nse_scraper as nse_scraper
from bs4 import BeautifulSoup

def clean_html(text: str) -> str:
    if not text:
        return ""
    # Parse HTML and extract text
    return BeautifulSoup(text, "html.parser").get_text()

# Suppress peewee logging warning noise.
logging.getLogger("peewee").setLevel(logging.ERROR)

NAIROBI_TZ = pytz.timezone("Africa/Nairobi")

from data.stocks_registry import NSE_STOCKS, BASE_PRICES

NEWS_FEEDS = [
    {"source": "Business Daily Africa", "url": "https://www.businessdailyafrica.com/rss/markets"},
    {"source": "Business Daily Africa", "url": "https://www.businessdailyafrica.com/rss/economy"},
    {"source": "Capital Business",      "url": "https://www.capitalfm.co.ke/business/feed/"},
    {"source": "The Standard",          "url": "https://www.standardmedia.co.ke/rss/business.php"},
    {"source": "KBC",                   "url": "https://www.kbc.co.ke/category/business/feed/"},
]

# Simple TTL cache
_cache: dict = {}

def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() < entry["expires"]:
        return entry["data"]
    return None

def _cache_set(key: str, data, ttl_seconds: int):
    _cache[key] = {"data": data, "expires": time.time() + ttl_seconds}


def get_all_stocks() -> list:
    """Fetch all NSE stocks in parallel. Cached for 5 minutes."""
    cached = _cache_get("all_stocks")
    if cached:
        return cached

    # Pre-fetch and cache prices globally to prevent parallel request storms on scraper fallbacks
    try:
        nse_scraper.get_all_prices()
    except Exception as e:
        logging.getLogger(__name__).warning("Batch scraper pre-fetch failed: %s", e)

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_single_stock, t, m): t for t, m in NSE_STOCKS.items()}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
    results.sort(key=lambda x: x["ticker"])
    _cache_set("all_stocks", results, 300)
    return results


def get_stock_info(ticker: str) -> Optional[dict]:
    """Fetch single stock. Cached for 5 minutes."""
    ticker = ticker.upper()
    cached = _cache_get(f"stock_{ticker}")
    if cached:
        return cached
    meta = NSE_STOCKS.get(ticker)
    if not meta:
        return None
    result = _fetch_single_stock(ticker, meta)
    if result:
        _cache_set(f"stock_{ticker}", result, 300)
    return result


def get_historical_data(ticker: str, period: str = "6mo") -> list:
    """Fetch OHLCV history from the local database or mock fallback."""
    ticker = ticker.upper()
    key    = f"history_{ticker}_{period}"
    cached = _cache_get(key)
    if cached:
        return cached
    meta = NSE_STOCKS.get(ticker)
    if not meta:
        return []

    data = []


    # 3. Fall back to deterministic mock
    if not data:
        data = _generate_mock_history(ticker, period)
        # Scale mock history to match the latest live scraped price
        try:
            live_data = nse_scraper.get_price(ticker)
            if live_data and live_data.get("price"):
                live_price = live_data["price"]
                mock_latest = data[-1]["close"]
                if mock_latest > 0:
                    scale = live_price / mock_latest
                    for day in data:
                        day["open"] = round(day["open"] * scale, 2)
                        day["high"] = round(day["high"] * scale, 2)
                        day["low"] = round(day["low"] * scale, 2)
                        day["close"] = round(day["close"] * scale, 2)
        except Exception as e:
            logging.getLogger(__name__).error("Failed to scale mock history: %s", e)

    _cache_set(key, data, 900)
    return data


def get_news_feed(ticker_filter: Optional[str] = None) -> list:
    """Fetch RSS feeds in parallel. Cached for 10 minutes."""
    key = f"news_{ticker_filter or 'all'}"
    cached = _cache_get(key)
    if cached:
        return cached

    def _fetch_feed(feed_meta):
        items = []
        try:
            feed = feedparser.parse(feed_meta["url"])
            for entry in feed.entries[:8]:
                title   = clean_html(entry.get("title", ""))
                summary = clean_html(entry.get("summary", entry.get("description", "")))
                link    = entry.get("link", "")
                pub     = entry.get("published", datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000"))
                related = _extract_tickers(title + " " + summary)
                if ticker_filter and ticker_filter.upper() not in related:
                    continue
                items.append({
                    "title":           title,
                    "summary":         summary[:300] + "..." if len(summary) > 300 else summary,
                    "url":             link,
                    "source":          feed_meta["source"],
                    "published":       pub,
                    "related_tickers": related,
                })
        except Exception:
            pass
        return items

    raw = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        for result in as_completed([executor.submit(_fetch_feed, f) for f in NEWS_FEEDS]):
            raw.extend(result.result())

    seen, unique = set(), []
    for a in raw:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)

    _cache_set(key, unique[:40], 600)
    return unique[:40]


def clear_cache():
    _cache.clear()
    # Note: Do not clear nse_scraper's cache or reset its circuit breaker
    # across regular pollings to protect the public scrape endpoints.


def _fetch_single_stock(ticker: str, meta: dict) -> Optional[dict]:
    """NSE Scraper → mock fallback."""

    # 1. Try NSE scraper (real prices from public sources)
    scraped = nse_scraper.get_price(ticker)
    if scraped:
        price = scraped["price"]
        change = scraped["change"]
        open_val = round(price - change, 2)
        rng = _seeded_rng(ticker)
        high_val = round(max(price, open_val) * rng.uniform(1.001, 1.01), 2)
        low_val = round(min(price, open_val) * rng.uniform(0.990, 0.999), 2)
        return {
            "ticker": ticker, "name": meta["name"], "sector": meta["sector"],
            "open": open_val, "high": high_val, "low": low_val,
            "currency": "KES",
            "timestamp": datetime.now(NAIROBI_TZ).isoformat(),
            **{k: scraped[k] for k in ("price", "change", "change_pct", "volume", "data_source")},
        }



    # 3. Deterministic mock data
    return _fallback_stock(ticker, meta)


def _extract_tickers(text: str) -> list:
    mapping = {
        "Safaricom": "SCOM", "SCOM": "SCOM", "Equity": "EQTY", "EQTY": "EQTY",
        "KCB": "KCB", "Co-operative Bank": "COOP", "COOP": "COOP",
        "EABL": "EABL", "East African Breweries": "EABL",
        "BAT": "BAT", "British American Tobacco": "BAT",
        "Kenya Power": "KPLC", "KPLC": "KPLC",
        "Absa": "ABSA", "ABSA": "ABSA", "NCBA": "NCBA",
        "Standard Chartered": "STND", "Bamburi": "BAMB",
        "Jubilee": "JUB", "Stanbic": "SBIC",
        "HF Group": "HFCK", "HFCK": "HFCK",
    }
    found = []
    for kw, t in mapping.items():
        if kw.lower() in text.lower() and t not in found:
            found.append(t)
    return found


def _seeded_rng(ticker: str) -> random.Random:
    """Deterministic RNG seeded by ticker + today's date — same prices all day."""
    seed = hash(ticker + datetime.now().strftime("%Y-%m-%d")) % (2 ** 32)
    return random.Random(seed)


def _fallback_stock(ticker: str, meta: dict) -> dict:
    """Generate consistent mock stock data derived from mock history."""
    history = _generate_mock_history(ticker)
    rng     = _seeded_rng(ticker)
    price   = history[-1]["close"] if history else BASE_PRICES.get(ticker, 50.0)
    prev    = history[-2]["close"] if len(history) >= 2 else price
    change  = round(price - prev, 2)
    change_pct = round((change / prev) * 100, 2) if prev else 0.0
    return {
        "ticker": ticker, "name": meta["name"], "sector": meta["sector"],
        "price":  round(price, 2), "open": round(prev, 2),
        "high":   round(max(price, prev) * rng.uniform(1.001, 1.01), 2),
        "low":    round(min(price, prev) * rng.uniform(0.990, 0.999), 2),
        "volume": rng.randint(100_000, 5_000_000),
        "change": change, "change_pct": change_pct,
        "currency": "KES",
        "data_source": "estimated",
        "data_as_of":  None,
        "timestamp":   datetime.now(NAIROBI_TZ).isoformat(),
    }


def _generate_mock_history(ticker: str, period: str = "6mo") -> list:
    """Deterministic OHLCV walk — same result for same ticker+day."""
    rng   = _seeded_rng(ticker)
    price = BASE_PRICES.get(ticker, 50.0)
    history = []
    date    = datetime.now() - timedelta(days=365)
    for _ in range(365):
        date += timedelta(days=1)
        if date.weekday() >= 5:
            continue
        change = rng.uniform(-0.03, 0.03)
        price  = max(0.5, price * (1 + change))
        history.append({
            "date":   date.strftime("%Y-%m-%d"),
            "open":   round(price, 2),
            "high":   round(price * rng.uniform(1.001, 1.015), 2),
            "low":    round(price * rng.uniform(0.985, 0.999), 2),
            "close":  round(price * rng.uniform(0.995, 1.005), 2),
            "volume": rng.randint(100_000, 5_000_000),
        })

    days_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}
    days = days_map.get(period, 180)
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    return [h for h in history if h["date"] >= cutoff_str]
