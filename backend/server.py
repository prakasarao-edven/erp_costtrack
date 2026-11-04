from sqlalchemy import select, insert, update, delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
import logging
import os

from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

try:
    from backend.clerk_auth import clerk_router
    from backend.core import ACTIVE, ENV, IN_ENV, RANK, ROLES, audit, current_member, database_transaction, db, tables, effective_role, new_id, now_iso, require_role
    from backend.engine import PENDING, build_cost_transactions, get_settings, next_status, plan_rows, route_on_submit, step_roles, validate
    from backend.erp import get_adapter
    from backend.seed import next_ref, seed
except ModuleNotFoundError:
    from clerk_auth import clerk_router
    from core import ACTIVE, ENV, IN_ENV, RANK, ROLES, audit, current_member, database_transaction, db, tables, effective_role, new_id, now_iso, require_role
    from engine import PENDING, build_cost_transactions, get_settings, next_status, plan_rows, route_on_submit, step_roles, validate
    from erp import get_adapter
    from seed import next_ref, seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="CostBridge")
api = APIRouter(prefix="/api", dependencies=[Depends(database_transaction)])


@app.exception_handler(IntegrityError)
async def data_conflict(request, exc):
    return JSONResponse(status_code=409, content={"detail": "This change conflicts with an existing or referenced record."})

PLANNERS = ["admin", "project_manager", "foreman"]
CAPTURE = {"labor": PLANNERS, "equipment": PLANNERS, "material": ["admin", "store_manager", "foreman"]}
APPROVERS = ["admin", "project_manager", "cost_controller"]
ERP_ROLES = ["admin", "cost_controller"]


def all_active():
    return require_role(*ACTIVE)


@app.on_event("startup")
async def startup():
    await db.initialize()
    async with db.transaction():
        await db.scalar(select(func.pg_advisory_xact_lock(714237)))
        await seed()
        await db.execute(update(tables.erp_batches).where(tables.erp_batches.c.status == 'running')
                         .values(status='error', error='Interrupted by server restart'))


@app.on_event("shutdown")
async def shutdown():
    await db.close()


# ---------- Users ----------
@api.get("/me")
async def me(member: dict = Depends(current_member)):
    return member


@api.get("/users")
async def list_users(admin: dict = Depends(require_role("admin"))):
    people = await db.all(select(tables.users).where(*IN_ENV).limit(1000))
    return {"roles": [r for r in ROLES if RANK[r] <= RANK[admin["role"]]],
            "users": [{**p, "role": effective_role(p.get("role"))} for p in people]}


class RoleIn(BaseModel):
    role: str


@api.patch("/users/{user_id}/role")
async def set_role(user_id: str, body: RoleIn, admin: dict = Depends(require_role("admin"))):
    if body.role not in ROLES or RANK[body.role] > RANK[admin["role"]]:
        raise HTTPException(403, "Not allowed")
    target = await db.one(select(tables.users).where(tables.users.c['user_id'] == user_id, *IN_ENV))
    if target is None:
        raise HTTPException(404, "Not found")
    if (effective_role(target.get("role")) == "admin" and body.role != "admin"
            and await db.scalar(select(func.count()).select_from(tables.users).where(tables.users.c['role'] == 'admin', *IN_ENV)) <= 1):
        raise HTTPException(409, "Keep at least one admin")
    await db.execute(update(tables.users).where(tables.users.c['user_id'] == user_id).values({'role': body.role}))
    await audit("user", user_id, f"role set to {body.role}", admin)
    return {"user_id": user_id, "role": body.role}


# ---------- Master data ----------
@api.get("/master")
async def master(member: dict = Depends(all_active())):
    out = {}
    for name in ["projects", "tasks", "employees", "equipment", "items", "crews", "reason_codes", "budgets"]:
        out[name] = await db.all(select(getattr(tables, name)).limit(10000))
    out["hour_types"] = await db.all(select(tables.hour_types).order_by(tables.hour_types.c['order'].asc()).limit(100))
    out["settings"] = await get_settings()
    return out


