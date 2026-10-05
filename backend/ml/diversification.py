"""
NSE AI Platform — Portfolio Diversification & Sector Covariance/Correlation Engine
Calculates Herfindahl-Hirschman Index (HHI), Effective Constituents,
Asset and Sector Covariance/Correlation Matrices, and Kenyan Macro Risk Insights.
"""

import logging
from typing import Dict, List, Any, Tuple, Optional
import numpy as np
import pandas as pd
from auth.models import StockHistory
from data.stocks_registry import NSE_STOCKS, load_registry

logger = logging.getLogger(__name__)

# Sector color branding for visualization
SECTOR_COLORS: Dict[str, str] = {
    "Banking": "#448aff",              # Vivid Blue
    "Telecommunications": "#00e676", # Emerald Green
    "Consumer Staples": "#ff9100",    # Deep Orange
    "Energy": "#ffd600",              # Amber Yellow
    "Manufacturing": "#ab47bc",       # Purple
    "Insurance": "#29b6f6",           # Sky Blue
    "Investment": "#26a69a",          # Teal
    "Agricultural": "#8bc34a",        # Lime Green
    "Other": "#9e9e9e"                 # Grey
}

BLUE_CHIP_BENCHMARK = ["SCOM", "EQTY", "KCB", "EABL", "KPLC"]


def calculate_hhi(weights: List[float]) -> float:
    """
    Computes the Herfindahl-Hirschman Index (HHI) for an asset or sector allocation.
    Weights should sum to 1.0 (or will be normalized).
    HHI ranges from 1/N (perfect diversification) to 1.0 (pure concentration).
    """
    if not weights:
        return 0.0
    total = sum(weights)
    if total <= 0:
        return 0.0
    norm_weights = [w / total for w in weights]
    return round(float(sum(w ** 2 for w in norm_weights)), 4)


def classify_hhi(hhi: float) -> Tuple[str, str, str]:
    """
    Categorizes HHI into standard antitrust & portfolio concentration tiers:
      - < 0.15: Diversified (Green)
      - 0.15 - 0.25: Moderate Concentration (Yellow)
      - > 0.25: Highly Concentrated (Red)
    Returns: (status, color, description)
    """
    if hhi < 0.15:
        return (
            "DIVERSIFIED",
            "#00e676",
            "Well-diversified portfolio across multiple sectors with low idiosyncratic risk."
        )
    elif hhi <= 0.25:
        return (
            "MODERATE",
            "#ffd700",
            "Moderately concentrated. A few sectors carry substantial portfolio influence."
        )
    else:
        return (
            "CONCENTRATED",
            "#ff5252",
            "Highly concentrated portfolio. Significant vulnerability to single-sector shocks."
        )


def calculate_effective_constituents(weights: List[float]) -> float:
    """
    Computes the Effective Number of Constituents / Sectors (Inverse HHI):
      N_eff = 1 / sum(w_i^2)
    """
    hhi = calculate_hhi(weights)
    if hhi <= 0:
        return 0.0
    return round(1.0 / hhi, 2)


