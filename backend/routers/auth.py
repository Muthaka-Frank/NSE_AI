"""
NSE AI Platform — Authentication Router
"""
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from auth.database import get_db
from auth.models import User
from auth.schemas import RegisterRequest, LoginRequest, GoogleAuthRequest, TokenResponse, UserPublic
from auth.utils import hash_password, verify_password, create_access_token, verify_google_token
from auth.dependencies import get_current_user

load_dotenv()
router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.get("/google-config")
def google_config():
    """Return the Google Client ID for the frontend (safe — not a secret)."""
    return {"client_id": os.getenv("GOOGLE_CLIENT_ID", "")}


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    user = User(
        email=body.email,
        name=body.name,
        provider="email",
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token, user=UserPublic.model_validate(user))


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    user.last_login = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token, user=UserPublic.model_validate(user))


# ── Google OAuth ──────────────────────────────────────────────────────────────

@router.post("/google", response_model=TokenResponse)
def google_auth(body: GoogleAuthRequest, db: Session = Depends(get_db)):
    info = verify_google_token(body.credential)
    if not info:
        raise HTTPException(
            status_code=401,
            detail="Invalid Google token. Ensure GOOGLE_CLIENT_ID is set in .env"
        )

    email      = info.get("email")
    name       = info.get("name", email)
    avatar_url = info.get("picture")

    # Upsert: find existing user or create new one
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name=name, avatar_url=avatar_url, provider="google")
        db.add(user)
    else:
        # Update profile from Google in case it changed
        user.name       = name
        user.avatar_url = avatar_url
        if user.provider == "email":
            user.provider = "google+email"  # linked account

    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token, user=UserPublic.model_validate(user))


# ── Me ────────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)):
    return UserPublic.model_validate(current_user)


# ── Logout info (client-side) ─────────────────────────────────────────────────

@router.post("/logout")
def logout():
    """JWT is stateless — logout is handled client-side by deleting the token."""
    return {"message": "Logged out. Delete your token client-side."}
