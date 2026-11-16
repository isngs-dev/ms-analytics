from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AppUser
from ..security import ROLES, decode_token

COOKIE_NAME = "ms_session"


def current_user(request: Request, db: Session = Depends(get_db)) -> AppUser:
    token = request.cookies.get(COOKIE_NAME)
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:]
    claims = decode_token(token) if token else None
    if not claims:
        raise HTTPException(401, "Not authenticated")
    user = db.get(AppUser, int(claims["sub"]))
    if user is None or not user.active:
        raise HTTPException(401, "Not authenticated")
    return user  # role comes from the database row, not from the token


def require_role(minimum: str):
    def dep(user: AppUser = Depends(current_user)) -> AppUser:
        if ROLES.get(user.role, 0) < ROLES[minimum]:
            raise HTTPException(403, f"{minimum} role required")
        return user
    return dep


viewer = Depends(require_role("viewer"))
manager = Depends(require_role("manager"))
admin = Depends(require_role("admin"))
