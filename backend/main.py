"""
NSE AI Platform — FastAPI Entry Point
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from routers import stocks, news, recommendations
from routers import auth as auth_router
from routers import watchlist, alerts
import data.alpha_vantage as av
from auth.database import init_db
from data.scheduler import start_scheduler

load_dotenv()

app = FastAPI(
    title="NSE AI Investment Intelligence API",
    description="AI-powered stock analysis, news sentiment & recommendations for the Nairobi Securities Exchange.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    init_db()   # create users table if not exists
    start_scheduler()  # start daily scraper scheduler loop

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(stocks.router)
app.include_router(news.router)
app.include_router(recommendations.router)
app.include_router(auth_router.router)
app.include_router(watchlist.router)
app.include_router(alerts.router)


@app.get("/")
def root():
    return {
        "service": "NSE AI Investment Intelligence API",
        "version": "1.0.0",
        "status":  "operational",
        "docs":    "/docs",
        "endpoints": {
            "stocks":          "/api/stocks",
            "stock_detail":    "/api/stocks/{ticker}",
            "stock_history":   "/api/stocks/{ticker}/history",
            "stock_signal":    "/api/stocks/{ticker}/prediction",
            "news":            "/api/news",
            "recommendations": "/api/recommendations",
            "data_sources":    "/api/data-sources",
            "auth_register":   "/api/auth/register",
            "auth_login":      "/api/auth/login",
            "auth_google":     "/api/auth/google",
            "auth_me":         "/api/auth/me",
            "watchlist":       "/api/watchlist",
            "portfolio":       "/api/portfolio",
            "alerts_sub":      "/api/alerts/subscribe",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/data-sources")
def data_sources():
    av_configured = av.is_configured()
    av_quota      = av.remaining_calls() if av_configured else None
    return {
        "sources": {
            "yahoo_finance":  {"active": True,  "description": "Yahoo Finance — 15-min delayed"},
            "alpha_vantage":  {"active": av_configured, "quota": av_quota,
                               "setup": "Add ALPHA_VANTAGE_API_KEY to .env" if not av_configured else None},
            "estimated":      {"active": True,  "description": "Deterministic mock fallback"},
        },
        "priority": ["yahoo_finance", "alpha_vantage", "estimated"],
    }
