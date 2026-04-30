"""NSE AI Platform — News Router"""
from fastapi import APIRouter, Query
from typing import Optional
from data.fetcher import get_news_feed
from ml.sentiment import analyse

router = APIRouter(prefix="/api/news", tags=["News"])


@router.get("")
def get_news(ticker: Optional[str] = Query(None, description="Filter by NSE ticker")):
    """Return Kenyan financial news with sentiment labels."""
    articles = get_news_feed(ticker_filter=ticker)
    enriched = []
    for article in articles:
        text      = article["title"] + " " + article["summary"]
        sentiment = analyse(text)
        enriched.append({
            **article,
            "sentiment": {
                "label":     sentiment.label,
                "score":     sentiment.score,
                "score_pct": f"{sentiment.score * 100:.0f}%",
                "reasoning": sentiment.reasoning,
            }
        })
    return {"articles": enriched, "count": len(enriched)}
