"""Costing + validation + approval routing engine shared by labor, equipment and material."""
from sqlalchemy import select, or_
try:
    from backend.core import db, tables
except ModuleNotFoundError:
    from core import db, tables

DEFAULT_SETTINGS = {
    "id": "global",
    "rate_source": {"labor": "app", "equipment": "app"},
    "budget_behavior": "warning",
    "budget_warning_pct": 90,
    "tolerance_pct": {"labor": 15, "equipment": 15, "material": 10},
    "tolerance_behavior": "warning",
    "auto_approval": "step1",
    "special_hour_types": ["DOWN", "MAINT"],
    "special_on_wastage": True,
    "special_approver_role": "cost_controller",
    "currency": "USD",
    "oracle": {
        "transaction_source": "CostBridge",
        "document": {"labor": "Time Cards", "equipment": "Equipment Usage", "material": "Material Issues"},
        "document_entry": {"labor": "Labor", "equipment": "Equipment", "material": "Material"},
        "labor_uom": "Hours", "equipment_uom": "Hours",
    },
}

PENDING = ["pending_step1", "pending_special", "pending_step2"]


async def plan_rows(plan: dict, rtype: str) -> list[dict]:
    """Expected timesheet rows (one per resource x hour type) from a published crew plan."""
    order = [h["code"] for h in await db.all(select(tables.hour_types).where(tables.hour_types.c['resource_type'] == rtype).order_by(tables.hour_types.c['order'].asc()).limit(50))]
    rows = []
    for ln in plan["lines"]:
        if ln.get("resource_type") != rtype:
            continue
        for code in order:
            h = ln["hours"].get(code)
            if h:
                rows.append({"resource_number": ln["resource_number"], "hour_type": code, "planned_hours": h, "hours": h,
                             "present": True, "plan_line": True})
    return rows


async def _apply_plan(tx: dict) -> bool:
    """Server-side plan comparison: planned hours come from the published plan, never the client. Returns unmodified flag."""
    for ln in tx["lines"]:
        ln["plan_line"], ln["planned_hours"] = False, None
    if tx["type"] == "material" or tx.get("mode") != "plan" or not tx.get("plan_id"):
        return False
    plan = await db.one(select(tables.plans).where(tables.plans.c['id'] == tx['plan_id'], tables.plans.c['kind'] == 'crew', tables.plans.c['status'] == 'published', tables.plans.c['project_number'] == tx['project_number'], tables.plans.c['task_number'] == tx['task_number'], tables.plans.c['crew_id'] == tx.get('crew_id'), tables.plans.c['start_date'] <= tx['date'], tables.plans.c['end_date'] >= tx['date']))
    if not plan:
        return False
    expected = {(r["resource_number"], r["hour_type"]): r["planned_hours"] for r in await plan_rows(plan, tx["type"])}
    seen = set()
    for ln in tx["lines"]:
        k = (ln["resource_number"], ln["hour_type"])
        if k in expected and k not in seen:
            ln["plan_line"], ln["planned_hours"] = True, expected[k]
            seen.add(k)
    return (seen == set(expected) and len(tx["lines"]) == len(expected)
            and all(ln["present"] and ln["hours"] == ln["planned_hours"] for ln in tx["lines"]))


async def get_settings() -> dict:
    s = await db.one(select(tables.settings).where(tables.settings.c['id'] == 'global'))
    return s or DEFAULT_SETTINGS


def step_roles(status: str, s: dict) -> list[str]:
    return {
        "pending_step1": ["project_manager", "admin"],
        "pending_special": [s.get("special_approver_role", "cost_controller"), "admin"],
        "pending_step2": ["cost_controller", "admin"],
    }.get(status, [])


