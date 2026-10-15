"""Give analyses and jobs created before per-user ownership to one user.

Rows with no owner are invisible to every user. Run once to claim them:

    python -m scripts.assign_legacy_owner --email you@example.com          # dry run
    python -m scripts.assign_legacy_owner --email you@example.com --apply  # write changes

Run from the backend directory with DATABASE_URL set.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select, update

from app.db.models import AnalysisJob, AnalysisRecord, User
from app.db.session import SessionLocal, engine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Email of the user who should own the old rows.")
    parser.add_argument("--apply", action="store_true", help="Write the change (default is a dry run).")
    args = parser.parse_args()

    if engine is None or SessionLocal is None:
        print("DATABASE_URL is not configured.", file=sys.stderr)
        return 1

    session = SessionLocal()
    try:
        user = session.scalar(select(User).where(func.lower(User.email) == args.email.strip().lower()))
        if user is None:
            print(f"No user with email {args.email!r}.", file=sys.stderr)
            return 1

        counts = {}
        for model in (AnalysisRecord, AnalysisJob):
            counts[model.__tablename__] = session.scalar(
                select(func.count()).select_from(model).where(model.user_id.is_(None))
            )
        print(f"Unowned rows: {counts}")
        if not args.apply:
            print(f"Dry run. Re-run with --apply to assign them to {user.email} ({user.id}).")
            return 0

        for model in (AnalysisRecord, AnalysisJob):
            session.execute(update(model).where(model.user_id.is_(None)).values(user_id=user.id))
        session.commit()
        print(f"Assigned to {user.email}.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
