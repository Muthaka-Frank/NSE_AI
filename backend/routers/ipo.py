"""
NSE AI Platform — IPO Listings & Alerts Router
Provides endpoints to query upcoming NSE IPO listings, manage SMS alert subscriptions,
and trigger news-based IPO signal scans.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from auth.database import get_db
from auth.models import IPOListing, IPOSubscriber, User
from auth.dependencies import get_current_user_optional
from ml.ipo_detector import seed_ipo_pipeline, scan_articles_for_ipo_signals, check_and_send_ipo_alert
from data.fetcher import get_news_feed

router = APIRouter(prefix="/api/ipo", tags=["IPO Alerts & Pipeline"])


class IPOSubscribeRequest(BaseModel):
    phone_number: str
    email: Optional[str] = None


class SimulateAlertRequest(BaseModel):
    ipo_id: Optional[str] = None
    custom_company: Optional[str] = None
    custom_price: Optional[float] = None


def _format_ipo_dict(ipo: IPOListing) -> dict:
    today_str = datetime.now().strftime("%Y-%m-%d")
    days_to_open = None
    days_to_close = None
    
    if ipo.offer_open_date:
        try:
            d_open = datetime.strptime(ipo.offer_open_date, "%Y-%m-%d")
            d_today = datetime.strptime(today_str, "%Y-%m-%d")
            days_to_open = (d_open - d_today).days
        except Exception:
            pass
            
    if ipo.offer_close_date:
        try:
            d_close = datetime.strptime(ipo.offer_close_date, "%Y-%m-%d")
            d_today = datetime.strptime(today_str, "%Y-%m-%d")
            days_to_close = (d_close - d_today).days
        except Exception:
            pass

    return {
        "id": ipo.id,
        "company_name": ipo.company_name,
        "proposed_ticker": ipo.proposed_ticker,
        "sector": ipo.sector,
        "listing_type": ipo.listing_type,
        "offer_price": ipo.offer_price,
        "offer_price_range": ipo.offer_price_range,
        "shares_offered": ipo.shares_offered,
        "target_capital": ipo.target_capital,
        "min_application_shares": ipo.min_application_shares,
        "announcement_date": ipo.announcement_date,
        "offer_open_date": ipo.offer_open_date,
        "offer_close_date": ipo.offer_close_date,
        "allotment_date": ipo.allotment_date,
        "listing_date": ipo.listing_date,
        "status": ipo.status,
        "cma_approval": ipo.cma_approval,
        "prospectus_url": ipo.prospectus_url,
        "ai_summary": ipo.ai_summary,
        "ai_verdict": ipo.ai_verdict,
        "ai_verdict_score": ipo.ai_verdict_score,
        "highlights": [h.strip() for h in (ipo.highlights or "").split(";") if h.strip()],
        "risk_factors": [r.strip() for r in (ipo.risk_factors or "").split(";") if r.strip()],
        "is_active_alert": ipo.is_active_alert,
        "days_to_open": days_to_open,
        "days_to_close": days_to_close,
        "created_at": ipo.created_at.isoformat() if ipo.created_at else None,
    }


@router.get("")
def list_ipos(status: Optional[str] = Query(None, description="Filter by status e.g. OFFER_OPEN, UPCOMING, LISTED"), db: Session = Depends(get_db)):
    """List all tracked IPOs with pipeline statistics and currently active alert banner."""
    # Ensure seed data exists
    seed_ipo_pipeline(db)
    
    query = db.query(IPOListing)
    if status:
        query = query.filter(IPOListing.status == status.upper())
        
    all_ipos = query.all()
    
    # Sort order: OFFER_OPEN first, then UPCOMING, then others
    status_priority = {"OFFER_OPEN": 0, "UPCOMING": 1, "OFFER_CLOSED": 2, "LISTED": 3, "POSTPONED": 4}
    formatted = [_format_ipo_dict(item) for item in all_ipos]
    formatted.sort(key=lambda x: (status_priority.get(x["status"], 9), x["offer_open_date"] or "9999-99-99"))
    
    # Identify the highest priority active alert item
    active_alert = next((x for x in formatted if x["is_active_alert"] and x["status"] in ["OFFER_OPEN", "UPCOMING"]), None)
    
    stats = {
        "total": len(formatted),
        "offer_open_count": sum(1 for x in formatted if x["status"] == "OFFER_OPEN"),
        "upcoming_count": sum(1 for x in formatted if x["status"] == "UPCOMING"),
        "listed_count": sum(1 for x in formatted if x["status"] == "LISTED")
    }
    
    return {
        "pipeline": formatted,
        "stats": stats,
        "active_alert": active_alert
    }


@router.get("/active")
def get_active_ipo_alert(db: Session = Depends(get_db)):
    """Returns currently active IPO alert for in-app banner display."""
    seed_ipo_pipeline(db)
    active = db.query(IPOListing).filter(
        IPOListing.is_active_alert.is_(True),
        IPOListing.status.in_(["OFFER_OPEN", "UPCOMING"])
    ).order_by(
        IPOListing.status.asc()  # OFFER_OPEN before UPCOMING alphabetically
    ).first()
    
    if not active:
        return {"has_active_alert": False, "alert": None}
        
    formatted = _format_ipo_dict(active)
    return {
        "has_active_alert": True,
        "alert": formatted
    }


@router.get("/{ipo_id}")
def get_ipo_detail(ipo_id: str, db: Session = Depends(get_db)):
    """Get detailed prospectus breakdown and timetable for a specific IPO."""
    ipo = db.query(IPOListing).filter(IPOListing.id == ipo_id).first()
    if not ipo:
        raise HTTPException(status_code=404, detail="IPO listing not found")
    return _format_ipo_dict(ipo)


@router.post("/subscribe")
def subscribe_to_ipo_alerts(
    body: IPOSubscribeRequest,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """Subscribe a user's mobile phone number to instant SMS alerts for new NSE IPOs."""
    phone = body.phone_number.strip()
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Phone number must include country code (e.g. +254700000000)")
        
    sub = db.query(IPOSubscriber).filter(IPOSubscriber.phone_number == phone).first()
    if not sub:
        sub = IPOSubscriber(
            user_id=current_user.id if current_user else None,
            phone_number=phone,
            email=body.email or (current_user.email if current_user else None),
            sms_enabled=True
        )
        db.add(sub)
    else:
        sub.sms_enabled = True
        if current_user and not sub.user_id:
            sub.user_id = current_user.id
            
    db.commit()
    
    # Send a confirmation SMS
    welcome_text = (
        "NSE AI Platform: You are now subscribed to real-time IPO alerts! "
        "You will receive instant SMS notifications when new companies file to list or float shares on the Nairobi Securities Exchange."
    )
    from routers.alerts import send_sms_via_africastalking
    send_sms_via_africastalking(welcome_text, [phone])
    
    return {
        "message": "Successfully subscribed to real-time NSE IPO alerts",
        "phone_number": phone
    }