class CrewIn(BaseModel):
    name: str = Field(min_length=1)
    project_number: str
    foreman: str = ""


@api.post("/crews")
async def create_crew(body: CrewIn, member: dict = Depends(require_role(*PLANNERS))):
    doc = {"id": new_id(), **body.model_dump()}
    await db.execute(insert(tables.crews).values(doc))
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
        if not body.crew_id or not await db.one(select(tables.crews).where(tables.crews.c['id'] == body.crew_id)):
            raise HTTPException(400, "Valid crew is required")
        for ln in body.lines:
            coll = tables.employees if ln.resource_type == "labor" else tables.equipment
            if not ln.resource_type or not ln.resource_number or not await db.one(select(coll).where(coll.c['number'] == ln.resource_number)):
                raise HTTPException(400, "Every plan line needs a valid employee or equipment")
            if any(v < 0 or v > 24 for v in ln.hours.values()):
                raise HTTPException(400, "Planned hours must be between 0 and 24")
    else:
        for ln in body.lines:
            if not ln.item_number or not await db.one(select(tables.items).where(tables.items.c['number'] == ln.item_number)):
                raise HTTPException(400, "Every material plan line needs a valid item")
            if not ln.planned_qty or ln.planned_qty <= 0:
                raise HTTPException(400, f"{ln.item_number}: planned quantity must be greater than 0")
    if not await db.one(select(tables.tasks).where(tables.tasks.c['project_number'] == body.project_number, tables.tasks.c['number'] == body.task_number)):
        raise HTTPException(400, "Unknown Project# / Task#")
    lines = [ln.model_dump(exclude_none=True) for ln in body.lines]
    return {**body.model_dump(exclude={"lines"}), "lines": lines}


@api.get("/plans")
async def list_plans(kind: Optional[str] = None, member: dict = Depends(all_active())):
    q = [tables.plans.c.kind == kind] if kind else []
    return await db.all(select(tables.plans).where(*q).order_by(tables.plans.c['created_at'].desc()).limit(1000))


@api.post("/plans")
async def create_plan(body: PlanIn, member: dict = Depends(all_active())):
    await _plan_roles_check(body.kind, member)
    doc = {"id": new_id(), **(await _plan_doc(body)), "status": "draft", "created_by": member.get("name"), "created_by_id": member["user_id"], "created_at": now_iso()}
    await db.execute(insert(tables.plans).values(doc))
    await audit("plan", doc["id"], "created (draft)", member)
    doc.pop("_id", None)
    return doc


@api.put("/plans/{plan_id}")
async def update_plan(plan_id: str, body: PlanIn, member: dict = Depends(all_active())):
    await _plan_roles_check(body.kind, member)
    if not await db.one(select(tables.plans).where(tables.plans.c['id'] == plan_id)):
        raise HTTPException(404, "Not found")
    if await db.one(select(tables.transactions).where(tables.transactions.c['plan_id'] == plan_id, tables.transactions.c['status'].is_distinct_from('draft'))):
        raise HTTPException(409, "Entries were already captured against this plan - create a new plan instead")
    upd = {**(await _plan_doc(body)), "status": "draft", "updated_at": now_iso()}
    await db.execute(update(tables.plans).where(tables.plans.c['id'] == plan_id).values(upd))
    await audit("plan", plan_id, "updated (back to draft)", member)
    return await db.one(select(tables.plans).where(tables.plans.c['id'] == plan_id))


