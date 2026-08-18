"""
NSE AI Platform - Data Fetcher
Parallel fetching with in-memory TTL cache.
- Stock prices: fetched concurrently via ThreadPoolExecutor
- News: RSS feeds fetched concurrently
- Cache TTL: 5 min (stocks), 10 min (news), 15 min (history)
"""

import logging
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
    """Fetch OHLCV history from local DB (strictly real data only, no mock data)."""
    ticker = ticker.upper()
    key    = f"history_{ticker}_{period}"
    cached = _cache_get(key)
    if cached:
        return cached
    meta = NSE_STOCKS.get(ticker)
    if not meta:
        return []

    data = []
    
    # Query real quotes from SQLite DB
    from auth.database import SessionLocal
    from auth.models import StockHistory
    db = SessionLocal()
    try:
        limit_days = 180
        if period == "1mo":
            limit_days = 30
        elif period == "3mo":
            limit_days = 90
        elif period == "1y":
            limit_days = 365
            
        records = db.query(StockHistory).filter(
            StockHistory.ticker == ticker
        ).order_by(StockHistory.date.desc()).limit(limit_days).all()
        
        if records:
            # Sort ascending
            records = sorted(records, key=lambda x: x.date)
            data = [{
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume
            } for r in records]
    except Exception as e:
        logging.getLogger(__name__).error(f"Error querying StockHistory: {e}")
    finally:
        db.close()

    _cache_set(key, data, 900)
    return data


