"""
NSE AI Platform — Liquidity Intelligence Engine
Implements:
1. Corwin-Schultz (2012) High-Low Bid-Ask Spread Estimator
2. Monthly and Annualized Turnover Velocity Metrics
3. Free-Float Adjusted Screening and Liquidity Tier Classification
"""

import math
import numpy as np
from dataclasses import dataclass
from typing import Optional, List, Dict
from data.stocks_registry import get_shares_outstanding, get_free_float_pct

SQRT_2 = math.sqrt(2.0)
CONST_K = 3.0 - 2.0 * SQRT_2  # ~0.1715728752538099
SQRT_K = math.sqrt(CONST_K)   # ~0.4142135623730951


@dataclass
class LiquidityMetrics:
    ticker: str
    spread_pct: float                 # Estimated bid-ask spread % (e.g. 0.85%)
    turnover_velocity_monthly_pct: float  # Shares traded past 20d / shares outstanding %
    turnover_velocity_annual_pct: float   # Monthly velocity * 12
    free_float_velocity_monthly_pct: float # Shares traded past 20d / free-float shares %
    shares_outstanding: int
    free_float_pct: float
    liquidity_rating: str            # "HIGH" | "MODERATE" | "ILLIQUID"
    rating_badge: str                # e.g. "🟢 High Liquidity"
    risk_premium_pct: float          # Half-spread slippage buffer %
    zero_vol_ratio: float            # Ratio of zero-volume days in past 20 days
    summary: str


def estimate_corwin_schultz_spread(history: List[Dict]) -> float:
    """
    Estimates the bid-ask spread percentage from daily high and low prices
    using the Corwin & Schultz (2012) Journal of Finance model.
    """
    if not history or len(history) < 2:
        return 2.50  # Default moderate spread fallback

    # Use up to the most recent 20 trading sessions
    recent = history[-min(20, len(history)):]
    spreads = []

    for i in range(len(recent) - 1):
        d1 = recent[i]
        d2 = recent[i + 1]

        h1, l1 = float(d1.get("high", 0)), float(d1.get("low", 0))
        h2, l2 = float(d2.get("high", 0)), float(d2.get("low", 0))

        if h1 <= 0 or l1 <= 0 or h2 <= 0 or l2 <= 0:
            continue

        # Single-day price ratios (guard against l > h anomalies)
        r1 = max(h1 / l1, 1.0)
        r2 = max(h2 / l2, 1.0)

        gamma_term = max(max(h1, h2) / min(l1, l2), 1.0)

        beta = (math.log(r1) ** 2) + (math.log(r2) ** 2)
        gamma = math.log(gamma_term) ** 2

        # Corwin-Schultz alpha formula
        alpha = (math.sqrt(2.0 * beta) - math.sqrt(beta)) / CONST_K - math.sqrt(gamma / CONST_K)

        if alpha <= 0:
            spreads.append(0.0)
        else:
            # Spread S = 2*(exp(alpha) - 1) / (1 + exp(alpha))
            exp_a = math.exp(min(alpha, 10.0))  # Cap alpha to prevent float overflow
            s = (2.0 * (exp_a - 1.0)) / (1.0 + exp_a)
            spreads.append(max(0.0, s * 100.0))

    if not spreads:
        return 2.50

    # Calculate median spread from the sliding window
    spread_pct = float(np.median(spreads))

    # Check for stagnant / zero price volatility counters (High == Low for almost all days)
    flat_days = sum(1 for d in recent if abs(float(d.get("high", 0)) - float(d.get("low", 0))) < 1e-4)
    if flat_days / len(recent) >= 0.70:
        # Stock rarely moves; wide hidden liquidity hurdle
        spread_pct = max(spread_pct, 6.50)

    return round(spread_pct, 2)