async def price(tx: dict) -> dict:
    t = tx["type"]
    tc = cost = 0.0
    if t in ("labor", "equipment"):
        rmap = {}
        for r in await db.all(select(tables.rate_cards).where(tables.rate_cards.c['resource_type'] == t, tables.rate_cards.c['effective_from'] <= tx['date']).limit(5000)):
            if r.get("effective_to") and r["effective_to"] < tx["date"]:
                continue
            k = (r["key"], r["hour_type"])
            if k not in rmap or r["effective_from"] > rmap[k]["effective_from"]:
                rmap[k] = r
        coll = tables.employees if t == "labor" else tables.equipment
        res = {r["number"]: r for r in await db.all(select(coll).limit(20000))}
        for ln in tx["lines"]:
            r = res.get(ln["resource_number"], {})
            ln["resource_name"] = r.get("name", ln.get("resource_name", ln["resource_number"]))
            key = r.get("grade") if t == "labor" else r.get("cls")
            # rate lookup order: named resource override -> grade/class
            rc = rmap.get((f"RES:{ln['resource_number']}", ln["hour_type"])) or rmap.get((key, ln["hour_type"]))
            rate = round(rc["base_rate"] * rc.get("multiplier", 1) + rc.get("premium", 0), 2) if rc else 0.0
            ln["present"] = ln.get("present", True)
            hrs = float(ln.get("hours") or 0) if ln["present"] else 0.0
            ln.update(hours=hrs, rate=rate, rate_key=key, rate_missing=rc is None, cost=round(hrs * rate, 2))
            tc += hrs
            cost += ln["cost"]
        bonus = round(sum(float(b.get("amount") or 0) for b in tx.get("bonuses", [])), 2)
        tx["totals"] = {"qty": round(tc, 2), "uom": "hrs", "cost": round(cost + bonus, 2), "bonus": bonus}
    else:
        items = {i["number"]: i for i in await db.all(select(tables.items).limit(10000))}
        uoms = set()
        for ln in tx["lines"]:
            it = items.get(ln["item_number"], {})
            issued, wasted, returned = (float(ln.get(k) or 0) for k in ("qty_issued", "qty_wasted", "qty_returned"))
            consumed = max(issued - returned, 0)
            unit = float(it.get("unit_cost", 0))
            ln.update(item_name=it.get("description", ln["item_number"]), uom=it.get("uom", ""), unit_cost=unit,
                      qty_issued=issued, qty_wasted=wasted, qty_returned=returned, qty_consumed=consumed,
                      cost=round(consumed * unit, 2), wastage_cost=round(wasted * unit, 2))
            uoms.add(ln["uom"])
            tc += consumed
            cost += ln["cost"]
        tx["totals"] = {"qty": round(tc, 2), "uom": uoms.pop() if len(uoms) == 1 else "mixed", "cost": round(cost, 2)}
    return tx


def _budget_status(pct: float, warn: float) -> str:
    return "exceeded" if pct > 100 else "warning" if pct >= warn else "ok"


async def _active_txs(tx: dict, extra=()) -> list[dict]:
    q = [tables.transactions.c.type == tx["type"], tables.transactions.c.project_number == tx["project_number"],
         tables.transactions.c.task_number == tx["task_number"], tables.transactions.c.status.not_in(["draft", "rejected"]),
         tables.transactions.c.id.is_distinct_from(tx.get("id")), *extra]
    return await db.all(select(tables.transactions).where(*q).limit(10000))


async def _budget_check(tx: dict, s: dict) -> dict:
    t, warn = tx["type"], s.get("budget_warning_pct", 90)
    checks = []
    prior_docs = await _active_txs(tx)
    if t in ("labor", "equipment"):
        b = await db.one(select(tables.budgets).where(tables.budgets.c['project_number'] == tx['project_number'], tables.budgets.c['task_number'] == tx['task_number'], tables.budgets.c['resource_type'] == t))
        prior = sum(d["totals"]["qty"] for d in prior_docs if d.get("totals"))
        if b:
            after = prior + tx["totals"]["qty"]
            pct = after / b["qty"] * 100 if b["qty"] else 0
            checks.append({"label": f"{t.title()} hours", "budget": b["qty"], "prior": round(prior, 2), "this": tx["totals"]["qty"],
                           "after": round(after, 2), "pct": round(pct, 1), "uom": "hrs", "status": _budget_status(pct, warn)})
    else:
        for item in {ln["item_number"] for ln in tx["lines"]}:
            b = await db.one(select(tables.budgets).where(tables.budgets.c['project_number'] == tx['project_number'], tables.budgets.c['task_number'] == tx['task_number'], tables.budgets.c['resource_type'] == 'material', tables.budgets.c['item_number'] == item))
            if not b:
                continue
            prior = sum(ln.get("qty_consumed", 0) for d in prior_docs for ln in d["lines"] if ln["item_number"] == item)
            this = sum(ln["qty_consumed"] for ln in tx["lines"] if ln["item_number"] == item)
            after = prior + this
            pct = after / b["qty"] * 100 if b["qty"] else 0
            checks.append({"label": item, "budget": b["qty"], "prior": round(prior, 2), "this": round(this, 2), "after": round(after, 2),
                           "pct": round(pct, 1), "uom": b.get("uom", ""), "status": _budget_status(pct, warn)})
    order = ["ok", "warning", "exceeded"]
    status = max((c["status"] for c in checks), key=order.index) if checks else "no_budget"
    return {"checks": checks, "status": status, "behavior": s["budget_behavior"],
            "blocked": status == "exceeded" and s["budget_behavior"] == "stop"}


