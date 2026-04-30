"""
NSE AI Platform — Signal Predictor
Technical analysis + sentiment fusion engine with confidence thresholds.
Outputs BUY/SELL/HOLD signals or stays SILENT when confidence is too low.
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional
from ml.sentiment import SentimentResult

CONFIDENCE_THRESHOLD = 0.72   # Minimum to issue a signal (configurable)
SILENCE_LABEL = "NO_SIGNAL"


@dataclass
class PredictionResult:
    ticker: str
    direction: str          # "BUY" | "SELL" | "HOLD" | "NO_SIGNAL"
    confidence: float       # 0.0 – 1.0
    reasoning: list[str]    # Bullet points shown to user
    signal_strength: str    # "STRONG" | "MODERATE" | "WEAK" | "NONE"
    price_target: Optional[float] = None
    risk_level: str = "MEDIUM"


def predict(ticker: str, history: list[dict], sentiment: Optional[SentimentResult] = None) -> PredictionResult:
    """
    Generate a trading signal from OHLCV history + optional news sentiment.
    Returns NO_SIGNAL if confidence is below the threshold.
    """
    if not history or len(history) < 14:
        return _no_signal(ticker, "Insufficient historical data.")

    closes  = np.array([d["close"]  for d in history], dtype=float)
    volumes = np.array([d["volume"] for d in history], dtype=float)

    # ── Technical Indicators ──────────────────────────────────────────────
    indicators = {}
    reasons    = []

    # 1. RSI (14-period)
    rsi = _rsi(closes, 14)
    indicators["rsi"] = rsi
    if rsi < 30:
        reasons.append(f"RSI {rsi:.1f} - oversold territory (bullish reversal signal)")
    elif rsi > 70:
        reasons.append(f"RSI {rsi:.1f} - overbought territory (bearish reversal signal)")
    else:
        reasons.append(f"RSI {rsi:.1f} - neutral zone")

    # 2. Moving Average crossover (20 vs 50)
    if len(closes) >= 50:
        ma20 = np.mean(closes[-20:])
        ma50 = np.mean(closes[-50:])
        indicators["ma_cross"] = "bullish" if ma20 > ma50 else "bearish"
        if ma20 > ma50:
            reasons.append(f"MA20 ({ma20:.2f}) above MA50 ({ma50:.2f}) - bullish crossover")
        else:
            reasons.append(f"MA20 ({ma20:.2f}) below MA50 ({ma50:.2f}) - bearish crossover")

    # 3. MACD (12/26/9)
    macd_line, signal_line = _macd(closes)
    indicators["macd"] = "bullish" if macd_line > signal_line else "bearish"
    if macd_line > signal_line:
        reasons.append("MACD above signal line - upward momentum")
    else:
        reasons.append("MACD below signal line - downward momentum")

    # 4. Bollinger Bands (20-period)
    upper, lower, mid = _bollinger(closes, 20)
    current_price = closes[-1]
    if current_price < lower:
        indicators["bb"] = "oversold"
        reasons.append(f"Price below lower Bollinger Band - potential bounce")
    elif current_price > upper:
        indicators["bb"] = "overbought"
        reasons.append(f"Price above upper Bollinger Band - potential pullback")
    else:
        indicators["bb"] = "neutral"

    # 5. Volume trend
    avg_vol = np.mean(volumes[-10:])
    recent_vol = volumes[-1]
    if recent_vol > avg_vol * 1.5:
        indicators["volume"] = "high"
        reasons.append(f"Volume spike ({int(recent_vol):,}) - 1.5x above 10-day average")
    else:
        indicators["volume"] = "normal"

    # ── Score Calculation ─────────────────────────────────────────────────
    bull_signals = 0
    bear_signals = 0

    if indicators["rsi"] < 35:          bull_signals += 2
    elif indicators["rsi"] > 65:        bear_signals += 2

    if indicators.get("ma_cross") == "bullish":  bull_signals += 2
    elif indicators.get("ma_cross") == "bearish": bear_signals += 2

    if indicators["macd"] == "bullish": bull_signals += 1
    else:                               bear_signals += 1

    if indicators["bb"] == "oversold":  bull_signals += 1
    elif indicators["bb"] == "overbought": bear_signals += 1

    if indicators["volume"] == "high":
        if bull_signals > bear_signals: bull_signals += 1
        else:                           bear_signals += 1

    # Sentiment fusion (adds up to 2 points each direction)
    if sentiment:
        if sentiment.label == "POSITIVE":
            bull_signals += int(sentiment.score * 2)
            reasons.append(f"News sentiment: POSITIVE ({sentiment.score:.0%}) - {sentiment.reasoning}")
        elif sentiment.label == "NEGATIVE":
            bear_signals += int(sentiment.score * 2)
            reasons.append(f"News sentiment: NEGATIVE ({sentiment.score:.0%}) - {sentiment.reasoning}")

    total = bull_signals + bear_signals
    if total == 0:
        return _no_signal(ticker, "No clear technical signals detected.")

    bull_ratio = bull_signals / total
    bear_ratio = bear_signals / total
    raw_conf   = max(bull_ratio, bear_ratio)

    # Normalise confidence to 0.5–0.95
    confidence = round(min(0.95, 0.50 + (raw_conf - 0.50) * 0.9), 3)

    if confidence < CONFIDENCE_THRESHOLD:
        return PredictionResult(
            ticker=ticker,
            direction=SILENCE_LABEL,
            confidence=confidence,
            reasoning=["Confidence below threshold - market direction unclear.", "Holding pattern. No signal issued."],
            signal_strength="NONE",
            risk_level="UNKNOWN",
        )

    # ── Build Final Signal ────────────────────────────────────────────────
    if bull_signals > bear_signals:
        direction = "BUY"
        target    = round(current_price * 1.08, 2)
        risk      = "LOW" if confidence > 0.85 else "MEDIUM"
    else:
        direction = "SELL"
        target    = round(current_price * 0.93, 2)
        risk      = "MEDIUM" if confidence > 0.85 else "HIGH"

    strength = (
        "STRONG"   if confidence >= 0.85 else
        "MODERATE" if confidence >= 0.75 else
        "WEAK"
    )

    return PredictionResult(
        ticker=ticker,
        direction=direction,
        confidence=confidence,
        reasoning=reasons,
        signal_strength=strength,
        price_target=target,
        risk_level=risk,
    )


def score_all(stocks_data: list[dict]) -> list[dict]:
    """Score all stocks and return ranked recommendations (signals only)."""
    from data.fetcher import get_historical_data
    recommendations = []
    for stock in stocks_data:
        ticker  = stock["ticker"]
        history = get_historical_data(ticker, period="3mo")
        result  = predict(ticker, history)
        if result.direction == "BUY" and result.confidence >= CONFIDENCE_THRESHOLD:
            recommendations.append({
                "ticker":          ticker,
                "name":            stock["name"],
                "sector":          stock["sector"],
                "price":           stock["price"],
                "change_pct":      stock["change_pct"],
                "direction":       result.direction,
                "confidence":      result.confidence,
                "signal_strength": result.signal_strength,
                "price_target":    result.price_target,
                "risk_level":      result.risk_level,
                "reasoning":       result.reasoning[:3],
            })
    return sorted(recommendations, key=lambda x: x["confidence"], reverse=True)


# ── Private Technical Indicator Functions ─────────────────────────────────────

def _rsi(closes: np.ndarray, period: int = 14) -> float:
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:]) if len(gains) >= period else np.mean(gains)
    avg_loss = np.mean(losses[-period:]) if len(losses) >= period else np.mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _ema(closes: np.ndarray, span: int) -> np.ndarray:
    alpha  = 2 / (span + 1)
    ema    = np.zeros_like(closes)
    ema[0] = closes[0]
    for i in range(1, len(closes)):
        ema[i] = alpha * closes[i] + (1 - alpha) * ema[i - 1]
    return ema


def _macd(closes: np.ndarray):
    ema12    = _ema(closes, 12)
    ema26    = _ema(closes, 26)
    macd_arr = ema12 - ema26
    signal   = _ema(macd_arr, 9)
    return macd_arr[-1], signal[-1]


def _bollinger(closes: np.ndarray, period: int = 20):
    if len(closes) < period:
        period = len(closes)
    mid   = np.mean(closes[-period:])
    std   = np.std(closes[-period:])
    return mid + 2 * std, mid - 2 * std, mid


def _no_signal(ticker: str, reason: str) -> PredictionResult:
    return PredictionResult(
        ticker=ticker,
        direction=SILENCE_LABEL,
        confidence=0.0,
        reasoning=[reason],
        signal_strength="NONE",
        risk_level="UNKNOWN",
    )