@api.post("/plans/{plan_id}/publish")
async def publish_plan(plan_id: str, member: dict = Depends(all_active())):
    plan = await db.one(select(tables.plans).where(tables.plans.c['id'] == plan_id))
    if not plan:
        raise HTTPException(404, "Not found")
    await _plan_roles_check(plan["kind"], member)
    if not plan["lines"]:
        raise HTTPException(400, "Add at least one line before publishing")
    if plan["kind"] == "crew":
        others = await db.all(select(tables.plans).where(tables.plans.c['kind'] == 'crew', tables.plans.c['status'] == 'published', tables.plans.c['id'].is_distinct_from(plan_id), tables.plans.c['shift'] == plan.get('shift'), tables.plans.c['start_date'] <= plan['end_date'], tables.plans.c['end_date'] >= plan['start_date']).limit(1000))
        mine = {ln.get("resource_number") for ln in plan["lines"]}
        for o in others:
            clash = mine & {ln.get("resource_number") for ln in o["lines"]}
            if clash:
                raise HTTPException(409, f"Conflict: {', '.join(sorted(clash))} already planned on {o['project_number']}/{o['task_number']} "
                                         f"({o['start_date']} to {o['end_date']}, {o.get('shift')})")
    await db.execute(update(tables.plans).where(tables.plans.c['id'] == plan_id).values({'status': 'published', 'published_at': now_iso()}))
    await audit("plan", plan_id, "published", member)
    return await db.one(select(tables.plans).where(tables.plans.c['id'] == plan_id))


@api.delete("/plans/{plan_id}")
async def delete_plan(plan_id: str, member: dict = Depends(require_role(*PLANNERS, "store_manager"))):
    res = await db.execute(delete(tables.plans).where(tables.plans.c['id'] == plan_id, tables.plans.c['status'] == 'draft'))
    if not res.rowcount:
        raise HTTPException(404, "Draft plan not found")
    await audit("plan", plan_id, "deleted", member)
    return {"ok": True}


@api.get("/plans/autofill")
async def autofill(type: Literal["labor", "equipment"], project_number: str, task_number: str, crew_id: str, date: str,
                   member: dict = Depends(all_active())):
    plan = await db.one(select(tables.plans).where(tables.plans.c['kind'] == 'crew', tables.plans.c['status'] == 'published', tables.plans.c['project_number'] == project_number, tables.plans.c['task_number'] == task_number, tables.plans.c['crew_id'] == crew_id, tables.plans.c['start_date'] <= date, tables.plans.c['end_date'] >= date))
    if not plan:
        return {"plan": None, "lines": []}
    return {"plan": plan, "lines": await plan_rows(plan, type)}


@api.get("/plans/material-autofill")
async def material_autofill(project_number: str, task_number: str, date: str, member: dict = Depends(all_active())):
    plan = await db.one(select(tables.plans).where(tables.plans.c['kind'] == 'material', tables.plans.c['status'] == 'published', tables.plans.c['project_number'] == project_number, tables.plans.c['task_number'] == task_number, tables.plans.c['start_date'] <= date, tables.plans.c['end_date'] >= date))
    if not plan:
        return {"plan": None, "lines": []}
    done = await db.all(select(tables.transactions).where(tables.transactions.c['type'] == 'material', tables.transactions.c['project_number'] == project_number, tables.transactions.c['task_number'] == task_number, tables.transactions.c['status'].not_in(['draft', 'rejected']), tables.transactions.c['date'] >= plan['start_date'], tables.transactions.c['date'] <= plan['end_date']).limit(10000))
    lines = []
    for ln in plan["lines"]:
        used = sum(x.get("qty_consumed", 0) for d in done for x in d["lines"] if x["item_number"] == ln["item_number"])
        remaining = max(round(ln["planned_qty"] - used, 2), 0)
        lines.append({"item_number": ln["item_number"], "plan_line": True, "planned_qty": ln["planned_qty"], "used_qty": round(used, 2),
                      "qty_issued": remaining or None, "qty_wasted": None, "qty_returned": None})
    return {"plan": plan, "lines": lines}


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
    if not await db.one(select(tables.tasks).where(tables.tasks.c['project_number'] == body.project_number, tables.tasks.c['number'] == body.task_number)):
        raise HTTPException(400, "Unknown Project# / Task#")
    for ln in body.lines:
        if body.type == "material" and not ln.item_number:
            raise HTTPException(400, "Item is required on every line")
        if body.type != "material" and (not ln.resource_number or not ln.hour_type):
            raise HTTPException(400, "Resource and Hour Type are required on every line")
    coll, key = {"labor": (tables.employees, "resource_number"), "equipment": (tables.equipment, "resource_number"), "material": (tables.items, "item_number")}[body.type]
    nums = {getattr(ln, key) for ln in body.lines}
    known = {d["number"] for d in await db.all(select(coll).where(coll.c['number'].in_(list(nums))).limit(10000))}
    if nums - known:
        raise HTTPException(400, f"Unknown: {', '.join(sorted(nums - known))}")
    if body.type != "material":
        codes = {h["code"] for h in await db.all(select(tables.hour_types).where(tables.hour_types.c['resource_type'] == body.type).limit(50))}
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
    else:
        tx["status"] = "draft"
    return tx


