from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import settings
from ...db import get_db
from ...models import AppUser
from ...security import create_token, verify_password
from ..deps import COOKIE_NAME, current_user

router = APIRouter(prefix="/auth", tags=["auth"])

# in-memory throttle (per process): 8 attempts / 5 min per (email, ip)
_ATTEMPTS: dict[tuple[str, str], deque] = defaultdict(deque)
_WINDOW, _LIMIT = 300, 8
# a valid-format hash used to keep response time similar when the email does not exist
_DUMMY = "pbkdf2_sha256$310000$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


class LoginIn(BaseModel):
    email: str
    password: str


def user_out(u: AppUser) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    key = (body.email.lower(), request.client.host if request.client else "?")
    q, now = _ATTEMPTS[key], time.time()
    while q and now - q[0] > _WINDOW:
        q.popleft()
    if len(q) >= _LIMIT:
        raise HTTPException(429, "Too many attempts, try again later")
    user = db.scalar(select(AppUser).where(func.lower(AppUser.email) == body.email.lower()))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY)
    if not (user and user.active and ok):
        q.append(now)
        raise HTTPException(401, "Invalid email or password")
    q.clear()
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    token = create_token(user.id, user.role)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
                        max_age=settings.jwt_expire_minutes * 60, path="/")
    return {"user": user_out(user)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: AppUser = Depends(current_user)):
    return user_out(user)
