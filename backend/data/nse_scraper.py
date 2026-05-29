"""
NSE AI Platform — NSE Kenya Real-Price Scraper
Fetches live prices from public NSE data sources.
Primary source: afx.kwayisi.org (robust and comprehensive)
Fallbacks: Investing.com, ACMN table scrape.
"""

import logging
import time
import requests
from bs4 import BeautifulSoup
from typing import Optional

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

# Ticker mappings between backend tickers and Kwayisi tickers
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

def _scrape_kwayisi() -> dict[str, dict]:
    """
    Scrape NSE prices from afx.kwayisi.org/nse/ HTML table.
    Returns {ticker: {price, change, change_pct, volume, data_source}}
    """
    global _LAST_GLOBAL_FETCH
    now = time.time()
    if now - _LAST_GLOBAL_FETCH < _GLOBAL_CACHE_TTL and _PRICE_CACHE:
        return _PRICE_CACHE

    results = {}
    try:
        logger.info("Scraping real NSE prices from %s", _KWAYISI_URL)
        r = requests.get(_KWAYISI_URL, headers=_HEADERS, timeout=12)
        if r.status_code != 200:
            logger.error("Kwayisi scrape failed with status code: %d", r.status_code)
            return results

        soup = BeautifulSoup(r.text, "lxml")
        table_container = soup.find("div", class_="t")
        if not table_container:
            table_container = soup
        
        table = table_container.find("table")
        if not table:
            logger.error("Kwayisi scrape: table not found in HTML")
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

            item = _store(kwayisi_ticker, price, change, change_pct, volume, source="kwayisi_scrape")
            results[kwayisi_ticker] = item
            if local_alias:
                _store(local_alias, price, change, change_pct, volume, source="kwayisi_scrape")
                results[local_alias] = _PRICE_CACHE[local_alias]
            count += 1

        _LAST_GLOBAL_FETCH = now
        logger.info("Kwayisi scrape complete. Parsed %d listings.", count)

    except Exception as e:
        logger.error("Error during Kwayisi scrape: %s", e)
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

def _scrape_investing(ticker: str) -> Optional[dict]:
    """Fetch a single ticker from Investing.com's unofficial data API."""
    pair_id = _INVESTING_IDS.get(ticker.upper())
    if not pair_id:
        return None
    try:
        r = requests.get(
            f"https://www.investing.com/equities/{ticker.lower()}-kenya",
            headers={**_HEADERS, "Referer": "https://www.investing.com/"},
            timeout=10,
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
    return None

# ── Source 3: African Capital Markets News (table scrape fallback) ────────────
_ACMN_URL = "https://africancapitalmarketsnews.com/nairobi-stock-exchange-prices/"
_ACMN_NAME_MAP = {
    "SCOM": ["safaricom"],
    "EQTY": ["equity group", "equity bank"],
    "KCB":  ["kcb group", "kcb bank"],
    "COOP": ["co-op bank", "co-operative bank", "cooperative bank"],
    "EABL": ["east african breweries", "eabl"],
    "BAT":  ["bat kenya", "british american tobacco"],
    "KPLC": ["kenya power", "kplc"],
    "ABSA": ["absa bank", "absa kenya"],
    "NCBA": ["ncba group", "ncba bank"],
    "STND": ["standard chartered", "stanchart"],
    "BAMB": ["bamburi cement", "bamburi"],
    "KENR": ["kenya re", "kenya reinsurance"],
    "JUB":  ["jubilee holdings", "jubilee insurance"],
    "SBIC": ["stanbic holdings", "stanbic bank"],
    "HFCK": ["hf group", "housing finance", "hfck"],
    "IMH":  ["i&m", "i and m", "imh"],
    "DTK":  ["diamond trust bank", "dtb"],
    "BRIT": ["britam"],
    "CIC":  ["cic insurance", "cic group"],
    "KEGN": ["kengen", "kenya electricity generating"],
    "TOTL": ["totalenergies", "total marketing", "total kenya"],
    "CTUM": ["centum"],
    "UNGA": ["unga group", "unga"],
    "KUKZ": ["kakuzi"],
    "SASN": ["sasini"],
}

def _scrape_acmn() -> dict[str, dict]:
    results = {}
    try:
        r = requests.get(_ACMN_URL, headers=_HEADERS, timeout=12)
        if r.status_code != 200:
            return results

        soup = BeautifulSoup(r.text, "lxml")
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if len(cells) < 3:
                    continue

                row_text = " ".join(cells).lower()
                for ticker, keywords in _ACMN_NAME_MAP.items():
                    if ticker in results:
                        continue
                    if any(kw in row_text for kw in keywords):
                        price = _extract_price(cells)
                        if price:
                            change, pct = _extract_change(cells)
                            results[ticker] = _store(ticker, price, change, pct, source="african_markets")
                            break
    except Exception as e:
        logger.debug("ACMN scrape failed: %s", e)
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
    Uses Kwayisi (cached) as primary, then tries Investing.com/ACMN.
    """
    ticker = ticker.upper()

    # 1. Check cache first
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

    # 4. Fallback to ACMN
    acmn_prices = _scrape_acmn()
    if ticker in acmn_prices:
        return acmn_prices[ticker]

    return None

def get_all_prices() -> dict[str, dict]:
    """
    Batch-fetch NSE prices for all tracked stocks.
    """
    # Populate cache using Kwayisi
    _scrape_kwayisi()
    
    results = {}
    for ticker in _ACMN_NAME_MAP:
        cached = _cached(ticker)
        if cached:
            results[ticker] = cached
    return results
