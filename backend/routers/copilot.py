"""
NSE AI Platform — Conversational Copilot Router
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from auth.database import get_db
from auth.dependencies import get_current_user
from auth.models import User, WatchlistItem, PortfolioItem
from data.fetcher import get_all_stocks, get_stock_info, get_news_feed
from ml.predictor import predict
from data.stocks_registry import NSE_STOCKS
import httpx

router = APIRouter(prefix="/api/copilot", tags=["Copilot"])

class ChatRequest(BaseModel):
    message: str

@router.post("/chat")
async def chat_copilot(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    RAG-powered conversational investment copilot.
    Extracts tickers, holdings, and metrics to synthesize dynamic responses.
    """
    user_msg = body.message.strip().lower()
    
    # 1. Extract tickers mentioned in the user's message
    mentioned_tickers = []
    for ticker in NSE_STOCKS.keys():
        if f" {ticker.lower()}" in f" {user_msg} " or f"({ticker.lower()})" in user_msg:
            mentioned_tickers.append(ticker)
            
    # 2. Gather context based on query intent
    context = []
    
    # Handle portfolio queries
    if "portfolio" in user_msg or "holdings" in user_msg or "my shares" in user_msg:
        holdings = db.query(PortfolioItem).filter(PortfolioItem.user_id == current_user.id).all()
        if holdings:
            context.append("User's Portfolio holdings:")
            for h in holdings:
                live = get_stock_info(h.ticker)
                curr_p = live["price"] if live else h.buy_price
                pl = (curr_p - h.buy_price) * h.quantity
                context.append(f"- {h.ticker}: {h.quantity} shares, bought at KES {h.buy_price:.2f}, current price: KES {curr_p:.2f} (P&L: KES {pl:+.2f})")
        else:
            context.append("User does not have any assets in their portfolio currently.")
            
    # Handle stock queries
    if mentioned_tickers:
        context.append("Real-time metrics for mentioned stocks:")
        for t in mentioned_tickers[:3]:
            info = get_stock_info(t)
            if info:
                # Get prediction
                news = get_news_feed()
                related = [a for a in news if t in a.get("related_tickers", [])]
                sentiment_label = "NEUTRAL"
                if related:
                    pos = sum(1 for a in related if a.get("sentiment", {}).get("label") == "POSITIVE")
                    neg = sum(1 for a in related if a.get("sentiment", {}).get("label") == "NEGATIVE")
                    sentiment_label = "POSITIVE" if pos > neg else ("NEGATIVE" if neg > pos else "NEUTRAL")
                
                context.append(f"- {t} ({info['name']}): Price KES {info['price']:.2f} ({info['change_pct']:+.2f}%), Sector: {info['sector']}, Sentiment: {sentiment_label}")
                if len(related) > 0:
                    context.append(f"  Latest news: \"{related[0]['title']}\" ({related[0]['source']})")
                    
    # Handle general recommendation queries
    if "recommend" in user_msg or "buy" in user_msg or "best stock" in user_msg:
        stocks = get_all_stocks()
        gainers = [s for s in stocks if s["change_pct"] > 0]
        gainers.sort(key=lambda x: x["change_pct"], reverse=True)
        context.append("Top gaining stocks today:")
        for g in gainers[:3]:
            context.append(f"- {g['ticker']}: KES {g['price']:.2f} ({g['change_pct']:+.2f}%)")

    # 3. Call OpenAI / external LLM if API Key is configured, else use rule-based template generator
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key and len(openai_key) > 10:
        try:
            headers = {
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are Antigravity, the expert AI investment copilot for the Nairobi Securities Exchange (NSE). Answer the user's question accurately using the provided local context. Keep responses concise, professional, and formatted in markdown. Always include specific prices, P&L numbers, and news details from the context. Recommend watchlists or portfolios if appropriate."},
                    {"role": "user", "content": f"Context:\n" + "\n".join(context) + f"\n\nQuestion: {body.message}"}
                ],
                "max_tokens": 300,
                "temperature": 0.5
            }
            async with httpx.AsyncClient() as client:
                res = await client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=10.0)
                if res.status_code == 200:
                    answer = res.json()["choices"][0]["message"]["content"]
                    return {"reply": answer, "rag_sources": mentioned_tickers}
        except Exception as e:
            # Fallback to local rule-based engine on API error
            pass

    # 4. Local Rule-Based Template Generator (Default Fallback)
    reply = ""
    if "portfolio" in user_msg or "holdings" in user_msg:
        holdings = db.query(PortfolioItem).filter(PortfolioItem.user_id == current_user.id).all()
        if not holdings:
            reply = "You don't have any stocks in your portfolio yet! Go to the portfolio section, enter a transaction price and quantity, and click **Buy** to track your holdings."
        else:
            total_val = 0
            total_cost = 0
            for h in holdings:
                live = get_stock_info(h.ticker)
                p = live["price"] if live else h.buy_price
                total_val += p * h.quantity
                total_cost += h.buy_price * h.quantity
            profit = total_val - total_cost
            pct = (profit / total_cost * 100) if total_cost > 0 else 0
            reply = f"### 💼 Portfolio Overview\n\nYour portfolio is currently valued at **KES {total_val:,.2f}** against a total purchase cost of **KES {total_cost:,.2f}**.\n\nYour total net profit/loss is **KES {profit:+,.2f} ({pct:+.2f}%)**.\n\n*   Use the new **AI Portfolio Optimizer** at the top of your portfolio tab to compute the mathematically optimal weight distributions using Modern Portfolio Theory!"
            
    elif mentioned_tickers:
        t = mentioned_tickers[0]
        info = get_stock_info(t)
        if info:
            up_down = "up" if info["change_pct"] >= 0 else "down"
            arrow = "▲" if info["change_pct"] >= 0 else "▼"
            reply = f"### 📊 Analysis for {t} ({info['name']})\n\n"
            reply += f"*   **Current Price**: KES {info['price']:.2f}\n"
            reply += f"*   **Daily Change**: {info['change_pct']:+.2f}% {arrow}\n"
            reply += f"*   **Sector**: {info['sector']}\n\n"
            
            # Find news
            news = get_news_feed()
            related = [a for a in news if t in a.get("related_tickers", [])]
            if related:
                reply += f"**Latest Ticker News**:\n"
                reply += f"*   *\"{related[0]['title']}\"* — {related[0]['source']} ({related[0]['published']})\n\n"
            
            reply += f"Would you like me to analyze its technical indicators (RSI, MACD) or add it to your Watchlist?"
    else:
        # Default welcome/help message
        reply = "### 👋 Hello! I'm your NSE AI Investment Copilot.\n\nHow can I help you today? You can ask me questions like:\n"
        reply += "*   *\"Analyze SCOM and check its latest price.\"*\n"
        reply += "*   *\"How is my portfolio performing?\"*\n"
        reply += "*   *\"What are the top gaining stocks today?\"*\n\n"
        reply += "Just mention a stock ticker (like `SCOM`, `EQTY`, `EABL`) to get instant metrics!"

    return {"reply": reply, "rag_sources": mentioned_tickers}
