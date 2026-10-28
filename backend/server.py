import logging
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

try:
    from backend.clerk_auth import clerk_router
    from backend.core import ACTIVE, ENV, IN_ENV, RANK, ROLES, audit, client, current_member, db, effective_role, new_id, now_iso, require_role
    from backend.engine import PENDING, build_cost_transactions, get_settings, next_status, plan_rows, route_on_submit, step_roles, validate
    from backend.erp import get_adapter
    from backend.seed import next_ref, seed
except ModuleNotFoundError:
    from clerk_auth import clerk_router
    from core import ACTIVE, ENV, IN_ENV, RANK, ROLES, audit, client, current_member, db, effective_role, new_id, now_iso, require_role
    from engine import PENDING, build_cost_transactions, get_settings, next_status, plan_rows, route_on_submit, step_roles, validate
    from erp import get_adapter
    from seed import next_ref, seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="CostBridge")
api = APIRouter(prefix="/api")

PLANNERS = ["admin", "project_manager", "foreman"]
CAPTURE = {"labor": PLANNERS, "equipment": PLANNERS, "material": ["admin", "store_manager", "foreman"]}
APPROVERS = ["admin", "project_manager", "cost_controller"]
ERP_ROLES = ["admin", "cost_controller"]
P = {"_id": 0}


def all_active():
    return require_role(*ACTIVE)


@app.on_event("startup")
async def startup():
    await seed()
    await db.transactions.create_index("id", unique=True)
    await db.users.create_index("user_id", unique=True)


@app.on_event("shutdown")
async def shutdown():
    client.close()


# ---------- Users ----------
@api.get("/me")
async def me(member: dict = Depends(current_member)):
    return member


@api.get("/users")
async def list_users(admin: dict = Depends(require_role("admin"))):
    people = await db.users.find(IN_ENV, P).to_list(1000)
    return {"roles": [r for r in ROLES if RANK[r] <= RANK[admin["role"]]],
            "users": [{**p, "role": effective_role(p.get("role"))} for p in people]}


class RoleIn(BaseModel):
    role: str


@api.patch("/users/{user_id}/role")
async def set_role(user_id: str, body: RoleIn, admin: dict = Depends(require_role("admin"))):
    if body.role not in ROLES or RANK[body.role] > RANK[admin["role"]]:
        raise HTTPException(403, "Not allowed")
    target = await db.users.find_one({"user_id": user_id, **IN_ENV}, P)
    if target is None:
        raise HTTPException(404, "Not found")
    if (effective_role(target.get("role")) == "admin" and body.role != "admin"
            and await db.users.count_documents({"role": "admin", **IN_ENV}) <= 1):
        raise HTTPException(409, "Keep at least one admin")
    await db.users.update_one({"user_id": user_id}, {"$set": {"role": body.role}})
    await audit("user", user_id, f"role set to {body.role}", admin)
    return {"user_id": user_id, "role": body.role}


# ---------- Master data ----------
@api.get("/master")
async def master(member: dict = Depends(all_active())):
    out = {}
    for name in ["projects", "tasks", "employees", "equipment", "items", "crews", "reason_codes", "budgets"]:
        out[name] = await db[name].find({}, P).to_list(10000)
    out["hour_types"] = await db.hour_types.find({}, P).sort("order", 1).to_list(100)
    out["settings"] = await get_settings()
    return out


class CrewIn(BaseModel):
    name: str = Field(min_length=1)
    project_number: str
    foreman: str = ""


@api.post("/crews")
async def create_crew(body: CrewIn, member: dict = Depends(require_role(*PLANNERS))):
    doc = {"id": new_id(), **body.model_dump()}
    await db.crews.insert_one(doc)
    await audit("crew", doc["id"], "created", member)
    doc.pop("_id", None)
    return doc


