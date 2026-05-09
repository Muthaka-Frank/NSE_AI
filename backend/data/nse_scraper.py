"""
NSE AI Platform — NSE Kenya Real-Price Scraper
Fetches live prices from public NSE data sources since Yahoo Finance
no longer covers NSE Kenya (.NR) tickers.

Sources tried in order:
  1. African Capital Markets News (table scrape)
  2. Investing.com Kenya equities (unofficial JSON)
  3. None (caller falls back to mock)
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

# Simple in-memory cache: {ticker: {"price": x, "change": y, "pct": z, "ts": epoch}}
_PRICE_CACHE: dict = {}
_CACHE_TTL = 300  # 5 minutes


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


# ── Source 1: African Capital Markets News ────────────────────────────────────
# Page: https://africancapitalmarketsnews.com/nairobi-stock-exchange-prices/

_ACMN_URL = "https://africancapitalmarketsnews.com/nairobi-stock-exchange-prices/"

# Map our ticker codes → the name fragments that appear in the ACMN table
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
}


def _scrape_acmn() -> dict[str, dict]:
    """Scrape NSE prices from African Capital Markets News table."""
    results = {}
    try:
        r = requests.get(_ACMN_URL, headers=_HEADERS, timeout=12)
        if r.status_code != 200:
            return results

        soup = BeautifulSoup(r.text, "lxml")
        # Find any table with stock price data
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
                        # Try to extract price (first numeric-looking cell)
                        price = _extract_price(cells)
                        if price:
                            change, pct = _extract_change(cells)
                            results[ticker] = _store(ticker, price, change, pct,
                                                     source="african_markets")
                            break
    except Exception as e:
        logger.debug("ACMN scrape failed: %s", e)
    return results


# ── Source 2: Investing.com Kenya (unofficial search API) ─────────────────────

_INVESTING_SEARCH = "https://www.investing.com/search/service/searchTopBar"
_INVESTING_QUOTE  = "https://www.investing.com/instruments/Service/GetInstrument"

# Pre-mapped Investing.com pair IDs for NSE Kenya stocks (discovered manually)
_INVESTING_IDS = {
    "SCOM": 953792,   # Safaricom
    "EQTY": 953793,   # Equity Group
    "KCB":  953794,   # KCB Group
    "COOP": 953801,   # Co-op Bank
    "EABL": 953795,   # EABL
    "BAT":  953796,   # BAT Kenya
    "KPLC": 953797,   # Kenya Power
    "ABSA": 953798,   # Absa Kenya
    "NCBA": 953799,   # NCBA
    "BAMB": 953802,   # Bamburi
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
        # Look for the price in meta tags or data attributes
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


# ── Helper functions ──────────────────────────────────────────────────────────

def _parse_number(text: str) -> Optional[float]:
    """Parse a price string like '19.80', '1,234.50', '-2.5%' → float or None."""
    cleaned = text.replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _extract_price(cells: list[str]) -> Optional[float]:
    """Return first valid numeric value from a row that looks like a price."""
    for cell in cells:
        val = _parse_number(cell)
        if val and 0.5 < val < 50_000:  # reasonable KES price range
            return val
    return None


def _extract_change(cells: list[str]) -> tuple[float, float]:
    """Try to extract (change, change_pct) from row cells."""
    numbers = []
    for cell in cells:
        v = _parse_number(cell)
        if v is not None and v != 0:
            numbers.append(v)
    # Heuristic: if we have ≥3 numbers, last two are often change and pct
    if len(numbers) >= 3:
        return numbers[-2], numbers[-1]
    return 0.0, 0.0


# ── Public API ────────────────────────────────────────────────────────────────

def get_price(ticker: str) -> Optional[dict]:
    """
    Get real NSE price for a single ticker.
    Returns dict with price, change, change_pct, volume, data_source
    or None if unavailable.
    """
    ticker = ticker.upper()

    # Check cache first
    cached = _cached(ticker)
    if cached:
        return cached

    # Try Investing.com (single stock, faster)
    result = _scrape_investing(ticker)
    if result:
        return result

    return None


def get_all_prices() -> dict[str, dict]:
    """
    Batch-fetch NSE prices for all tracked stocks.
    Returns {ticker: {price, change, change_pct, ...}}
    """
    # Return cache hits first
    results = {}
    missing = []
    for ticker in _ACMN_NAME_MAP:
        cached = _cached(ticker)
        if cached:
            results[ticker] = cached
        else:
            missing.append(ticker)

    if not missing:
        return results

    # Try bulk scrape from ACMN
    scraped = _scrape_acmn()
    results.update(scraped)

    # Log summary
    if scraped:
        logger.info("NSE scraper: fetched %d/%d prices from African Markets",
                    len(scraped), len(_ACMN_NAME_MAP))
    else:
        logger.debug("NSE scraper: no prices from ACMN, falling back to mock")

    return results
