"""NSE AI Platform — Stocks Router"""
import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from data.fetcher import get_stock_info, get_all_stocks, get_historical_data, NSE_STOCKS, clear_cache
from ml.predictor import predict

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
                clear_cache()  # Always fetch fresh from Yahoo Finance
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


@router.get("/{ticker}/prediction")
def stock_prediction(ticker: str):
    """
    Return AI prediction for a stock.
    Returns NO_SIGNAL if confidence is below threshold — never guesses.
    """
    info = get_stock_info(ticker.upper())
    if not info:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")
    history = get_historical_data(ticker.upper(), "3mo")
    result  = predict(ticker.upper(), history)
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

