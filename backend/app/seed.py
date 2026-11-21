"""Create the first Admin account (run once).

    python -m app.seed admin@company.com "Full Name"
The password is asked for interactively (or read from WORKCODE_ADMIN_PASSWORD).
"""
import getpass
import os
import sys

from app.core.security import hash_password
from app.database.connection import SessionLocal
from app.database.models import AdminProfile, EmploymentHistory, InternVacancy, User
from app.core.config import settings


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    email, name = sys.argv[1].strip().lower(), sys.argv[2]
    password = os.environ.get("WORKCODE_ADMIN_PASSWORD") or getpass.getpass("Admin password (min 8 chars): ")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters.")
    db = SessionLocal()
    try:
        if db.query(User).filter_by(email=email).first():
            sys.exit("A user with this email already exists.")
        if db.query(User).filter_by(role="admin", is_active=True).count() >= settings.MAX_ADMINS:
            sys.exit(f"{settings.MAX_ADMINS} admin accounts already exist.")
        u = User(email=email, full_name=name, role="admin", password_hash=hash_password(password))
        db.add(u)
        db.flush()
        db.add(AdminProfile(user_id=u.id))
        db.add(EmploymentHistory(user_id=u.id, event="joined", to_role="admin"))
        if not db.query(InternVacancy).first():
            db.add(InternVacancy(target_headcount=settings.INTERN_TARGET_HEADCOUNT))
        db.commit()
        print(f"Admin created: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
