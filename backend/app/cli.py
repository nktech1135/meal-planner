"""Server-side maintenance commands (run on the host, e.g. via `mealplan reset-link`).

    python -m app.cli reset-link EMAIL [--base-url URL]
    python -m app.cli make-admin EMAIL
"""

import argparse
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.services.accounts import new_reset_token
from app.settings_store import runtime_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mealplan")
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser("reset-link", help="print a one-time password reset link (valid 24 h)")
    reset.add_argument("email")
    reset.add_argument("--base-url", help="site address, if not set in Settings")
    admin = sub.add_parser("make-admin", help="give an account admin rights")
    admin.add_argument("email")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if user is None:
            print(f"No account with email {args.email}", file=sys.stderr)
            return 1
        if args.command == "make-admin":
            user.is_admin = user.is_active = True
            db.commit()
            print(f"{user.email} is now an admin")
            return 0
        base = args.base_url or runtime_settings(db).public_url
        token = new_reset_token(db, user)
        if base:
            print(f"{base.rstrip('/')}/reset-password?token={token}")
        else:
            print(f"Open <your site address>/reset-password?token={token}\n"
                  "(set the site address in Settings, or pass --base-url, to get a full link)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
