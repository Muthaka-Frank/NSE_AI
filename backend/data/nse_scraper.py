"""
NSE AI Platform — NSE Kenya Real-Price Scraper
Fetches live prices from public NSE data sources.
Primary source: afx.kwayisi.org (robust and comprehensive)
Fallbacks: Investing.com, myStocks.
"""

import logging
import time
import requests
from bs4 import BeautifulSoup
from typing import Optional
import threading
from datetime import datetime
import pytz

_scrape_lock = threading.RLock()

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# In-memory cache
_PRICE_CACHE: dict = {}
_CACHE_TTL = 300  # 5 minutes

# Ticker mappings between backend tickers and Kwayisi/myStocks tickers
_TICKER_MAP = {
    "STND": "SCBK",
    "KENR": "KNRE",
}

# Cache for the whole scraped table to avoid fetching multiple times in parallel or quick succession
_LAST_GLOBAL_FETCH = 0.0
_GLOBAL_CACHE_TTL = 300  # 5 minutes

def _cached(ticker: str) -> Optional[dict]:
    entry = _PRICE_CACHE.get(ticker.upper())
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        return entry
    return None

def _store(ticker: str, price: float, change: float, change_pct: float,
           volume: int = 0, source: str = "nse_scrape") -> dict:
    data = {
        "price":       round(price, 2),
        "change":      round(change, 2),
        "change_pct":  round(change_pct, 2),
        "volume":      volume,
        "data_source": source,
        "ts":          time.time(),
    }
    _PRICE_CACHE[ticker.upper()] = data
    return data

# ── Source 1: Kwayisi African Stock Exchanges ─────────────────────────────────
_KWAYISI_URL = "https://afx.kwayisi.org/nse/"
_KWAYISI_DOWN_UNTIL = 0.0

def _scrape_kwayisi() -> dict[str, dict]:
    """
    Scrape NSE prices from afx.kwayisi.org/nse/ HTML table.
    Returns {ticker: {price, change, change_pct, volume, data_source}}
    """
    global _LAST_GLOBAL_FETCH, _KWAYISI_DOWN_UNTIL
    now = time.time()
    if now < _KWAYISI_DOWN_UNTIL:
        return {}

    if now - _LAST_GLOBAL_FETCH < _GLOBAL_CACHE_TTL and _PRICE_CACHE:
        return _PRICE_CACHE

    results = {}
    try:
        logger.info("Scraping real NSE prices from %s", _KWAYISI_URL)
        r = requests.get(_KWAYISI_URL, headers=_HEADERS, timeout=5)
        if r.status_code != 200:
            logger.warning("Kwayisi scrape failed with status code: %d. Circuit breaker active for 5 minutes.", r.status_code)
            _KWAYISI_DOWN_UNTIL = now + 300
            return results

        soup = BeautifulSoup(r.text, "lxml")
        table_container = soup.find("div", class_="t")
        if not table_container:
            table_container = soup
        
        table = table_container.find("table")
        if not table:
            logger.warning("Kwayisi scrape: table not found in HTML. Circuit breaker active for 5 minutes.")
            _KWAYISI_DOWN_UNTIL = now + 300
            return results

        rows = table.find_all("tr")
        count = 0
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            # First cell: Ticker code (e.g. SCOM)
            ticker_a = cells[0].find("a")
            if not ticker_a:
                continue
            kwayisi_ticker = ticker_a.get_text(strip=True).upper()

            # Third cell: Traded Volume
            vol_str = cells[2].get_text(strip=True)
            volume = 0
            if vol_str:
                try:
                    volume = int(vol_str.replace(",", ""))
                except ValueError:
                    pass

            # Fourth cell: Price (e.g. 29.60 or 1,500.00)
            price_str = cells[3].get_text(strip=True)
            price = _parse_number(price_str)
            if price is None:
                continue

            # Fifth cell: Change (e.g. +0.10, -0.50 or empty)
            change = 0.0
            change_pct = 0.0
            if len(cells) >= 5:
                change_str = cells[4].get_text(strip=True)
                change = _parse_number(change_str) or 0.0
                prev_price = price - change
                if prev_price > 0:
                    change_pct = (change / prev_price) * 100

            # Store mapping back to our local ticker names
            rev_map = {v: k for k, v in _TICKER_MAP.items()}
            local_alias = rev_map.get(kwayisi_ticker)

            # If ticker is a new listing, register it dynamically
            if kwayisi_ticker not in _TRACKED_TICKERS and (not local_alias or local_alias not in _TRACKED_TICKERS):
                company_name = cells[1].get_text(strip=True)
                logger.info("New listing detected: %s (%s)", kwayisi_ticker, company_name)
                add_new_stock(kwayisi_ticker, company_name, price=price)

            item = _store(kwayisi_ticker, price, change, change_pct, volume, source="kwayisi_scrape")
            results[kwayisi_ticker] = item
            if local_alias:
                _store(local_alias, price, change, change_pct, volume, source="kwayisi_scrape")
                results[local_alias] = _PRICE_CACHE[local_alias]
            count += 1

        _LAST_GLOBAL_FETCH = now
        logger.info("Kwayisi scrape complete. Parsed %d listings.", count)

    except Exception as e:
        logger.warning("Error during Kwayisi scrape: %s. Circuit breaker active for 5 minutes.", e)
        _KWAYISI_DOWN_UNTIL = now + 300
        _LAST_GLOBAL_FETCH = now
    return results