async def _create_costs(tx: dict, s: dict):
    for c in await build_cost_transactions(tx, s):
        await db.execute(insert(tables.cost_transactions).values({'id': new_id(), **c, 'transaction_id': tx['id'], 'transaction_ref': tx['ref'], 'type': tx['type'], 'status': 'sample' if tx.get('sample') else 'recorded' if c['kind'] == 'return_to_store' else 'queued', 'created_at': now_iso(), 'attempts': 0, 'response': None}))


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
    await db.execute(insert(tables.transactions).values(tx))
    if tx["status"] == "approved":
        await _create_costs(tx, await get_settings())
    await audit("transaction", tx["id"], f"created ({tx['status']})", member, {"ref": tx["ref"], "cost": tx["totals"]["cost"]})
    tx.pop("_id", None)
    return tx


@api.put("/transactions/{tx_id}")
async def update_tx(tx_id: str, body: TxIn, member: dict = Depends(all_active())):
    _check_capture(body.type, member)
    old = await db.one(select(tables.transactions).where(tables.transactions.c['id'] == tx_id, tables.transactions.c['created_by_id'] == member['user_id']))
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
    if tx["status"] != "rejected":
        tx["rejection_reason"] = None
    result = await db.execute(update(tables.transactions).where(tables.transactions.c.id == tx_id,
                              tables.transactions.c.status == old["status"]).values(tx))
    if not result.rowcount:
        raise HTTPException(409, "Entry was already actioned by someone else")
    if tx["status"] == "approved":
        await _create_costs(tx, await get_settings())
    await audit("transaction", tx_id, f"updated ({tx['status']})", member, {"cost": tx["totals"]["cost"]})
    return tx


@api.get("/transactions")
async def list_tx(type: Optional[str] = None, status: Optional[str] = None, project_number: Optional[str] = None,
                  mine: bool = False, member: dict = Depends(all_active())):
    q = []
    if type:
        q.append(tables.transactions.c.type == type)
    if status:
        q.append(tables.transactions.c.status == status)
    if project_number:
        q.append(tables.transactions.c.project_number == project_number)
    if mine or member["role"] in ("foreman", "store_manager"):
        q.append(tables.transactions.c.created_by_id == member["user_id"])
    return await db.all(select(tables.transactions).where(*q).order_by(tables.transactions.c['created_at'].desc()).limit(2000))


@api.get("/transactions/{tx_id}")
async def get_tx(tx_id: str, member: dict = Depends(all_active())):
    q = [tables.transactions.c.id == tx_id]
    if member["role"] in ("foreman", "store_manager"):
        q.append(tables.transactions.c.created_by_id == member["user_id"])
    tx = await db.one(select(tables.transactions).where(*q))
    if not tx:
        raise HTTPException(404, "Not found")
    tx["audit"] = await db.all(select(tables.audit).where(tables.audit.c['entity_id'] == tx_id).order_by(tables.audit.c['at'].asc()).limit(500))
    tx["cost_transactions"] = await db.all(select(tables.cost_transactions).where(tables.cost_transactions.c['transaction_id'] == tx_id).limit(500))
    return tx


