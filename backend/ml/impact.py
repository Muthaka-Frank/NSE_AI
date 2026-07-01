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


from ml.relevance import evaluate_relevance

def get_matching_sentences(ticker: str, company_name: str, title: str, summary: str) -> list[str]:
    import re
    all_text = title + " " + summary
    cleaned_name = company_name
    for suffix in ["PLC", "Limited", "Ltd", "Group", "Holdings", "Holding", "Co.", "Co", "Ltd.", "Company"]:
        cleaned_name = re.sub(rf"\b{suffix}\b", "", cleaned_name, flags=re.IGNORECASE)
    name_lower = cleaned_name.strip().lower()
    ticker_lower = ticker.lower()
    
    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', all_text)
    matching = []
    for s in sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        s_lower = s_clean.lower()
        if (ticker_lower in s_lower) or (name_lower in s_lower):
            matching.append(s_clean)
    return matching

def get_transmission_mechanism(reason: str, is_direct: bool) -> str:
    r_lower = reason.lower()
    if is_direct:
        if "dividend" in r_lower or "payout" in r_lower:
            return "Dividend Payout"
        elif "earnings" in r_lower or "profit" in r_lower or "revenue" in r_lower or "financials" in r_lower:
            return "Corporate Earnings"
        elif "acquisition" in r_lower or "merger" in r_lower or "takeover" in r_lower:
            return "M&A Activity"
        elif "layoffs" in r_lower or "redundancy" in r_lower or "job cuts" in r_lower:
            return "Labor / Cost Scaling"
        elif "regulatory" in r_lower or "investigation" in r_lower or "fine" in r_lower or "compliance" in r_lower:
            return "Regulatory / Compliance"
        elif "contract" in r_lower or "partnership" in r_lower or "opportunity" in r_lower:
            return "Business Expansion"
        return "Corporate News Sentiment"
    else:
        if "energy costs" in r_lower or "tariff" in r_lower or "fuel" in r_lower:
            return "Macro Energy Cost Channel"
        elif "inflation" in r_lower:
            return "Macro Inflation Channel"
        elif "interest rate" in r_lower or "margin" in r_lower:
            return "Macro Interest Rate Channel"
        elif "shilling" in r_lower or "import" in r_lower:
            return "Exchange Rate Channel"
        elif "tax" in r_lower or "vat" in r_lower or "levy" in r_lower:
            return "Government / Tax Channel"
        return "Macroeconomic Spillover"

def analyse_ticker_impacts(article: dict) -> dict:
    """
    For a news article, return a dict mapping each related ticker
    to its impact: {direction, reason, confidence, is_direct, relevance, transmission_mechanism, matching_sentences}.
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
        meta = NSE_STOCKS.get(ticker, {})
        company_name = meta.get("name", ticker)
        
        # Evaluate relevance
        relevance_score = evaluate_relevance(ticker, company_name, title, summary, len(tickers))
        
        # Discard low-relevance matches
        if relevance_score < 0.45:
            continue
            
        direction, reason, confidence = _direct_impact(ticker, overall, text)
        mechanism = get_transmission_mechanism(reason, is_direct=True)
        sentences = get_matching_sentences(ticker, company_name, title, summary)
        
        impacts[ticker] = {
            "direction":              direction,
            "reason":                 reason,
            "confidence":             confidence,
            "is_direct":              True,
            "relevance":              relevance_score,
            "transmission_mechanism": mechanism,
            "matching_sentences":     sentences
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
                mechanism = get_transmission_mechanism(reason, is_direct=False)
                # Spillover relevance is linked to the overall article sentiment strength
                spillover_relevance = round(overall.score * 0.8, 3)
                
                impacts[ticker] = {
                    "direction":              direction,
                    "reason":                 reason,
                    "confidence":             round(overall.score * 0.7, 3),  # lower confidence for spillover
                    "is_direct":              False,
                    "relevance":              spillover_relevance,
                    "transmission_mechanism": mechanism,
                    "matching_sentences":     []  # Sector spillovers are conceptual/macro
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
