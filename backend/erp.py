"""ERP adapter layer. Oracle Fusion PPM is implemented; SAP plugs in via the same interface."""
import asyncio
import os
from typing import Protocol

import httpx

API_VERSION = "11.13.18.05"
CLOSED = {"Closed", "Completed", "Rejected", "Cancelled"}


class ErpAdapter(Protocol):
    name: str
    async def test(self) -> dict: ...
    async def pull(self, entity: str) -> list[dict]: ...
    async def push_cost(self, payload: dict) -> dict: ...


class OracleFusionAdapter:
    name = "Oracle Fusion PPM"

    def __init__(self, base: str, user: str, password: str):
        self.base = "".join(base.split()).rstrip("/")
        self.auth = (user.strip(), password)

    def _url(self, service: str, resource: str) -> str:
        return f"{self.base}/{service}/resources/{API_VERSION}/{resource}"

    async def _get_all(self, service: str, resource: str, params: dict | None = None, cap: int = 5000) -> list[dict]:
        out, offset, limit = [], 0, 200
        async with httpx.AsyncClient(auth=self.auth, timeout=60) as c:
            while len(out) < cap:
                r = await c.get(self._url(service, resource), params={**(params or {}), "limit": limit, "offset": offset, "onlyData": "true"},
                                headers={"Accept": "application/json"})
                r.raise_for_status()
                body = r.json()
                rows = body.get("items", [])
                out += rows
                if not body.get("hasMore") or not rows:
                    break
                offset += limit
        return out

    async def test(self) -> dict:
        async with httpx.AsyncClient(auth=self.auth, timeout=30) as c:
            r = await c.get(self._url("fscmRestApi", "projects"), params={"limit": 1, "onlyData": "true", "fields": "ProjectNumber"})
        return {"ok": r.is_success, "status": r.status_code, "message": "" if r.is_success else r.text[:300]}

    async def pull(self, entity: str) -> list[dict]:
        if entity == "projects":
            rows = await self._get_all("fscmRestApi", "projects", {"fields": "ProjectId,ProjectNumber,ProjectName,ProjectStatus,BusinessUnitName"})
            return [{"number": r.get("ProjectNumber"), "name": (r.get("ProjectName") or "").strip(), "erp_id": r.get("ProjectId"),
                     "client": r.get("BusinessUnitName") or "", "status": r.get("ProjectStatus") or ""}
                    for r in rows if r.get("ProjectNumber") and r.get("ProjectStatus") not in CLOSED]
        if entity == "tasks":
            projects = await self.pull("projects")
            sem = asyncio.Semaphore(8)

            async def one(p):
                async with sem:
                    rows = await self._get_all("fscmRestApi", f"projects/{p['erp_id']}/child/Tasks", {"fields": "TaskNumber,TaskName"})
                return [{"project_number": p["number"], "number": r.get("TaskNumber"), "name": r.get("TaskName")} for r in rows if r.get("TaskNumber")]
            return [t for chunk in await asyncio.gather(*(one(p) for p in projects)) for t in chunk]
        if entity == "employees":
            rows = await self._get_all("hcmRestApi", "workers", {"expand": "names", "fields": "PersonNumber;names:DisplayName"}, cap=50000)
            out = []
            for r in rows:
                names = (r.get("names") or [])
                names = names.get("items", []) if isinstance(names, dict) else names
                out.append({"number": r.get("PersonNumber"), "name": (names[0].get("DisplayName") if names else r.get("PersonNumber")),
                            "grade": "Skilled", "trade": ""})
            return [o for o in out if o["number"]]
        if entity == "items":
            rows = await self._get_all("fscmRestApi", "itemCosts", cap=50000)
            latest = {}
            for r in rows:  # one row per item: most recent cost across cost orgs
                n = r.get("ItemNumber")
                if n and (n not in latest or (r.get("CostAsOfDate") or "") > (latest[n].get("CostAsOfDate") or "")):
                    latest[n] = r
            return [{"number": n, "description": r.get("ItemDescription") or n, "uom": r.get("UOMName") or r.get("UOMCode") or "Ea",
                     "unit_cost": float(r.get("TotalUnitCost") or 0), "category": r.get("ItemCategory") or "",
                     "cost_org": r.get("CostOrganizationName") or "", "currency": r.get("CurrencyCode") or "USD"} for n, r in latest.items()]
        if entity == "budgets":
            rows = await self._get_all("fscmRestApi", "projectBudgets", {"q": "PlanVersionStatus='Current Baseline'"})
            seen = {}
            for r in rows:
                seen[(r.get("ProjectNumber"), r.get("PlanVersionId"))] = {
                    "project_number": r.get("ProjectNumber"), "erp_id": r.get("PlanVersionId"),
                    "total_cost": float(r.get("TotalPlannedRawCostInProjectCurrency") or r.get("PCRawCostAmounts") or 0)}
            return list(seen.values())
        raise ValueError(f"Unsupported entity {entity}")

    async def push_cost(self, payload: dict) -> dict:
        async with httpx.AsyncClient(auth=self.auth, timeout=60) as c:
            r = await c.post(self._url("fscmRestApi", "unprocessedProjectCosts"), json=payload, headers={"Content-Type": "application/json"})
        body = None
        try:
            body = r.json() if r.content else None
        except ValueError:
            body = r.text[:500]
        return {"ok": r.is_success, "status": r.status_code, "body": body}


def get_adapter() -> ErpAdapter | None:
    base, user, pw = os.environ.get("ORACLE_FUSION_BASE"), os.environ.get("ORACLE_USER"), os.environ.get("ORACLE_PASSWORD")
    if base and user and pw:
        return OracleFusionAdapter(base, user, pw)
    return None