# ---------- Approvals ----------
@api.get("/approvals")
async def approvals(member: dict = Depends(require_role(*APPROVERS))):
    s = await get_settings()
    statuses = [st for st in PENDING if member["role"] in step_roles(st, s)]
    q = [tables.transactions.c.status.in_(statuses)]
    if member["role"] != "admin":
        q.append(tables.transactions.c.submitted_by_id.is_distinct_from(member["user_id"]))
    return await db.all(select(tables.transactions).where(*q).order_by(tables.transactions.c['submitted_at'].asc()).limit(2000))


class DecisionIn(BaseModel):
    comment: str = ""


@api.post("/transactions/{tx_id}/approve")
async def approve(tx_id: str, body: DecisionIn, member: dict = Depends(require_role(*APPROVERS))):
    s = await get_settings()
    tx = await db.one(select(tables.transactions).where(tables.transactions.c['id'] == tx_id))
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
    res = await db.execute(update(tables.transactions).where(tables.transactions.c.id == tx_id,
                           tables.transactions.c.status == step).values(**upd, approvals=tx["approvals"] + [entry]))
    if not res.rowcount:
        raise HTTPException(409, "Entry was already actioned by someone else")
    tx = await db.one(select(tables.transactions).where(tables.transactions.c['id'] == tx_id))
    if new_status == "approved":
        await _create_costs(tx, s)
    await audit("transaction", tx_id, f"approved {step} -> {new_status}", member, {"comment": body.comment})
    return tx


class RejectIn(BaseModel):
    reason: str = Field(min_length=3)


@api.post("/transactions/{tx_id}/reject")
async def reject(tx_id: str, body: RejectIn, member: dict = Depends(require_role(*APPROVERS))):
    s = await get_settings()
    tx = await db.one(select(tables.transactions).where(tables.transactions.c['id'] == tx_id))
    if not tx or tx["status"] not in PENDING:
        raise HTTPException(404, "Not pending")
    if member["role"] not in step_roles(tx["status"], s):
        raise HTTPException(403, "Not your approval step")
    step = tx["status"]
    entry = {"step": step, "decision": "rejected", "by": member.get("name"), "role": member["role"], "at": now_iso(), "comment": body.reason}
    res = await db.execute(update(tables.transactions).where(tables.transactions.c.id == tx_id,
                           tables.transactions.c.status == step).values(status="rejected",
                           rejection_reason=body.reason, approvals=tx["approvals"] + [entry]))
    if not res.rowcount:
        raise HTTPException(409, "Entry was already actioned by someone else")
    await audit("transaction", tx_id, f"rejected at {step}", member, {"reason": body.reason})
    return await db.one(select(tables.transactions).where(tables.transactions.c['id'] == tx_id))


# ---------- Dashboard / reports ----------
@api.get("/dashboard")
async def dashboard(project_number: Optional[str] = None, member: dict = Depends(all_active())):
    s = await get_settings()
    warn = s.get("budget_warning_pct", 90)
    tx_query = select(tables.transactions).where(tables.transactions.c.status.not_in(['draft', 'rejected']))
    budget_query = select(tables.budgets)
    if project_number:
        tx_query = tx_query.where(tables.transactions.c.project_number == project_number)
        budget_query = budget_query.where(tables.budgets.c.project_number == project_number)
    txs = await db.all(tx_query.limit(20000))
    budgets = await db.all(budget_query.limit(5000))
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
    queued = await db.scalar(select(func.count()).select_from(tables.cost_transactions).where(tables.cost_transactions.c['status'].in_(['queued', 'error'])))
    return {"rows": rows, "cost_by_type": by_type,
            "kpis": {"actual_cost": round(sum(by_type.values()), 2),
                     "approved_cost": round(sum(t["totals"]["cost"] for t in txs if t["status"] in ("approved", "posted")), 2),
                     "pending_cost": round(sum(t["totals"]["cost"] for t in pending), 2), "pending_count": len(pending),
                     "flagged_count": sum(1 for t in pending if t["validation"]["special"]["required"]),
                     "erp_queue": queued, "over_budget": sum(1 for r in rows if r["status"] == "stopped")}}


