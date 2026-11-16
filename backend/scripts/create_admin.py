"""Create (or reset) one real user, for a deployed system where the demo accounts must not exist.

    ADMIN_PASSWORD='a long password' PYTHONPATH=/app python scripts/create_admin.py you@company.com "Your Name" [admin|manager|viewer]

The password is read from the environment, never printed, and must be at least 12 characters.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AppUser
from app.security import hash_password


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    email, name = sys.argv[1].strip().lower(), sys.argv[2].strip()
    role = sys.argv[3] if len(sys.argv) > 3 else "admin"
    if role not in ("admin", "manager", "viewer"):
        raise SystemExit("role must be admin, manager or viewer")
    pw = os.environ.get("ADMIN_PASSWORD", "")
    if len(pw) < 12:
        raise SystemExit("Set ADMIN_PASSWORD (at least 12 characters) in the environment first.")
    with SessionLocal() as s:
        user = s.scalar(select(AppUser).where(AppUser.email == email))
        if user is None:
            s.add(AppUser(email=email, name=name, role=role, password_hash=hash_password(pw)))
            print(f"created {role}: {email}")
        else:
            user.name, user.role, user.active = name, role, True
            user.password_hash = hash_password(pw)
            print(f"updated {role}: {email} (password reset)")
        s.commit()


if __name__ == "__main__":
    main()
