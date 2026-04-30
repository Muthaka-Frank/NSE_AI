"""
NSE AI Platform — FastAPI Entry Point
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from routers import stocks, news, recommendations

load_dotenv()

app = FastAPI(
    title="NSE AI Investment Intelligence API",
    description="AI-powered stock analysis, news sentiment & recommendations for the Nairobi Securities Exchange.",
    version="1.0.0",
)

# CORS — allow all origins in development (restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(stocks.router)
app.include_router(news.router)
app.include_router(recommendations.router)


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
            "alerts":          "/api/recommendations/alerts",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}