async def _tolerance_check(tx: dict, s: dict) -> dict:
    t = tx["type"]
    tol = s["tolerance_pct"].get(t, 10)
    breach = False
    if t in ("labor", "equipment"):
        for ln in tx["lines"]:
            p = ln.get("planned_hours")
            if p is None:
                ln["tolerance_status"], ln["vs_plan_pct"] = "unplanned", None
            elif not ln["present"]:
                ln["tolerance_status"], ln["vs_plan_pct"] = "absent", None
            else:
                dev = (ln["hours"] - p) / p * 100 if p else (100.0 if ln["hours"] > 0 else 0.0)
                ln["vs_plan_pct"] = round(dev, 1)
                ln["tolerance_status"] = "matches" if ln["hours"] == p else "within" if abs(dev) <= tol else "breach"
                breach = breach or ln["tolerance_status"] == "breach"
    else:
        plan = await db.one(select(tables.plans).where(tables.plans.c['kind'] == 'material', tables.plans.c['status'] == 'published', tables.plans.c['project_number'] == tx['project_number'], tables.plans.c['task_number'] == tx['task_number'], tables.plans.c['start_date'] <= tx['date'], tables.plans.c['end_date'] >= tx['date']))
        prior_docs = await _active_txs(tx, [tables.transactions.c.date >= plan["start_date"],
                                          tables.transactions.c.date <= plan["end_date"]]) if plan else []
        planned = {ln["item_number"]: ln["planned_qty"] for ln in (plan or {}).get("lines", []) if ln.get("planned_qty")}
        for ln in tx["lines"]:
            p = planned.get(ln["item_number"])
            if p is None:
                ln.update(planned_qty=None, vs_plan_pct=None, tolerance_status="unplanned")
                continue
            prior = sum(x.get("qty_consumed", 0) for d in prior_docs for x in d["lines"] if x["item_number"] == ln["item_number"])
            used = prior + ln["qty_consumed"]
            dev = (used - p) / p * 100 if p else 100.0
            ln.update(planned_qty=p, period_used=round(used, 2), vs_plan_pct=round(dev, 1),
                      tolerance_status="breach" if dev > tol else "within")
            breach = breach or ln["tolerance_status"] == "breach"
        tx["plan_id"] = (plan or {}).get("id")
    has_plan = any(ln.get("tolerance_status") not in (None, "unplanned") for ln in tx["lines"])
    return {"pct": tol, "breach": breach, "has_plan": has_plan, "behavior": s["tolerance_behavior"],
            "blocked": breach and s["tolerance_behavior"] == "stop"}


async def validate(tx: dict) -> dict:
    s = await get_settings()
    await price(tx)
    unmodified = await _apply_plan(tx)
    t = tx["type"]
    budget = await _budget_check(tx, s)
    tolerance = await _tolerance_check(tx, s)
    errors, reasons = [], []
    if t == "equipment":
        rr = {h["code"] for h in await db.all(select(tables.hour_types).where(tables.hour_types.c['resource_type'] == 'equipment', tables.hour_types.c['requires_reason'].is_(True)).limit(50))}
        for ln in tx["lines"]:
            if ln["hour_type"] in rr and ln["hours"] > 0 and not ln.get("reason_code"):
                errors.append(f"{ln['resource_number']} {ln['hour_type']}: reason code is required")
            if ln["hour_type"] in s["special_hour_types"] and ln["hours"] > 0:
                reasons.append(f"{ln['resource_number']} {ln['hour_type']} {ln['hours']}h ({ln.get('reason_code') or 'no reason'})")
    if t == "material":
        for ln in tx["lines"]:
            if ln["qty_issued"] <= 0:
                errors.append(f"{ln['item_number']}: quantity issued must be greater than 0")
            if ln["qty_wasted"] + ln["qty_returned"] > ln["qty_issued"]:
                errors.append(f"{ln['item_number']}: wasted + returned cannot exceed issued")
            if ln["qty_wasted"] > 0:
                if not ln.get("reason_code"):
                    errors.append(f"{ln['item_number']}: reason code is required for wastage")
                if s.get("special_on_wastage"):
                    reasons.append(f"{ln['item_number']} wastage {ln['qty_wasted']} {ln['uom']} ({ln.get('reason_code') or 'no reason'})")
    if t in ("labor", "equipment"):
        per = {}
        for ln in tx["lines"]:
            per[ln["resource_number"]] = per.get(ln["resource_number"], 0) + ln["hours"]
        errors += [f"{r}: {h}h in one day exceeds 24h" for r, h in per.items() if h > 24]
    if t == "labor":
        brs = {b["bonus_type"]: b for b in await db.all(select(tables.bonus_rates).limit(100))}
        for b in tx.get("bonuses", []):
            br = brs.get(b["bonus_type"])
            hrs = sum(ln["hours"] for ln in tx["lines"] if ln["resource_number"] == b["resource_number"])
            cap = (br["amount"] * hrs if br["basis"] == "per_hour" else br["amount"]) if br else 0
            if b["amount"] > cap + 0.005:
                reasons.append(f"{b['resource_number']} {b['bonus_type']} bonus ${b['amount']} above rate card (${round(cap, 2)})")
    if not tx["lines"]:
        errors.append("Add at least one line")
    v = {"budget": budget, "tolerance": tolerance, "special": {"required": bool(reasons), "reasons": reasons},
         "errors": errors, "unmodified_from_plan": unmodified,
         "blocked": bool(errors) or budget["blocked"] or tolerance["blocked"]}
    tx["validation"] = v
    return v


