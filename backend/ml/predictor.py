"""
NSE AI Platform — Signal Predictor
Technical analysis + sentiment fusion engine with confidence thresholds.
Outputs BUY/SELL/HOLD signals or stays SILENT when confidence is too low.
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional
from ml.sentiment import SentimentResult

CONFIDENCE_THRESHOLD = 0.95   # Minimum to issue a signal (configurable)
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
    timeframe: Optional[str] = None


def predict(ticker: str, history: list[dict], sentiment: Optional[SentimentResult] = None) -> PredictionResult:
    """
    Generate a trading signal from OHLCV history + optional news sentiment.
    Returns NO_SIGNAL if confidence is below the threshold.
    """
    if not history or len(history) < 14:
        return _no_signal(ticker, "Insufficient historical data.")

    closes  = np.array([d["close"]  for d in history], dtype=float)
    highs   = np.array([d["high"]   for d in history], dtype=float)
    lows    = np.array([d["low"]    for d in history], dtype=float)
    volumes = np.array([d["volume"] for d in history], dtype=float)
    current_price = closes[-1]

    # ── Advanced Technical Indicators ──────────────────────────────────────────
    indicators = {}
    reasons    = []

    # 1. Wilder's Smoothed RSI (14-period)
    rsi = _rsi(closes, 14)
    indicators["rsi"] = rsi

    # 2. Money Flow Index (MFI) (14-period)
    mfi = _mfi(highs, lows, closes, volumes, 14)
    indicators["mfi"] = mfi

    # 3. Average Directional Index (ADX) (14-period)
    adx = _adx(highs, lows, closes, 14)
    indicators["adx"] = adx

    # 4. Moving Average crossover (20 vs 50)
    if len(closes) >= 50:
        ma20 = np.mean(closes[-20:])
        ma50 = np.mean(closes[-50:])
        indicators["ma_cross"] = "bullish" if ma20 > ma50 else "bearish"
    else:
        ma20 = np.mean(closes)
        ma50 = np.mean(closes)
        indicators["ma_cross"] = "neutral"

    # 5. MACD (12/26/9)
    macd_line, signal_line = _macd(closes)
    indicators["macd"] = "bullish" if macd_line > signal_line else "bearish"

    # 6. Bollinger Bands (20-period)
    upper, lower, mid = _bollinger(closes, 20)
    if current_price < lower:
        indicators["bb"] = "oversold"
    elif current_price > upper:
        indicators["bb"] = "overbought"
    else:
        indicators["bb"] = "neutral"

    # 7. Volume trend
    avg_vol = np.mean(volumes[-10:])
    recent_vol = volumes[-1]
    if recent_vol > avg_vol * 1.5:
        indicators["volume"] = "high"
    else:
        indicators["volume"] = "normal"

    # ── Trend-Adaptive Dynamic Scoring & Reasoning ──────────────────────────────
    # Base weightings adapt dynamically depending on the trend strength (ADX)
    is_trending = adx > 25
    is_ranging = adx < 20

    bull_signals = 0
    bear_signals = 0

    # Log Trend state
    if is_trending:
        reasons.append(f"ADX {adx:.1f} shows a strong trend. Prioritizing trend-following indicators.")
    elif is_ranging:
        reasons.append(f"ADX {adx:.1f} shows a ranging/neutral market. Prioritizing oscillators (RSI, MFI, BB).")
    else:
        reasons.append(f"ADX {adx:.1f} shows moderate trend strength. Evaluating balanced indicator set.")

    # Oscillator evaluations (RSI & MFI)
    # Strong consensus when both RSI & MFI point to oversold/overbought
    if rsi < 35 and mfi < 35:
        bull_signals += 3 if is_ranging else 2
        reasons.append(f"Bullish consensus: RSI ({rsi:.1f}) & MFI ({mfi:.1f}) are both in oversold territory")
    elif rsi > 65 and mfi > 65:
        bear_signals += 3 if is_ranging else 2
        reasons.append(f"Bearish consensus: RSI ({rsi:.1f}) & MFI ({mfi:.1f}) are both in overbought territory")
    else:
        # Separate evaluations
        if rsi < 30:
            bull_signals += 2 if is_ranging else 1
            reasons.append(f"RSI ({rsi:.1f}) is oversold")
        elif rsi > 70:
            bear_signals += 2 if is_ranging else 1
            reasons.append(f"RSI ({rsi:.1f}) is overbought")
        
        if mfi < 30:
            bull_signals += 1
            reasons.append(f"MFI ({mfi:.1f}) indicates buying pressure build-up")
        elif mfi > 70:
            bear_signals += 1
            reasons.append(f"MFI ({mfi:.1f}) indicates distribution/selling pressure")

    # Moving Average Crossover (High weight in trending markets, penalized/disabled in ranging)
    ma_cross = indicators.get("ma_cross")
    if ma_cross == "bullish":
        if is_trending:
            bull_signals += 3
            reasons.append(f"Bullish MA crossover (MA20 > MA50) confirmed by strong trend (ADX {adx:.1f})")
        elif not is_ranging:
            bull_signals += 2
            reasons.append(f"MA20 ({ma20:.2f}) is above MA50 ({ma50:.2f}) - bullish crossover")
    elif ma_cross == "bearish":
        if is_trending:
            bear_signals += 3
            reasons.append(f"Bearish MA crossover (MA20 < MA50) confirmed by strong trend (ADX {adx:.1f})")
        elif not is_ranging:
            bear_signals += 2
            reasons.append(f"MA20 ({ma20:.2f}) is below MA50 ({ma50:.2f}) - bearish crossover")

    # MACD (Trend-following)
    if indicators["macd"] == "bullish":
        bull_signals += 2 if is_trending else 1
        if is_trending:
            reasons.append("MACD shows strong upward momentum (confirmed by trend)")
        else:
            reasons.append("MACD is above signal line - positive momentum")
    else:
        bear_signals += 2 if is_trending else 1
        if is_trending:
            reasons.append("MACD shows strong downward momentum (confirmed by trend)")
        else:
            reasons.append("MACD is below signal line - negative momentum")

    # Bollinger Bands (Mean-reversion - High weight in ranging markets)
    if indicators["bb"] == "oversold":
        bull_signals += 2 if is_ranging else 1
        reasons.append(f"Price ({current_price:.2f}) pierced lower Bollinger Band - oversold bounce expected")
    elif indicators["bb"] == "overbought":
        bear_signals += 2 if is_ranging else 1
        reasons.append(f"Price ({current_price:.2f}) pierced upper Bollinger Band - pullback expected")

    # Volume trend
    if indicators["volume"] == "high":
        if bull_signals > bear_signals:
            bull_signals += 1
            reasons.append(f"Volume spike ({int(recent_vol):,}) confirms bullish direction")
        else:
            bear_signals += 1
            reasons.append(f"Volume spike ({int(recent_vol):,}) confirms bearish direction")

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

    # Normalise confidence to 0.5–0.99
    confidence = round(min(0.99, 0.50 + (raw_conf - 0.50) * 0.98), 3)

    if confidence < CONFIDENCE_THRESHOLD:
        return PredictionResult(
            ticker=ticker,
            direction=SILENCE_LABEL,
            confidence=confidence,
            reasoning=["Confidence below threshold - market direction unclear.", "Holding pattern. No signal issued."],
            signal_strength="NONE",
            risk_level="UNKNOWN",
        )

    # ── Statistical ATR Volatility Stop-Loss & Target Pricing ─────────────────
    atr = _atr(highs, lows, closes, 14)
    # Stop loss standard (1.5 * ATR), Target (2.5 * ATR)
    if bull_signals > bear_signals:
        direction = "BUY"
        target    = round(current_price + 2.5 * atr, 2)
        risk      = "LOW" if confidence > 0.85 else "MEDIUM"
        reasons.append(f"ATR Volatility ({atr:.2f}) target set at {target:.2f} (+2.5 ATR)")
    else:
        direction = "SELL"
        target    = round(current_price - 2.5 * atr, 2)
        risk      = "MEDIUM" if confidence > 0.85 else "HIGH"
        reasons.append(f"ATR Volatility ({atr:.2f}) target set at {target:.2f} (-2.5 ATR)")

    strength = (
        "STRONG"   if confidence >= 0.85 else
        "MODERATE" if confidence >= 0.75 else
        "WEAK"
    )

    # ── Expected Timeframe Calculation (Based on ATR and standard volatility) ────
    timeframe = None
    if direction in ["BUY", "SELL"] and target is not None:
        if len(closes) > 1:
            pct_changes = np.diff(closes) / closes[:-1]
            volatility = float(np.std(pct_changes))
        else:
            volatility = 0.02
        volatility = max(0.005, volatility)
        pct_distance = abs(target - current_price) / current_price
        expected_days = pct_distance / (volatility * 1.2)
        min_days = max(1, int(round(expected_days * 0.75)))
        max_days = max(min_days + 1, int(round(expected_days * 1.25)))
        if max_days > 30:
            max_days = 30
            min_days = min(20, min_days)
        timeframe = f"{min_days} to {max_days} days"

    # Send real-time high-confidence alerts if >= 99%
    if confidence >= 0.99 and direction in ["BUY", "SELL"]:
        try:
            from routers.alerts import check_and_send_high_confidence_alert
            check_and_send_high_confidence_alert(ticker, direction, confidence, target, timeframe)
        except Exception:
            pass

    return PredictionResult(
        ticker=ticker,
        direction=direction,
        confidence=confidence,
        reasoning=reasons,
        signal_strength=strength,
        price_target=target,
        risk_level=risk,
        timeframe=timeframe,
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
                "timeframe":       result.timeframe,
            })
    return sorted(recommendations, key=lambda x: x["confidence"], reverse=True)


# ── Private Technical Indicator Functions ─────────────────────────────────────

def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < 2:
        return 0.1
    tr = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        pc = closes[i-1]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    tr = np.array(tr)
    if len(tr) < period:
        return float(np.mean(tr))
    
    atr_val = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr_val = (atr_val * (period - 1) + tr[i]) / period
    return float(atr_val)


def _adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 20.0
    
    deltas_h = np.diff(highs)
    deltas_l = -np.diff(lows)
    
    plus_dm = np.where((deltas_h > deltas_l) & (deltas_h > 0), deltas_h, 0.0)
    minus_dm = np.where((deltas_l > deltas_h) & (deltas_l > 0), deltas_l, 0.0)
    
    tr = []
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
    tr = np.array(tr)
    
    def smooth(arr, p):
        smoothed = np.zeros(len(arr))
        smoothed[p-1] = np.mean(arr[:p])
        for idx in range(p, len(arr)):
            smoothed[idx] = (smoothed[idx-1] * (p - 1) + arr[idx]) / p
        return smoothed
        
    smoothed_tr = smooth(tr, period)
    smoothed_plus_dm = smooth(plus_dm, period)
    smoothed_minus_dm = smooth(minus_dm, period)
    
    plus_di = 100 * smoothed_plus_dm / np.where(smoothed_tr == 0, 1.0, smoothed_tr)
    minus_di = 100 * smoothed_minus_dm / np.where(smoothed_tr == 0, 1.0, smoothed_tr)
    
    dx = 100 * abs(plus_di - minus_di) / np.where((plus_di + minus_di) == 0, 1.0, plus_di + minus_di)
    
    adx_arr = smooth(dx, period)
    return float(adx_arr[-1])


def _mfi(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, volumes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    typical_prices = (highs + lows + closes) / 3
    raw_money_flow = typical_prices * volumes
    
    money_flow_deltas = np.diff(typical_prices)
    pos_flow = np.where(money_flow_deltas > 0, raw_money_flow[1:], 0.0)
    neg_flow = np.where(money_flow_deltas < 0, raw_money_flow[1:], 0.0)
    
    avg_pos = np.mean(pos_flow[-period:]) if len(pos_flow) >= period else np.mean(pos_flow)
    avg_neg = np.mean(neg_flow[-period:]) if len(neg_flow) >= period else np.mean(neg_flow)
    
    if avg_neg == 0:
        return 100.0
    mfr = avg_pos / avg_neg
    return round(100.0 - (100.0 / (1.0 + mfr)), 2)


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