def fetch_historical_returns(
    tickers: List[str],
    db_session,
    limit_days: int = 180
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Queries daily closing prices from StockHistory in SQLite and returns
    a percentage returns DataFrame and the list of successfully retrieved tickers.
    """
    price_dict = {}
    valid_tickers = []
    
    for t in tickers:
        t_clean = t.upper().strip()
        records = db_session.query(StockHistory).filter(
            StockHistory.ticker == t_clean
        ).order_by(StockHistory.date.desc()).limit(limit_days).all()
        
        if records and len(records) >= 10:
            # Reverse to chronological order (asc)
            chronological = sorted(records, key=lambda r: r.date)
            price_dict[t_clean] = {r.date: r.close for r in chronological}
            valid_tickers.append(t_clean)
            
    if not price_dict or len(valid_tickers) == 0:
        return pd.DataFrame(), []
        
    df = pd.DataFrame(price_dict)
    df = df.ffill().bfill()
    returns_df = df.pct_change().dropna()
    return returns_df, valid_tickers


def compute_correlation_matrix(returns_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Computes the Pearson correlation matrix for daily asset returns.
    """
    if returns_df.empty or len(returns_df.columns) == 0:
        return {"tickers": [], "matrix": []}
        
    corr = returns_df.corr().fillna(0.0)
    # Ensure diagonals are exactly 1.0
    for col in corr.columns:
        corr.loc[col, col] = 1.0
        
    tickers = list(corr.columns)
    matrix = [[round(float(corr.loc[r, c]), 2) for c in tickers] for r in tickers]
    
    return {
        "tickers": tickers,
        "matrix": matrix
    }


def compute_covariance_matrix(returns_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Computes annualized covariance matrix (252 trading days).
    """
    if returns_df.empty or len(returns_df.columns) == 0:
        return {"tickers": [], "matrix": []}
        
    cov = (returns_df.cov() * 252).fillna(0.0)
    tickers = list(cov.columns)
    matrix = [[round(float(cov.loc[r, c]), 6) for c in tickers] for r in tickers]
    
    return {
        "tickers": tickers,
        "matrix": matrix
    }


def compute_sector_correlation_matrix(
    returns_df: pd.DataFrame,
    ticker_sector_map: Dict[str, str]
) -> Dict[str, Any]:
    """
    Aggregates asset returns into sector-composite return series and calculates
    inter-sector Pearson correlation.
    """
    if returns_df.empty or len(returns_df.columns) == 0:
        return {"sectors": [], "matrix": []}
        
    # Map each column to its sector
    sector_series = {}
    for col in returns_df.columns:
        sector = ticker_sector_map.get(col, "Other")
        if sector not in sector_series:
            sector_series[sector] = []
        sector_series[sector].append(returns_df[col])
        
    # Average returns across assets within each sector
    sector_df_dict = {}
    for sector, series_list in sector_series.items():
        if len(series_list) == 1:
            sector_df_dict[sector] = series_list[0]
        else:
            sector_df_dict[sector] = pd.concat(series_list, axis=1).mean(axis=1)
            
    sector_df = pd.DataFrame(sector_df_dict)
    if sector_df.empty:
        return {"sectors": [], "matrix": []}
        
    corr = sector_df.corr().fillna(0.0)
    for col in corr.columns:
        corr.loc[col, col] = 1.0
        
    sectors = list(corr.columns)
    matrix = [[round(float(corr.loc[r, c]), 2) for c in sectors] for r in sectors]
    
    return {
        "sectors": sectors,
        "matrix": matrix
    }


def compute_fallback_correlation(tickers: List[str], ticker_sector_map: Dict[str, str]) -> Dict[str, Any]:
    """
    Provides estimated cross-asset correlation based on sector classifications
    when historical DB records are limited or unavailable.
    Same sector assets: ~0.65 correlation. Different sectors: ~0.18 correlation.
    """
    matrix = []
    for i, t1 in enumerate(tickers):
        row = []
        s1 = ticker_sector_map.get(t1, "Other")
        for j, t2 in enumerate(tickers):
            if i == j:
                row.append(1.0)
            else:
                s2 = ticker_sector_map.get(t2, "Other")
                if s1 == s2 and s1 != "Other":
                    row.append(0.65)
                else:
                    row.append(0.18)
        matrix.append(row)
    return {"tickers": tickers, "matrix": matrix}


def compute_fallback_sector_correlation(sectors: List[str]) -> Dict[str, Any]:
    """
    Provides estimated inter-sector correlation when historical time-series
    are limited or unavailable.
    """
    matrix = []
    for i, s1 in enumerate(sectors):
        row = []
        for j, s2 in enumerate(sectors):
            if i == j:
                row.append(1.0)
            else:
                row.append(0.22)
        matrix.append(row)
    return {"sectors": sectors, "matrix": matrix}


def generate_diversification_insights(
    sector_allocations: List[Dict[str, Any]],
    asset_allocations: List[Dict[str, Any]],
    corr_dict: Dict[str, Any],
    hhi: float
) -> List[str]:
    """
    Generates actionable, macro-aware diversification advisory for Kenyan investors.
    """
    insights = []
    
    # 1. Sector Dominance Insights
    for s in sector_allocations:
        weight = s.get("weight_pct", 0.0)
        sector_name = s.get("sector", "Unknown")
        
        if weight >= 50.0:
            if sector_name == "Banking":
                insights.append(
                    f"⚠️ Heavy Banking Concentration ({weight:.1f}%): High vulnerability to Central Bank of Kenya (CBK) "
                    f"Monetary Policy Committee rate adjustments and Non-Performing Loan (NPL) cycles. "
                    f"Consider reallocating to defensive sectors like Telecommunications or Consumer Staples."
                )
            elif sector_name == "Telecommunications":
                insights.append(
                    f"⚠️ Single-Sector Dominance ({weight:.1f}% in Telecommunications): Strong dependence on Safaricom's "
                    f"M-Pesa monetization and regulatory tariff directives. Cross-sector diversification recommended."
                )
            else:
                insights.append(
                    f"⚠️ Elevated Sector Concentration ({weight:.1f}% in {sector_name}): Sector-specific shocks will disproportionately impact total returns."
                )
        elif 35.0 <= weight < 50.0:
            insights.append(
                f"ℹ️ Notable Exposure: {sector_name} represents {weight:.1f}% of your portfolio. Keep an eye on sector-wide earnings reports."
            )
            
    # 2. Pairwise Asset Correlation Warnings & Stabilizers
    tickers = corr_dict.get("tickers", [])
    matrix = corr_dict.get("matrix", [])
    
    high_pairs = []
    low_pairs = []
    
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            t1 = tickers[i]
            t2 = tickers[j]
            rho = matrix[i][j]
            if rho >= 0.70:
                high_pairs.append((t1, t2, rho))
            elif rho <= 0.20:
                low_pairs.append((t1, t2, rho))
                
    if high_pairs:
        t1, t2, rho = high_pairs[0]
        insights.append(
            f"⚠️ Redundant Risk Pair: {t1} and {t2} have high co-movement (correlation: {rho:.2f}). Holding both offers diminished diversification benefit during market drawdowns."
        )
        
    if low_pairs:
        t1, t2, rho = low_pairs[0]
        insights.append(
            f"🛡️ Diversification Buffer: {t1} and {t2} exhibit low correlation ({rho:.2f}), helping dampen total portfolio volatility."
        )
        
    # 3. Overall Portfolio Health
    status, _, desc = classify_hhi(hhi)
    insights.append(f"Diversification Rating: {status}. {desc}")
    
    return insights


def compute_portfolio_diversification(
    holdings: List[Dict[str, Any]],
    db_session
) -> Dict[str, Any]:
    """
    Master controller: calculates sector exposures, asset weights, HHI,
    correlation matrices, and diversification insights.
    """
    load_registry()
    is_fallback = False
    
    # Check if user has holdings
    if not holdings or len(holdings) == 0:
        return {
            "has_holdings": False,
            "is_fallback": False,
            "total_portfolio_value": 0.0,
            "sector_allocations": [],
            "asset_allocations": [],
            "hhi_score": 0.0,
            "asset_hhi_score": 0.0,
            "status": "NO_HOLDINGS",
            "status_color": "#9e9e9e",
            "status_description": "No portfolio holdings recorded yet. Record a stock purchase to track your sector diversification and correlation heatmap.",
            "effective_sectors": 0.0,
            "effective_assets": 0.0,
            "asset_correlation": {"tickers": [], "matrix": []},
            "sector_correlation": {"sectors": [], "matrix": []},
            "risk_insights": [
                "Your portfolio currently has no active holdings.",
                "Click '+ Record Purchase' to add stocks and generate real-time sector concentration and correlation analytics."
            ]
        }
        
    # Calculate market value per holding
    total_portfolio_value = 0.0
    asset_data = []
    tickers = []
    ticker_sector_map = {}
    
    for h in holdings:
        ticker = h.get("ticker", "").upper().strip()
        if not ticker:
            continue
            
        qty = float(h.get("quantity", 1))
        price = float(h.get("current_price", h.get("buy_price", 1.0)))
        val = qty * price
        
        meta = NSE_STOCKS.get(ticker, {})
        name = meta.get("name", ticker)
        sector = meta.get("sector", "Other")
        
        tickers.append(ticker)
        ticker_sector_map[ticker] = sector
        total_portfolio_value += val
        
        asset_data.append({
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "value": round(val, 2),
            "quantity": qty,
            "price": price,
            "color": SECTOR_COLORS.get(sector, "#9e9e9e")
        })
        
    # Compute asset weights
    asset_allocations = []
    asset_weights = []
    for a in asset_data:
        weight = (a["value"] / total_portfolio_value) if total_portfolio_value > 0 else (1.0 / len(asset_data))
        asset_weights.append(weight)
        asset_allocations.append({
            "ticker": a["ticker"],
            "name": a["name"],
            "sector": a["sector"],
            "value": a["value"],
            "weight_pct": round(weight * 100.0, 2),
            "color": a["color"]
        })
        
    # Aggregate into sector allocations
    sector_buckets = {}
    for a in asset_allocations:
        s = a["sector"]
        if s not in sector_buckets:
            sector_buckets[s] = {"sector": s, "value": 0.0, "tickers": []}
        sector_buckets[s]["value"] += a["value"]
        sector_buckets[s]["tickers"].append(a["ticker"])
        
    sector_allocations = []
    sector_weights = []
    for s, data in sector_buckets.items():
        weight = (data["value"] / total_portfolio_value) if total_portfolio_value > 0 else (1.0 / len(sector_buckets))
        sector_weights.append(weight)
        sector_allocations.append({
            "sector": s,
            "value": round(data["value"], 2),
            "weight_pct": round(weight * 100.0, 2),
            "tickers": data["tickers"],
            "color": SECTOR_COLORS.get(s, "#9e9e9e")
        })
        
    # Sort sector allocations by weight descending
    sector_allocations.sort(key=lambda x: x["weight_pct"], reverse=True)
    
    # Calculate HHI & Effective numbers
    sector_hhi = calculate_hhi(sector_weights)
    asset_hhi = calculate_hhi(asset_weights)
    effective_sectors = calculate_effective_constituents(sector_weights)
    effective_assets = calculate_effective_constituents(asset_weights)
    status, status_color, description = classify_hhi(sector_hhi)
    
    # Compute returns and correlation matrices
    # If single holding, include top blue chips to give cross-market context
    calc_tickers = list(dict.fromkeys(tickers))
    if len(calc_tickers) < 2:
        calc_tickers = list(dict.fromkeys(calc_tickers + BLUE_CHIP_BENCHMARK[:4]))
        
    returns_df, valid_tickers = fetch_historical_returns(calc_tickers, db_session)
    if not returns_df.empty and len(valid_tickers) >= 2:
        asset_corr = compute_correlation_matrix(returns_df)
        sector_corr = compute_sector_correlation_matrix(returns_df, ticker_sector_map)
    else:
        asset_corr = compute_fallback_correlation(calc_tickers, ticker_sector_map)
        unique_sectors = list(dict.fromkeys(ticker_sector_map.get(t, "Other") for t in calc_tickers))
        sector_corr = compute_fallback_sector_correlation(unique_sectors)
    
    # Contextual Insights
    insights = generate_diversification_insights(
        sector_allocations=sector_allocations,
        asset_allocations=asset_allocations,
        corr_dict=asset_corr,
        hhi=sector_hhi
    )
    
    return {
        "has_holdings": True,
        "is_fallback": is_fallback,
        "total_portfolio_value": round(total_portfolio_value, 2),
        "sector_allocations": sector_allocations,
        "asset_allocations": asset_allocations,
        "hhi_score": sector_hhi,
        "asset_hhi_score": asset_hhi,
        "status": status,
        "status_color": status_color,
        "status_description": description,
        "effective_sectors": effective_sectors,
        "effective_assets": effective_assets,
        "asset_correlation": asset_corr,
        "sector_correlation": sector_corr,
        "risk_insights": insights
    }