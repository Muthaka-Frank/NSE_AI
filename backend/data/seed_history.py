"""
NSE AI Platform — CSV History Seeder Script
Imports historical price tables (customized for NSE daily/annual report format).
Usage:
  Single-Ticker: venv/Scripts/python.exe data/seed_history.py <TICKER> <PATH_TO_CSV>
  Multi-Ticker:  venv/Scripts/python.exe data/seed_history.py ALL <PATH_TO_CSV>
"""
import sys
import os
import csv
import logging
from datetime import datetime

# Adjust path to import backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth.database import SessionLocal, init_db
from auth.models import StockHistory

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seeder")

def parse_volume(vol_str: str) -> int:
    """Clean volume string and parse suffixes like M or K."""
    if not vol_str:
        return 0
    vol_str = vol_str.strip().upper().replace(",", "")
    if vol_str == "-" or vol_str == "":
        return 0
    try:
        if "M" in vol_str:
            return int(float(vol_str.replace("M", "")) * 1_000_000)
        elif "K" in vol_str:
            return int(float(vol_str.replace("K", "")) * 1_000)
        else:
            return int(float(vol_str))
    except ValueError:
        return 0

def parse_date(date_str: str) -> str:
    """Parse various date formats to standard YYYY-MM-DD."""
    date_str = date_str.strip().replace('"', '')
    # Normalize 4-letter month abbreviations like Sept -> Sep, Sept. -> Sep
    date_str = date_str.replace("Sept", "Sep").replace("sept", "Sep")
    date_str = date_str.replace("June", "Jun").replace("june", "Jun")
    date_str = date_str.replace("July", "Jul").replace("july", "Jul")
    # Supported formats including Day-MonthName-Year (e.g., 02-Jan-25)
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Could not parse date format for: '{date_str}'")

def parse_float(val_str: str, default: float = 0.0) -> float:
    """Safely parse float values, handling dashes and commas."""
    if not val_str:
        return default
    val_str = val_str.strip().replace(",", "")
    if val_str == "-" or val_str == "":
        return default
    try:
        return float(val_str)
    except ValueError:
        return default

def seed_from_csv(target_ticker: str, csv_path: str):
    target_ticker = target_ticker.upper().strip()
    if not os.path.exists(csv_path):
        logger.error(f"CSV file not found: {csv_path}")
        return

    init_db()  # Ensure tables exist
    db = SessionLocal()
    added_count = 0
    skipped_count = 0

    logger.info(f"Reading CSV from {csv_path} (Filter Ticker: {target_ticker})...")
    try:
        # Detect delimiter (e.g., commas or tabs/semicolons)
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            sample = f.read(2048)
            dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
            f.seek(0)
            
            reader = csv.DictReader(f, dialect=dialect)
            
            # Map column names (strip quotes/whitespace)
            fieldnames = [fn.strip().replace('"', '') for fn in reader.fieldnames]
            reader.fieldnames = fieldnames
            
            # Determine column mappings
            date_col = next((c for c in fieldnames if "date" in c.lower()), None)
            close_col = next((c for c in fieldnames if c.lower() in ["close", "price", "day price"]), None)
            open_col = next((c for c in fieldnames if c.lower() in ["open", "previous"]), None)
            high_col = next((c for c in fieldnames if c.lower() in ["high", "day high"]), None)
            low_col = next((c for c in fieldnames if c.lower() in ["low", "day low"]), None)
            vol_col = next((c for c in fieldnames if c.lower() in ["vol.", "volume", "vol"]), None)
            ticker_col = next((c for c in fieldnames if c.lower() in ["code", "ticker", "symbol", "stock"]), None)

            if not date_col or not close_col:
                logger.error(f"Missing required columns in CSV. Found columns: {fieldnames}")
                return

            if not ticker_col and target_ticker == "ALL":
                logger.error("CSV does not contain a Ticker/Code column. You must specify a specific ticker name instead of 'ALL'.")
                return

            rows = list(reader)
            # Process oldest first
            rows.reverse()

            for row_idx, row in enumerate(rows):
                try:
                    # Determine row ticker
                    row_ticker = row[ticker_col].upper().strip() if ticker_col else target_ticker
                    
                    # Filter if we are targeting a specific ticker
                    if target_ticker != "ALL" and row_ticker != target_ticker:
                        continue

                    date_val = parse_date(row[date_col])
                    close_val = parse_float(row[close_col])
                    
                    open_val = parse_float(row[open_col]) if open_col and row[open_col] else close_val
                    high_val = parse_float(row[high_col]) if high_col and row[high_col] else close_val
                    low_val = parse_float(row[low_col]) if low_col and row[low_col] else close_val
                    volume = parse_volume(row[vol_col]) if vol_col and row[vol_col] else 0

                    # Check if already exists in DB
                    exists = db.query(StockHistory).filter(
                        StockHistory.ticker == row_ticker,
                        StockHistory.date == date_val
                    ).first()

                    if not exists:
                        hist_item = StockHistory(
                            ticker=row_ticker,
                            date=date_val,
                            open=open_val,
                            high=high_val,
                            low=low_val,
                            close=close_val,
                            volume=volume
                        )
                        db.add(hist_item)
                        added_count += 1
                    else:
                        skipped_count += 1

                except Exception as row_err:
                    logger.warning(f"Row {row_idx + 1} skipped due to parsing error: {row_err}")
                    continue

        if added_count > 0:
            db.commit()
            logger.info(f"Successfully seeded {added_count} records. (Skipped {skipped_count} existing).")
        else:
            logger.info(f"No new records added. (All {skipped_count} already existed in database).")

    except Exception as e:
        logger.error(f"Failed to process CSV file: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python seed_history.py <TICKER/ALL> <CSV_FILE_PATH>")
        sys.exit(1)
    
    seed_ticker = sys.argv[1]
    seed_path = sys.argv[2]
    seed_from_csv(seed_ticker, seed_path)
