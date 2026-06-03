"""NSE AI Platform — Recommendations Router"""
from fastapi import APIRouter
from data.fetcher import get_all_stocks, get_historical_data
from ml.predictor import predict, CONFIDENCE_THRESHOLD
from ml.sentiment import analyse
from data.fetcher import get_news_feed

router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])


@router.get("")
def get_recommendations():
    """
    Return AI-ranked BUY and SELL signals above the confidence threshold.
    Stocks with unclear signals are excluded — no guessing.
    """
    stocks = get_all_stocks()
    news   = get_news_feed()
    buys, sells = [], []

    for stock in stocks:
        ticker  = stock["ticker"]
        history = get_historical_data(ticker, "3mo")

        # Aggregate sentiment from related news
        related = [a for a in news if ticker in a.get("related_tickers", [])]
        sentiment = None
        if related:
            texts      = [a["title"] + " " + a["summary"] for a in related[:5]]
            sentiments = [analyse(t) for t in texts]
            pos = sum(1 for s in sentiments if s.label == "POSITIVE")
            neg = sum(1 for s in sentiments if s.label == "NEGATIVE")
            avg = sum(s.score for s in sentiments) / len(sentiments)
            from ml.sentiment import SentimentResult
            label     = "POSITIVE" if pos > neg else ("NEGATIVE" if neg > pos else "NEUTRAL")
            sentiment = SentimentResult(label=label, score=round(avg, 3),
                                        reasoning=f"Based on {len(related)} news articles")

        result = predict(ticker, history, sentiment)

        if result.confidence < CONFIDENCE_THRESHOLD or result.direction == "NO_SIGNAL":
            continue

        entry = {
            "ticker":          ticker,
            "name":            stock["name"],
            "sector":          stock["sector"],
            "price":           stock["price"],
            "change_pct":      stock["change_pct"],
            "direction":       result.direction,
            "confidence":      result.confidence,
            "confidence_pct":  f"{result.confidence * 100:.1f}%",
            "signal_strength": result.signal_strength,
            "price_target":    result.price_target,
            "risk_level":      result.risk_level,
            "timeframe":       result.timeframe,
            "reasoning":       result.reasoning[:3],
            "news_sentiment":  sentiment.label if sentiment else "NEUTRAL",
        }

        if result.direction == "BUY":
            buys.append(entry)
        elif result.direction == "SELL":
            sells.append(entry)

    buys.sort(key=lambda x: x["confidence"], reverse=True)
    sells.sort(key=lambda x: x["confidence"], reverse=True)
    all_signals = buys + sells

    return {
        "recommendations": all_signals,
        "buys":            buys,
        "sells":           sells,
        "count":           len(all_signals),
        "threshold":       CONFIDENCE_THRESHOLD,
        "disclaimer":      "AI signals are informational only. Not financial advice.",
    }


@router.get("/alerts")
def get_alerts():
    """Return only STRONG confidence signals as actionable alerts."""
    all_recs = get_recommendations()
    alerts   = [r for r in all_recs["recommendations"] if r["signal_strength"] == "STRONG"]
    return {"alerts": alerts, "count": len(alerts)}