def get_batch_historical_data(tickers: list[str], period: str = "3mo") -> dict[str, list[dict]]:
    """
    Batch-fetches OHLCV historical records for multiple tickers in a SINGLE SQLite query.
    Populates internal caches and returns a dict mapping ticker -> list of historical records.
    """
    if not tickers:
        return {}

    norm_tickers = [t.upper() for t in tickers if t.upper() in NSE_STOCKS]
    results = {}
    missing_tickers = []

    # Check cache first for each ticker
    for t in norm_tickers:
        key = f"history_{t}_{period}"
        cached = _cache_get(key)
        if cached is not None:
            results[t] = cached
        else:
            missing_tickers.append(t)

    if not missing_tickers:
        return results

    limit_days = 90
    if period == "1mo":
        limit_days = 30
    elif period == "6mo":
        limit_days = 180
    elif period == "1y":
        limit_days = 365

    from datetime import datetime, timedelta
    cutoff_date = (datetime.now() - timedelta(days=int(limit_days * 1.6))).strftime("%Y-%m-%d")

    from auth.database import SessionLocal
    from auth.models import StockHistory

    db = SessionLocal()
    try:
        records = db.query(StockHistory).filter(
            StockHistory.ticker.in_(missing_tickers),
            StockHistory.date >= cutoff_date
        ).order_by(StockHistory.ticker, StockHistory.date.asc()).all()

        # Group by ticker
        grouped = {t: [] for t in missing_tickers}
        for r in records:
            if r.ticker in grouped:
                grouped[r.ticker].append({
                    "date": r.date,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                })

        # Cache each ticker and assign to results (slice to limit_days)
        for t, data in grouped.items():
            trimmed = data[-limit_days:]
            _cache_set(f"history_{t}_{period}", trimmed, 900)
            results[t] = trimmed

    except Exception as e:
        logging.getLogger(__name__).error(f"Error in get_batch_historical_data: {e}")
        # Fallback to individual fetches on failure
        for t in missing_tickers:
            results[t] = get_historical_data(t, period)
    finally:
        db.close()

    return results


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
                
                raw_related = _extract_tickers(title + " " + summary)
                from ml.relevance import evaluate_relevance
                related = []
                for t in raw_related:
                    meta = NSE_STOCKS.get(t, {})
                    company_name = meta.get("name", t)
                    score = evaluate_relevance(t, company_name, title, summary, total_matches=len(raw_related))
                    if score >= 0.40:
                        related.append(t)
                        
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
    import re
    found = []
    
    # 1. Direct Case-Sensitive Ticker Matches
    # This matches \bSCOM\b, \bPORT\b, etc. in all-caps as standalone words
    tickers = list(NSE_STOCKS.keys())
    if tickers:
        tickers_pattern = rf"\b({'|'.join(re.escape(t) for t in tickers)})\b"
        for m in re.finditer(tickers_pattern, text):
            t = m.group(0)
            if t not in found:
                found.append(t)
            
    # 2. Dynamic Phrase/Alias Matches (Case-Insensitive Whole-Phrase)
    # List of generic words that should not be matched case-insensitively as standalone words
    generic_words = {
        "port", "equity", "total", "family", "bat", "cic", "cooperative", 
        "co-operative", "standard", "jubilee", "unga", "group", "limited", 
        "company", "plc", "ltd", "corporation", "capital"
    }
    
    # Map of lowercase phrase/keyword -> ticker
    phrase_map = {}
    
    # Pre-populate with robust curated aliases
    curated_aliases = {
        "SCOM": ["Safaricom"],
        "EQTY": ["Equity Bank", "Equity Group", "Equity Holdings"],
        "KCB":  ["KCB Bank", "KCB Group", "KCB PLC", "K.C.B"],
        "COOP": ["Co-operative Bank", "Cooperative Bank", "Coop Bank"],
        "EABL": ["East African Breweries", "EABL", "Kenya Breweries", "KBL"],
        "BAT":  ["British American Tobacco", "BAT Kenya"],
        "KPLC": ["Kenya Power", "KPLC", "Kenya Power & Lighting"],
        "ABSA": ["Absa", "Absa Bank", "Absa Group", "Absa Kenya"],
        "NCBA": ["NCBA Bank", "NCBA Group", "NCBA Kenya"],
        "STND": ["Standard Chartered", "Stanchart"],
        "BAMB": ["Bamburi Cement", "Bamburi"],
        "KENR": ["Kenya Re", "Kenya Re-Insurance", "Kenya Reinsurance"],
        "JUB":  ["Jubilee Insurance", "Jubilee Holdings"],
        "SBIC": ["Stanbic Bank", "Stanbic Group", "Stanbic Holdings"],
        "HFCK": ["HF Group", "Housing Finance"],
        "IMH":  ["I&M Bank", "I&M Group", "I & M"],
        "DTK":  ["Diamond Trust Bank", "DTB Bank", "DTB Kenya", "DTB"],
        "BRIT": ["Britam", "Britam Holdings"],
        "CIC":  ["CIC Insurance", "CIC Group", "CIC Holdings"],
        "KEGN": ["KenGen", "Kenya Electricity Generating"],
        "TOTL": ["TotalEnergies", "Total Energies", "Total Kenya"],
        "CTUM": ["Centum", "Centum Investment"],
        "UNGA": ["Unga Group", "Unga Limited"],
        "KUKZ": ["Kakuzi"],
        "SASN": ["Sasini"],
        "FMLY": ["Family Bank"],
        "PORT": ["Portland Cement", "East African Portland"],
        "BKG":  ["BK Group", "BK", "BK Group Plc"],
    }
    
    # Add curated aliases for those present in NSE_STOCKS
    for ticker, aliases in curated_aliases.items():
        if ticker in NSE_STOCKS:
            for alias in aliases:
                phrase_map[alias.lower()] = ticker
                
    # Dynamically generate aliases for any stocks not covered by curated aliases (e.g. new dynamic listings)
    for ticker, info in NSE_STOCKS.items():
        if ticker in curated_aliases:
            continue
            
        ticker_upper = ticker.upper()
        name = info.get("name", "")
        if not name:
            continue
            
        # Clean company name of suffixes
        cleaned = name
        for suffix in ["PLC", "Limited", "Ltd", "Group", "Holdings", "Holding", "Co.", "Co", "Ltd.", "Company"]:
            cleaned = re.sub(rf"\b{suffix}\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()
        
        # If it's a multi-word phrase, it is safe to match case-insensitively
        if " " in cleaned:
            phrase_map[cleaned.lower()] = ticker_upper
        else:
            # If it's a single word, check if it's not a generic word
            if cleaned.lower() not in generic_words and len(cleaned) >= 2:
                phrase_map[cleaned.lower()] = ticker_upper
                
    # Search text for phrases case-insensitively using whole-word boundaries
    for phrase, ticker in phrase_map.items():
        if ticker in found:
            continue
        # Use regex to match the phrase case-insensitively as a whole phrase
        pattern = rf"\b{re.escape(phrase)}\b"
        if re.search(pattern, text, re.IGNORECASE):
            found.append(ticker)
            
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
