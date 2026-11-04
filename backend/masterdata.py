from sqlalchemy import select, insert, func, or_, update as sql_update, delete as sql_delete
from sqlalchemy.exc import IntegrityError
"""Standalone master data: per-entity source modes, ERP-locked records, local CRUD, deactivate, bulk upload."""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from backend.core import ACTIVE, audit, database_transaction, db, tables, new_id, now_iso, require_role
except ModuleNotFoundError:
    from core import ACTIVE, audit, database_transaction, db, tables, new_id, now_iso, require_role

md = APIRouter(prefix="/api/md", dependencies=[Depends(database_transaction)])
EDITORS = ["admin", "master_data_admin"]

# key: natural key fields; req: required; lo: local-only fields editable on ERP records; ref: (collection, field) usage check
ENT = {
    "projects": {"key": ["number"], "req": ["number", "name"], "lo": ["site"], "ref": ("transactions", "project_number")},
    "tasks": {"key": ["project_number", "number"], "req": ["project_number", "number", "name"], "lo": ["allowed_types"], "ref": ("transactions", "task_number")},
    "employees": {"key": ["number"], "req": ["number", "name", "grade"], "lo": ["supervisor", "badge_id", "email", "mobile"], "ref": ("transactions", "lines.resource_number")},
    "equipment": {"key": ["number"], "req": ["number", "name", "cls"], "lo": ["default_operator", "current_project"], "ref": ("transactions", "lines.resource_number")},
    "items": {"key": ["number"], "req": ["number", "description", "uom"], "lo": ["default_store"], "ref": ("transactions", "lines.item_number")},
    "stores": {"key": ["code"], "req": ["code", "name", "store_type"], "lo": [], "ref": None},
    "lookups": {"key": ["type", "code"], "req": ["type", "code", "meaning"], "lo": [], "ref": None},
}
SYS = {"id", "source", "external_id", "synced_at", "created_at", "created_by", "updated_at", "updated_by", "erp_id"}
CODE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,29}$")


def is_erp(doc: dict) -> bool:
    return doc.get("source") == "oracle"


async def source_modes() -> dict:
    s = await db.one(select(tables.settings).where(tables.settings.c['id'] == 'global')) or {}
    return {e: (s.get("source_modes") or {}).get(e, "hybrid") for e in ENT}


def _ent(entity: str) -> dict:
    if entity not in ENT:
        raise HTTPException(404, "Unknown entity")
    return ENT[entity]


def _clean(entity: str, data: dict) -> dict:
    unknown = set(data) - set(getattr(tables, entity).c.keys()) - SYS
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    out = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items() if k not in SYS}
    for k in ENT[entity]["key"]:
        if k == "project_number" or k == "type":
            continue
        if out.get(k) is not None:
            out[k] = str(out[k]).upper().replace(" ", "")
            if not CODE.match(out[k]):
                raise ValueError(f"{k}: uppercase letters/digits, no spaces, max 30 chars")
    for k in ("unit_cost", "order"):
        if out.get(k) not in (None, ""):
            out[k] = float(out[k])
    missing = [k for k in ENT[entity]["req"] if out.get(k) in (None, "")]
    if missing:
        raise ValueError(f"Required: {', '.join(missing)}")
    if entity == "projects" and out.get("end_date") and out.get("start_date") and out["end_date"] < out["start_date"]:
        raise ValueError("End date is before start date")
    return out


async def _referenced(entity: str, doc: dict) -> bool:
    if entity == "projects" and await db.one(select(tables.tasks).where(tables.tasks.c['project_number'] == doc['number'])):
        return True
    if entity in ("employees", "equipment") and await db.one(select(tables.plans).where(
            tables.plans.c.lines.contains([{"resource_number": doc["number"]}]))):
        return True
    ref = ENT[entity]["ref"]
    if not ref:
        return False
    key = doc.get("number")
    table = getattr(tables, ref[0])
    if ref[1].startswith("lines."):
        q = [table.c.lines.contains([{ref[1].split(".")[1]: key}])]
    else:
        q = [table.c[ref[1]] == key]
    if entity == "tasks":
        q.append(table.c.project_number == doc["project_number"])
    return bool(await db.one(select(getattr(tables, ref[0])).where(*q)))


