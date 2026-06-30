"""
NSE AI Platform — News Impact Analyser
For each news article, determines per-ticker impact:
  direction: POSITIVE | NEGATIVE | NEUTRAL
  reason: one-line human-readable explanation
  confidence: 0.0 - 1.0
"""

from ml.sentiment import analyse, SentimentResult
from data.stocks_registry import NSE_STOCKS

SECTOR_MAP = {}
TICKER_SECTOR = {}

def refresh_sector_maps():
    global SECTOR_MAP, TICKER_SECTOR
    SECTOR_MAP.clear()
    TICKER_SECTOR.clear()
    for ticker, info in NSE_STOCKS.items():
        sector = info.get("sector", "Investment")
        if sector not in SECTOR_MAP:
            SECTOR_MAP[sector] = []
        SECTOR_MAP[sector].append(ticker)
        TICKER_SECTOR[ticker] = sector

# Run initially
refresh_sector_maps()

# Keyword rules that override general sentiment for specific contexts
# Format: (keywords, affected_sectors_or_tickers, direction, reason_template)
DOMAIN_RULES = [
    # Interest rates
    ({"interest rate hike", "rate hike", "higher interest rates", "cbk raises rates", "raises central bank rate", "mpr hike"},
     ["Banking"], "POSITIVE",
     "Higher interest rates typically widen banking net interest margins"),
    ({"rate cut", "lower interest rates", "rate reduction", "cbk cuts rates", "cuts central bank rate", "mpr cut"},
     ["Banking"], "NEGATIVE",
     "Rate cuts compress banking net interest margins"),

    # Inflation
    ({"rising inflation", "inflation rises", "elevated inflation", "inflation spike", "cost of living rise"},
     ["Consumer Staples", "Manufacturing"], "NEGATIVE",
     "Rising inflation squeezes consumer goods margins"),
    ({"rising inflation", "elevated inflation", "inflation spike"},
     ["Banking"], "NEGATIVE",
     "Elevated inflation can erode real loan book returns"),

    # Fuel / energy
    ({"fuel price hike", "fuel prices rise", "electricity tariff hike", "rising fuel costs", "expensive power", "higher power costs", "energy costs rise"},
     ["Manufacturing", "Consumer Staples"], "NEGATIVE",
     "Higher energy costs increase production expenses"),
    ({"fuel levy", "electricity tariff hike", "power prices up"},
     ["Energy"], "POSITIVE",
     "Higher tariffs directly boost Kenya Power revenue"),

    # Telecom / mobile money
    ({"mpesa growth", "m-pesa transaction volume", "mobile money revenue", "mpesa expansion"},
     ["Telecommunications"], "POSITIVE",
     "Mobile money growth expands transaction revenue"),
    ({"data price cut", "lower data prices", "sim card registration rules", "data price cap"},
     ["Telecommunications"], "NEGATIVE",
     "Regulatory pressure on data prices limits revenue growth"),

    # NSE / market
    ({"nse", "nairobi securities", "stock market"},
     None, "NEUTRAL",
     "Broad market news — monitor for sector-specific developments"),

    # Shilling / forex
    ({"shilling depreciates", "shilling depreciation", "weak shilling", "shilling drops", "shilling weakens", "shilling slides", "falling shilling"},
     ["Consumer Staples", "Manufacturing"], "NEGATIVE",
     "Shilling weakness raises cost of imported inputs"),
    ({"shilling strengthens", "strong shilling", "shilling rally", "shilling gains", "shilling appreciates"},
     ["Consumer Staples", "Manufacturing"], "POSITIVE",
     "Stronger shilling lowers import costs for manufacturers"),
    ({"shilling volatility", "currency volatility", "forex trading gains", "kes volatility"},
     ["Banking"], "POSITIVE",
     "Currency volatility can boost forex trading income"),

    # Government / taxation
    ({"tax hike", "new vat", "excise duty increase", "higher tax", "increased taxation"},
     ["Consumer Staples"], "NEGATIVE",
     "Higher taxation on consumer goods reduces demand"),
    ({"government contract", "public tender", "infrastructure project", "contract award"},
     ["Manufacturing"], "POSITIVE",
     "Government contracts provide stable order books"),
]


