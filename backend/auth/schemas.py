"""NSE AI Platform — Auth Pydantic Schemas"""
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class RegisterRequest(BaseModel):
    name:     str
    email:    EmailStr
    password: str


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    credential: str   # Google ID token from GIS


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         "UserPublic"


class UserPublic(BaseModel):
    id:         str
    email:      str
    name:       str
    avatar_url: Optional[str]
    provider:   str
    created_at: datetime

    class Config:
        from_attributes = True


TokenResponse.model_rebuild()
