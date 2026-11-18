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
from data.http_client import (
    safe_scrape_get,
    is_circuit_breaker_active,
    trip_circuit_breaker,
    polite_delay,
)

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
    if time.time() < _SYNC_BLOCKED_UNTIL or is_circuit_breaker_active():
        logger.warning(f"History sync skipped for {ticker} due to active rate-limit cooldown.")
        return 0
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
    
    logger.info(f"Politely syncing history for {ticker} from Kwayisi: {url}...")
    try:
        r = safe_scrape_get(url, timeout=(3.0, 6.0))
        if not r or r.status_code != 200:
            return 0
            
        try:
            soup = BeautifulSoup(r.text, "lxml")
        except Exception:
            soup = BeautifulSoup(r.text, "html.parser")

        import re
        table = soup.find("table", {"data-hist": True})
        if not table:
            for t in soup.find_all("table"):
                if t.find(string=re.compile(r"\d{4}-\d{2}-\d{2}")):
                    table = t
                    break

        if not table:
            logger.warning(f"No historical table found for {ticker}")
            return 0
            
        rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")[1:]
        
        db = SessionLocal()
        added_count = 0
        import re
        
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue
                
            date_raw = cols[0].text.strip()  # YYYY-MM-DD
            date_match = re.search(r"\d{4}-\d{2}-\d{2}", date_raw)
            if not date_match:
                continue
            date_str = date_match.group(0)

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
        
    tickers = sorted(list(active_tickers))[:5]  # Cap to 5 to protect IP address
    logger.info(f"Targeting active/core tickers for history sync (capped at 5 to protect IP): {tickers}")
    
    for index, ticker in enumerate(tickers):
        # Break immediately if circuit breaker got triggered in a previous loop step
        if time.time() < _SYNC_BLOCKED_UNTIL or is_circuit_breaker_active():
            logger.warning("Aborting bulk history sync loop due to active rate-limit block.")
            break
            
        # Add random crawl delay to prevent IP blocking
        if index > 0:
            polite_delay(3.5, 6.0)
            
        total_added += sync_stock_history(ticker, period)
        
    logger.info(f"All history sync complete. Total new records added: {total_added}")
    return total_added
