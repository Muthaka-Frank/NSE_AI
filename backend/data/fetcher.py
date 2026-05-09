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
import yfinance as yf
import pytz
import random
import time
from datetime import datetime, timedelta
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import data.alpha_vantage as av
import data.nse_scraper as nse_scraper

# Suppress yfinance "possibly delisted" and "No data found" console noise.
# These are expected for NSE tickers not listed on Yahoo Finance —
# the fallback chain (AV → mock) handles them silently.
logging.getLogger("yfinance").setLevel(logging.ERROR)
logging.getLogger("peewee").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*possibly delisted.*")
warnings.filterwarnings("ignore", message=".*No data found.*")

NAIROBI_TZ = pytz.timezone("Africa/Nairobi")

NSE_STOCKS = {
    "SCOM": {"name": "Safaricom PLC",           "sector": "Telecommunications", "yahoo": "SCOM.NR"},
    "EQTY": {"name": "Equity Group Holdings",   "sector": "Banking",            "yahoo": "EQTY.NR"},
    "KCB":  {"name": "KCB Group PLC",           "sector": "Banking",            "yahoo": "KCB.NR"},
    "COOP": {"name": "Co-operative Bank",       "sector": "Banking",            "yahoo": "COOP.NR"},
    "EABL": {"name": "East African Breweries",  "sector": "Consumer Staples",   "yahoo": "EABL.NR"},
    "BAT":  {"name": "BAT Kenya",               "sector": "Consumer Staples",   "yahoo": "BAT.NR"},
    "KPLC": {"name": "Kenya Power & Lighting",  "sector": "Energy",             "yahoo": "KPLC.NR"},
    "ABSA": {"name": "Absa Bank Kenya",         "sector": "Banking",            "yahoo": "ABSA.NR"},
    "NCBA": {"name": "NCBA Group PLC",          "sector": "Banking",            "yahoo": "NCBA.NR"},
    "STND": {"name": "Standard Chartered Kenya","sector": "Banking",            "yahoo": "SCBK.NR"},
    "BAMB": {"name": "Bamburi Cement",          "sector": "Manufacturing",      "yahoo": "BAMB.NR"},
    "KENR": {"name": "Kenya Re-Insurance",      "sector": "Insurance",          "yahoo": "KENR.NR"},
    "JUB":  {"name": "Jubilee Holdings",        "sector": "Insurance",          "yahoo": "JUB.NR"},
    "SBIC": {"name": "Stanbic Holdings",        "sector": "Banking",            "yahoo": "SBIC.NR"},
    "HFCK": {"name": "HF Group",               "sector": "Banking",            "yahoo": "HFCK.NR"},
}

NEWS_FEEDS = [
    {"source": "Business Daily Africa", "url": "https://www.businessdailyafrica.com/rss/markets"},
    {"source": "Business Daily Africa", "url": "https://www.businessdailyafrica.com/rss/economy"},
    {"source": "Capital Business",      "url": "https://www.capitalfm.co.ke/business/feed/"},
    {"source": "The Standard",          "url": "https://www.standardmedia.co.ke/rss/business.php"},
    {"source": "KBC",                   "url": "https://www.kbc.co.ke/category/business/feed/"},
]

BASE_PRICES = {
    "SCOM": 19.80, "EQTY": 52.00, "KCB": 42.50, "COOP": 13.20,
    "EABL": 160.00, "BAT": 420.00, "KPLC": 2.30, "ABSA": 15.50,
    "NCBA": 44.00,  "STND": 238.00, "BAMB": 40.00, "KENR": 18.00,
    "JUB":  270.00, "SBIC": 115.00, "HFCK": 4.80,
}

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
    """Fetch OHLCV history. Yahoo Finance first, Alpha Vantage fallback."""
    ticker = ticker.upper()
    key    = f"history_{ticker}_{period}"
    cached = _cache_get(key)
    if cached:
        return cached
    meta = NSE_STOCKS.get(ticker)
    if not meta:
        return []

    data = []

    # 1. Try Yahoo Finance
    try:
        tk   = yf.Ticker(meta["yahoo"])
        hist = tk.history(period=period, interval="1d", timeout=8)
        if not hist.empty:
            data = [
                {"date": str(idx.date()), "open": round(float(r["Open"]),2),
                 "high": round(float(r["High"]),2), "low": round(float(r["Low"]),2),
                 "close": round(float(r["Close"]),2), "volume": int(r["Volume"])}
                for idx, r in hist.iterrows()
            ]
    except Exception:
        pass

    # 2. Try Alpha Vantage if Yahoo Finance failed
    if not data and av.is_configured():
        outputsize = "full" if period in ("6mo", "1y") else "compact"
        av_data    = av.get_daily_history(meta["yahoo"], outputsize)
        if av_data:
            # Slice to approximate the requested period
            days_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}
            limit    = days_map.get(period, 180)
            data     = av_data[-limit:]

    # 3. Fall back to deterministic mock
    if not data:
        data = _generate_mock_history(ticker)

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
                title   = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
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


def _fetch_single_stock(ticker: str, meta: dict) -> Optional[dict]:
    """Yahoo Finance → NSE Scraper → Alpha Vantage → mock data."""

    # 1. Try Yahoo Finance
    try:
        tk   = yf.Ticker(meta["yahoo"])
        hist = tk.history(period="5d", interval="1d", timeout=8)
        if not hist.empty:
            latest     = hist.iloc[-1]
            prev       = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]
            change     = float(latest["Close"] - prev["Close"])
            change_pct = (change / float(prev["Close"])) * 100 if float(prev["Close"]) else 0.0
            return {
                "ticker": ticker, "name": meta["name"], "sector": meta["sector"],
                "price":  round(float(latest["Close"]), 2),
                "open":   round(float(latest["Open"]), 2),
                "high":   round(float(latest["High"]), 2),
                "low":    round(float(latest["Low"]), 2),
                "volume": int(latest["Volume"]),
                "change": round(change, 2), "change_pct": round(change_pct, 2),
                "currency": "KES",
                "data_source": "yahoo_finance",
                "data_as_of":  str(hist.index[-1].date()),
                "timestamp":   datetime.now(NAIROBI_TZ).isoformat(),
            }
    except Exception:
        pass

    # 2. Try NSE scraper (real prices from public sources)
    scraped = nse_scraper.get_price(ticker)
    if scraped:
        return {
            "ticker": ticker, "name": meta["name"], "sector": meta["sector"],
            "open": scraped["price"], "high": scraped["price"], "low": scraped["price"],
            "currency": "KES",
            "timestamp": datetime.now(NAIROBI_TZ).isoformat(),
            **{k: scraped[k] for k in ("price", "change", "change_pct", "volume", "data_source")},
        }

    # 3. Try Alpha Vantage (rate-limited free quota)
    if av.is_configured():
        quote = av.get_quote(meta["yahoo"])
        if quote:
            return {
                "ticker":  ticker,
                "name":    meta["name"],
                "sector":  meta["sector"],
                "currency": "KES",
                "timestamp": datetime.now(NAIROBI_TZ).isoformat(),
                **quote,
            }

    # 4. Deterministic mock data
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


def _generate_mock_history(ticker: str) -> list:
    """Deterministic 180-day OHLCV walk — same result for same ticker+day."""
    rng   = _seeded_rng(ticker)
    price = BASE_PRICES.get(ticker, 50.0)
    history = []
    date    = datetime.now() - timedelta(days=180)
    for _ in range(180):
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
    return history
