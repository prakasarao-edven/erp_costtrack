"""Read-only lookup of an Oracle project's BU, org, tasks and team for building a cost payload."""
import asyncio
import sys

import httpx
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from erp import get_adapter  # noqa: E402

PN = sys.argv[1] if len(sys.argv) > 1 else "PCS10020"


async def main():
    a = get_adapter()
    async with httpx.AsyncClient(auth=a.auth, timeout=100) as c:
        async def get(res, params):
            r = await c.get(a._url("fscmRestApi", res), params={"onlyData": "true", **params})
            if not r.is_success:
                print(res, r.status_code, r.text[:300])
                return []
            return r.json().get("items", [])
        p = (await get("projects", {"limit": 1, "q": f"ProjectNumber='{PN}'"}))
        if not p:
            return
        p = p[0]
        print({k: p.get(k) for k in p if any(s in k for s in ["Project", "BusinessUnit", "Organization", "Date", "Status", "Currency"]) and p.get(k) is not None})
        tasks = await get(f"projects/{p['ProjectId']}/child/Tasks", {"limit": 8})
        print([{k: t.get(k) for k in ["TaskNumber", "TaskName", "ChargeableFlag", "TaskStartDate", "TaskFinishDate"]} for t in tasks])
        team = await get(f"projects/{p['ProjectId']}/child/ProjectTeamMembers", {"limit": 5})
        print([{k: t.get(k) for k in t if any(s in k for s in ["Person", "Email", "Role", "Date"])} for t in team])

asyncio.run(main())
