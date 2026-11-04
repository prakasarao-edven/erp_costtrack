"""Idempotent sample master data so the app works before the Oracle connection is configured."""
from datetime import date, timedelta
import calendar

try:
    from backend.core import db, new_id, now_iso
    from backend.engine import DEFAULT_SETTINGS, validate
except ModuleNotFoundError:
    from core import db, new_id, now_iso
    from engine import DEFAULT_SETTINGS, validate

SRC = "sample"

PROJECTS = [("PRJ-1042", "Metro Line Expansion - Phase 2", "Sample Metro Rail Corp"),
            ("PRJ-2088", "Refinery Unit 4 Upgrade", "Sample Refining Co")]
TASKS = [("PRJ-1042", "Civil-WBS-3", "Station Box Civil Works"), ("PRJ-1042", "MEP-WBS-7", "Station MEP Installation"),
         ("PRJ-1042", "Struct-WBS-2", "Viaduct Piers"), ("PRJ-2088", "Mech-WBS-1", "Equipment Erection"),
         ("PRJ-2088", "Piping-WBS-4", "Process Piping")]
EMPLOYEES = [("E-10021", "E. Reddy", "Skilled", "Mason"), ("E-10022", "K. Sharma", "Skilled", "Carpenter"),
             ("E-10023", "R. Verma", "Semi-skilled", "Steel Fixer"), ("E-10024", "P. Nair", "Helper", "General"),
             ("E-10025", "M. Khan", "Operator", "Equipment Operator"), ("E-10026", "S. Das", "Supervisor", "Site Supervisor"),
             ("E-10027", "A. Patel", "Skilled", "Electrician"), ("E-10028", "J. Thomas", "Skilled", "Pipefitter"),
             ("E-10029", "V. Rao", "Semi-skilled", "Welder Helper"), ("E-10030", "L. Gomez", "Helper", "General")]
EQUIPMENT = [("EXC-014", "Excavator CAT 320", "Excavator", "Heavy Earthmoving"), ("LDR-009", "Wheel Loader 950", "Loader", "Heavy Earthmoving"),
             ("CRN-022", "Mobile Crane 50T", "Crane", "Lifting"), ("DMP-031", "Dump Truck 25T", "Truck", "Haulage"),
             ("GEN-007", "Generator 125kVA", "Generator", "Power")]
ITEMS = [("CEM-OPC53", "Cement OPC 53 (50kg bag)", "BAG", 9.5, "Civil"), ("REBAR-GR60-25MM", "Rebar Gr60 25mm", "TON", 820.0, "Steel"),
         ("RMC-M30", "Ready-mix Concrete M30", "M3", 115.0, "Civil"), ("PIPE-CS-6IN", "CS Pipe 6in SCH40", "M", 42.0, "Piping"),
         ("CBL-4C-95", "Power Cable 4C x 95mm2", "M", 18.5, "Electrical")]
HOUR_TYPES = [("labor", "REG", "Regular", False, "Labor - Regular", 1.0, 0), ("labor", "OT", "Overtime", False, "Labor - Overtime", 1.5, 0),
              ("labor", "IDLE", "Idle", False, "Labor - Idle", 0.5, 0), ("labor", "HW", "Harsh Weather", False, "Labor - Weather Premium", 1.0, 3.0),
              ("equipment", "REG", "Regular / Active", False, "Equipment - Active", None, None),
              ("equipment", "IDLE", "Idle", False, "Equipment - Idle", None, None),
              ("equipment", "MAINT", "Maintenance", True, "Equipment - Maintenance", None, None),
              ("equipment", "DOWN", "Downtime", True, "Equipment - Downtime", None, None)]
GRADES = {"Supervisor": 48, "Skilled": 36, "Semi-skilled": 28, "Helper": 22, "Operator": 40}
EQ_RATES = {"Heavy Earthmoving": {"REG": 145, "IDLE": 60, "MAINT": 35, "DOWN": 20}, "Lifting": {"REG": 210, "IDLE": 90, "MAINT": 50, "DOWN": 30},
            "Haulage": {"REG": 85, "IDLE": 35, "MAINT": 20, "DOWN": 12}, "Power": {"REG": 30, "IDLE": 12, "MAINT": 8, "DOWN": 5}}