# ---------- Planning ----------
class PlanLine(BaseModel):
    resource_type: Optional[Literal["labor", "equipment"]] = None
    resource_number: Optional[str] = None
    hours: dict[str, float] = {}
    item_number: Optional[str] = None
    planned_qty: Optional[float] = None


class PlanIn(BaseModel):
    kind: Literal["crew", "material"]
    project_number: str
    task_number: str
    crew_id: Optional[str] = None
    shift: Optional[str] = None
    period_type: Optional[Literal["weekly", "monthly"]] = None
    start_date: str
    end_date: str
    lines: list[PlanLine] = []


async def _plan_roles_check(kind: str, member: dict):
    allowed = PLANNERS + (["store_manager"] if kind == "material" else [])
    if member["role"] not in allowed:
        raise HTTPException(403, "Not allowed")


async def _plan_doc(body: PlanIn) -> dict:
    if body.end_date < body.start_date:
        raise HTTPException(400, "End date is before start date")
    if body.kind == "crew":
        if not body.crew_id or not await db.crews.find_one({"id": body.crew_id}):
            raise HTTPException(400, "Valid crew is required")
        for ln in body.lines:
            coll = db.employees if ln.resource_type == "labor" else db.equipment
            if not ln.resource_type or not ln.resource_number or not await coll.find_one({"number": ln.resource_number}):
                raise HTTPException(400, "Every plan line needs a valid employee or equipment")
            if any(v < 0 or v > 24 for v in ln.hours.values()):
                raise HTTPException(400, "Planned hours must be between 0 and 24")
    else:
        for ln in body.lines:
            if not ln.item_number or not await db.items.find_one({"number": ln.item_number}):
                raise HTTPException(400, "Every material plan line needs a valid item")
            if not ln.planned_qty or ln.planned_qty <= 0:
                raise HTTPException(400, f"{ln.item_number}: planned quantity must be greater than 0")
    if not await db.tasks.find_one({"project_number": body.project_number, "number": body.task_number}):
        raise HTTPException(400, "Unknown Project# / Task#")
    lines = [ln.model_dump(exclude_none=True) for ln in body.lines]
    return {**body.model_dump(exclude={"lines"}), "lines": lines}


@api.get("/plans")
async def list_plans(kind: Optional[str] = None, member: dict = Depends(all_active())):
    q = {"kind": kind} if kind else {}
    return await db.plans.find(q, P).sort("created_at", -1).to_list(1000)


@api.post("/plans")
async def create_plan(body: PlanIn, member: dict = Depends(all_active())):
    await _plan_roles_check(body.kind, member)
    doc = {"id": new_id(), **(await _plan_doc(body)), "status": "draft", "created_by": member.get("name"), "created_by_id": member["user_id"], "created_at": now_iso()}
    await db.plans.insert_one(doc)
    await audit("plan", doc["id"], "created (draft)", member)
    doc.pop("_id", None)
    return doc


@api.put("/plans/{plan_id}")
async def update_plan(plan_id: str, body: PlanIn, member: dict = Depends(all_active())):
    await _plan_roles_check(body.kind, member)
    if not await db.plans.find_one({"id": plan_id}):
        raise HTTPException(404, "Not found")
    if await db.transactions.find_one({"plan_id": plan_id, "status": {"$ne": "draft"}}):
        raise HTTPException(409, "Entries were already captured against this plan - create a new plan instead")
    upd = {**(await _plan_doc(body)), "status": "draft", "updated_at": now_iso()}
    await db.plans.update_one({"id": plan_id}, {"$set": upd})
    await audit("plan", plan_id, "updated (back to draft)", member)
    return await db.plans.find_one({"id": plan_id}, P)


