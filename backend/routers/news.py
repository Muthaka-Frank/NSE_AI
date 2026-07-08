"""NSE AI Platform — News Router"""
from fastapi import APIRouter, Query
from typing import Optional
from data.fetcher import get_news_feed
from ml.sentiment import analyse
from ml.impact import analyse_ticker_impacts

router = APIRouter(prefix="/api/news", tags=["News"])


@router.get("")
def get_news(ticker: Optional[str] = Query(None, description="Filter by NSE ticker")):
    """
    Return Kenyan financial news with:
    - Overall sentiment label + score
    - Per-ticker impact analysis (direction, reason, confidence)
    """
    articles = get_news_feed(ticker_filter=ticker)
    enriched = []

    for article in articles:
        text      = article["title"] + " " + article["summary"]
        sentiment = analyse(text)
        impacts   = analyse_ticker_impacts(article)

        # Build a sorted impact list: direct mentions first, then spillovers
        impact_list = []
        for t, imp in impacts.items():
            impact_list.append({
                "ticker":     t,
                "direction":  imp["direction"],
                "reason":     imp["reason"],
                "confidence": imp["confidence"],
                "is_direct":  imp["is_direct"],
            })
        impact_list.sort(key=lambda x: (not x["is_direct"], -x["confidence"]))

        enriched.append({
            **article,
            "sentiment": {
                "label":     sentiment.label,
                "score":     sentiment.score,
                "score_pct": f"{sentiment.score * 100:.0f}%",
                "reasoning": sentiment.reasoning,
            },
            "ticker_impacts": impact_list,
        })

    return {"articles": enriched, "count": len(enriched)}
