"""
NSE AI Platform — Macro Benchmark & Yield Comparison Router
Endpoints for CBK Treasury Bill Rates (91d, 182d, 364d), Stock Dividend Yield Spreads,
Tax Shield Analysis, and Portfolio Macro Opportunity Cost Evaluations.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from auth.database import get_db
from auth.dependencies import get_current_user
from auth.models import User, PortfolioItem
from data.fetcher import get_all_stocks, get_stock_info
from data.nse_scraper import get_price
from ml.macro import (
    get_cbk_benchmarks,
    compute_stock_macro_profile,
    compute_market_yield_comparison,
    compute_portfolio_macro_yield,
)

router = APIRouter(prefix="/api/macro", tags=["Macro Benchmarks"])


@router.get("/benchmarks")
def get_benchmarks():
    """Return latest Central Bank of Kenya (CBK) Treasury Bill yields and macro indicators."""
    return get_cbk_benchmarks()


@router.get("/yield-comparison")
def get_yield_comparison():
    """
    Return all NSE stocks ranked by dividend yield, compared against
    CBK 91-Day, 182-Day, and 364-Day Treasury Bill benchmarks.
    """
    stocks = get_all_stocks()
    return compute_market_yield_comparison(stocks)


@router.get("/stock/{ticker}")
def get_stock_macro(ticker: str):
    """
    Return macro risk-free benchmark comparison for a specific stock ticker.
    Includes dividend yield, spread vs 91-day T-bill, tax-shield benefit,
    and required capital growth hurdle.
    """
    ticker_clean = ticker.upper().strip()
    info = get_stock_info(ticker_clean)
    if not info:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")

    price = float(info.get("price", 1.0))
    dps = float(info.get("dividend_per_share", 0.0))
    return compute_stock_macro_profile(ticker_clean, price, dps)


@router.get("/portfolio")
def get_portfolio_macro(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Evaluates the authenticated user's portfolio weighted dividend cash yield
    against guaranteed returns from CBK 91-Day Treasury Bills.
    """
    items = db.query(PortfolioItem).filter(PortfolioItem.user_id == current_user.id).all()
    holdings = []
    for item in items:
        ticker = item.ticker.upper().strip()
        live_data = get_price(ticker)
        current_price = float(live_data.get("price")) if (live_data and live_data.get("price") and float(live_data.get("price")) > 0) else float(item.buy_price)
        holdings.append({
            "ticker": ticker,
            "quantity": item.quantity,
            "buy_price": item.buy_price,
            "current_price": current_price,
        })

    return compute_portfolio_macro_yield(holdings)