async def _save(entity: str, data: dict, member: dict, existing: dict | None) -> tuple[str, dict]:
    """Returns (action, doc). Raises ValueError on rule violations."""
    e = ENT[entity]
    modes = await source_modes()
    if existing:
        if is_erp(existing):
            bad = [k for k, v in data.items() if k not in e["lo"] and k not in SYS and existing.get(k) != v and v not in (None, "")]
            if bad:
                raise ValueError(f"ERP record - only local-only fields can change ({', '.join(e['lo']) or 'none'}); blocked: {', '.join(bad)}")
            upd = {k: data[k] for k in e["lo"] if k in data}
        else:
            upd = _clean(entity, {**existing, **data})
            if any(upd.get(k) != existing.get(k) for k in e["key"]) and await _referenced(entity, existing):
                raise ValueError("Key is locked after first transaction")
        upd.update(updated_at=now_iso(), updated_by=member.get("name"))
        await db.execute(sql_update(getattr(tables, entity)).where(getattr(tables, entity).c['id'] == existing['id']).values(upd))
        return "update", {**existing, **upd}
    if modes[entity] == "erp":
        raise ValueError(f"{entity} are ERP-synced - create them in the ERP")
    doc = _clean(entity, data)
    if await db.one(select(getattr(tables, entity)).where(*(getattr(tables, entity).c[k] == v for k, v in {k: doc[k] for k in e['key']}.items()))):
        raise ValueError("Key already exists (ERP or local)")
    if entity == "tasks" and not await db.one(select(tables.projects).where(tables.projects.c['number'] == doc['project_number'])):
        raise ValueError(f"Unknown project {doc['project_number']}")
    doc.update(id=new_id(), source="local", status=doc.get("status") or "Active", created_at=now_iso(), created_by=member.get("name"))
    await db.execute(insert(getattr(tables, entity)).values(dict(doc)))
    return "create", doc


@md.get("/summary")
async def summary(member: dict = Depends(require_role(*ACTIVE))):
    modes = await source_modes()
    out = []
    for e in ENT:
        out.append({"entity": e, "mode": modes[e], "total": await db.scalar(select(func.count()).select_from(getattr(tables, e))),
                    "erp": await db.scalar(select(func.count()).select_from(getattr(tables, e)).where(getattr(tables, e).c['source'] == 'oracle')),
                    "inactive": await db.scalar(select(func.count()).select_from(getattr(tables, e)).where(getattr(tables, e).c['status'] == 'Inactive'))})
    conflicts = await db.scalar(select(func.count()).select_from(tables.erp_conflicts).where(tables.erp_conflicts.c['resolved'].is_distinct_from(True)))
    return {"entities": out, "conflicts": conflicts}


class ModesIn(BaseModel):
    modes: dict[str, Literal["erp", "local", "hybrid"]]


@md.put("/source-modes")
async def set_modes(body: ModesIn, member: dict = Depends(require_role("admin"))):
    current = await db.one(select(tables.settings).where(tables.settings.c.id == "global").with_for_update())
    modes = {**((current or {}).get("source_modes") or {}), **{k: v for k, v in body.modes.items() if k in ENT}}
    await db.execute(sql_update(tables.settings).where(tables.settings.c.id == "global").values(source_modes=modes))
    await audit("settings", "source_modes", "updated", member, body.modes)
    return await source_modes()


@md.get("/conflicts")
async def conflicts(member: dict = Depends(require_role(*EDITORS))):
    return await db.all(select(tables.erp_conflicts).where(tables.erp_conflicts.c['resolved'].is_distinct_from(True)).order_by(tables.erp_conflicts.c['at'].desc()).limit(500))


@md.get("/{entity}")
async def list_entity(entity: str, q: str = "", status: str = "", source: str = "", project_number: str = "", type: str = "",
                      member: dict = Depends(require_role(*ACTIVE))):
    e = _ent(entity)
    table = getattr(tables, entity)
    flt = []
    if q:
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        flt.append(or_(*(table.c[k].ilike(pattern, escape="\\")
                        for k in set(e["key"] + ["name", "description", "meaning"]) if k in table.c)))
    if status:
        flt.append(or_(table.c.status == status, table.c.status.is_(None)) if status == "Active" else table.c.status == status)
    if source:
        flt.append(table.c.source == "oracle" if source == "erp" else table.c.source.is_distinct_from("oracle"))
    if project_number:
        if "project_number" in table.c:
            flt.append(table.c.project_number == project_number)
    if type:
        if "type" in table.c:
            flt.append(table.c.type == type)
    total = await db.scalar(select(func.count()).select_from(getattr(tables, entity)).where(*flt))
    rows = await db.all(select(getattr(tables, entity)).where(*flt).order_by(getattr(tables, entity).c[e['key'][-1]].asc()).limit(500))
    return {"total": total, "rows": rows, "lo": e["lo"], "mode": (await source_modes())[entity]}


@md.post("/{entity}")
async def create(entity: str, body: dict, member: dict = Depends(require_role(*EDITORS))):
    _ent(entity)
    try:
        _, doc = await _save(entity, body, member, None)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    await audit(entity, doc["id"], "created", member)
    return doc