@api.post("/plans/{plan_id}/publish")
async def publish_plan(plan_id: str, member: dict = Depends(all_active())):
    plan = await db.plans.find_one({"id": plan_id}, P)
    if not plan:
        raise HTTPException(404, "Not found")
    await _plan_roles_check(plan["kind"], member)
    if not plan["lines"]:
        raise HTTPException(400, "Add at least one line before publishing")
    if plan["kind"] == "crew":
        others = await db.plans.find({"kind": "crew", "status": "published", "id": {"$ne": plan_id}, "shift": plan.get("shift"),
                                      "start_date": {"$lte": plan["end_date"]}, "end_date": {"$gte": plan["start_date"]}}, P).to_list(1000)
        mine = {ln.get("resource_number") for ln in plan["lines"]}
        for o in others:
            clash = mine & {ln.get("resource_number") for ln in o["lines"]}
            if clash:
                raise HTTPException(409, f"Conflict: {', '.join(sorted(clash))} already planned on {o['project_number']}/{o['task_number']} "
                                         f"({o['start_date']} to {o['end_date']}, {o.get('shift')})")
    await db.plans.update_one({"id": plan_id}, {"$set": {"status": "published", "published_at": now_iso()}})
    await audit("plan", plan_id, "published", member)
    return await db.plans.find_one({"id": plan_id}, P)


@api.delete("/plans/{plan_id}")
async def delete_plan(plan_id: str, member: dict = Depends(require_role(*PLANNERS, "store_manager"))):
    res = await db.plans.delete_one({"id": plan_id, "status": "draft"})
    if not res.deleted_count:
        raise HTTPException(404, "Draft plan not found")
    await audit("plan", plan_id, "deleted", member)
    return {"ok": True}


@api.get("/plans/autofill")
async def autofill(type: Literal["labor", "equipment"], project_number: str, task_number: str, crew_id: str, date: str,
                   member: dict = Depends(all_active())):
    plan = await db.plans.find_one({"kind": "crew", "status": "published", "project_number": project_number, "task_number": task_number,
                                    "crew_id": crew_id, "start_date": {"$lte": date}, "end_date": {"$gte": date}}, P)
    if not plan:
        return {"plan": None, "lines": []}
    return {"plan": plan, "lines": await plan_rows(plan, type)}


# ---------- Capture ----------
class TxLine(BaseModel):
    resource_number: Optional[str] = None
    hour_type: Optional[str] = None
    hours: Optional[float] = Field(default=None, ge=0, le=24)
    planned_hours: Optional[float] = None
    present: bool = True
    plan_line: bool = False
    reason_code: Optional[str] = None
    item_number: Optional[str] = None
    qty_issued: Optional[float] = Field(default=None, ge=0)
    qty_wasted: Optional[float] = Field(default=None, ge=0)
    qty_returned: Optional[float] = Field(default=None, ge=0)
    warehouse: Optional[str] = None


class TxIn(BaseModel):
    type: Literal["labor", "equipment", "material"]
    project_number: str
    task_number: str
    date: str
    crew_id: Optional[str] = None
    plan_id: Optional[str] = None
    mode: Literal["plan", "manual"] = "manual"
    source: Literal["manual", "plan", "swipe", "iot"] = "manual"
    notes: str = ""
    lines: list[TxLine]
    action: Literal["draft", "submit"] = "draft"


def _check_capture(t: str, member: dict):
    if member["role"] not in CAPTURE[t]:
        raise HTTPException(403, "Not allowed")


async def _check_master(body: TxIn):
    if not await db.tasks.find_one({"project_number": body.project_number, "number": body.task_number}):
        raise HTTPException(400, "Unknown Project# / Task#")
    for ln in body.lines:
        if body.type == "material" and not ln.item_number:
            raise HTTPException(400, "Item is required on every line")
        if body.type != "material" and (not ln.resource_number or not ln.hour_type):
            raise HTTPException(400, "Resource and Hour Type are required on every line")
    coll, key = {"labor": (db.employees, "resource_number"), "equipment": (db.equipment, "resource_number"), "material": (db.items, "item_number")}[body.type]
    nums = {getattr(ln, key) for ln in body.lines}
    known = {d["number"] for d in await coll.find({"number": {"$in": list(nums)}}, {"_id": 0, "number": 1}).to_list(10000)}
    if nums - known:
        raise HTTPException(400, f"Unknown: {', '.join(sorted(nums - known))}")
    if body.type != "material":
        codes = {h["code"] for h in await db.hour_types.find({"resource_type": body.type}, P).to_list(50)}
        bad = {ln.hour_type for ln in body.lines} - codes
        if bad:
            raise HTTPException(400, f"Unknown hour type: {', '.join(sorted(bad))}")


