"""
Import staff users from a CSV.

    python -m app.scripts.import_staff                       # reads app/scripts/staff_users.csv
    python -m app.scripts.import_staff path/to/file.csv
    python -m app.scripts.import_staff --dry-run             # show what would happen, change nothing
    python -m app.scripts.import_staff --reset-passwords     # also overwrite passwords of users that already exist

CSV columns: email,password,name,firm,mobile,telephone,address,city,state,pin_code,status
(status "Inactive" -> the account is created suspended; anything else -> approved).

Each user is created as STAFF (is_staff = true, not admin): they can use the workspace and appear in the
checkout's salesman list. Passwords are hashed exactly like normal registration — they are never stored
in plain text in the database. Emails are saved lower-case. Users that already exist (any letter case)
are NOT duplicated: they are just marked staff (and their password is left alone unless --reset-passwords).

The CSV holds plain-text passwords — delete it once the import has run.
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import func

from app.db import SessionLocal
from app.models.user import User
from app.services.auth_utils import hash_password

DEFAULT_CSV = Path(__file__).with_name("staff_users.csv")


def _clean(v) -> str | None:
    v = (v or "").strip()
    return None if v.lower() in ("", "none", "null") else v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", nargs="?", default=str(DEFAULT_CSV))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reset-passwords", action="store_true")
    args = ap.parse_args()

    path = Path(args.csv_path)
    if not path.exists():
        sys.exit(f"CSV not found: {path}")

    db = SessionLocal()
    created = updated = skipped = 0
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                email = (row.get("email") or "").strip().lower()
                if not email or "@" not in email:
                    print(f"SKIP  (bad email): {row}")
                    skipped += 1
                    continue

                status = "SUSPENDED" if (row.get("status") or "").strip().lower() == "inactive" else "APPROVED"
                user = db.query(User).filter(func.lower(User.email) == email).first()

                if user:
                    user.is_staff = True
                    if args.reset_passwords and _clean(row.get("password")):
                        user.password = hash_password(row["password"].strip())
                    print(f"UPDATE {email}: marked staff" + (" + password reset" if args.reset_passwords else ""))
                    updated += 1
                    continue

                password = _clean(row.get("password"))
                if not password:
                    print(f"SKIP  {email}: no password in the CSV")
                    skipped += 1
                    continue

                db.add(User(
                    email=email,
                    password=hash_password(password),
                    name=_clean(row.get("name")) or email,
                    firm=_clean(row.get("firm")),
                    mobile=_clean(row.get("mobile")),
                    telephone=_clean(row.get("telephone")),
                    address=_clean(row.get("address")),
                    city=_clean(row.get("city")),
                    state=_clean(row.get("state")),
                    pin_code=_clean(row.get("pin_code")),
                    status=status,
                    is_admin=False,
                    is_staff=True,
                    approved_at=datetime.utcnow() if status == "APPROVED" else None,
                    signup_source="itl_ai",
                ))
                print(f"CREATE {email} ({status})")
                created += 1

        if args.dry_run:
            db.rollback()
            print("\nDry run — nothing was saved.")
        else:
            db.commit()
        print(f"\nCreated {created}, updated {updated}, skipped {skipped}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