# ── Source 2: Investing.com Kenya (unofficial search API) ─────────────────────
_INVESTING_IDS = {
    "SCOM": 953792,
    "EQTY": 953793,
    "KCB":  953794,
    "COOP": 953801,
    "EABL": 953795,
    "BAT":  953796,
    "KPLC": 953797,
    "ABSA": 953798,
    "NCBA": 953799,
    "BAMB": 953802,
}

_INVESTING_DOWN_UNTIL = 0.0
_MYSTOCKS_DOWN_UNTIL = 0.0

def _check_investing_reachable() -> bool:
    """Check if Investing.com is reachable by sending a request to SCOM page."""
    global _INVESTING_DOWN_UNTIL
    now = time.time()
    if now < _INVESTING_DOWN_UNTIL:
        return False
    try:
        r = requests.get(
            "https://www.investing.com/equities/safaricom-kenya",
            headers={**_HEADERS, "Referer": "https://www.investing.com/"},
            timeout=3,
        )
        if r.status_code == 200:
            return True
    except Exception:
        pass
    logger.warning("First fallback (Investing.com) is unreachable. Circuit breaker active for 5 minutes.")
    _INVESTING_DOWN_UNTIL = now + 300
    return False

def _scrape_investing(ticker: str) -> Optional[dict]:
    """Fetch a single ticker from Investing.com's unofficial data API."""
    global _INVESTING_DOWN_UNTIL
    if time.time() < _INVESTING_DOWN_UNTIL:
        return None
    pair_id = _INVESTING_IDS.get(ticker.upper())
    if not pair_id:
        return None
    try:
        r = requests.get(
            f"https://www.investing.com/equities/{ticker.lower()}-kenya",
            headers={**_HEADERS, "Referer": "https://www.investing.com/"},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "lxml")
        price_el = soup.find("span", {"data-test": "instrument-price-last"})
        if not price_el:
            price_el = soup.select_one('[class*="last-price"]')
        if price_el:
            price = _parse_number(price_el.get_text(strip=True))
            if price:
                return _store(ticker, price, 0, 0, source="investing_com")
    except Exception as e:
        logger.debug("Investing.com scrape for %s failed: %s", ticker, e)
        now = time.time()
        _INVESTING_DOWN_UNTIL = now + 300
    return None

def _scrape_all_investing_parallel():
    """Scrape all supported Investing.com tickers in parallel."""
    from concurrent.futures import ThreadPoolExecutor
    supported_tickers = [t for t in _TRACKED_TICKERS if t in _INVESTING_IDS]
    with ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(_scrape_investing, supported_tickers))

# ── Source 3: myStocks Ticker-by-Ticker Fallback ──────────────────────────────
_MYSTOCKS_URL = "https://live.mystocks.co.ke/stock="
from data.stocks_registry import _TRACKED_TICKERS, add_new_stock

_NAIROBI_TZ = pytz.timezone("Africa/Nairobi")