def _tx_from(body: TxIn) -> dict:
    lines = [ln.model_dump(exclude_none=True) for ln in body.lines]
    return {**body.model_dump(exclude={"lines", "action"}), "lines": lines}


async def _finalize(tx: dict, action: str, member: dict) -> dict:
    v = await validate(tx)
    if action == "submit":
        if v["blocked"]:
            msgs = v["errors"] + (["Budget exceeded (Stopper)"] if v["budget"]["blocked"] else []) + \
                   (["Plan tolerance breached (Stopper)"] if v["tolerance"]["blocked"] else [])
            raise HTTPException(422, "; ".join(msgs))
        s = await get_settings()
        status, note = route_on_submit(tx, s)
        tx.update(status=status, submitted_at=now_iso(), submitted_by=member.get("name"), submitted_by_id=member["user_id"])
        tx.setdefault("approvals", []).append({"step": "submit", "decision": "submitted", "by": member.get("name"), "role": member["role"],
                                               "at": now_iso(), "comment": note})
        if status in ("pending_step2", "approved"):
            tx["approvals"].append({"step": "pending_step1", "decision": "auto-approved", "by": "System", "role": "system", "at": now_iso(),
                                    "comment": note})
        if status == "approved":
            await _create_costs(tx, s)
    else:
        tx["status"] = "draft"
    return tx


async def _create_costs(tx: dict, s: dict):
    for c in await build_cost_transactions(tx, s):
        await db.cost_transactions.insert_one({
            "id": new_id(), **c, "transaction_id": tx["id"], "transaction_ref": tx["ref"], "type": tx["type"],
            "status": "sample" if tx.get("sample") else ("recorded" if c["kind"] == "return_to_store" else "queued"),
            "created_at": now_iso(), "attempts": 0, "response": None})


@api.post("/transactions/preview")
async def preview(body: TxIn, member: dict = Depends(all_active())):
    _check_capture(body.type, member)
    await _check_master(body)
    tx = _tx_from(body)
    await validate(tx)
    return tx


@api.post("/transactions")
async def create_tx(body: TxIn, member: dict = Depends(all_active())):
    _check_capture(body.type, member)
    await _check_master(body)
    tx = {"id": new_id(), "ref": await next_ref({"labor": "LAB", "equipment": "EQP", "material": "MAT"}[body.type]), **_tx_from(body),
          "created_by": member.get("name"), "created_by_id": member["user_id"], "submitted_by": member.get("name"),
          "submitted_by_id": member["user_id"], "created_at": now_iso(), "approvals": []}
    await _finalize(tx, body.action, member)
    await db.transactions.insert_one(tx)
    await audit("transaction", tx["id"], f"created ({tx['status']})", member, {"ref": tx["ref"], "cost": tx["totals"]["cost"]})
    tx.pop("_id", None)
    return tx


