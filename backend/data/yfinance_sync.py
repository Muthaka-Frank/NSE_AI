"""
NSE AI Platform — Stock History Sync Module (Scrapes from Kwayisi historical tables)
Polite rate-limiting & check-before-sync controls to prevent IP blocking.
"""
import logging
import requests
import time
import random
from bs4 import BeautifulSoup
from datetime import datetime
from auth.database import SessionLocal
from auth.models import StockHistory

logger = logging.getLogger(__name__)

# Global circuit breaker for history scraping to prevent IP bans on 403/429
_SYNC_BLOCKED_UNTIL = 0.0

def sync_stock_history(ticker: str, period: str = "6mo") -> int:
    """
    Scrapes historical daily OHLCV quotes for a ticker from afx.kwayisi.org
    and saves new records to the local StockHistory database.
    Skips request if history is already up-to-date in DB.
    """
    global _SYNC_BLOCKED_UNTIL
    ticker = ticker.upper().strip()
    
    # 1. Check circuit breaker
    if time.time() < _SYNC_BLOCKED_UNTIL:
        logger.warning(f"History sync skipped for {ticker} due to active 30-minute rate-limit cooldown.")
        return 0

    # 2. Check if database already has recent history for this stock
    db = SessionLocal()
    try:
        count = db.query(StockHistory).filter(StockHistory.ticker == ticker).count()
        if count >= 10:
            latest = db.query(StockHistory).filter(StockHistory.ticker == ticker).order_by(StockHistory.date.desc()).first()
            if latest:
                latest_date = datetime.strptime(latest.date, "%Y-%m-%d")
                days_elapsed = (datetime.now() - latest_date).days
                if days_elapsed <= 2:
                    logger.info(f"Skipping history sync for {ticker}: already up to date ({count} records, latest: {latest.date})")
                    db.close()
                    return 0
    except Exception as e:
        logger.warning(f"Error checking existing history count: {e}")
    finally:
        db.close()

    # Map ticker to Kwayisi ticker name if mapped (e.g. STND -> SCBK, KENR -> KNRE)
    from data.nse_scraper import _TICKER_MAP
    kwayisi_ticker = _TICKER_MAP.get(ticker, ticker)
    url = f"https://afx.kwayisi.org/nse/{kwayisi_ticker.lower()}.html"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    
    logger.info(f"Syncing history for {ticker} from Kwayisi: {url}...")
    try:
        r = requests.get(url, headers=headers, timeout=10)
        
        # Trigger circuit breaker if blocked
        if r.status_code in [403, 429]:
            logger.error(f"Kwayisi has rate-limited or blocked requests (HTTP {r.status_code}). Triggering 30-minute history cooldown.")
            _SYNC_BLOCKED_UNTIL = time.time() + 1800
            return 0
            
        if r.status_code != 200:
            logger.warning(f"Failed to fetch Kwayisi history for {ticker}: HTTP {r.status_code}")
            return 0
            
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table", {"data-hist": True})
        if not table:
            logger.warning(f"No historical table (data-hist) found for {ticker}")
            return 0
            
        rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")[1:]
        
        db = SessionLocal()
        added_count = 0
        
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue
                
            date_str = cols[0].text.strip()  # YYYY-MM-DD
            volume_str = cols[1].text.strip().replace(",", "")
            close_str = cols[2].text.strip()
            
            # Clean and parse volume
            try:
                if "m" in volume_str.lower():
                    volume = int(float(volume_str.lower().replace("m", "")) * 1_000_000)
                elif "k" in volume_str.lower():
                    volume = int(float(volume_str.lower().replace("k", "")) * 1_000)
                else:
                    volume = int(volume_str)
            except ValueError:
                volume = 0
                
            # Clean and parse close price
            try:
                close_val = float(close_str.replace(",", ""))
            except ValueError:
                continue
                
            # Parse change to compute open
            change_val = 0.0
            if len(cols) >= 4:
                change_str = cols[3].text.strip().replace("+", "").replace(",", "")
                try:
                    change_val = float(change_str)
                except ValueError:
                    pass
                    
            open_val = round(close_val - change_val, 2)
            high_val = round(max(open_val, close_val), 2)
            low_val = round(min(open_val, close_val), 2)
            
            # Verify date format is YYYY-MM-DD
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
                
            # Check if record already exists
            exists = db.query(StockHistory).filter(
                StockHistory.ticker == ticker,
                StockHistory.date == date_str
            ).first()
            
            if not exists:
                hist_item = StockHistory(
                    ticker=ticker,
                    date=date_str,
                    open=open_val,
                    high=high_val,
                    low=low_val,
                    close=close_val,
                    volume=volume
                )
                db.add(hist_item)
                added_count += 1
                
        if added_count > 0:
            db.commit()
            logger.info(f"Synced {added_count} historical records from Kwayisi for {ticker}")
        else:
            logger.info(f"No new records to sync for {ticker}")
            
        db.close()
        return added_count
    except Exception as e:
        logger.error(f"Error syncing history for {ticker} from Kwayisi: {e}")
        return 0

def sync_all_history(period: str = "6mo") -> int:
    """Syncs history for active user stocks (watchlist & portfolio) with rate-limiting controls."""
    total_added = 0
    
    # Query database to find user-active tickers
    db = SessionLocal()
    active_tickers = set()
    try:
        from auth.models import WatchlistItem, PortfolioItem
        # Get watchlist tickers
        wl = db.query(WatchlistItem.ticker).distinct().all()
        active_tickers.update([w[0].upper().strip() for w in wl if w[0]])
        # Get portfolio tickers
        pf = db.query(PortfolioItem.ticker).distinct().all()
        active_tickers.update([p[0].upper().strip() for p in pf if p[0]])
    except Exception as e:
        logger.warning(f"Error querying active tickers for bulk sync: {e}")
    finally:
        db.close()

    # Fallback to top core tickers if no active items yet to keep dashboard loaded
    if not active_tickers:
        active_tickers = {"SCOM", "EQTY", "KCB", "COOP", "BRIT", "EABL", "ABSA", "NCBA"}
        
    tickers = sorted(list(active_tickers))
    logger.info(f"Targeting active/core tickers for history sync: {tickers}")
    
    for index, ticker in enumerate(tickers):
        # Break immediately if circuit breaker got triggered in a previous loop step
        if time.time() < _SYNC_BLOCKED_UNTIL:
            logger.warning("Aborting bulk history sync loop due to active rate-limit block.")
            break
            
        # Add random crawl delay to prevent IP blocking
        if index > 0:
            sleep_time = random.uniform(2.0, 4.0)
            logger.info(f"Rate-limiting: Sleeping for {sleep_time:.2f}s before fetching {ticker}...")
            time.sleep(sleep_time)
            
        total_added += sync_stock_history(ticker, period)
        
    logger.info(f"All history sync complete. Total new records added: {total_added}")
    return total_added
