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

@router.get("/portfolio")
def get_portfolio(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fetch user's portfolio holding values with dynamic, real-time valuation and profit/loss calculation."""
    items = db.query(PortfolioItem).filter(PortfolioItem.user_id == current_user.id).all()
    results = []
    
    total_cost = 0.0
    total_value = 0.0
    
    for item in items:
        ticker = item.ticker.upper()
        live_data = get_price(ticker)
        current_price = live_data.get("price") if live_data else item.buy_price
        
        cost = item.buy_price * item.quantity
        value = current_price * item.quantity
        profit_loss = value - cost
        profit_loss_pct = (profit_loss / cost * 100) if cost > 0 else 0.0
        
        total_cost += cost
        total_value += value
        
        results.append({
            "id": item.id,
            "ticker": ticker,
            "quantity": item.quantity,
            "buy_price": item.buy_price,
            "current_price": current_price,
            "total_cost": round(cost, 2),
            "market_value": round(value, 2),
            "profit_loss": round(profit_loss, 2),
            "profit_loss_pct": round(profit_loss_pct, 2),
            "added_at": item.created_at
        })
        
    portfolio_profit_loss = total_value - total_cost
    portfolio_profit_loss_pct = (portfolio_profit_loss / total_cost * 100) if total_cost > 0 else 0.0
    
    return {
        "holdings": results,
        "summary": {
            "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "portfolio_profit_loss": round(portfolio_profit_loss, 2),
            "portfolio_profit_loss_pct": round(portfolio_profit_loss_pct, 2)
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

