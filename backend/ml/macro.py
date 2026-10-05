"""
NSE AI Platform — Macro Benchmark & Yield Spread Engine
Compares Central Bank of Kenya (CBK) Risk-Free Treasury Bills (91d, 182d, 364d)
against Nairobi Securities Exchange (NSE) equity dividend yields, factoring in
statutory Withholding Tax (5% on dividends vs 15% on Treasury Bills).
"""

import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
NAIROBI_TZ = pytz.timezone("Africa/Nairobi")

# ── CBK Macro Benchmark Rates (Official CBK Weekly Auction Baseline) ────────
# In Kenya, CBK conducts weekly Treasury Bill auctions.
# Rates are annualized discount yields.
CBK_BENCHMARKS = {
    "tbill_91d": 15.68,        # 91-Day Treasury Bill benchmark (Risk-Free Rate Rf)
    "tbill_182d": 16.42,       # 182-Day Treasury Bill
    "tbill_364d": 16.65,       # 364-Day Treasury Bill
    "cbr_rate": 12.75,         # Central Bank Rate (policy rate)
    "inflation_rate": 4.40,    # Kenya National Bureau of Statistics (KNBS) headline inflation
    "interbank_rate": 12.85,   # Interbank lending rate
    "auction_date": "2025-02-27",
    "data_source": "Central Bank of Kenya (CBK)",
}

# ── Statutory Withholding Tax Rates (Kenya Revenue Authority) ───────────────
WHT_TBILL_RATE = 0.15          # 15% flat WHT on Treasury Bill discount earnings
WHT_EQUITY_RESIDENT = 0.05      # 5% WHT on qualifying cash dividends for Kenyan residents
WHT_EQUITY_NON_RESIDENT = 0.15  # 15% WHT for non-resident investors

# In-memory cache for live CBK rates
_macro_cache = {}


def get_cbk_benchmarks() -> Dict[str, Any]:
    """
    Returns latest CBK Treasury Bill and macro benchmark rates,
    including after-tax net rates and real risk-free yields.
    """
    cached = _macro_cache.get("cbk_rates")
    if cached and time.time() < cached["expires"]:
        return cached["data"]

    # Base figures
    tbill_91d = CBK_BENCHMARKS["tbill_91d"]
    tbill_182d = CBK_BENCHMARKS["tbill_182d"]
    tbill_364d = CBK_BENCHMARKS["tbill_364d"]
    cbr = CBK_BENCHMARKS["cbr_rate"]
    inflation = CBK_BENCHMARKS["inflation_rate"]

    # Compute net-of-tax rates (15% WHT)
    net_91d = round(tbill_91d * (1.0 - WHT_TBILL_RATE), 2)
    net_182d = round(tbill_182d * (1.0 - WHT_TBILL_RATE), 2)
    net_364d = round(tbill_364d * (1.0 - WHT_TBILL_RATE), 2)

    # Real risk-free yield (Fisher hypothesis approximation: Nominal - Inflation)
    real_rf_91d = round(tbill_91d - inflation, 2)
    real_net_91d = round(net_91d - inflation, 2)

    payload = {
        "tbill_91d": tbill_91d,
        "tbill_182d": tbill_182d,
        "tbill_364d": tbill_364d,
        "cbr_rate": cbr,
        "inflation_rate": inflation,
        "interbank_rate": CBK_BENCHMARKS["interbank_rate"],
        "net_tbill_91d": net_91d,
        "net_tbill_182d": net_182d,
        "net_tbill_364d": net_364d,
        "real_risk_free_rate": real_rf_91d,
        "real_net_risk_free_rate": real_net_91d,
        "wht_tbill_pct": round(WHT_TBILL_RATE * 100, 1),
        "wht_equity_resident_pct": round(WHT_EQUITY_RESIDENT * 100, 1),
        "wht_equity_non_resident_pct": round(WHT_EQUITY_NON_RESIDENT * 100, 1),
        "auction_date": CBK_BENCHMARKS["auction_date"],
        "data_source": CBK_BENCHMARKS["data_source"],
        "as_of": datetime.now(NAIROBI_TZ).strftime("%Y-%m-%d %H:%M EAT"),
    }

    _macro_cache["cbk_rates"] = {"data": payload, "expires": time.time() + 1800}
    return payload


