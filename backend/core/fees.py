"""
NSE AI Platform — Statutory Brokerage Fee & Regulatory Tax Engine
Adheres to Capital Markets Authority (CMA) and Nairobi Securities Exchange (NSE) statutory fee schedules:
  - Brokerage Commission: 1.50% (capped retail equity rate)
  - VAT on Brokerage Commission: 16% (0.24%)
  - CMA Regulatory Levy: 0.14%
  - NSE Transaction Levy: 0.12%
  - CDSC Clearing Fee: 0.08%
  - Investor Compensation Fund (ICF): 0.01%
Total single-way equity fee = 2.09% (approx 2.10%)
Roundtrip breakeven hurdle = (1 + fee) / (1 - fee) - 1 ≈ +4.27% (or 4.29% at 2.10%)
Withholding Tax on Dividends: 5% (Resident), 15% (Non-Resident)
"""

from typing import Dict, Any

# ── Statutory Equity Fee Schedule (Kenya CMA / NSE / CDSC) ────────────────────
BROKERAGE_RATE: float = 0.0150        # 1.50% Broker Commission
VAT_RATE_ON_BROKERAGE: float = 0.16   # 16% VAT on Brokerage (0.24% of trade)
CMA_LEVY_RATE: float = 0.0014         # 0.14% CMA Regulatory Levy
NSE_LEVY_RATE: float = 0.0012         # 0.12% NSE Transaction Levy
CDSC_LEVY_RATE: float = 0.0008        # 0.08% CDSC Clearing Fee
ICF_LEVY_RATE: float = 0.0001         # 0.01% Investor Compensation Fund

# Aggregate Single-Way Rate: 0.0150 + (0.0150 * 0.16) + 0.0014 + 0.0012 + 0.0008 + 0.0001 = 0.0209 (2.09%)
TOTAL_SINGLE_WAY_RATE: float = (
    BROKERAGE_RATE
    + (BROKERAGE_RATE * VAT_RATE_ON_BROKERAGE)
    + CMA_LEVY_RATE
    + NSE_LEVY_RATE
    + CDSC_LEVY_RATE
    + ICF_LEVY_RATE
)

# Minimum roundtrip breakeven multiplier: (1 + r) / (1 - r)
ROUNDTRIP_BREAKEVEN_MULTIPLIER: float = (1.0 + TOTAL_SINGLE_WAY_RATE) / (1.0 - TOTAL_SINGLE_WAY_RATE)
ROUNDTRIP_BREAKEVEN_HURDLE_PCT: float = (ROUNDTRIP_BREAKEVEN_MULTIPLIER - 1.0) * 100.0  # ~4.269%

# Dividend Withholding Tax (WHT)
WHT_DIVIDEND_RESIDENT: float = 0.05      # 5.0% for Kenyan tax residents
WHT_DIVIDEND_NON_RESIDENT: float = 0.15  # 15.0% for non-residents


def get_fee_schedule() -> Dict[str, Any]:
    """Returns statutory fee components and percentages."""
    return {
        "brokerage_pct": round(BROKERAGE_RATE * 100, 2),
        "vat_on_brokerage_pct": round(BROKERAGE_RATE * VAT_RATE_ON_BROKERAGE * 100, 3),
        "cma_levy_pct": round(CMA_LEVY_RATE * 100, 3),
        "nse_levy_pct": round(NSE_LEVY_RATE * 100, 3),
        "cdsc_levy_pct": round(CDSC_LEVY_RATE * 100, 3),
        "icf_levy_pct": round(ICF_LEVY_RATE * 100, 3),
        "total_single_way_pct": round(TOTAL_SINGLE_WAY_RATE * 100, 2),
        "roundtrip_breakeven_hurdle_pct": round(ROUNDTRIP_BREAKEVEN_HURDLE_PCT, 2),
        "dividend_wht_resident_pct": round(WHT_DIVIDEND_RESIDENT * 100, 1),
        "dividend_wht_non_resident_pct": round(WHT_DIVIDEND_NON_RESIDENT * 100, 1),
    }


def calculate_breakeven_price(buy_price: float) -> float:
    """
    Computes the exact selling price per share required to cover all
    statutory buying and selling fees (net P&L = 0).
    """
    if buy_price <= 0:
        return 0.0
    return round(buy_price * ROUNDTRIP_BREAKEVEN_MULTIPLIER, 2)


