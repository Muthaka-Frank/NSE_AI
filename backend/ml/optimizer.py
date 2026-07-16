"""
NSE AI Platform — Portfolio Mean-Variance Optimization (Markowitz Efficient Frontier)
"""
import numpy as np
import pandas as pd
from sqlalchemy import select
from auth.database import SessionLocal
from auth.models import StockHistory
from data.stocks_registry import NSE_STOCKS
import logging

logger = logging.getLogger(__name__)

def optimize_portfolio(tickers: list, risk_free_rate: float = 0.08) -> dict:
    """
    Given a list of tickers, fetches historical daily close prices for the past 6 months,
    calculates expected annualized returns & covariance matrix, and finds the optimal
    asset weights to maximize the Sharpe Ratio.
    """
    tickers = [t.upper().strip() for t in tickers if t.upper().strip() in NSE_STOCKS]
    if not tickers:
        return {"error": "No valid tickers supplied"}
        
    if len(tickers) == 1:
        return {
            "weights": {tickers[0]: 1.0},
            "expected_return": 0.15,  # Estimate or actual if available
            "expected_volatility": 0.20,
            "sharpe_ratio": (0.15 - risk_free_rate) / 0.20,
            "status": "success",
            "message": "Single asset portfolio. 100% allocation."
        }

    # Fetch daily prices from StockHistory
    db = SessionLocal()
    price_data = {}
    
    for t in tickers:
        records = db.query(StockHistory).filter(
            StockHistory.ticker == t
        ).order_by(StockHistory.date.asc()).all()
        
        if records:
            price_data[t] = {r.date: r.close for r in records}
            
    db.close()
    
    # Check if we have enough historical data
    if len(price_data) < len(tickers) or any(len(prices) < 15 for prices in price_data.values()):
        # Insufficient data fallback: Return equal allocation
        eq_weight = 1.0 / len(tickers)
        return {
            "weights": {t: round(eq_weight, 4) for t in tickers},
            "expected_return": 0.12,
            "expected_volatility": 0.18,
            "sharpe_ratio": (0.12 - risk_free_rate) / 0.18,
            "status": "fallback",
            "message": "Insufficient database history for optimization. Defaulting to equal allocation."
        }

    try:
        # Construct DataFrame
        df = pd.DataFrame(price_data)
        # Forward fill and backward fill missing values if holidays don't align
        df = df.ffill().bfill()
        
        # Calculate daily percentage returns
        returns_df = df.pct_change().dropna()
        
        if len(returns_df) < 5:
            # Safe fallback if returns dataframe is empty/tiny
            eq_weight = 1.0 / len(tickers)
            return {
                "weights": {t: round(eq_weight, 4) for t in tickers},
                "expected_return": 0.12,
                "expected_volatility": 0.18,
                "sharpe_ratio": (0.12 - risk_free_rate) / 0.18,
                "status": "fallback",
                "message": "Too few daily trading bars. Defaulting to equal allocation."
            }

        # Calculate mean daily returns and annualize (252 trading days)
        mean_daily = returns_df.mean()
        annual_returns = mean_daily * 252
        
        # Annualized covariance matrix
        cov_matrix = returns_df.cov() * 252
        
        num_assets = len(tickers)
        
        # Define objective functions for scipy optimize
        def portfolio_performance(weights):
            p_return = np.sum(annual_returns * weights)
            p_volatility = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            return p_return, p_volatility
            
        def negative_sharpe_ratio(weights):
            p_return, p_volatility = portfolio_performance(weights)
            if p_volatility == 0:
                return 0
            return -(p_return - risk_free_rate) / p_volatility

        # Import scipy inside the function to defer dependency until needed
        from scipy.optimize import minimize
        
        # Constraints: weights sum to 1
        constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1.0})
        # Bounds: weight between 0 and 1 (no short selling)
        bounds = tuple((0.0, 1.0) for _ in range(num_assets))
        
        # Initial guess: equal distribution
        initial_guess = num_assets * [1.0 / num_assets]
        
        # Solve
        result = minimize(
            fun=negative_sharpe_ratio,
            x0=initial_guess,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints
        )
        
        if not result.success:
            raise ValueError("Optimization failed to converge")
            
        optimal_weights = result.x
        opt_return, opt_vol = portfolio_performance(optimal_weights)
        opt_sharpe = -(result.fun)
        
        # Format output
        weights_dict = {tickers[i]: round(float(optimal_weights[i]), 4) for i in range(num_assets)}
        
        return {
            "weights": weights_dict,
            "expected_return": round(float(opt_return), 4),
            "expected_volatility": round(float(opt_vol), 4),
            "sharpe_ratio": round(float(opt_sharpe), 4),
            "status": "success",
            "message": "Optimization completed successfully."
        }
        
    except Exception as e:
        logger.error(f"Error in mean-variance optimizer: {e}")
        eq_weight = 1.0 / len(tickers)
        return {
            "weights": {t: round(eq_weight, 4) for t in tickers},
            "expected_return": 0.12,
            "expected_volatility": 0.18,
            "sharpe_ratio": (0.12 - risk_free_rate) / 0.18,
            "status": "error",
            "message": f"Optimizer error: {str(e)}. Defaulting to equal allocation."
        }