def compute_stock_macro_profile(
    ticker: str,
    current_price: float,
    dividend_per_share: Optional[float] = None
) -> Dict[str, Any]:
    """
    Computes macro benchmark comparison for an individual stock vs CBK 91-Day T-Bill.
    Evaluates:
      - Gross and Net dividend yield
      - Yield spread vs 91-Day T-bill (gross & after statutory taxes)
      - Required annual capital growth hurdle
      - Kenyan resident tax-shield advantage (5% equity WHT vs 15% T-bill WHT)
      - Actionable macro verdict
    """
    ticker_clean = ticker.upper().strip()
    from data.stocks_registry import get_dividend_per_share, get_payout_frequency, get_payout_ratio_pct

    dps = dividend_per_share if dividend_per_share is not None else get_dividend_per_share(ticker_clean)
    payout_freq = get_payout_frequency(ticker_clean)
    payout_ratio = get_payout_ratio_pct(ticker_clean)

    benchmarks = get_cbk_benchmarks()
    rf_gross = benchmarks["tbill_91d"]
    rf_net = benchmarks["net_tbill_91d"]

    price = float(current_price) if current_price and current_price > 0 else 1.0

    gross_div_yield = round((dps / price) * 100, 2)
    net_div_yield = round(gross_div_yield * (1.0 - WHT_EQUITY_RESIDENT), 2)

    # Spreads: Equity Yield minus Risk-Free Rate
    gross_yield_spread = round(gross_div_yield - rf_gross, 2)
    net_yield_spread = round(net_div_yield - rf_net, 2)

    # Required annual capital growth so total return matches 91-Day T-Bill
    required_growth_hurdle = round(max(0.0, rf_gross - gross_div_yield), 2)
    net_required_growth_hurdle = round(max(0.0, rf_net - net_div_yield), 2)

    # Tax Shield Advantage:
    # Because equities are taxed at 5% instead of 15%, the investor retains an extra 10% of gross dividend
    tax_shield_advantage_pct = round(gross_div_yield * (WHT_TBILL_RATE - WHT_EQUITY_RESIDENT), 2)

    # Macro categorization and advisory
    if gross_div_yield >= 12.0:
        verdict_category = "EXCEPTIONAL_YIELD"
        verdict_badge = "🔥 High-Yield Outperformer"
        verdict_color = "#00e676"
        verdict_text = (
            f"{ticker_clean} yields {gross_div_yield:.1f}% cash dividend, directly competing with "
            f"risk-free 91-day T-bills ({rf_gross:.1f}%). After taxes, it yields {net_div_yield:.1f}% vs "
            f"{rf_net:.1f}% net T-bill. Only +{required_growth_hurdle:.1f}% annual share appreciation is needed to beat government paper."
        )
    elif gross_div_yield >= 6.0:
        verdict_category = "BALANCED_YIELD"
        verdict_badge = "⚖️ Defensive Cash-Flow"
        verdict_color = "#69f0ae"
        verdict_text = (
            f"Solid {gross_div_yield:.1f}% cash dividend provides strong downside insulation against market drawdowns. "
            f"Requires +{required_growth_hurdle:.1f}% annual capital growth to outperform the 91-day T-bill ({rf_gross:.1f}%)."
        )
    elif gross_div_yield >= 2.0:
        verdict_category = "MODERATE_YIELD"
        verdict_badge = "📈 Growth-Dependent"
        verdict_color = "#ffd700"
        verdict_text = (
            f"Modest {gross_div_yield:.1f}% dividend yield. With risk-free T-bills yielding {rf_gross:.1f}%, "
            f"investors require at least +{required_growth_hurdle:.1f}% price appreciation to justify equity risk."
        )
    elif gross_div_yield > 0.0:
        verdict_category = "LOW_YIELD"
        verdict_badge = "⚡ Pure Capital Growth"
        verdict_color = "#ff9100"
        verdict_text = (
            f"Minimal {gross_div_yield:.1f}% dividend payout. Total investment return is almost entirely reliant on capital appreciation "
            f"(+{required_growth_hurdle:.1f}% hurdle to beat 91-day T-bills)."
        )
    else:
        verdict_category = "ZERO_DIVIDEND"
        verdict_badge = "⚠️ Zero Cash Cushion"
        verdict_color = "#ff5252"
        verdict_text = (
            f"Zero dividend cash flow. Carries high opportunity cost vs guaranteed {rf_gross:.1f}% T-bill yield. "
            f"Share price must appreciate by at least +{rf_gross:.1f}%/year to break even with risk-free government debt."
        )

    return {
        "ticker": ticker_clean,
        "current_price": round(price, 2),
        "dividend_per_share": round(dps, 2),
        "payout_frequency": payout_freq,
        "payout_ratio_pct": payout_ratio,
        "gross_dividend_yield": gross_div_yield,
        "net_dividend_yield": net_div_yield,
        "tbill_91d_rate": rf_gross,
        "net_tbill_91d_rate": rf_net,
        "tbill_182d_rate": benchmarks["tbill_182d"],
        "tbill_364d_rate": benchmarks["tbill_364d"],
        "gross_yield_spread": gross_yield_spread,
        "net_yield_spread": net_yield_spread,
        "required_growth_hurdle": required_growth_hurdle,
        "net_required_growth_hurdle": net_required_growth_hurdle,
        "tax_shield_advantage_pct": tax_shield_advantage_pct,
        "verdict_category": verdict_category,
        "verdict_badge": verdict_badge,
        "verdict_color": verdict_color,
        "verdict_text": verdict_text,
    }