REASONS = [("BRK-HYD", "Breakdown - Hydraulic", "equipment"), ("BRK-ENG", "Breakdown - Engine", "equipment"),
           ("WTH", "Weather delay", "equipment"), ("PM-SCH", "Scheduled maintenance", "equipment"),
           ("NO-OP", "No operator available", "equipment"), ("WASTE-DMG", "Damaged in handling", "material"),
           ("WASTE-SPL", "Spillage / over-pour", "material"), ("WASTE-EXP", "Expired / set material", "material")]
BUDGETS = [("PRJ-1042", "Civil-WBS-3", "labor", None, 600, "hrs"), ("PRJ-1042", "Civil-WBS-3", "equipment", None, 50, "hrs"),
           ("PRJ-1042", "Civil-WBS-3", "material", "CEM-OPC53", 3500, "BAG"), ("PRJ-1042", "Civil-WBS-3", "material", "REBAR-GR60-25MM", 120, "TON"),
           ("PRJ-1042", "MEP-WBS-7", "labor", None, 400, "hrs"), ("PRJ-1042", "MEP-WBS-7", "equipment", None, 30, "hrs"),
           ("PRJ-1042", "MEP-WBS-7", "material", "CBL-4C-95", 2000, "M"),
           ("PRJ-1042", "Struct-WBS-2", "labor", None, 900, "hrs"), ("PRJ-1042", "Struct-WBS-2", "equipment", None, 120, "hrs"),
           ("PRJ-1042", "Struct-WBS-2", "material", "RMC-M30", 1500, "M3"),
           ("PRJ-2088", "Mech-WBS-1", "labor", None, 1200, "hrs"), ("PRJ-2088", "Mech-WBS-1", "equipment", None, 200, "hrs"),
           ("PRJ-2088", "Piping-WBS-4", "labor", None, 800, "hrs"), ("PRJ-2088", "Piping-WBS-4", "material", "PIPE-CS-6IN", 3000, "M")]


LOOKUPS = [("CRAFT", c) for c in ["Carpenter", "Electrician", "Welder", "Rigger", "Helper", "Operator", "Mason", "Steel Fixer", "Pipefitter"]] + \
    [("GRADE", g) for g in GRADES] + [("EQUIPMENT_CLASS", c) for c in EQ_RATES] + \
    [("UOM", u) for u in ["EA", "HR", "DAY", "KG", "MT", "M", "M2", "M3", "L", "BAG", "TON"]] + \
    [("ITEM_CATEGORY", c) for c in ["Civil", "Steel", "Piping", "Electrical", "Consumables"]] + \
    [("BONUS_TYPE", b) for b in ["Safety", "Bad Weather", "Remote Site"]] + [("PROJECT_TYPE", p) for p in ["Lump Sum", "T&M", "Cost Plus"]]
NEW_LABOR_HT = [("WKD", "Weekend", "Labor - Weekend", 1.5), ("HOL", "Holiday", "Labor - Holiday", 2.0)]
BONUS_RATES = [("Safety", "per_day", 10.0), ("Bad Weather", "per_hour", 2.5), ("Remote Site", "per_day", 25.0)]


async def migrate():
    """Idempotent additions for the master data module."""
    if not await db.lookups.count_documents({}):
        await db.lookups.insert_many([{"id": new_id(), "type": t, "code": c.upper().replace(" ", "_").replace("&", "N"), "meaning": c,
                                       "order": i, "status": "Active", "source": "local"} for i, (t, c) in enumerate(LOOKUPS)])
    if not await db.stores.count_documents({}):
        await db.stores.insert_many([{"id": new_id(), "code": "STR-SITE-1042", "name": "Metro Phase 2 Site Store", "store_type": "Site Store",
                                      "linked_projects": "PRJ-1042", "status": "Active", "source": "local"},
                                     {"id": new_id(), "code": "STR-CWH-01", "name": "Central Warehouse", "store_type": "Central Warehouse",
                                      "status": "Active", "source": "local"}])
    if not await db.bonus_rates.count_documents({}):
        await db.bonus_rates.insert_many([{"id": new_id(), "bonus_type": b, "basis": basis, "amount": a, "effective_from": "2026-01-01"}
                                          for b, basis, a in BONUS_RATES])
    for i, (code, name, et, mult) in enumerate(NEW_LABOR_HT):
        if await db.hour_types.find_one({"resource_type": "labor", "code": code}):
            continue
        await db.hour_types.insert_one({"id": new_id(), "resource_type": "labor", "code": code, "name": name, "requires_reason": False,
                                        "expenditure_type": et, "order": 3.5 + i * 0.1})
        keys = {r["key"]: r["base_rate"] for r in await db.rate_cards.find({"resource_type": "labor", "hour_type": "REG"}, {"_id": 0}).to_list(1000)}
        if keys:
            await db.rate_cards.insert_many([{"id": new_id(), "resource_type": "labor", "key": k, "hour_type": code, "base_rate": b, "multiplier": mult,
                                              "premium": 0, "effective_from": "2026-01-01"} for k, b in keys.items()])


