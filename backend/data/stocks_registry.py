import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

STOCKS_JSON_PATH = os.path.join(os.path.dirname(__file__), "stocks.json")

DEFAULT_STOCKS = {
    "SCOM": {"name": "Safaricom PLC",           "sector": "Telecommunications", "yahoo": "SCOM.NR", "base_price": 30.90},
    "EQTY": {"name": "Equity Group Holdings",   "sector": "Banking",            "yahoo": "EQTY.NR", "base_price": 72.00},
    "KCB":  {"name": "KCB Group PLC",           "sector": "Banking",            "yahoo": "KCB.NR", "base_price": 67.50},
    "COOP": {"name": "Co-operative Bank",       "sector": "Banking",            "yahoo": "COOP.NR", "base_price": 31.85},
    "EABL": {"name": "East African Breweries",  "sector": "Consumer Staples",   "yahoo": "EABL.NR", "base_price": 248.25},
    "BAT":  {"name": "BAT Kenya",               "sector": "Consumer Staples",   "yahoo": "BAT.NR", "base_price": 520.00},
    "KPLC": {"name": "Kenya Power & Lighting",  "sector": "Energy",             "yahoo": "KPLC.NR", "base_price": 15.50},
    "ABSA": {"name": "Absa Bank Kenya",         "sector": "Banking",            "yahoo": "ABSA.NR", "base_price": 29.60},
    "NCBA": {"name": "NCBA Group PLC",          "sector": "Banking",            "yahoo": "NCBA.NR", "base_price": 89.00},
    "STND": {"name": "Standard Chartered Kenya","sector": "Banking",            "yahoo": "SCBK.NR", "base_price": 342.75},
    "BAMB": {"name": "Bamburi Cement",          "sector": "Manufacturing",      "yahoo": "BAMB.NR", "base_price": 54.00},
    "KENR": {"name": "Kenya Re-Insurance",      "sector": "Insurance",          "yahoo": "KENR.NR", "base_price": 3.30},
    "JUB":  {"name": "Jubilee Holdings",        "sector": "Insurance",          "yahoo": "JUB.NR", "base_price": 366.00},
    "SBIC": {"name": "Stanbic Holdings",        "sector": "Banking",            "yahoo": "SBIC.NR", "base_price": 270.00},
    "HFCK": {"name": "HF Group",               "sector": "Banking",            "yahoo": "HFCK.NR", "base_price": 9.78},
    "IMH":  {"name": "I&M Group PLC",           "sector": "Banking",            "yahoo": "IMH.NR", "base_price": 21.00},
    "DTK":  {"name": "Diamond Trust Bank Kenya","sector": "Banking",            "yahoo": "DTK.NR", "base_price": 54.00},
    "BRIT": {"name": "Britam Holdings PLC",     "sector": "Insurance",          "yahoo": "BRIT.NR", "base_price": 5.20},
    "CIC":  {"name": "CIC Insurance Group",     "sector": "Insurance",          "yahoo": "CIC.NR", "base_price": 2.20},
    "KEGN": {"name": "KenGen",                  "sector": "Energy",             "yahoo": "KEGN.NR", "base_price": 2.30},
    "TOTL": {"name": "TotalEnergies Marketing", "sector": "Energy",             "yahoo": "TOTL.NR", "base_price": 18.00},
    "CTUM": {"name": "Centum Investment Company","sector": "Investment",          "yahoo": "CTUM.NR", "base_price": 9.00},
    "UNGA": {"name": "Unga Group PLC",          "sector": "Manufacturing",      "yahoo": "UNGA.NR", "base_price": 17.00},
    "KUKZ": {"name": "Kakuzi PLC",              "sector": "Agricultural",      "yahoo": "KUKZ.NR", "base_price": 385.00},
    "SASN": {"name": "Sasini PLC",              "sector": "Agricultural",      "yahoo": "SASN.NR", "base_price": 20.00},
    "FMLY": {"name": "Family Bank Limited",     "sector": "Banking",            "yahoo": "FMLY.NR", "base_price": 18.00},
}