@api.put("/transactions/{tx_id}")
async def update_tx(tx_id: str, body: TxIn, member: dict = Depends(all_active())):
    _check_capture(body.type, member)
    old = await db.transactions.find_one({"id": tx_id, "created_by_id": member["user_id"]}, P)
    if not old:
        raise HTTPException(404, "Not found")
    if old["status"] not in ("draft", "rejected"):
        raise HTTPException(409, "Only drafts or rejected entries can be edited")
    await _check_master(body)
    tx = {**old, **_tx_from(body)}
    if old["status"] == "rejected":
        tx["approvals"] = old.get("approvals", []) + [{"step": "resubmit", "decision": "restarted", "by": member.get("name"),
                                                       "role": member["role"], "at": now_iso(), "comment": "Approval chain restarted"}]
    await _finalize(tx, body.action, member)
    tx.pop("rejection_reason", None) if tx["status"] != "rejected" else None
    await db.transactions.replace_one({"id": tx_id}, tx)
    await audit("transaction", tx_id, f"updated ({tx['status']})", member, {"cost": tx["totals"]["cost"]})
    return tx


@api.get("/transactions")
async def list_tx(type: Optional[str] = None, status: Optional[str] = None, project_number: Optional[str] = None,
                  mine: bool = False, member: dict = Depends(all_active())):
    q = {}
    if type:
        q["type"] = type
    if status:
        q["status"] = status
    if project_number:
        q["project_number"] = project_number
    if mine or member["role"] in ("foreman", "store_manager"):
        q["created_by_id"] = member["user_id"]
    return await db.transactions.find(q, P).sort("created_at", -1).to_list(2000)


@api.get("/transactions/{tx_id}")
async def get_tx(tx_id: str, member: dict = Depends(all_active())):
    q = {"id": tx_id}
    if member["role"] in ("foreman", "store_manager"):
        q["created_by_id"] = member["user_id"]
    tx = await db.transactions.find_one(q, P)
    if not tx:
        raise HTTPException(404, "Not found")
    tx["audit"] = await db.audit.find({"entity_id": tx_id}, P).sort("at", 1).to_list(500)
    tx["cost_transactions"] = await db.cost_transactions.find({"transaction_id": tx_id}, P).to_list(500)
    return tx


# ---------- Approvals ----------
@api.get("/approvals")
async def approvals(member: dict = Depends(require_role(*APPROVERS))):
    s = await get_settings()
    statuses = [st for st in PENDING if member["role"] in step_roles(st, s)]
    q = {"status": {"$in": statuses}}
    if member["role"] != "admin":
        q["submitted_by_id"] = {"$ne": member["user_id"]}
    return await db.transactions.find(q, P).sort("submitted_at", 1).to_list(2000)


class DecisionIn(BaseModel):
    comment: str = ""


@api.post("/transactions/{tx_id}/approve")
async def approve(tx_id: str, body: DecisionIn, member: dict = Depends(require_role(*APPROVERS))):
    s = await get_settings()
    tx = await db.transactions.find_one({"id": tx_id}, P)
    if not tx or tx["status"] not in PENDING:
        raise HTTPException(404, "Not pending")
    if member["role"] not in step_roles(tx["status"], s):
        raise HTTPException(403, "Not your approval step")
    if tx.get("submitted_by_id") == member["user_id"] and member["role"] != "admin":
        raise HTTPException(403, "You cannot approve your own entry")
    step = tx["status"]
    new_status = next_status(tx)
    entry = {"step": step, "decision": "approved", "by": member.get("name"), "role": member["role"], "at": now_iso(), "comment": body.comment}
    upd = {"status": new_status, **({"approved_at": now_iso()} if new_status == "approved" else {})}
    res = await db.transactions.update_one({"id": tx_id, "status": step}, {"$set": upd, "$push": {"approvals": entry}})
    if not res.modified_count:
        raise HTTPException(409, "Entry was already actioned by someone else")
    tx = await db.transactions.find_one({"id": tx_id}, P)
    if new_status == "approved":
        await _create_costs(tx, s)
    await audit("transaction", tx_id, f"approved {step} -> {new_status}", member, {"comment": body.comment})
    return tx


class RejectIn(BaseModel):
    reason: str = Field(min_length=3)