def analyse_ticker_impacts(article: dict) -> dict:
    """
    For a news article, return a dict mapping each related ticker
    to its impact: {direction, reason, confidence, is_direct}.
    """
    refresh_sector_maps()
    title   = article.get("title", "")
    summary = article.get("summary", "")
    text    = (title + " " + summary).lower()
    tickers = article.get("related_tickers", [])

    overall = analyse(title + " " + summary)
    impacts: dict = {}

    # 1. Direct ticker mentions — use overall article sentiment
    for ticker in tickers:
        direction, reason, confidence = _direct_impact(ticker, overall, text)
        impacts[ticker] = {
            "direction":  direction,
            "reason":     reason,
            "confidence": confidence,
            "is_direct":  True,
        }

    # 2. Domain rules — may add additional affected tickers (sector spillover)
    for keywords, targets, direction, reason in DOMAIN_RULES:
        if not any(kw in text for kw in keywords):
            continue

        affected_tickers = []
        if targets is None:
            continue
        for target in targets:
            # target may be a sector name or a specific ticker
            if target in SECTOR_MAP:
                affected_tickers.extend(SECTOR_MAP[target])
            elif target in TICKER_SECTOR:
                affected_tickers.append(target)

        for ticker in affected_tickers:
            if ticker not in impacts:
                # Only add as spillover if not already directly mentioned
                impacts[ticker] = {
                    "direction":  direction,
                    "reason":     reason,
                    "confidence": round(overall.score * 0.7, 3),  # lower confidence for spillover
                    "is_direct":  False,
                }

    return impacts


def _direct_impact(ticker: str, sentiment: SentimentResult, text: str) -> tuple:
    """Determine direct impact for a ticker based on article sentiment + context clues."""
    direction  = sentiment.label
    confidence = sentiment.score
    reason     = _build_reason(ticker, sentiment, text)
    return direction, reason, confidence


def _build_reason(ticker: str, sentiment: SentimentResult, text: str) -> str:
    """Generate a concise impact reason from article keywords."""
    refresh_sector_maps()
    sector = TICKER_SECTOR.get(ticker, "")

    # Priority keyword patterns → reason templates
    patterns = [
        (["profit", "earnings beat", "record profit", "revenue growth"],
         "POSITIVE", f"Strong earnings signal upside for {ticker} shareholders"),
        (["loss", "profit warning", "revenue decline", "missed targets"],
         "NEGATIVE", f"Weak financials may weigh on {ticker} share price"),
        (["dividend", "payout", "special dividend"],
         "POSITIVE", f"Dividend announcement is a direct positive for {ticker} investors"),
        (["acquisition", "merger", "takeover", "joint venture"],
         "POSITIVE", f"M&A activity could unlock value for {ticker}"),
        (["layoffs", "redundancy", "job cuts"],
         "NEGATIVE", f"Workforce reduction signals financial stress at {ticker}"),
        (["rating upgrade", "buy rating", "outperform"],
         "POSITIVE", f"Analyst upgrade strengthens bullish case for {ticker}"),
        (["downgrade", "sell rating", "underperform"],
         "NEGATIVE", f"Analyst downgrade raises caution on {ticker}"),
        (["regulatory", "investigation", "fine", "penalty"],
         "NEGATIVE", f"Regulatory risk creates uncertainty for {ticker}"),
        (["new contract", "partnership", "licence"],
         "POSITIVE", f"New business opportunity expands {ticker} revenue outlook"),
    ]

    for keywords, expected_dir, template in patterns:
        if expected_dir == sentiment.label and any(kw in text for kw in keywords):
            return template

    # Generic fallback based on sentiment + sector
    if sentiment.label == "POSITIVE":
        return f"Positive news sentiment likely to support {ticker}" + (f" ({sector})" if sector else "")
    elif sentiment.label == "NEGATIVE":
        return f"Negative news sentiment may pressure {ticker}" + (f" ({sector})" if sector else "")
    return f"Mixed signals — limited directional impact expected on {ticker}"
