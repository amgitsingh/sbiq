"""One-time bootstrap: seed the core roles (Super Admin, Admin, User) and
create the first active Super Admin account.

Without this, a genuinely fresh deployment (empty user_master/role_master
after `alembic upgrade head`) has no way in at all: every route that could
create or activate a user (POST /public/register, POST /admin/registrations/
{id}/activate) either requires an already-active Super Admin session, or -
for plain registration - a "User" role row that doesn't exist yet either.
Ported from IndMatchmaking's own app/db/seed.py (which solves the identical
bootstrap problem there), but takes a real email/password instead of a
hardcoded default (admin@matchmaking.local / Admin@123) - this script is
meant for real deployments (see docs/DEPLOY_EC2.md), not just local dev
convenience, so a well-known default credential isn't appropriate here.

Usage:
    python seed_admin.py --email admin@example.com --first-name Jane --last-name Admin
    (prompts for a password interactively; or pass --password, or set the
    SEED_ADMIN_PASSWORD env var, to run non-interactively)

Idempotent - re-running is safe: existing roles are left untouched, and an
existing user with the given email is reported, not modified/duplicated.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from app.core.database import session_scope
from app.models.rbac import RoleMaster
from app.models.user import UserMaster
from app.services.auth.security import hash_password

CORE_ROLES = ["Super Admin", "Admin", "User"]


def ensure_roles(db) -> dict[str, RoleMaster]:
    roles: dict[str, RoleMaster] = {}
    for name in CORE_ROLES:
        role = db.query(RoleMaster).filter(RoleMaster.role_name == name).first()
        if role is None:
            role = RoleMaster(role_name=name, description=f"{name} role", status="active")
            db.add(role)
            db.flush()
            print(f"Created role: {name}")
        else:
            print(f"Role already exists: {name}")
        roles[name] = role
    return roles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--first-name", default="Super")
    parser.add_argument("--last-name", default="Admin")
    parser.add_argument(
        "--password", default=None, help="If omitted, prompts interactively (or reads SEED_ADMIN_PASSWORD)."
    )
    args = parser.parse_args()

    password = args.password or os.environ.get("SEED_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Super Admin password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords did not match.", file=sys.stderr)
            raise SystemExit(1)
    if len(password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        raise SystemExit(1)

    with session_scope() as db:
        roles = ensure_roles(db)

        email = args.email.lower().strip()
        existing = db.query(UserMaster).filter(UserMaster.email == email).first()
        if existing is not None:
            print(f"User {email} already exists (id={existing.id}) - not modified.")
            db.commit()
            return

        user = UserMaster(
            first_name=args.first_name,
            last_name=args.last_name,
            email=email,
            password_hash=hash_password(password),
            role_id=roles["Super Admin"].id,
            status="active",
        )
        db.add(user)
        db.commit()
        print(f"Created Super Admin: {email}")


if __name__ == "__main__":
    main()