@api.get("/audit")
async def audit_log(member: dict = Depends(require_role("admin", "cost_controller"))):
    return await db.all(select(tables.audit).order_by(tables.audit.c['at'].desc()).limit(500))


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
    await db.execute(pg_insert(tables.settings).values(id="global", **body.model_dump())
                     .on_conflict_do_update(index_elements=["id"], set_=body.model_dump()))
    await audit("settings", "global", "updated", member, body.model_dump())
    return await get_settings()


@api.get("/rate-cards")
async def rate_cards(member: dict = Depends(all_active())):
    return await db.all(select(tables.rate_cards).limit(5000))


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
    if await db.one(select(tables.rate_cards).where(tables.rate_cards.c['resource_type'] == body.resource_type, tables.rate_cards.c['key'] == body.key, tables.rate_cards.c['hour_type'] == body.hour_type)):
        raise HTTPException(409, "Rate already exists for this key and hour type")
    doc = {"id": new_id(), **body.model_dump()}
    await db.execute(insert(tables.rate_cards).values(doc))
    await audit("rate_card", doc["id"], "created", member, body.model_dump())
    doc.pop("_id", None)
    return doc


@api.put("/rate-cards/{rid}")
async def update_rate(rid: str, body: RateIn, member: dict = Depends(require_role("admin"))):
    res = await db.execute(update(tables.rate_cards).where(tables.rate_cards.c['id'] == rid).values(body.model_dump()))
    if not res.rowcount:
        raise HTTPException(404, "Not found")
    await audit("rate_card", rid, "updated", member, body.model_dump())
    return await db.one(select(tables.rate_cards).where(tables.rate_cards.c['id'] == rid))


class HourTypeIn(BaseModel):
    name: str
    expenditure_type: str
    requires_reason: bool


@api.put("/hour-types/{hid}")
async def update_hour_type(hid: str, body: HourTypeIn, member: dict = Depends(require_role("admin"))):
    res = await db.execute(update(tables.hour_types).where(tables.hour_types.c['id'] == hid).values(body.model_dump()))
    if not res.rowcount:
        raise HTTPException(404, "Not found")
    await audit("hour_type", hid, "updated", member, body.model_dump())
    return await db.one(select(tables.hour_types).where(tables.hour_types.c['id'] == hid))