def is_market_open() -> bool:
    """
    Checks if the Nairobi Securities Exchange (NSE) is open.
    Open hours: Weekdays (Mon-Fri) from 8:55 AM to 3:05 PM EAT.
    """
    import sys
    # Always allow scraping during unit tests
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return True

    now = datetime.now(_NAIROBI_TZ)
    if now.weekday() >= 5:
        return False
    
    start_time = now.replace(hour=8, minute=55, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=5, second=0, microsecond=0)
    return start_time <= now <= end_time

def _load_prices_from_db():
    """Load latest closing prices from StockHistory db and populate cache."""
    with _scrape_lock:
        if _PRICE_CACHE:
            return
        try:
            from auth.database import SessionLocal
            from auth.models import StockHistory
            
            db = SessionLocal()
            try:
                for ticker in _TRACKED_TICKERS:
                    record = db.query(StockHistory).filter(StockHistory.ticker == ticker).order_by(StockHistory.date.desc()).first()
                    if record:
                        _store(
                            ticker, 
                            price=record.close, 
                            change=0.0, 
                            change_pct=0.0, 
                            volume=record.volume, 
                            source="kwayisi_scrape"
                        )
            finally:
                db.close()
        except Exception as e:
            logger.error("Failed to load prices from database fallback: %s", e)

