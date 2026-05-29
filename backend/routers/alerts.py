import os
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from auth.database import get_db
from auth.dependencies import get_current_user
from auth.models import User
from pydantic import BaseModel
from typing import List

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/alerts", tags=["Alerts & Notifications"])

# We'll persist subscriptions in a simple table or file, or a list.
# For simplicity, we can dynamically save/fetch subscribed user numbers from the user model!
# Let's add a quick subscription check. We'll simulate a SMS subscription database or log.

class SubscribeRequest(BaseModel):
    phone_number: str

# Keep track of subscriptions in-memory or in simple backend/tmp/alerts.txt file
SUBSCRIPTIONS_FILE = os.path.join(os.path.dirname(__file__), "..", "tmp", "alert_subscribers.txt")

def _load_subscribers() -> List[str]:
    os.makedirs(os.path.dirname(SUBSCRIPTIONS_FILE), exist_ok=True)
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return []
    with open(SUBSCRIPTIONS_FILE, "r") as f:
        return [line.strip() for line in f if line.strip()]

def _save_subscriber(phone: str):
    os.makedirs(os.path.dirname(SUBSCRIPTIONS_FILE), exist_ok=True)
    subs = _load_subscribers()
    if phone not in subs:
        with open(SUBSCRIPTIONS_FILE, "a") as f:
            f.write(f"{phone}\n")

def send_sms_via_africastalking(message: str, recipients: List[str]):
    """Sends SMS using Africa's Talking API, falling back to file logging if unconfigured."""
    username = os.getenv("AFRICAS_TALKING_USERNAME", "sandbox")
    api_key = os.getenv("AFRICAS_TALKING_API_KEY", "")
    
    if not api_key:
        # Local logging fallback
        sms_log_path = os.path.join(os.path.dirname(__file__), "..", "tmp", "sms_outbox.log")
        os.makedirs(os.path.dirname(sms_log_path), exist_ok=True)
        with open(sms_log_path, "a") as f:
            import datetime
            f.write(f"[{datetime.datetime.now().isoformat()}] Recipients: {recipients} | Message: {message}\n")
        logger.info("[MOCK SMS] Sent to %s: %s", recipients, message)
        return {"status": "success", "mode": "sandbox", "log": sms_log_path}

    try:
        import africastalking
        africastalking.initialize(username, api_key)
        sms = africastalking.SMS
        response = sms.send(message, recipients)
        logger.info("Africa's Talking SMS response: %s", response)
        return {"status": "success", "response": response}
    except Exception as e:
        logger.error("Failed to send SMS via Africa's Talking: %s", e)
        # Log to local file anyway
        sms_log_path = os.path.join(os.path.dirname(__file__), "..", "tmp", "sms_outbox.log")
        with open(sms_log_path, "a") as f:
            f.write(f"[ERROR SENDING: {e}] Recipients: {recipients} | Message: {message}\n")
        return {"status": "failed", "error": str(e)}

@router.post("/subscribe")
def subscribe_to_alerts(body: SubscribeRequest, current_user: User = Depends(get_current_user)):
    """Subscribe user's phone number to AI-powered market alerts."""
    phone = body.phone_number.strip()
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Phone number must include country code (e.g. +254700000000)")
        
    _save_subscriber(phone)
    
    # Send a welcome SMS
    welcome_msg = (
        "NSE AI Platform: Subscribed successfully! "
        "You will receive daily high-confidence AI signal recommendations and important market updates."
    )
    send_sms_via_africastalking(welcome_msg, [phone])
    
    return {"message": "Successfully subscribed to SMS alerts", "phone_number": phone}

@router.get("/subscribers")
def get_subscribers(current_user: User = Depends(get_current_user)):
    """List all registered alert subscribers."""
    return {"subscribers": _load_subscribers()}

@router.post("/broadcast")
def broadcast_market_update(message: str, background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user)):
    """Broadcast a critical market update or signal to all subscribers."""
    subscribers = _load_subscribers()
    if not subscribers:
        return {"message": "No subscribers registered to receive updates."}
        
    # Queue the sending in background tasks to avoid blocking the API thread
    background_tasks.add_task(send_sms_via_africastalking, message, subscribers)
    return {"message": f"Broadcast queued in background for {len(subscribers)} subscribers"}
