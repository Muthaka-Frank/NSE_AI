import threading
import time
from datetime import datetime
import pytz
import logging
from auth.database import SessionLocal
from auth.models import StockHistory
from data.nse_scraper import get_all_prices

logger = logging.getLogger(__name__)
NAIROBI_TZ = pytz.timezone("Africa/Nairobi")

def run_daily_scrape():
    """Scrapes closing prices and saves them to StockHistory."""
    logger.info("Starting scheduled daily NSE stock history scrape...")
    try:
        prices = get_all_prices()
        if not prices:
            logger.warning("Daily scrape: No prices fetched from scraper.")
            return

        db = SessionLocal()
        today_str = datetime.now(NAIROBI_TZ).strftime("%Y-%m-%d")
        
        added_count = 0
        for ticker, data in prices.items():
            # Check if record already exists for today and this ticker
            exists = db.query(StockHistory).filter(
                StockHistory.ticker == ticker,
                StockHistory.date == today_str
            ).first()
            
            if not exists:
                price = data.get("price", 0.0)
                hist_item = StockHistory(
                    ticker=ticker,
                    date=today_str,
                    open=data.get("open", price),
                    high=data.get("high", price),
                    low=data.get("low", price),
                    close=price,
                    volume=data.get("volume", 0)
                )
                db.add(hist_item)
                added_count += 1
                
        if added_count > 0:
            db.commit()
            logger.info("Daily scrape complete: saved %d records for %s", added_count, today_str)
        else:
            logger.info("Daily scrape: records for %s already exist.", today_str)
            
        db.close()
    except Exception as e:
        logger.error("Error in daily stock history scrape task: %s", e)

def _scheduler_loop():
    """Loops and checks time to run the scrape daily at 18:00 EAT (6:00 PM)."""
    logger.info("NSE background scheduler loop started.")
    last_run_date = None
    while True:
        try:
            now = datetime.now(NAIROBI_TZ)
            # Run at 18:00 EAT (6:00 PM) or later if not yet run today
            if now.hour >= 18 and last_run_date != now.date():
                run_daily_scrape()
                last_run_date = now.date()
        except Exception as e:
            logger.error("Error in scheduler loop: %s", e)
        # Check every 15 minutes
        time.sleep(900)

def start_scheduler():
    """Starts the background scheduler thread."""
    t = threading.Thread(target=_scheduler_loop, daemon=True)
    t.start()
