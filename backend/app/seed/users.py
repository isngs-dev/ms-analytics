"""Create demo users for local development.

    DEMO_USER_PASSWORD=... python -m app.seed.users

The password comes from the environment (.env), is never printed, and must be at least 10 chars.
"""
from __future__ import annotations

from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import AppUser
from ..security import hash_password

DEMO = [("admin@example.com", "Demo Admin", "admin"), ("manager@example.com", "Demo Manager", "manager"),
        ("viewer@example.com", "Demo Viewer", "viewer")]


def main():
    pw = settings.demo_user_password
    if len(pw) < 10:
        raise SystemExit("Set DEMO_USER_PASSWORD (at least 10 characters) in .env first.")
    with SessionLocal() as s:
        for email, name, role in DEMO:
            if s.scalar(select(AppUser.id).where(AppUser.email == email)) is None:
                s.add(AppUser(email=email, name=name, role=role, password_hash=hash_password(pw)))
                print(f"created {role}: {email}")
            else:
                print(f"exists  {role}: {email}")
        s.commit()


if __name__ == "__main__":
    main()