@router.post("/scan")
def scan_news_for_ipos(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Scans live RSS news articles for breaking IPO announcements and triggers notifications."""
    seed_ipo_pipeline(db)
    news_items = get_news_feed()
    detected = scan_articles_for_ipo_signals(news_items)
    
    # If active IPOs exist, check and send alerts if needed
    active_ipos = db.query(IPOListing).filter(IPOListing.is_active_alert.is_(True)).all()
    dispatched = []
    
    for ipo in active_ipos:
        res = check_and_send_ipo_alert(ipo, event_type="AUTOMATED_SCAN", db=db)
        if res.get("status") == "sent":
            dispatched.append(ipo.company_name)
            
    return {
        "scanned_articles_count": len(news_items),
        "detected_ipo_events": detected,
        "dispatched_alerts": dispatched
    }


@router.post("/simulate-alert")
def simulate_ipo_alert(
    body: SimulateAlertRequest,
    db: Session = Depends(get_db)
):
    """
    Test/demo endpoint: Triggers a simulated real-time IPO announcement alert
    and dispatches SMS outbox entries.
    """
    seed_ipo_pipeline(db)
    
    if body.ipo_id:
        target_ipo = db.query(IPOListing).filter(IPOListing.id == body.ipo_id).first()
    else:
        target_ipo = db.query(IPOListing).filter(IPOListing.status == "OFFER_OPEN").first()
        if not target_ipo:
            target_ipo = db.query(IPOListing).first()
            
    if not target_ipo:
        raise HTTPException(status_code=404, detail="No IPO listing available for simulation.")
        
    # Temporarily force bypass duplicate filter for test simulation
    from routers.alerts import send_sms_via_africastalking, _load_subscribers
    recipients = set(_load_subscribers())
    ipo_subs = db.query(IPOSubscriber).filter(IPOSubscriber.sms_enabled.is_(True)).all()
    for s in ipo_subs:
        recipients.add(s.phone_number)
        
    company = body.custom_company or target_ipo.company_name
    price = body.custom_price or (target_ipo.offer_price or 16.50)
    
    msg = (
        f"🔔 [TEST SIMULATION] NSE IPO ALERT: {company} Initial Public Offering is approved by CMA! "
        f"Offer Price: KES {price:.2f}. "
        f"Subscription window opens soon. Check prospectus on NSE AI Platform."
    )
    
    result = send_sms_via_africastalking(msg, list(recipients) if recipients else ["+254700000000"])
    
    return {
        "status": "simulation_dispatched",
        "message": msg,
        "recipients_count": len(recipients) if recipients else 1,
        "simulated_ipo": company,
        "sms_result": result
    }
