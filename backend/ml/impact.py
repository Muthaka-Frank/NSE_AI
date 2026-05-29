"""
NSE AI Platform — News Impact Analyser
For each news article, determines per-ticker impact:
  direction: POSITIVE | NEGATIVE | NEUTRAL
  reason: one-line human-readable explanation
  confidence: 0.0 - 1.0
"""

from ml.sentiment import analyse, SentimentResult

SECTOR_MAP = {
    "Banking":         ["EQTY", "KCB", "COOP", "ABSA", "NCBA", "STND", "SBIC", "HFCK", "IMH", "DTK"],
    "Telecommunications": ["SCOM"],
    "Consumer Staples":["EABL", "BAT"],
    "Energy":          ["KPLC", "KEGN", "TOTL"],
    "Manufacturing":   ["BAMB", "UNGA"],
    "Insurance":       ["KENR", "JUB", "BRIT", "CIC"],
    "Investment":      ["CTUM"],
    "Agricultural":    ["KUKZ", "SASN"],
}

TICKER_SECTOR = {t: s for s, tickers in SECTOR_MAP.items() for t in tickers}

# Keyword rules that override general sentiment for specific contexts
# Format: (keywords, affected_sectors_or_tickers, direction, reason_template)
DOMAIN_RULES = [
    # Interest rates
    ({"interest rate", "cbk rate", "central bank rate", "mpr"},
     ["Banking"], "POSITIVE",
     "Higher interest rates typically widen banking net interest margins"),
    ({"rate cut", "lower rates", "rate reduction"},
     ["Banking"], "NEGATIVE",
     "Rate cuts compress banking net interest margins"),

    # Inflation
    ({"inflation", "cpi", "cost of living"},
     ["Consumer Staples", "Manufacturing"], "NEGATIVE",
     "Rising inflation squeezes consumer goods margins"),
    ({"inflation", "cpi"},
     ["Banking"], "NEGATIVE",
     "Elevated inflation can erode real loan book returns"),

    # Fuel / energy
    ({"fuel", "electricity", "power tariff", "energy costs"},
     ["Manufacturing", "Consumer Staples"], "NEGATIVE",
     "Higher energy costs increase production expenses"),
    ({"fuel levy", "tariff hike", "electricity tariff"},
     ["Energy"], "POSITIVE",
     "Higher tariffs directly boost Kenya Power revenue"),

    # Telecom / mobile money
    ({"mobile money", "mpesa", "m-pesa", "fintech"},
     ["Telecommunications"], "POSITIVE",
     "Mobile money growth expands transaction revenue"),
    ({"data prices", "mobile data", "sim card"},
     ["Telecommunications"], "NEGATIVE",
     "Regulatory pressure on data prices limits revenue growth"),

    # NSE / market
    ({"nse", "nairobi securities", "stock market"},
     None, "NEUTRAL",
     "Broad market news — monitor for sector-specific developments"),

    # Shilling / forex
    ({"shilling", "kes", "forex", "exchange rate", "dollar"},
     ["Consumer Staples", "Manufacturing"], "NEGATIVE",
     "Shilling weakness raises cost of imported inputs"),
    ({"shilling", "kes"},
     ["Banking"], "POSITIVE",
     "Currency volatility can boost forex trading income"),

    # Government / taxation
    ({"tax", "vat", "excise", "levy"},
     ["Consumer Staples"], "NEGATIVE",
     "Higher taxation on consumer goods reduces demand"),
    ({"government contract", "public tender", "infrastructure"},
     ["Manufacturing"], "POSITIVE",
     "Government contracts provide stable order books"),
]


def analyse_ticker_impacts(article: dict) -> dict:
    """
    For a news article, return a dict mapping each related ticker
    to its impact: {direction, reason, confidence, is_direct}.
    """
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