def calculate_turnover_velocity(ticker: str, history: List[Dict]) -> tuple[float, float, float, float]:
    """
    Computes turnover velocity:
    - Monthly Velocity % = (20-day Volume / Shares Outstanding) * 100
    - Annualized Velocity % = Monthly Velocity * 12
    - Free-Float Monthly Velocity % = (20-day Volume / Free-Float Shares) * 100
    - Zero Volume Days Ratio in the past 20 sessions
    """
    shares_out = get_shares_outstanding(ticker)
    free_float_pct = get_free_float_pct(ticker)

    if not history:
        return 0.0, 0.0, 0.0, 0.0

    recent = history[-min(20, len(history)):]
    total_volume = sum(int(d.get("volume", 0) or 0) for d in recent)
    zero_vol_days = sum(1 for d in recent if int(d.get("volume", 0) or 0) <= 0)
    zero_vol_ratio = zero_vol_days / len(recent) if recent else 0.0

    # Normalize to 20 trading days (1 market month)
    scale_factor = 20.0 / len(recent) if len(recent) > 0 else 1.0
    norm_month_vol = total_volume * scale_factor

    monthly_velocity = (norm_month_vol / max(shares_out, 1)) * 100.0
    annual_velocity = monthly_velocity * 12.0

    free_float_shares = shares_out * (free_float_pct / 100.0)
    free_float_velocity = (norm_month_vol / max(free_float_shares, 1.0)) * 100.0

    return (
        round(monthly_velocity, 3),
        round(annual_velocity, 2),
        round(free_float_velocity, 3),
        round(zero_vol_ratio, 2)
    )


def classify_liquidity(spread_pct: float, monthly_velocity: float, zero_vol_ratio: float) -> tuple[str, str, float, str]:
    """
    Classifies a counter into one of three liquidity tiers:
    - HIGH (🟢): Tight spread (<2.0%) AND active monthly velocity (>0.40%)
    - MODERATE (🟡): Normal spread (2.0% - 5.0%) OR moderate velocity (0.08% - 0.40%)
    - ILLIQUID (🔴): Wide spread (>5.0%) OR velocity < 0.08% OR zero-volume days >= 50%
    """
    # Half-spread is the minimum slippage risk premium per single-way trade
    risk_premium_pct = round(max(spread_pct / 2.0, 0.25), 2)

    if zero_vol_ratio >= 0.50 or spread_pct >= 5.0 or monthly_velocity < 0.08:
        rating = "ILLIQUID"
        badge = "🔴 Illiquid Trap"
        summary = (
            f"Illiquidity Alert: High friction (est. spread {spread_pct:.1f}%) and dormant turnover "
            f"({monthly_velocity:.2f}%/mo, {int(zero_vol_ratio*100)}% zero-trade days). Capital exit is constrained."
        )
    elif spread_pct <= 2.0 and monthly_velocity >= 0.40 and zero_vol_ratio < 0.20:
        rating = "HIGH"
        badge = "🟢 High Liquidity"
        summary = (
            f"Active Liquidity: Tight estimated spread ({spread_pct:.1f}%) and healthy turnover "
            f"({monthly_velocity:.2f}%/mo). Orders can be liquidated with minimal price slippage."
        )
    else:
        rating = "MODERATE"
        badge = "🟡 Moderate"
        summary = (
            f"Moderate Liquidity: Standard trading activity (est. spread {spread_pct:.1f}%, "
            f"turnover {monthly_velocity:.2f}%/mo). Exercise patient execution on larger orders."
        )

    return rating, badge, risk_premium_pct, summary


def analyze_liquidity(ticker: str, history: List[Dict]) -> LiquidityMetrics:
    """
    Primary entry point: analyzes spread, turnover velocity, free-float, and tier classification.
    """
    ticker = ticker.upper()
    shares_out = get_shares_outstanding(ticker)
    free_float_pct = get_free_float_pct(ticker)

    spread_pct = estimate_corwin_schultz_spread(history)
    monthly_vel, annual_vel, ff_vel, zero_ratio = calculate_turnover_velocity(ticker, history)
    rating, badge, risk_premium, summary = classify_liquidity(spread_pct, monthly_vel, zero_ratio)

    return LiquidityMetrics(
        ticker=ticker,
        spread_pct=spread_pct,
        turnover_velocity_monthly_pct=monthly_vel,
        turnover_velocity_annual_pct=annual_vel,
        free_float_velocity_monthly_pct=ff_vel,
        shares_outstanding=shares_out,
        free_float_pct=free_float_pct,
        liquidity_rating=rating,
        rating_badge=badge,
        risk_premium_pct=risk_premium,
        zero_vol_ratio=zero_ratio,
        summary=summary,
    )