@api.post("/transactions/{tx_id}/reject")
async def reject(tx_id: str, body: RejectIn, member: dict = Depends(require_role(*APPROVERS))):
    s = await get_settings()
    tx = await db.transactions.find_one({"id": tx_id}, P)
    if not tx or tx["status"] not in PENDING:
        raise HTTPException(404, "Not pending")
    if member["role"] not in step_roles(tx["status"], s):
        raise HTTPException(403, "Not your approval step")
    step = tx["status"]
    entry = {"step": step, "decision": "rejected", "by": member.get("name"), "role": member["role"], "at": now_iso(), "comment": body.reason}
    res = await db.transactions.update_one({"id": tx_id, "status": step},
                                           {"$set": {"status": "rejected", "rejection_reason": body.reason}, "$push": {"approvals": entry}})
    if not res.modified_count:
        raise HTTPException(409, "Entry was already actioned by someone else")
    await audit("transaction", tx_id, f"rejected at {step}", member, {"reason": body.reason})
    return await db.transactions.find_one({"id": tx_id}, P)


# ---------- Dashboard / reports ----------
@api.get("/dashboard")
async def dashboard(project_number: Optional[str] = None, member: dict = Depends(all_active())):
    s = await get_settings()
    warn = s.get("budget_warning_pct", 90)
    pq = {"project_number": project_number} if project_number else {}
    txs = await db.transactions.find({**pq, "status": {"$nin": ["draft", "rejected"]}}, P).to_list(20000)
    budgets = await db.budgets.find(pq, P).to_list(5000)
    rows = []
    for b in budgets:
        rel = [t for t in txs if t["type"] == b["resource_type"] and t["project_number"] == b["project_number"] and t["task_number"] == b["task_number"]]
        if b["resource_type"] == "material":
            actual = sum(ln.get("qty_consumed", 0) for t in rel for ln in t["lines"] if ln["item_number"] == b["item_number"])
            cost = sum(ln.get("cost", 0) for t in rel for ln in t["lines"] if ln["item_number"] == b["item_number"])
        else:
            actual = sum(t["totals"]["qty"] for t in rel)
            cost = sum(t["totals"]["cost"] for t in rel)
        pct = actual / b["qty"] * 100 if b["qty"] else 0
        rows.append({**b, "actual": round(actual, 2), "actual_cost": round(cost, 2), "pct": round(pct, 1),
                     "status": "stopped" if pct > 100 else "warning" if pct >= warn else "ok"})
    by_type = {t: round(sum(x["totals"]["cost"] for x in txs if x["type"] == t), 2) for t in ("labor", "equipment", "material")}
    pending = [t for t in txs if t["status"] in PENDING]
    queued = await db.cost_transactions.count_documents({"status": {"$in": ["queued", "error"]}})
    return {"rows": rows, "cost_by_type": by_type,
            "kpis": {"actual_cost": round(sum(by_type.values()), 2),
                     "approved_cost": round(sum(t["totals"]["cost"] for t in txs if t["status"] in ("approved", "posted")), 2),
                     "pending_cost": round(sum(t["totals"]["cost"] for t in pending), 2), "pending_count": len(pending),
                     "flagged_count": sum(1 for t in pending if t["validation"]["special"]["required"]),
                     "erp_queue": queued, "over_budget": sum(1 for r in rows if r["status"] == "stopped")}}


@api.get("/audit")
async def audit_log(member: dict = Depends(require_role("admin", "cost_controller"))):
    return await db.audit.find({}, P).sort("at", -1).to_list(500)


# ---------- Setup ----------
class SettingsIn(BaseModel):
    rate_source: dict[str, Literal["app", "erp"]]
    budget_behavior: Literal["warning", "stop"]
    budget_warning_pct: float = Field(ge=1, le=100)
    tolerance_pct: dict[str, float]
    tolerance_behavior: Literal["warning", "stop"]
    auto_approval: Literal["off", "step1", "full"]
    special_hour_types: list[str]
    special_on_wastage: bool
    special_approver_role: Literal["cost_controller", "project_manager", "admin"]
    oracle: dict