async def next_ref(prefix: str) -> str:
    c = await db.counters.find_one_and_update({"id": prefix}, {"$inc": {"n": 1}}, upsert=True, return_document=True)
    return f"{prefix}-{c['n']:05d}"


async def _sample_tx(t, proj, task, d, lines, status, by, mode="manual"):
    tx = {"id": new_id(), "ref": await next_ref({"labor": "LAB", "equipment": "EQP", "material": "MAT"}[t]), "type": t,
          "project_number": proj, "task_number": task, "date": d, "crew_id": None, "mode": mode, "lines": lines,
          "status": status, "submitted_by": by, "submitted_by_id": "sample", "submitted_at": now_iso(),
          "created_at": now_iso(), "approvals": [], "notes": "Sample data", "sample": True}
    await validate(tx)
    await db.transactions.insert_one(tx)


async def seed():
    if await db.settings.count_documents({}) == 0:
        await db.settings.insert_one(dict(DEFAULT_SETTINGS))
    if await db.projects.count_documents({}) > 0:
        await migrate()
        return
    await db.projects.insert_many([{"id": new_id(), "number": n, "name": nm, "client": c, "source": SRC} for n, nm, c in PROJECTS])
    await db.tasks.insert_many([{"id": new_id(), "project_number": p, "number": n, "name": nm, "source": SRC} for p, n, nm in TASKS])
    await db.employees.insert_many([{"id": new_id(), "number": n, "name": nm, "grade": g, "trade": tr, "source": SRC} for n, nm, g, tr in EMPLOYEES])
    await db.equipment.insert_many([{"id": new_id(), "number": n, "name": nm, "type": ty, "cls": c, "organization": "Plant & Equipment", "source": SRC}
                                    for n, nm, ty, c in EQUIPMENT])
    await db.items.insert_many([{"id": new_id(), "number": n, "description": d, "uom": u, "unit_cost": c, "category": cat, "source": SRC}
                                for n, d, u, c, cat in ITEMS])
    await db.hour_types.insert_many([{"id": new_id(), "resource_type": rt, "code": c, "name": nm, "requires_reason": rr, "expenditure_type": et, "order": i}
                                     for i, (rt, c, nm, rr, et, _, _) in enumerate(HOUR_TYPES)])
    await db.reason_codes.insert_many([{"id": new_id(), "code": c, "name": n, "resource_type": rt} for c, n, rt in REASONS])
    await db.budgets.insert_many([{"id": new_id(), "project_number": p, "task_number": t, "resource_type": rt, "item_number": it, "qty": q, "uom": u, "source": SRC}
                                  for p, t, rt, it, q, u in BUDGETS])
    rcs = []
    for g, base in GRADES.items():
        for rt, c, _, _, _, mult, prem in HOUR_TYPES:
            if rt == "labor":
                rcs.append({"id": new_id(), "resource_type": "labor", "key": g, "hour_type": c, "base_rate": base, "multiplier": mult, "premium": prem})
    for cls, rates in EQ_RATES.items():
        for c, r in rates.items():
            rcs.append({"id": new_id(), "resource_type": "equipment", "key": cls, "hour_type": c, "base_rate": r, "multiplier": 1.0, "premium": 0})
    for r in rcs:
        r["effective_from"] = "2026-01-01"
    await db.rate_cards.insert_many(rcs)

    today = date.today()
    first = today.replace(day=1)
    last = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    crew_a, crew_b = new_id(), new_id()
    await db.crews.insert_many([
        {"id": crew_a, "name": "Crew-A (Civil)", "project_number": "PRJ-1042", "foreman": "S. Das"},
        {"id": crew_b, "name": "Crew-B (MEP)", "project_number": "PRJ-1042", "foreman": "A. Patel"}])
    await db.plans.insert_many([
        {"id": new_id(), "kind": "crew", "status": "published", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "crew_id": crew_a,
         "shift": "Day Shift (06:00-14:00)", "start_date": first.isoformat(), "end_date": last.isoformat(), "created_by": "Sample data",
         "created_at": now_iso(), "published_at": now_iso(),
         "lines": [{"resource_type": "labor", "resource_number": "E-10021", "hours": {"REG": 8}},
                   {"resource_type": "labor", "resource_number": "E-10022", "hours": {"REG": 8, "OT": 1}},
                   {"resource_type": "labor", "resource_number": "E-10023", "hours": {"REG": 8}},
                   {"resource_type": "equipment", "resource_number": "EXC-014", "hours": {"REG": 6.5, "IDLE": 1, "MAINT": 0.5}}]},
        {"id": new_id(), "kind": "material", "status": "published", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3",
         "period_type": "monthly", "start_date": first.isoformat(), "end_date": last.isoformat(), "created_by": "Sample data", "created_at": now_iso(),
         "published_at": now_iso(), "lines": [{"item_number": "CEM-OPC53", "planned_qty": 400}, {"item_number": "REBAR-GR60-25MM", "planned_qty": 15}]}])

    past = (today - timedelta(days=20)).isoformat()
    by = "Sample data"
    crew = ["E-10021", "E-10022", "E-10023", "E-10024"]
    for proj, task, total in [("PRJ-1042", "Civil-WBS-3", 494), ("PRJ-1042", "MEP-WBS-7", 410), ("PRJ-1042", "Struct-WBS-2", 300),
                              ("PRJ-2088", "Mech-WBS-1", 640)]:
        await _sample_tx("labor", proj, task, past, [{"resource_number": e, "hour_type": "REG", "hours": total / 4} for e in crew], "approved", by)
    for proj, task, eqn, hrs in [("PRJ-1042", "Civil-WBS-3", "EXC-014", 39), ("PRJ-1042", "Struct-WBS-2", "CRN-022", 70), ("PRJ-2088", "Mech-WBS-1", "CRN-022", 96)]:
        await _sample_tx("equipment", proj, task, past, [{"resource_number": eqn, "hour_type": "REG", "hours": hrs}], "approved", by)
    await _sample_tx("material", "PRJ-1042", "Civil-WBS-3", past, [{"item_number": "CEM-OPC53", "qty_issued": 3220, "qty_wasted": 0, "qty_returned": 0},
                                                                     {"item_number": "REBAR-GR60-25MM", "qty_issued": 70, "qty_wasted": 0, "qty_returned": 0}], "approved", by)
    await _sample_tx("material", "PRJ-1042", "Struct-WBS-2", past, [{"item_number": "RMC-M30", "qty_issued": 610, "qty_wasted": 0, "qty_returned": 0}], "approved", by)

    y = (today - timedelta(days=1)).isoformat()
    await _sample_tx("labor", "PRJ-1042", "Civil-WBS-3", y, [{"resource_number": "E-10021", "hour_type": "REG", "hours": 8},
                                                           {"resource_number": "E-10022", "hour_type": "REG", "hours": 10}], "pending_step1", "R. Naidu (Foreman)")
    await _sample_tx("equipment", "PRJ-1042", "Civil-WBS-3", y, [{"resource_number": "EXC-014", "hour_type": "REG", "hours": 6.5},
                                                               {"resource_number": "EXC-014", "hour_type": "IDLE", "hours": 1},
                                                               {"resource_number": "EXC-014", "hour_type": "DOWN", "hours": 0.5, "reason_code": "BRK-HYD"}],
                     "pending_step1", "R. Naidu (Foreman)")
    await _sample_tx("material", "PRJ-1042", "Civil-WBS-3", y, [{"item_number": "CEM-OPC53", "qty_issued": 120, "qty_wasted": 6, "qty_returned": 4,
                                                               "reason_code": "WASTE-DMG"}], "pending_step1", "S. Iyer (Store Mgr)")
    await migrate()
