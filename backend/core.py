from sqlalchemy import select, insert, update, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from starlette.concurrency import run_in_threadpool

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent / ".env.local", override=False)

try:
    from backend.clerk_auth import require_user
    from backend.database import Database, t as tables
except ModuleNotFoundError:
    from clerk_auth import require_user
    from database import Database, t as tables

db = Database(os.environ["DATABASE_URL"])

# Highest first; "pending" has no access until an admin assigns a role.
ROLES = ["admin", "master_data_admin", "cost_controller", "project_manager", "store_manager", "foreman", "pending"]
DEFAULT_ROLE = "pending"
RETIRED_ROLES = {}
RANK = {r: len(ROLES) - i for i, r in enumerate(ROLES)}
ACTIVE = [r for r in ROLES if r != "pending"]

ENV = "live" if os.environ.get("CLERK_PUBLISHABLE_KEY", "").startswith("pk_live_") else "preview"
IN_ENV = [or_(tables.users.c.env == ENV, tables.users.c.env.is_(None))]


async def database_transaction():
    async with db.transaction():
        yield


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def effective_role(role) -> str:
    role = RETIRED_ROLES.get(role, role)
    return role if role in ROLES else DEFAULT_ROLE


def _clerk_profile(user_id: str) -> dict:
    """One Clerk lookup on first sign-in: name, email and whether it's a verified admin email."""
    admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAIL", "").split(",") if e.strip()}
    r = requests.get(f"https://api.clerk.com/v1/users/{user_id}", timeout=10,
                     headers={"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY']}", "User-Agent": "emergent-app"})
    r.raise_for_status()
    data = r.json()
    emails = data.get("email_addresses", [])
    is_admin = any(e["email_address"].lower() in admins and (e.get("verification") or {}).get("status") == "verified" for e in emails)
    email = emails[0]["email_address"] if emails else ""
    name = " ".join(x for x in [data.get("first_name"), data.get("last_name")] if x) or email.split("@")[0]
    return {"is_admin": is_admin, "email": email, "name": name}


async def current_member(user: dict = Depends(require_user)) -> dict:
    uid = user["user_id"]
    member = await db.one(select(tables.users).where(tables.users.c['user_id'] == uid))
    if member is None or not member.get("role"):
        prof = await run_in_threadpool(_clerk_profile, uid)
        role = "admin" if prof["is_admin"] else DEFAULT_ROLE
        await db.execute(update(tables.users).where(tables.users.c.user_id == uid,
                         or_(tables.users.c.role.is_(None), tables.users.c.role == "")).values(role=role))
        await db.execute(pg_insert(tables.users).values(user_id=uid, role=role, email=prof["email"],
                         name=prof["name"], created_at=now_iso()).on_conflict_do_nothing(index_elements=["user_id"]))
        member = await db.one(select(tables.users).where(tables.users.c.user_id == uid))
    if member.get("env") != ENV:
        await db.execute(update(tables.users).where(tables.users.c['user_id'] == uid).values({'env': ENV}))
    return {**member, "env": ENV, "role": effective_role(member["role"])}


def require_role(*roles: str):
    async def check(member: dict = Depends(current_member)) -> dict:
        if member["role"] not in roles:
            raise HTTPException(status_code=403, detail="Not allowed")
        return member
    return check


async def audit(entity: str, entity_id: str, action: str, member: dict, detail: dict | None = None):
    await db.execute(insert(tables.audit).values({'id': new_id(), 'entity': entity, 'entity_id': entity_id, 'action': action, 'by': member.get('name') or member.get('email'), 'by_id': member.get('user_id'), 'role': member.get('role'), 'at': now_iso(), 'detail': detail or {}}))