# In-memory dynamic references that other modules will import
NSE_STOCKS = {}
_TRACKED_TICKERS = []
BASE_PRICES = {}

def load_registry():
    """Load stocks from stocks.json, creating it with defaults if missing."""
    global NSE_STOCKS, _TRACKED_TICKERS, BASE_PRICES
    
    # 1. Load or initialize JSON file
    if not os.path.exists(STOCKS_JSON_PATH):
        try:
            with open(STOCKS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_STOCKS, f, indent=4)
            logger.info("Initialized stocks.json registry with default stocks.")
        except Exception as e:
            logger.error("Failed to write default stocks.json: %s", e)
            
    loaded_stocks = DEFAULT_STOCKS.copy()
    if os.path.exists(STOCKS_JSON_PATH):
        try:
            with open(STOCKS_JSON_PATH, "r", encoding="utf-8") as f:
                loaded_stocks = json.load(f)
        except Exception as e:
            logger.error("Failed to read stocks.json, using defaults: %s", e)
            
    # 2. Modify in-memory dictionaries in-place to preserve imports references
    NSE_STOCKS.clear()
    NSE_STOCKS.update(loaded_stocks)
    
    _TRACKED_TICKERS.clear()
    _TRACKED_TICKERS.extend(list(loaded_stocks.keys()))
    
    BASE_PRICES.clear()
    BASE_PRICES.update({ticker: info.get("base_price", 10.0) for ticker, info in loaded_stocks.items()})

def guess_sector(company_name: str) -> str:
    """Heuristic helper to guess NSE stock sector from its name."""
    name_lower = company_name.lower()
    if "bank" in name_lower or "holdings" in name_lower and any(w in name_lower for w in ["kcb", "absa", "equity", "coop", "stanbic", "standard"]):
        return "Banking"
    if "insurance" in name_lower or "re-insurance" in name_lower or "reinsurance" in name_lower:
        return "Insurance"
    if "telecom" in name_lower or "safaricom" in name_lower or "mobile" in name_lower:
        return "Telecommunications"
    if "power" in name_lower or "lighting" in name_lower or "electricity" in name_lower or "kengen" in name_lower or "total" in name_lower or "petroleum" in name_lower:
        return "Energy"
    if "breweries" in name_lower or "tobacco" in name_lower or "unilever" in name_lower or "diageo" in name_lower:
        return "Consumer Staples"
    if "cement" in name_lower or "carbacid" in name_lower or "bamburi" in name_lower or "manufacturing" in name_lower:
        return "Manufacturing"
    if "investment" in name_lower or "centum" in name_lower or "capital" in name_lower or "development" in name_lower:
        return "Investment"
    if "tea" in name_lower or "coffee" in name_lower or "agriculture" in name_lower or "sasini" in name_lower or "kakuzi" in name_lower or "limuru" in name_lower:
        return "Agricultural"
    return "Investment"  # default fallback

def add_new_stock(ticker: str, name: str, sector: Optional[str] = None, price: Optional[float] = None) -> bool:
    """Add a new stock listing permanently to the registry."""
    global NSE_STOCKS
    ticker = ticker.upper().strip()
    if ticker in NSE_STOCKS:
        return False
        
    if not sector:
        sector = guess_sector(name)
        
    base_price = price if price is not None else 10.0
    
    new_entry = {
        "name": name,
        "sector": sector,
        "yahoo": f"{ticker}.NR",
        "base_price": base_price
    }
    
    # Read current, modify, and save
    current_stocks = DEFAULT_STOCKS.copy()
    if os.path.exists(STOCKS_JSON_PATH):
        try:
            with open(STOCKS_JSON_PATH, "r", encoding="utf-8") as f:
                current_stocks = json.load(f)
        except Exception:
            pass
            
    current_stocks[ticker] = new_entry
    
    try:
        with open(STOCKS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(current_stocks, f, indent=4)
        logger.info("Permanently added new stock listing %s (%s) to registry.", ticker, name)
        
        # Reload to update active lists in memory
        load_registry()
        return True
    except Exception as e:
        logger.error("Failed to save new stock to stocks.json: %s", e)
        return False

# Initialize registry on import
load_registry()