def compute_market_yield_comparison(stocks_with_prices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Ranks all listed NSE stocks by dividend yield and compares them
    against CBK Treasury Bill benchmarks (gross and net-of-tax).
    """
    benchmarks = get_cbk_benchmarks()
    from data.stocks_registry import get_dividend_per_share, get_payout_frequency

    ranked_items = []
    total_yield = 0.0
    payers_yield = 0.0
    payer_count = 0

    for s in stocks_with_prices:
        ticker = s.get("ticker", "").upper().strip()
        if not ticker:
            continue
        price = float(s.get("price", 1.0))
        dps = float(s.get("dividend_per_share", get_dividend_per_share(ticker)))
        freq = s.get("payout_frequency", get_payout_frequency(ticker))
        
        prof = compute_stock_macro_profile(ticker, price, dps)
        prof["name"] = s.get("name", ticker)
        prof["sector"] = s.get("sector", "Other")
        
        ranked_items.append(prof)
        total_yield += prof["gross_dividend_yield"]
        if prof["gross_dividend_yield"] > 0:
            payers_yield += prof["gross_dividend_yield"]
            payer_count += 1

    # Sort descending by dividend yield
    ranked_items.sort(key=lambda x: x["gross_dividend_yield"], reverse=True)

    n_stocks = len(ranked_items)
    avg_market_yield = round(total_yield / n_stocks, 2) if n_stocks > 0 else 0.0
    avg_payer_yield = round(payers_yield / payer_count, 2) if payer_count > 0 else 0.0

    # Key macro insights
    top_yielders = [r["ticker"] for r in ranked_items[:5] if r["gross_dividend_yield"] > 0]
    outperformers = [r for r in ranked_items if r["gross_dividend_yield"] >= 10.0]

    macro_insights = [
        f"🏛️ CBK 91-Day Treasury Bill offers {benchmarks['tbill_91d']}% risk-free ({benchmarks['net_tbill_91d']}% after 15% WHT).",
        f"📊 NSE Market Average Dividend Yield stands at {avg_market_yield}% across all stocks ({avg_payer_yield}% among regular dividend payers).",
        f"🛡️ Tax Advantage: Kenyan residents pay only 5% WHT on stock dividends vs 15% on Treasury Bills, boosting net dividend efficiency.",
    ]
    if outperformers:
        macro_insights.append(
            f"🔥 {len(outperformers)} NSE counters ({', '.join(r['ticker'] for r in outperformers[:4])}) yield ≥10.0%, offering defensive cash buffers that significantly close the gap with government paper."
        )

    return {
        "benchmarks": benchmarks,
        "market_stats": {
            "total_stocks_evaluated": n_stocks,
            "dividend_paying_stocks": payer_count,
            "zero_dividend_stocks": n_stocks - payer_count,
            "average_market_dividend_yield": avg_market_yield,
            "average_payer_dividend_yield": avg_payer_yield,
            "top_dividend_tickers": top_yielders,
        },
        "macro_insights": macro_insights,
        "stocks": ranked_items,
    }


def compute_portfolio_macro_yield(
    holdings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Evaluates the user's actual portfolio holdings against the CBK 91-Day T-Bill benchmark.
    Computes:
      - Weighted portfolio dividend yield (gross and after resident 5% WHT)
      - Expected annual cash dividend income (KES)
      - Opportunity cost: Equivalent guaranteed annual return from CBK 91-day T-Bill (KES)
      - Net annual cash shortfall / surplus vs government paper
      - Required annual capital appreciation to beat risk-free government debt
    """
    benchmarks = get_cbk_benchmarks()
    rf_gross = benchmarks["tbill_91d"]
    rf_net = benchmarks["net_tbill_91d"]

    if not holdings or len(holdings) == 0:
        return {
            "has_holdings": False,
            "total_portfolio_value": 0.0,
            "portfolio_dividend_yield": 0.0,
            "portfolio_net_dividend_yield": 0.0,
            "expected_annual_dividends": 0.0,
            "expected_net_annual_dividends": 0.0,
            "equivalent_tbill_gross_return": 0.0,
            "equivalent_tbill_net_return": 0.0,
            "annual_cash_gap": 0.0,
            "required_portfolio_growth": rf_gross,
            "tbill_91d_rate": rf_gross,
            "net_tbill_91d_rate": rf_net,
            "macro_status": "NO_HOLDINGS",
            "macro_badge": "⚪ No Holdings",
            "macro_advisory": "No stocks recorded in portfolio. Record your stock purchases to compare your cash yield against CBK Treasury Bills.",
            "holding_breakdown": [],
        }

    from data.stocks_registry import get_dividend_per_share, get_payout_frequency

    total_value = 0.0
    items_calc = []

    for h in holdings:
        ticker = h.get("ticker", "").upper().strip()
        if not ticker:
            continue
        qty = float(h.get("quantity", 1))
        price = float(h.get("current_price", h.get("buy_price", 1.0)))
        market_val = qty * price
        total_value += market_val

        dps = float(h.get("dividend_per_share", get_dividend_per_share(ticker)))
        annual_div_cash = qty * dps
        net_div_cash = annual_div_cash * (1.0 - WHT_EQUITY_RESIDENT)
        div_yield = round((dps / price) * 100, 2) if price > 0 else 0.0
        net_div_yield = round(div_yield * (1.0 - WHT_EQUITY_RESIDENT), 2)

        items_calc.append({
            "ticker": ticker,
            "quantity": qty,
            "price": price,
            "market_value": market_val,
            "dps": dps,
            "annual_dividends": annual_div_cash,
            "net_annual_dividends": net_div_cash,
            "dividend_yield": div_yield,
            "net_dividend_yield": net_div_yield,
            "payout_frequency": get_payout_frequency(ticker),
        })

    if total_value <= 0:
        total_value = 1.0

    # Calculate portfolio weighted yields
    total_annual_divs = sum(i["annual_dividends"] for i in items_calc)
    total_net_annual_divs = sum(i["net_annual_dividends"] for i in items_calc)
    
    port_div_yield = round((total_annual_divs / total_value) * 100, 2)
    port_net_div_yield = round((total_net_annual_divs / total_value) * 100, 2)

    # Opportunity Cost: What would KES total_value earn in CBK 91-Day T-Bills?
    tbill_annual_gross = round(total_value * (rf_gross / 100.0), 2)
    tbill_annual_net = round(tbill_annual_gross * (1.0 - WHT_TBILL_RATE), 2)

    # Net Cash Income Differential (Annual cash payout gap)
    annual_cash_gap = round(total_net_annual_divs - tbill_annual_net, 2)

    # Required annual portfolio capital appreciation
    required_growth = round(max(0.0, rf_gross - port_div_yield), 2)
    net_required_growth = round(max(0.0, rf_net - port_net_div_yield), 2)

    # Calculate weights per holding
    holding_breakdown = []
    for item in items_calc:
        weight_pct = round((item["market_value"] / total_value) * 100, 1)
        holding_breakdown.append({
            "ticker": item["ticker"],
            "quantity": int(item["quantity"]),
            "market_value": round(item["market_value"], 2),
            "weight_pct": weight_pct,
            "dividend_per_share": item["dps"],
            "annual_dividends": round(item["annual_dividends"], 2),
            "dividend_yield": item["dividend_yield"],
            "net_dividend_yield": item["net_dividend_yield"],
            "payout_frequency": item["payout_frequency"],
        })

    # Sort holdings by weight
    holding_breakdown.sort(key=lambda x: x["weight_pct"], reverse=True)

    # Macro Status & Advisory
    if port_div_yield >= 10.0:
        macro_status = "HIGH_INCOME"
        macro_badge = "🔥 High-Yield Defensive Portfolio"
        macro_color = "#00e676"
        macro_advisory = (
            f"Outstanding cash-flow engine. Your portfolio yields {port_div_yield:.1f}% (KES {total_annual_divs:,.2f}/yr), "
            f"delivering income that nearly matches risk-free 91-day T-bills ({rf_gross:.1f}%). "
            f"Your equities only need +{required_growth:.1f}% annual share appreciation to outperform government paper."
        )
    elif port_div_yield >= 5.0:
        macro_status = "BALANCED"
        macro_badge = "⚖️ Balanced Income & Growth"
        macro_color = "#69f0ae"
        macro_advisory = (
            f"Healthy income cushion. Your portfolio generates KES {total_annual_divs:,.2f} in gross annual dividends ({port_div_yield:.1f}% yield). "
            f"To beat the 91-day CBK T-Bill rate of {rf_gross:.1f}%, your holdings need to deliver at least +{required_growth:.1f}% in annual capital gains."
        )
    elif port_div_yield > 0.0:
        macro_status = "GROWTH_FOCUSED"
        macro_badge = "📈 Growth-Oriented (High Hurdle)"
        macro_color = "#ffd700"
        macro_advisory = (
            f"Growth-heavy portfolio. With a dividend yield of {port_div_yield:.1f}% (KES {total_annual_divs:,.2f}/yr), "
            f"your investment return heavily relies on capital appreciation. Your shares must appreciate by +{required_growth:.1f}%/year to beat risk-free government debt."
        )
    else:
        macro_status = "NO_DIVIDEND"
        macro_badge = "⚠️ Pure Capital Appreciation (15.7% Hurdle)"
        macro_color = "#ff5252"
        macro_advisory = (
            f"Zero dividend cash flow. Your entire return depends on stock price growth. "
            f"Holding these equities carries a high opportunity cost compared to the guaranteed {rf_gross:.1f}% yield on 91-day T-Bills."
        )

    return {
        "has_holdings": True,
        "total_portfolio_value": round(total_value, 2),
        "portfolio_dividend_yield": port_div_yield,
        "portfolio_net_dividend_yield": port_net_div_yield,
        "expected_annual_dividends": round(total_annual_divs, 2),
        "expected_net_annual_dividends": round(total_net_annual_divs, 2),
        "equivalent_tbill_gross_return": tbill_annual_gross,
        "equivalent_tbill_net_return": tbill_annual_net,
        "annual_cash_gap": annual_cash_gap,
        "required_portfolio_growth": required_growth,
        "net_required_portfolio_growth": net_required_growth,
        "tbill_91d_rate": rf_gross,
        "net_tbill_91d_rate": rf_net,
        "macro_status": macro_status,
        "macro_badge": macro_badge,
        "macro_color": macro_color,
        "macro_advisory": macro_advisory,
        "holding_breakdown": holding_breakdown,
    }