@md.put("/{entity}/{rid}")
async def update(entity: str, rid: str, body: dict, member: dict = Depends(require_role(*EDITORS))):
    _ent(entity)
    existing = await db.one(select(getattr(tables, entity)).where(getattr(tables, entity).c['id'] == rid))
    if not existing:
        raise HTTPException(404, "Not found")
    try:
        _, doc = await _save(entity, body, member, existing)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    await audit(entity, rid, "updated", member)
    return doc


class StatusIn(BaseModel):
    status: Literal["Active", "Inactive"]


@md.post("/{entity}/{rid}/status")
async def set_status(entity: str, rid: str, body: StatusIn, member: dict = Depends(require_role(*EDITORS))):
    _ent(entity)
    doc = await db.one(select(getattr(tables, entity)).where(getattr(tables, entity).c['id'] == rid))
    if not doc:
        raise HTTPException(404, "Not found")
    if is_erp(doc):
        raise HTTPException(400, "ERP record - status is controlled by the ERP")
    await db.execute(sql_update(getattr(tables, entity)).where(getattr(tables, entity).c['id'] == rid).values({'status': body.status, 'updated_at': now_iso(), 'updated_by': member.get('name')}))
    await audit(entity, rid, f"status {body.status}", member)
    return {"ok": True}


@md.delete("/{entity}/{rid}")
async def delete(entity: str, rid: str, member: dict = Depends(require_role(*EDITORS))):
    _ent(entity)
    doc = await db.one(select(getattr(tables, entity)).where(getattr(tables, entity).c['id'] == rid))
    if not doc:
        raise HTTPException(404, "Not found")
    if is_erp(doc) or await _referenced(entity, doc):
        raise HTTPException(409, "Used in transactions or ERP-sourced - deactivate instead")
    await db.execute(sql_delete(getattr(tables, entity)).where(getattr(tables, entity).c['id'] == rid))
    await audit(entity, rid, "deleted", member)
    return {"ok": True}


class BulkIn(BaseModel):
    rows: list[dict]
    commit: bool = False
    skip_errors: bool = True


@md.post("/{entity}/bulk")
async def bulk(entity: str, body: BulkIn, member: dict = Depends(require_role(*EDITORS))):
    e = _ent(entity)
    if len(body.rows) > 20000:
        raise HTTPException(400, "Max 20,000 rows per file")
    results, seen = [], set()
    for i, raw in enumerate(body.rows):
        row = {k: v for k, v in raw.items() if v not in (None, "")}
        try:
            probe = _clean(entity, {k: v for k, v in row.items() if k != "id"})
            key = tuple(probe.get(k) for k in e["key"])
            if key in seen:
                raise ValueError("Duplicate key in file")
            seen.add(key)
            existing = await db.one(select(getattr(tables, entity)).where(*(getattr(tables, entity).c[k] == v for k, v in {k: probe[k] for k in e['key']}.items())))
            if existing and is_erp(existing) and any(k not in e["lo"] and k not in e["key"] and existing.get(k) != v for k, v in probe.items()):
                raise ValueError("ERP record - only local-only fields can be uploaded")
            if not existing and (await source_modes())[entity] == "erp":
                raise ValueError("Entity is ERP-synced - cannot create")
            results.append({"row": i + 1, "result": "update" if existing else "new", "key": " / ".join(map(str, key)), "_data": probe, "_existing": existing})
        except ValueError as ex:
            results.append({"row": i + 1, "result": "error", "error": str(ex), "key": " / ".join(str(row.get(k, "")) for k in e["key"])})
    counts = {r: sum(1 for x in results if x["result"] == r) for r in ("new", "update", "error")}
    committed = 0
    if body.commit and (body.skip_errors or not counts["error"]):
        for r in results:
            if r["result"] in ("new", "update"):
                try:
                    async with db.transaction() as connection:
                        async with connection.begin_nested():
                            await _save(entity, r["_data"], member, r["_existing"])
                    committed += 1
                except ValueError as ex:
                    r.update(result="error", error=str(ex))
                except IntegrityError:
                    r.update(result="error", error="Record conflicts with existing or referenced master data")
        await db.execute(insert(tables.md_uploads).values({'id': new_id(), 'entity': entity, 'by': member.get('name'), 'at': now_iso(), 'counts': counts, 'committed': committed}))
        await audit(entity, "bulk", f"bulk upload committed {committed}", member, counts)
    for r in results:
        r.pop("_data", None)
        r.pop("_existing", None)
    return {"counts": counts, "committed": committed, "results": results[:2000]}
