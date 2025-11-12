# python scripts/create_user.py --email admin@gmail.com --password "admin123" --full-name "Admin"

import argparse
import sys
from pathlib import Path
from sqlalchemy.exc import IntegrityError

# Ensure project root is on sys.path for 'app' imports when running as a script
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import session as db_session
from app.models.user import User
from app.core.security import hash_password


def main():
    parser = argparse.ArgumentParser(description="Create a user in the database")
    parser.add_argument("--email", required=True, help="Email address (must be unique)")
    parser.add_argument("--password", required=True, help="Plain password (will be hashed)")
    parser.add_argument("--full-name", default="", help="Full name")
    parser.add_argument("--inactive", action="store_true", help="Create as inactive user")

    args = parser.parse_args()

    db_session.init_engine_and_create_tables()
    db = db_session.SessionLocal()

    try:
        user = User(
            email=args.email,
            hashed_password=hash_password(args.password),
            full_name=args.full_name,
            is_active=not args.inactive,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Created user id={user.id} email={user.email}")
    except IntegrityError:
        db.rollback()
        print("Error: A user with that email already exists.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
