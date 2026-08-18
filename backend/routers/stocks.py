"""NSE AI Platform — Stocks Router"""
import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from data.fetcher import get_stock_info, get_all_stocks, get_historical_data, NSE_STOCKS, clear_cache, get_news_feed
from ml.predictor import predict
from ml.sentiment import analyse

router = APIRouter(prefix="/api/stocks", tags=["Stocks"])


@router.get("")
def list_stocks():
    """Return all NSE stocks with current prices."""
    return {"stocks": get_all_stocks(), "count": len(NSE_STOCKS)}


@router.get("/stream")
async def stream_stocks():
    """
    Server-Sent Events — pushes live stock updates every 30 seconds.
    Connect with: new EventSource('http://localhost:8000/api/stocks/stream')
    """
    async def generator():
        while True:
            try:
                stocks  = get_all_stocks()
                payload = json.dumps({
                    "type":      "stocks_update",
                    "stocks":    stocks,
                    "count":     len(stocks),
                    "timestamp": datetime.now().isoformat(),
                })
                yield f"data: {payload}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"
            await asyncio.sleep(30)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


@router.get("/{ticker}")
def stock_detail(ticker: str):
    """Return detailed info for a single stock."""
    info = get_stock_info(ticker.upper())
    if not info:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")
    return info


@router.get("/{ticker}/history")
def stock_history(ticker: str, period: str = "6mo"):
    """Return OHLCV historical data. Period: 1mo | 3mo | 6mo | 1y"""
    valid = {"1mo", "3mo", "6mo", "1y"}
    if period not in valid:
        raise HTTPException(status_code=400, detail=f"Period must be one of: {valid}")
    data = get_historical_data(ticker.upper(), period)
    if not data:
        raise HTTPException(status_code=404, detail=f"No history for '{ticker}'.")
    return {"ticker": ticker.upper(), "period": period, "data": data}


@router.get("/{ticker}/intraday")
def stock_intraday(ticker: str, date: str = None):
    """
    Return today's (or latest session's) intraday price snapshots recorded during market hours.
    Used for the 1D Live Intraday Price Chart.
    """
    ticker = ticker.upper()
    info = get_stock_info(ticker)
    if not info:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")

    from auth.database import SessionLocal
    from auth.models import StockIntraday
    from data.nse_scraper import is_market_open
    from datetime import datetime, timezone
    import pytz
    from core.config import settings

    nairobi_tz = pytz.timezone(settings.TIMEZONE_NAME)
    today_str = date or datetime.now(nairobi_tz).strftime("%Y-%m-%d")

    db = SessionLocal()
    try:
        # Fetch today's intraday ticks
        ticks = db.query(StockIntraday).filter(
            StockIntraday.ticker == ticker,
            StockIntraday.date == today_str
        ).order_by(StockIntraday.timestamp.asc()).all()

        target_date = today_str
        if not ticks:
            # If no ticks for today yet, find latest recorded session
            latest_tick = db.query(StockIntraday).filter(
                StockIntraday.ticker == ticker
            ).order_by(StockIntraday.date.desc(), StockIntraday.timestamp.desc()).first()

            if latest_tick:
                target_date = latest_tick.date
                ticks = db.query(StockIntraday).filter(
                    StockIntraday.ticker == ticker,
                    StockIntraday.date == target_date
                ).order_by(StockIntraday.timestamp.asc()).all()

        prev_close = info.get("price", 0.0) - info.get("change", 0.0)
        if prev_close <= 0:
            prev_close = info.get("price", 0.0)

        formatted_ticks = []
        if ticks:
            for t in ticks:
                formatted_ticks.append({
                    "time": t.timestamp,
                    "time_str": t.time[:5],
                    "price": t.price,
                    "change": round(t.price - prev_close, 2),
                    "change_pct": round(((t.price - prev_close) / prev_close) * 100, 2) if prev_close > 0 else 0.0,
                    "volume": t.volume
                })
        else:
            now_ts = int(datetime.now(timezone.utc).timestamp())
            cur_p = info.get("price", 0.0)
            chg = info.get("change", 0.0)
            chg_pct = info.get("change_pct", 0.0)
            vol = info.get("volume", 0)
            formatted_ticks = [
                {"time": now_ts - 1800, "time_str": "09:00", "price": prev_close, "change": 0.0, "change_pct": 0.0, "volume": int(vol * 0.1)},
                {"time": now_ts, "time_str": datetime.now(nairobi_tz).strftime("%H:%M"), "price": cur_p, "change": chg, "change_pct": chg_pct, "volume": vol}
            ]

        return {
            "ticker": ticker,
            "date": target_date,
            "is_market_open": is_market_open(),
            "prev_close": round(prev_close, 2),
            "current_price": info["price"],
            "change": info["change"],
            "change_pct": info["change_pct"],
            "ticks": formatted_ticks,
            "count": len(formatted_ticks)
        }
    finally:
        db.close()


@router.get("/{ticker}/prediction")
def stock_prediction(ticker: str):
    """
    Return AI prediction for a stock.
    Returns NO_SIGNAL if confidence is below threshold — never guesses.
    """
    info = get_stock_info(ticker.upper())
    if not info:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")
        
    # Aggregate sentiment from related news with exponential time-decay
    news = get_news_feed()
    related = [a for a in news if ticker.upper() in a.get("related_tickers", [])]
    sentiment = None
    if related:
        from ml.sentiment import aggregate_sentiment_with_decay
        sentiment = aggregate_sentiment_with_decay(related[:5])

    history = get_historical_data(ticker.upper(), "3mo")
    result  = predict(ticker.upper(), history, sentiment)
    return {
        "ticker":          result.ticker,
        "direction":       result.direction,
        "confidence":      result.confidence,
        "confidence_pct":  f"{result.confidence * 100:.1f}%",
        "signal_strength": result.signal_strength,
        "price_target":    result.price_target,
        "risk_level":      result.risk_level,
        "timeframe":       result.timeframe,
        "reasoning":       result.reasoning,
        "current_price":   info["price"],
        "disclaimer":      "AI signals are informational only. Not financial advice.",
    }