@api.get("/settings")
async def get_settings_route(member: dict = Depends(all_active())):
    return await get_settings()


@api.put("/settings")
async def put_settings(body: SettingsIn, member: dict = Depends(require_role("admin"))):
    await db.settings.update_one({"id": "global"}, {"$set": body.model_dump()}, upsert=True)
    await audit("settings", "global", "updated", member, body.model_dump())
    return await get_settings()


@api.get("/rate-cards")
async def rate_cards(member: dict = Depends(all_active())):
    return await db.rate_cards.find({}, P).to_list(5000)


class RateIn(BaseModel):
    resource_type: Literal["labor", "equipment"]
    key: str = Field(min_length=1)
    hour_type: str
    base_rate: float = Field(ge=0)
    multiplier: float = Field(default=1.0, ge=0)
    premium: float = Field(default=0, ge=0)
    effective_from: str = "2026-01-01"


@api.post("/rate-cards")
async def add_rate(body: RateIn, member: dict = Depends(require_role("admin"))):
    if await db.rate_cards.find_one({"resource_type": body.resource_type, "key": body.key, "hour_type": body.hour_type}):
        raise HTTPException(409, "Rate already exists for this key and hour type")
    doc = {"id": new_id(), **body.model_dump()}
    await db.rate_cards.insert_one(doc)
    await audit("rate_card", doc["id"], "created", member, body.model_dump())
    doc.pop("_id", None)
    return doc


@api.put("/rate-cards/{rid}")
async def update_rate(rid: str, body: RateIn, member: dict = Depends(require_role("admin"))):
    res = await db.rate_cards.update_one({"id": rid}, {"$set": body.model_dump()})
    if not res.matched_count:
        raise HTTPException(404, "Not found")
    await audit("rate_card", rid, "updated", member, body.model_dump())
    return await db.rate_cards.find_one({"id": rid}, P)


class HourTypeIn(BaseModel):
    name: str
    expenditure_type: str
    requires_reason: bool


@api.put("/hour-types/{hid}")
async def update_hour_type(hid: str, body: HourTypeIn, member: dict = Depends(require_role("admin"))):
    res = await db.hour_types.update_one({"id": hid}, {"$set": body.model_dump()})
    if not res.matched_count:
        raise HTTPException(404, "Not found")
    await audit("hour_type", hid, "updated", member, body.model_dump())
    return await db.hour_types.find_one({"id": hid}, P)