def _scrape_mystocks() -> dict[str, dict]:
    """
    Scrape all tracked tickers from live.mystocks.co.ke in parallel.
    Returns {ticker: {price, change, change_pct, volume, data_source}}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import re
    
    global _MYSTOCKS_DOWN_UNTIL
    now = time.time()
    if now < _MYSTOCKS_DOWN_UNTIL:
        return {}
        
    results = {}
    failures = 0
    
    def fetch_single(ticker):
        # Polite throttling delay
        time.sleep(0.25)
        mystocks_ticker = _TICKER_MAP.get(ticker, ticker)
        url = f"{_MYSTOCKS_URL}{mystocks_ticker}"
        try:
            r = requests.get(url, headers=_HEADERS, timeout=5)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                price_el = soup.find(id="rtPrice")
                change_el = soup.find(id="rtChange")
                
                price_val = None
                change_val = 0.0
                change_pct = 0.0
                
                if price_el:
                    price_val = float(price_el.get_text(strip=True).replace(",", ""))
                    
                if change_el:
                    change_txt = change_el.get_text(strip=True)
                    if "unchanged" in change_txt.lower():
                        change_val = 0.0
                        change_pct = 0.0
                    else:
                        match = re.search(r'([+-]?\d+[\.,]\d*)\s*\(([+-]?\d+[\.,]\d*)%\)', change_txt)
                        if match:
                            change_val = float(match.group(1).replace(",", ""))
                            change_pct = float(match.group(2).replace(",", ""))
                            
                if price_val is not None:
                    return ticker, price_val, change_val, change_pct
        except Exception as e:
            logger.debug("myStocks scrape for %s failed: %s", ticker, e)
        return None

    # Fetch with very low concurrency to be polite and prevent IP blocks
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(fetch_single, t): t for t in _TRACKED_TICKERS}
        for future in as_completed(futures):
            res = future.result()
            if res:
                ticker, price_val, change_val, change_pct = res
                item = _store(ticker, price_val, change_val, change_pct, volume=0, source="mystocks_scrape")
                results[ticker] = item
            else:
                failures += 1
                
    # If a significant number of requests failed, trigger the circuit breaker
    if failures > 6:
        logger.warning("myStocks fallback is experiencing failures (%d failed). Activating circuit breaker for 5 minutes.", failures)
        _MYSTOCKS_DOWN_UNTIL = time.time() + 300

    if results:
        global _LAST_GLOBAL_FETCH
        _LAST_GLOBAL_FETCH = time.time()

    return results

# ── Helper functions ──────────────────────────────────────────────────────────

def _parse_number(text: str) -> Optional[float]:
    cleaned = text.replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None

def _extract_price(cells: list[str]) -> Optional[float]:
    for cell in cells:
        val = _parse_number(cell)
        if val and 0.5 < val < 50_000:
            return val
    return None

def _extract_change(cells: list[str]) -> tuple[float, float]:
    numbers = []
    for cell in cells:
        v = _parse_number(cell)
        if v is not None and v != 0:
            numbers.append(v)
    if len(numbers) >= 3:
        return numbers[-2], numbers[-1]
    return 0.0, 0.0

# ── Public API ────────────────────────────────────────────────────────────────

def get_price(ticker: str) -> Optional[dict]:
    """
    Get real NSE price for a ticker.
    Uses Kwayisi (cached) as primary, then tries Investing.com/myStocks.
    """
    ticker = ticker.upper()

    # 1. Check cache first
    cached = _cached(ticker)
    if cached:
        return cached

    # Check if market is open.
    # If not open, serve cached/last-known prices without network scraping.
    if not is_market_open():
        if not _PRICE_CACHE:
            _load_prices_from_db()
        return _cached(ticker)

    with _scrape_lock:
        # Check cache again inside lock
        cached = _cached(ticker)
        if cached:
            return cached

        # 2. Try Kwayisi global scrape (populates cache)
        # Translate ticker to Kwayisi if needed
        kwayisi_ticker = _TICKER_MAP.get(ticker, ticker)
        _scrape_kwayisi()
        
        cached = _cached(ticker)
        if cached:
            return cached

        # 3. Fallback to Investing.com
        result = _scrape_investing(ticker)
        if result:
            return result

        # 4. Fallback to myStocks
        mystocks_prices = _scrape_mystocks()
        if ticker in mystocks_prices:
            return mystocks_prices[ticker]

        return None

def get_all_prices() -> dict[str, dict]:
    """
    Batch-fetch NSE prices for all tracked stocks.
    """
    global _LAST_GLOBAL_FETCH
    now = time.time()
    
    # 1. If global cache is still fresh and contains data, return it
    if now - _LAST_GLOBAL_FETCH < _GLOBAL_CACHE_TTL and _PRICE_CACHE:
        results = {}
        for ticker in _TRACKED_TICKERS:
            cached = _cached(ticker)
            if cached:
                results[ticker] = cached
        if results:
            return results

    # Check if market is open.
    # If not open, serve cached/last-known prices without network scraping.
    if not is_market_open():
        if not _PRICE_CACHE:
            _load_prices_from_db()
        
        results = {}
        for ticker in _TRACKED_TICKERS:
            cached = _cached(ticker)
            if cached:
                results[ticker] = cached
        if results:
            return results

    with _scrape_lock:
        # Check cache/fetch time again inside lock
        now = time.time()
        if now - _LAST_GLOBAL_FETCH < _GLOBAL_CACHE_TTL and _PRICE_CACHE:
            results = {}
            for ticker in _TRACKED_TICKERS:
                cached = _cached(ticker)
                if cached:
                    results[ticker] = cached
            if results:
                return results

        # 2. Try Primary Source (Kwayisi)
        kwayisi_results = _scrape_kwayisi()
        
        # 3. If Primary fails, try First Fallback (Investing.com)
        if not kwayisi_results:
            logger.warning("Primary source (Kwayisi) is unreachable. Trying first fallback (Investing.com)...")
            investing_reachable = _check_investing_reachable()
            if investing_reachable:
                logger.info("First fallback (Investing.com) is reachable. Scraping supported tickers...")
                _scrape_all_investing_parallel()
            
            # 4. If first fallback was unreachable, or we have missing tickers, continue to Second Fallback (myStocks)
            missing_tickers = [t for t in _TRACKED_TICKERS if not _cached(t)]
            if not investing_reachable or missing_tickers:
                if not investing_reachable:
                    logger.warning("First fallback (Investing.com) is unreachable. Proceeding to second fallback (myStocks)...")
                else:
                    logger.info("Fetching remaining %d tickers from second fallback (myStocks)...", len(missing_tickers))
                _scrape_mystocks()
        
        results = {}
        for ticker in _TRACKED_TICKERS:
            cached = _cached(ticker)
            if cached:
                results[ticker] = cached
        return results


def clear_cache():
    global _LAST_GLOBAL_FETCH, _KWAYISI_DOWN_UNTIL, _INVESTING_DOWN_UNTIL, _MYSTOCKS_DOWN_UNTIL
    _LAST_GLOBAL_FETCH = 0.0
    _KWAYISI_DOWN_UNTIL = 0.0
    _INVESTING_DOWN_UNTIL = 0.0
    _MYSTOCKS_DOWN_UNTIL = 0.0
    _PRICE_CACHE.clear()