def route_on_submit(tx: dict, s: dict) -> tuple[str, str]:
    v = tx["validation"]
    clean = v["unmodified_from_plan"] and not v["tolerance"]["breach"] and not v["special"]["required"] and v["budget"]["status"] in ("ok", "no_budget")
    if clean and s["auto_approval"] == "full":
        return "approved", "Auto-approved: unmodified from plan (full skip per Setup)"
    if clean and s["auto_approval"] == "step1":
        return "pending_step2", "Step 1 auto-approved: unmodified from plan"
    return "pending_step1", "Submitted for Step 1 approval"


def next_status(tx: dict) -> str:
    st = tx["status"]
    if st == "pending_step1":
        return "pending_special" if tx["validation"]["special"]["required"] else "pending_step2"
    if st == "pending_special":
        return "pending_step2"
    return "approved"


async def build_cost_transactions(tx: dict, s: dict) -> list[dict]:
    o = s["oracle"]
    t = tx["type"]
    hts = {(h["resource_type"], h["code"]): h for h in await db.all(select(tables.hour_types).limit(100))}
    eq = {e["number"]: e for e in await db.all(select(tables.equipment).limit(10000))}
    out = []
    for i, ln in enumerate(tx["lines"]):
        ref = f"CB-{tx['ref']}-{i + 1}"
        base = {"TransactionSource": o["transaction_source"], "Document": o["document"][t], "DocumentEntry": o["document_entry"][t],
                "ProjectNumber": tx["project_number"], "TaskNumber": tx["task_number"], "ExpenditureItemDate": tx["date"],
                "TransactionCurrency": s.get("currency", "USD"), "OriginalTransactionReference": ref}
        if t in ("labor", "equipment"):
            if ln["hours"] <= 0:
                continue
            ht = hts.get((t, ln["hour_type"]), {})
            p = {**base, "ExpenditureType": ht.get("expenditure_type", ln["hour_type"]), "Quantity": ln["hours"],
                 "UnitOfMeasure": o["labor_uom"] if t == "labor" else o["equipment_uom"]}
            if t == "labor":
                p["PersonNumber"] = ln["resource_number"]
            else:
                p["NonlaborResource"] = ln["resource_number"]
                p["NonlaborResourceOrganization"] = eq.get(ln["resource_number"], {}).get("organization", "")
            if s["rate_source"].get(t) == "app":
                p["RawCostInTransactionCurrency"] = ln["cost"]
        else:
            if ln["qty_consumed"] <= 0:
                continue
            p = {**base, "ExpenditureType": "Material", "InventoryItemNumber": ln["item_number"], "Quantity": ln["qty_consumed"],
                 "UnitOfMeasure": ln["uom"], "RawCostInTransactionCurrency": ln["cost"]}
        out.append({"ref": ref, "kind": "project_cost", "payload": p, "amount": ln["cost"]})
        if t == "material" and (ln["qty_returned"] > 0 or ln["qty_wasted"] > 0):
            out.append({"ref": f"{ref}-RTS", "kind": "return_to_store", "amount": round(ln["qty_returned"] * ln["unit_cost"], 2),
                        "payload": {"ItemNumber": ln["item_number"], "ReturnedQuantity": ln["qty_returned"], "WastedQuantity": ln["qty_wasted"],
                                    "UnitOfMeasure": ln["uom"], "ProjectNumber": tx["project_number"], "TaskNumber": tx["task_number"],
                                    "TransactionDate": tx["date"], "ReasonCode": ln.get("reason_code", "")}})
    for j, b in enumerate(tx.get("bonuses", [])):
        if b["amount"] > 0:
            ref = f"CB-{tx['ref']}-B{j + 1}"
            out.append({"ref": ref, "kind": "project_cost", "amount": b["amount"], "payload": {
                "TransactionSource": o["transaction_source"], "Document": o["document"][t], "DocumentEntry": o["document_entry"][t],
                "ProjectNumber": tx["project_number"], "TaskNumber": tx["task_number"], "ExpenditureItemDate": tx["date"],
                "ExpenditureType": f"Labor - Bonus ({b['bonus_type']})", "PersonNumber": b["resource_number"], "Quantity": 1,
                "RawCostInTransactionCurrency": b["amount"], "TransactionCurrency": s.get("currency", "USD"), "OriginalTransactionReference": ref}})
    return out