class ReasonIn(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    resource_type: Literal["equipment", "material"]


@api.post("/reason-codes")
async def add_reason(body: ReasonIn, member: dict = Depends(require_role("admin"))):
    if await db.reason_codes.find_one({"code": body.code}):
        raise HTTPException(409, "Code already exists")
    doc = {"id": new_id(), **body.model_dump()}
    await db.reason_codes.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.delete("/reason-codes/{rid}")
async def del_reason(rid: str, member: dict = Depends(require_role("admin"))):
    await db.reason_codes.delete_one({"id": rid})
    return {"ok": True}


# ---------- ERP integration ----------
@api.get("/erp/status")
async def erp_status(member: dict = Depends(all_active())):
    a = get_adapter()
    counts = {s: await db.cost_transactions.count_documents({"status": s}) for s in ["queued", "sent", "error", "recorded", "sample"]}
    last = await db.erp_batches.find_one({}, P, sort=[("started_at", -1)])
    return {"connected": a is not None, "system": a.name if a else "Oracle Fusion PPM",
            "base_url": os.environ.get("ORACLE_FUSION_BASE", "") if member["role"] in ERP_ROLES else "",
            "counts": counts, "last_batch": last, "env": ENV}


@api.post("/erp/test")
async def erp_test(member: dict = Depends(require_role(*ERP_ROLES))):
    a = get_adapter()
    if not a:
        raise HTTPException(400, "Oracle connection is not configured")
    try:
        return await a.test()
    except Exception as e:
        return {"ok": False, "status": 0, "message": str(e)[:300]}


class SyncIn(BaseModel):
    entities: list[Literal["projects", "tasks", "employees", "items", "budgets"]]


KEYS = {"projects": ("projects", ["number"]), "tasks": ("tasks", ["project_number", "number"]), "employees": ("employees", ["number"]),
        "items": ("items", ["number"]), "budgets": ("erp_budget_versions", ["project_number", "erp_id"])}


@api.post("/erp/sync")
async def erp_sync(body: SyncIn, member: dict = Depends(require_role("admin"))):
    a = get_adapter()
    if not a:
        raise HTTPException(400, "Oracle connection is not configured")
    results = []
    for ent in body.entities:
        batch = {"id": new_id(), "direction": "pull", "entity": ent, "started_at": now_iso(), "by": member.get("name")}
        try:
            rows = await a.pull(ent)
            coll, keys = KEYS[ent]
            for r in rows:
                await db[coll].update_one({k: r[k] for k in keys}, {"$set": {**r, "source": "oracle", "synced_at": now_iso()},
                                                                   "$setOnInsert": {"id": new_id()}}, upsert=True)
            batch.update(status="success", count=len(rows))
        except Exception as e:
            batch.update(status="error", count=0, error=str(e)[:500])
        batch["finished_at"] = now_iso()
        await db.erp_batches.insert_one(batch)
        batch.pop("_id", None)
        results.append(batch)
    await audit("erp", "sync", "master data pull", member, {"entities": body.entities})
    return results


@api.post("/erp/push")
async def erp_push(member: dict = Depends(require_role(*ERP_ROLES))):
    a = get_adapter()
    if not a:
        raise HTTPException(400, "Oracle connection is not configured")
    pend = await db.cost_transactions.find({"status": {"$in": ["queued", "error"]}, "kind": "project_cost"}, P).to_list(2000)
    batch = {"id": new_id(), "direction": "push", "entity": "unprocessedProjectCosts", "started_at": now_iso(), "by": member.get("name")}
    ok = err = 0
    for c in pend:
        try:
            r = await a.push_cost(c["payload"])
        except Exception as e:
            r = {"ok": False, "status": 0, "body": str(e)[:300]}
        ok, err = ok + r["ok"], err + (not r["ok"])
        await db.cost_transactions.update_one({"id": c["id"]}, {"$set": {"status": "sent" if r["ok"] else "error", "response": r,
                                                                      "batch_id": batch["id"], "sent_at": now_iso()}, "$inc": {"attempts": 1}})
    for tid in {c["transaction_id"] for c in pend}:
        if not await db.cost_transactions.count_documents({"transaction_id": tid, "kind": "project_cost", "status": {"$ne": "sent"}}):
            await db.transactions.update_one({"id": tid}, {"$set": {"status": "posted", "posted_at": now_iso()}})
    batch.update(status="success" if not err else "partial" if ok else "error", count=len(pend), ok=ok, failed=err, finished_at=now_iso())
    await db.erp_batches.insert_one(batch)
    batch.pop("_id", None)
    await audit("erp", batch["id"], "cost push", member, {"ok": ok, "failed": err})
    return batch


@api.get("/erp/batches")
async def erp_batches(member: dict = Depends(require_role(*ERP_ROLES))):
    return await db.erp_batches.find({}, P).sort("started_at", -1).to_list(200)


@api.get("/erp/cost-transactions")
async def erp_costs(status: Optional[str] = None, member: dict = Depends(require_role(*ERP_ROLES))):
    q = {"status": status} if status else {}
    return await db.cost_transactions.find(q, P).sort("created_at", -1).to_list(2000)


app.include_router(api)
app.include_router(clerk_router)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])