def calculate_buy_costs(price: float, quantity: int) -> Dict[str, Any]:
    """
    Computes the itemized buy-side transaction fees and total cash outlay.
    """
    gross_consideration = round(price * quantity, 2)
    brokerage = round(gross_consideration * BROKERAGE_RATE, 2)
    vat = round(brokerage * VAT_RATE_ON_BROKERAGE, 2)
    cma = round(gross_consideration * CMA_LEVY_RATE, 2)
    nse = round(gross_consideration * NSE_LEVY_RATE, 2)
    cdsc = round(gross_consideration * CDSC_LEVY_RATE, 2)
    icf = round(gross_consideration * ICF_LEVY_RATE, 2)
    
    total_fees = round(brokerage + vat + cma + nse + cdsc + icf, 2)
    total_outlay = round(gross_consideration + total_fees, 2)
    breakeven_price = calculate_breakeven_price(price)
    
    return {
        "gross_consideration": gross_consideration,
        "brokerage": brokerage,
        "vat": vat,
        "cma_levy": cma,
        "nse_levy": nse,
        "cdsc_levy": cdsc,
        "icf_levy": icf,
        "total_fees": total_fees,
        "total_outlay": total_outlay,
        "effective_fee_pct": round((total_fees / gross_consideration * 100) if gross_consideration > 0 else 0.0, 2),
        "breakeven_price": breakeven_price,
        "breakeven_hurdle_pct": round(ROUNDTRIP_BREAKEVEN_HURDLE_PCT, 2),
    }


def calculate_sell_proceeds(price: float, quantity: int) -> Dict[str, Any]:
    """
    Computes the itemized sell-side transaction fees and net cash proceeds.
    """
    gross_consideration = round(price * quantity, 2)
    brokerage = round(gross_consideration * BROKERAGE_RATE, 2)
    vat = round(brokerage * VAT_RATE_ON_BROKERAGE, 2)
    cma = round(gross_consideration * CMA_LEVY_RATE, 2)
    nse = round(gross_consideration * NSE_LEVY_RATE, 2)
    cdsc = round(gross_consideration * CDSC_LEVY_RATE, 2)
    icf = round(gross_consideration * ICF_LEVY_RATE, 2)
    
    total_fees = round(brokerage + vat + cma + nse + cdsc + icf, 2)
    net_proceeds = round(gross_consideration - total_fees, 2)
    
    return {
        "gross_consideration": gross_consideration,
        "brokerage": brokerage,
        "vat": vat,
        "cma_levy": cma,
        "nse_levy": nse,
        "cdsc_levy": cdsc,
        "icf_levy": icf,
        "total_fees": total_fees,
        "net_proceeds": net_proceeds,
        "effective_fee_pct": round((total_fees / gross_consideration * 100) if gross_consideration > 0 else 0.0, 2),
    }


def calculate_trade_pnl(buy_price: float, current_price: float, quantity: int) -> Dict[str, Any]:
    """
    Calculates both Gross and Net Profit & Loss for a holding,
    taking into account actual buy-side fees and estimated sell-side exit fees.
    """
    buy = calculate_buy_costs(buy_price, quantity)
    sell = calculate_sell_proceeds(current_price, quantity)
    
    gross_profit_loss = round(sell["gross_consideration"] - buy["gross_consideration"], 2)
    gross_profit_loss_pct = round(
        (gross_profit_loss / buy["gross_consideration"] * 100.0)
        if buy["gross_consideration"] > 0 else 0.0,
        2
    )
    
    total_statutory_fees = round(buy["total_fees"] + sell["total_fees"], 2)
    net_profit_loss = round(sell["net_proceeds"] - buy["total_outlay"], 2)
    net_profit_loss_pct = round(
        (net_profit_loss / buy["total_outlay"] * 100.0)
        if buy["total_outlay"] > 0 else 0.0,
        2
    )
    
    breakeven_price = calculate_breakeven_price(buy_price)
    
    return {
        "quantity": quantity,
        "buy_price": buy_price,
        "current_price": current_price,
        "gross_cost": buy["gross_consideration"],
        "total_outlay": buy["total_outlay"],
        "gross_market_value": sell["gross_consideration"],
        "net_market_value": sell["net_proceeds"],
        "buy_fees": buy["total_fees"],
        "estimated_exit_fees": sell["total_fees"],
        "total_statutory_fees": total_statutory_fees,
        "gross_profit_loss": gross_profit_loss,
        "gross_profit_loss_pct": gross_profit_loss_pct,
        "net_profit_loss": net_profit_loss,
        "net_profit_loss_pct": net_profit_loss_pct,
        "breakeven_price": breakeven_price,
        "breakeven_hurdle_pct": round(ROUNDTRIP_BREAKEVEN_HURDLE_PCT, 2),
    }


def calculate_net_dividend(gross_dividend_per_share: float, shares: int, resident: bool = True) -> Dict[str, Any]:
    """
    Computes net dividend received after Kenya Withholding Tax (WHT).
    """
    wht_rate = WHT_DIVIDEND_RESIDENT if resident else WHT_DIVIDEND_NON_RESIDENT
    gross_dividend = round(gross_dividend_per_share * shares, 2)
    wht_amount = round(gross_dividend * wht_rate, 2)
    net_dividend = round(gross_dividend - wht_amount, 2)
    
    return {
        "shares": shares,
        "gross_dividend_per_share": gross_dividend_per_share,
        "gross_dividend": gross_dividend,
        "wht_rate_pct": round(wht_rate * 100, 1),
        "wht_amount": wht_amount,
        "net_dividend": net_dividend,
        "resident": resident,
    }
