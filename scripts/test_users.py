"""Creates Clerk dev test users for each CostBridge role and prints fresh session tokens (preview only)."""
import asyncio
import json
import os
import sys
from pathlib import Path
import urllib.error
import urllib.request

from sqlalchemy.dialects.postgresql import insert

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core import db, tables
SK = os.environ["CLERK_SECRET_KEY"]
USERS = {"admin": "cb.admin+clerk_test@example.com", "project_manager": "cb.pm+clerk_test@example.com",
         "cost_controller": "cb.cc+clerk_test@example.com", "foreman": "cb.foreman+clerk_test@example.com",
         "store_manager": "cb.store+clerk_test@example.com", "pending": "cb.pending+clerk_test@example.com"}
PW = "CostBridge-Test-2026!"


def bapi(path, body=None, method="POST"):
    req = urllib.request.Request("https://api.clerk.com/v1" + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": "Bearer " + SK, "Content-Type": "application/json", "User-Agent": "emergent-test"})
    return json.load(urllib.request.urlopen(req))


async def main():
    out = {}
    for role, email in USERS.items():
        found = bapi(f"/users?email_address={urllib.parse.quote(email)}", method="GET")
        user = found[0] if found else bapi("/users", {"email_address": [email], "password": PW, "skip_password_checks": True,
                                                      "first_name": "Test", "last_name": role.replace("_", " ").title()})
        values = {"user_id": user["id"], "role": role, "env": "preview", "email": email,
                  "name": f"Test {role.replace('_', ' ').title()}"}
        await db.execute(insert(tables.users).values(values).on_conflict_do_update(
                         index_elements=["user_id"], set_={k: v for k, v in values.items() if k != "user_id"}))
        out[role] = {"user_id": user["id"], "email": email}
        if "--tokens" in sys.argv:
            s = bapi("/sessions", {"user_id": user["id"]})
            out[role]["token"] = bapi(f"/sessions/{s['id']}/tokens", {"expires_in_seconds": 3600})["jwt"]
        if "--tickets" in sys.argv:
            out[role]["ticket"] = bapi("/sign_in_tokens", {"user_id": user["id"], "expires_in_seconds": 3600})["token"]
    print(json.dumps(out, indent=1))
    await db.close()

import urllib.parse  # noqa: E402
asyncio.run(main())
