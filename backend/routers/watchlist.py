from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth.database import get_db
from auth.dependencies import get_current_user
from auth.models import User, WatchlistItem, PortfolioItem
from data.nse_scraper import get_price
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["Watchlist & Portfolio"])

# Pydantic Schemas
class WatchlistRequest(BaseModel):
    ticker: str

class PortfolioRequest(BaseModel):
    ticker: str
    buy_price: float
    quantity: int

@router.get("/watchlist")
def get_watchlist(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fetch user's watchlist tickers along with their live prices."""
    items = db.query(WatchlistItem).filter(WatchlistItem.user_id == current_user.id).all()
    results = []
    for item in items:
        ticker = item.ticker.upper()
        # Fetch current price from real-time scraper
        live_data = get_price(ticker)
        results.append({
            "id": item.id,
            "ticker": ticker,
            "current_price": live_data.get("price") if live_data else None,
            "change_pct": live_data.get("change_pct") if live_data else 0.0,
            "data_source": live_data.get("data_source") if live_data else "fallback",
            "added_at": item.created_at
        })
    return results

@router.post("/watchlist")
def add_to_watchlist(body: WatchlistRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Add a stock to user's watchlist."""
    ticker = body.ticker.upper().strip()
    
    # Check if already watchlisted
    exists = db.query(WatchlistItem).filter(
        WatchlistItem.user_id == current_user.id,
        WatchlistItem.ticker == ticker
    ).first()
    
    if exists:
        raise HTTPException(status_code=400, detail="Stock is already in your watchlist")
        
    item = WatchlistItem(user_id=current_user.id, ticker=ticker)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"message": f"{ticker} added to watchlist", "id": item.id}

@router.delete("/watchlist/{ticker}")
def remove_from_watchlist(ticker: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove a stock from user's watchlist."""
    ticker = ticker.upper().strip()
    item = db.query(WatchlistItem).filter(
        WatchlistItem.user_id == current_user.id,
        WatchlistItem.ticker == ticker
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Stock not found in your watchlist")
        
    db.delete(item)
    db.commit()
    return {"message": f"{ticker} removed from watchlist"}

from core.fees import calculate_trade_pnl, get_fee_schedule, calculate_buy_costs

@router.get("/fees/schedule")
def get_fees_schedule():
    """Return the statutory fee schedule for Kenya CMA / NSE / CDSC transactions."""
    return get_fee_schedule()

@router.get("/fees/calculate")
def calculate_fees(price: float, quantity: int):
    """Calculate purchase consideration, statutory fees, total outlay, and breakeven price."""
    if price <= 0 or quantity <= 0:
        raise HTTPException(status_code=400, detail="Price and quantity must be greater than zero")
    return calculate_buy_costs(price, quantity)

@router.get("/portfolio")
def get_portfolio(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fetch user's portfolio holding values with dynamic valuation, statutory fees, breakeven, and net P&L."""
    items = db.query(PortfolioItem).filter(PortfolioItem.user_id == current_user.id).all()
    results = []
    
    total_cost = 0.0
    total_value = 0.0
    total_outlay = 0.0
    total_net_value = 0.0
    total_statutory_fees = 0.0
    
    for item in items:
        ticker = item.ticker.upper()
        live_data = get_price(ticker)
        current_price = live_data.get("price") if live_data else item.buy_price
        
        pnl = calculate_trade_pnl(item.buy_price, current_price, item.quantity)
        
        total_cost += pnl["gross_cost"]
        total_value += pnl["gross_market_value"]
        total_outlay += pnl["total_outlay"]
        total_net_value += pnl["net_market_value"]
        total_statutory_fees += pnl["total_statutory_fees"]
        
        results.append({
            "id": item.id,
            "ticker": ticker,
            "quantity": item.quantity,
            "buy_price": item.buy_price,
            "current_price": current_price,
            # Gross fields (backwards-compatible)
            "total_cost": pnl["gross_cost"],
            "market_value": pnl["gross_market_value"],
            "profit_loss": pnl["gross_profit_loss"],
            "profit_loss_pct": pnl["gross_profit_loss_pct"],
            "gross_profit_loss": pnl["gross_profit_loss"],
            "gross_profit_loss_pct": pnl["gross_profit_loss_pct"],
            # Statutory fee & Net fields
            "total_outlay": pnl["total_outlay"],
            "net_market_value": pnl["net_market_value"],
            "buy_fees": pnl["buy_fees"],
            "estimated_exit_fees": pnl["estimated_exit_fees"],
            "total_statutory_fees": pnl["total_statutory_fees"],
            "net_profit_loss": pnl["net_profit_loss"],
            "net_profit_loss_pct": pnl["net_profit_loss_pct"],
            "breakeven_price": pnl["breakeven_price"],
            "breakeven_hurdle_pct": pnl["breakeven_hurdle_pct"],
            "added_at": item.created_at
        })
        
    portfolio_profit_loss = total_value - total_cost
    portfolio_profit_loss_pct = (portfolio_profit_loss / total_cost * 100) if total_cost > 0 else 0.0
    
    portfolio_net_profit_loss = total_net_value - total_outlay
    portfolio_net_profit_loss_pct = (portfolio_net_profit_loss / total_outlay * 100) if total_outlay > 0 else 0.0
    
    return {
        "holdings": results,
        "summary": {
            "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "portfolio_profit_loss": round(portfolio_profit_loss, 2),
            "portfolio_profit_loss_pct": round(portfolio_profit_loss_pct, 2),
            "total_outlay": round(total_outlay, 2),
            "total_net_value": round(total_net_value, 2),
            "portfolio_net_profit_loss": round(portfolio_net_profit_loss, 2),
            "portfolio_net_profit_loss_pct": round(portfolio_net_profit_loss_pct, 2),
            "total_statutory_fees": round(total_statutory_fees, 2),
            "fee_schedule": get_fee_schedule()
        }
    }

@router.post("/portfolio")
def add_to_portfolio(body: PortfolioRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Add a stock transaction purchase to user's portfolio."""
    ticker = body.ticker.upper().strip()
    if body.quantity <= 0 or body.buy_price <= 0:
        raise HTTPException(status_code=400, detail="Invalid quantity or buy price")
        
    item = PortfolioItem(
        user_id=current_user.id,
        ticker=ticker,
        buy_price=body.buy_price,
        quantity=body.quantity
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"message": f"Successfully purchased {body.quantity} shares of {ticker}", "id": item.id}

@router.delete("/portfolio/{id}")
def remove_from_portfolio(id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove a specific holding from user's portfolio."""
    item = db.query(PortfolioItem).filter(
        PortfolioItem.user_id == current_user.id,
        PortfolioItem.id == id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Portfolio holding not found")
        
    db.delete(item)
    db.commit()
    return {"message": "Holding successfully deleted from portfolio"}

@router.post("/portfolio/optimize")
def get_portfolio_optimization(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Solve for optimal portfolio weight allocations using Markowitz Mean-Variance Optimization."""
    # Fetch user's holdings
    holdings = db.query(PortfolioItem).filter(PortfolioItem.user_id == current_user.id).all()
    tickers = [h.ticker for h in holdings]
    
    # If portfolio is empty, fall back to watchlist
    if not tickers:
        watchlist = db.query(WatchlistItem).filter(WatchlistItem.user_id == current_user.id).all()
        tickers = [w.ticker for w in watchlist]
        
    # If watchlist is also empty, fall back to blue-chip basket
    if not tickers:
        tickers = ["SCOM", "EQTY", "KCB", "EABL", "COOP"]
        
    from ml.optimizer import optimize_portfolio
    result = optimize_portfolio(tickers)
    return result

