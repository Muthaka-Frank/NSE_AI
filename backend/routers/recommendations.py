"""NSE AI Platform — Recommendations Router"""
import time
import threading
from fastapi import APIRouter
from data.fetcher import get_all_stocks, get_batch_historical_data, get_news_feed
from ml.predictor import predict, CONFIDENCE_THRESHOLD

router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])

# In-memory recommendations cache
_RECS_CACHE = None
_RECS_CACHE_TIMESTAMP = 0.0
_RECS_CACHE_TTL = 60.0  # 60 seconds
_RECS_LOCK = threading.Lock()


def clear_recommendations_cache():
    """Manually invalidates the in-memory recommendations cache."""
    global _RECS_CACHE, _RECS_CACHE_TIMESTAMP
    with _RECS_LOCK:
        _RECS_CACHE = None
        _RECS_CACHE_TIMESTAMP = 0.0


@router.get("")
def get_recommendations():
    """
    Return AI-ranked BUY and SELL signals above the confidence threshold.
    Optimized with single-batch SQLite querying and a 60-second in-memory cache.
    """
    global _RECS_CACHE, _RECS_CACHE_TIMESTAMP
    now = time.time()
    if _RECS_CACHE is not None and (now - _RECS_CACHE_TIMESTAMP) < _RECS_CACHE_TTL:
        return _RECS_CACHE

    with _RECS_LOCK:
        if _RECS_CACHE is not None and (time.time() - _RECS_CACHE_TIMESTAMP) < _RECS_CACHE_TTL:
            return _RECS_CACHE

        stocks = get_all_stocks()
        news   = get_news_feed()
        tickers = [s["ticker"] for s in stocks]

        # Single batch query to SQLite database for all 60+ stocks
        histories = get_batch_historical_data(tickers, "3mo")

        buys, sells = [], []
        for stock in stocks:
            ticker  = stock["ticker"]
            history = histories.get(ticker, [])

            # Aggregate sentiment from related news with exponential time-decay
            related = [a for a in news if ticker in a.get("related_tickers", [])]
            sentiment = None
            if related:
                from ml.sentiment import aggregate_sentiment_with_decay
                sentiment = aggregate_sentiment_with_decay(related[:5])

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

        response = {
            "recommendations": all_signals,
            "buys":            buys,
            "sells":           sells,
            "count":           len(all_signals),
            "threshold":       CONFIDENCE_THRESHOLD,
            "disclaimer":      "AI signals are informational only. Not financial advice.",
        }

        _RECS_CACHE = response
        _RECS_CACHE_TIMESTAMP = time.time()
        return response


@router.get("/alerts")
def get_alerts():
    """Return only STRONG confidence signals as actionable alerts."""
    all_recs = get_recommendations()
    alerts   = [r for r in all_recs["recommendations"] if r["signal_strength"] == "STRONG"]
    return {"alerts": alerts, "count": len(alerts)}