class ReasonIn(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    resource_type: Literal["equipment", "material"]


@api.post("/reason-codes")
async def add_reason(body: ReasonIn, member: dict = Depends(require_role("admin"))):
    if await db.one(select(tables.reason_codes).where(tables.reason_codes.c['code'] == body.code)):
        raise HTTPException(409, "Code already exists")
    doc = {"id": new_id(), **body.model_dump()}
    await db.execute(insert(tables.reason_codes).values(doc))
    doc.pop("_id", None)
    return doc


@api.delete("/reason-codes/{rid}")
async def del_reason(rid: str, member: dict = Depends(require_role("admin"))):
    await db.execute(delete(tables.reason_codes).where(tables.reason_codes.c['id'] == rid))
    return {"ok": True}


# ---------- ERP integration ----------
@api.get("/erp/status")
async def erp_status(member: dict = Depends(all_active())):
    a = get_adapter()
    counts = {s: await db.scalar(select(func.count()).select_from(tables.cost_transactions).where(tables.cost_transactions.c['status'] == s)) for s in ["queued", "sent", "error", "recorded", "sample"]}
    last = await db.one(select(tables.erp_batches).order_by(tables.erp_batches.c['started_at'].desc()))
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
async def erp_sync(body: SyncIn, background_tasks: BackgroundTasks, member: dict = Depends(require_role("admin"))):
    a = get_adapter()
    if not a:
        raise HTTPException(400, "Oracle connection is not configured")
    if await db.one(select(tables.erp_batches).where(tables.erp_batches.c['direction'] == 'pull', tables.erp_batches.c['status'] == 'running')):
        raise HTTPException(409, "A master data sync is already running")
    batches = [{"id": new_id(), "direction": "pull", "entity": ent, "started_at": now_iso(), "by": member.get("name"), "status": "running", "count": 0}
               for ent in body.entities]
    await db.insert_many(tables.erp_batches, [dict(b) for b in batches])
    background_tasks.add_task(_run_sync, a, batches)
    await audit("erp", "sync", "master data pull started", member, {"entities": body.entities})
    return batches


async def _run_sync(a, batches: list[dict]):
    for b in batches:
        upd = {}
        try:
            rows = await a.pull(b["entity"])
            coll, keys = KEYS[b["entity"]]
            table = getattr(tables, coll)
            async with db.transaction(independent=True):
                for i in range(0, len(rows), 1000):
                    documents = [{"id": new_id(), **row, "source": "oracle", "synced_at": now_iso()}
                                 for row in rows[i:i + 1000]]
                    statement = pg_insert(table).values(documents)
                    await db.execute(statement.on_conflict_do_update(index_elements=keys,
                                     set_={k: statement.excluded[k] for k in documents[0] if k != "id" and k not in keys}))
                await db.execute(update(tables.erp_batches).where(tables.erp_batches.c.id == b["id"])
                                 .values(status="success", count=len(rows), finished_at=now_iso()))
        except Exception as e:
            logger.exception("ERP sync %s failed", b["entity"])
            upd = {"status": "error", "error": str(e)[:500]}
            async with db.transaction(independent=True):
                await db.execute(update(tables.erp_batches).where(tables.erp_batches.c.id == b["id"])
                                 .values(**upd, finished_at=now_iso()))


@api.post("/erp/push")
async def erp_push(member: dict = Depends(require_role(*ERP_ROLES))):
    a = get_adapter()
    if not a:
        raise HTTPException(400, "Oracle connection is not configured")
    pend = await db.all(select(tables.cost_transactions).where(tables.cost_transactions.c['status'].in_(['queued', 'error']), tables.cost_transactions.c['kind'] == 'project_cost').limit(2000).with_for_update(skip_locked=True))
    batch = {"id": new_id(), "direction": "push", "entity": "unprocessedProjectCosts", "started_at": now_iso(), "by": member.get("name")}
    ok = err = 0
    for c in pend:
        try:
            r = await a.push_cost(c["payload"])
        except Exception as e:
            r = {"ok": False, "status": 0, "body": str(e)[:300]}
        ok, err = ok + r["ok"], err + (not r["ok"])
        await db.execute(update(tables.cost_transactions).where(tables.cost_transactions.c.id == c["id"])
                         .values(status="sent" if r["ok"] else "error", response=r, batch_id=batch["id"],
                                 sent_at=now_iso(), attempts=tables.cost_transactions.c.attempts + 1))
    for tid in {c["transaction_id"] for c in pend}:
        if not await db.scalar(select(func.count()).select_from(tables.cost_transactions).where(tables.cost_transactions.c['transaction_id'] == tid, tables.cost_transactions.c['kind'] == 'project_cost', tables.cost_transactions.c['status'].is_distinct_from('sent'))):
            await db.execute(update(tables.transactions).where(tables.transactions.c['id'] == tid).values({'status': 'posted', 'posted_at': now_iso()}))
    batch.update(status="success" if not err else "partial" if ok else "error", count=len(pend), ok=ok, failed=err, finished_at=now_iso())
    await db.execute(insert(tables.erp_batches).values(batch))
    batch.pop("_id", None)
    await audit("erp", batch["id"], "cost push", member, {"ok": ok, "failed": err})
    return batch


@api.get("/erp/batches")
async def erp_batches(member: dict = Depends(require_role(*ERP_ROLES))):
    return await db.all(select(tables.erp_batches).order_by(tables.erp_batches.c['started_at'].desc()).limit(200))


@api.get("/erp/cost-transactions")
async def erp_costs(status: Optional[str] = None, member: dict = Depends(require_role(*ERP_ROLES))):
    q = [tables.cost_transactions.c.status == status] if status else []
    return await db.all(select(tables.cost_transactions).where(*q).order_by(tables.cost_transactions.c['created_at'].desc()).limit(2000))


app.include_router(api)
app.include_router(clerk_router)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])
