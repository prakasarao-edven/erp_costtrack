"""Costing + validation + approval routing engine shared by labor, equipment and material."""
try:
    from backend.core import db
except ModuleNotFoundError:
    from core import db

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


async def get_settings() -> dict:
    s = await db.settings.find_one({"id": "global"}, {"_id": 0})
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
        rmap = {(r["key"], r["hour_type"]): r for r in await db.rate_cards.find({"resource_type": t}, {"_id": 0}).to_list(5000)}
        coll = db.employees if t == "labor" else db.equipment
        res = {r["number"]: r for r in await coll.find({}, {"_id": 0}).to_list(10000)}
        for ln in tx["lines"]:
            r = res.get(ln["resource_number"], {})
            ln["resource_name"] = r.get("name", ln.get("resource_name", ln["resource_number"]))
            key = r.get("grade") if t == "labor" else r.get("cls")
            rc = rmap.get((key, ln["hour_type"]))
            rate = round(rc["base_rate"] * rc.get("multiplier", 1) + rc.get("premium", 0), 2) if rc else 0.0
            ln["present"] = ln.get("present", True)
            hrs = float(ln.get("hours") or 0) if ln["present"] else 0.0
            ln.update(hours=hrs, rate=rate, rate_key=key, rate_missing=rc is None, cost=round(hrs * rate, 2))
            tc += hrs
            cost += ln["cost"]
        tx["totals"] = {"qty": round(tc, 2), "uom": "hrs", "cost": round(cost, 2)}
    else:
        items = {i["number"]: i for i in await db.items.find({}, {"_id": 0}).to_list(10000)}
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


async def _active_txs(tx: dict, extra: dict | None = None) -> list[dict]:
    q = {"type": tx["type"], "project_number": tx["project_number"], "task_number": tx["task_number"],
         "status": {"$nin": ["draft", "rejected"]}, "id": {"$ne": tx.get("id")}, **(extra or {})}
    return await db.transactions.find(q, {"_id": 0, "lines": 1, "totals": 1}).to_list(10000)


async def _budget_check(tx: dict, s: dict) -> dict:
    t, warn = tx["type"], s.get("budget_warning_pct", 90)
    checks = []
    prior_docs = await _active_txs(tx)
    if t in ("labor", "equipment"):
        b = await db.budgets.find_one({"project_number": tx["project_number"], "task_number": tx["task_number"], "resource_type": t}, {"_id": 0})
        prior = sum(d["totals"]["qty"] for d in prior_docs if d.get("totals"))
        if b:
            after = prior + tx["totals"]["qty"]
            pct = after / b["qty"] * 100 if b["qty"] else 0
            checks.append({"label": f"{t.title()} hours", "budget": b["qty"], "prior": round(prior, 2), "this": tx["totals"]["qty"],
                           "after": round(after, 2), "pct": round(pct, 1), "uom": "hrs", "status": _budget_status(pct, warn)})
    else:
        for item in {ln["item_number"] for ln in tx["lines"]}:
            b = await db.budgets.find_one({"project_number": tx["project_number"], "task_number": tx["task_number"],
                                           "resource_type": "material", "item_number": item}, {"_id": 0})
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
        plan = await db.plans.find_one({"kind": "material", "status": "published", "project_number": tx["project_number"],
                                        "task_number": tx["task_number"], "start_date": {"$lte": tx["date"]}, "end_date": {"$gte": tx["date"]}}, {"_id": 0})
        prior_docs = await _active_txs(tx, {"date": {"$gte": plan["start_date"], "$lte": plan["end_date"]}}) if plan else []
        planned = {ln["item_number"]: ln["planned_qty"] for ln in (plan or {}).get("lines", [])}
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
    return {"pct": tol, "breach": breach, "behavior": s["tolerance_behavior"],
            "blocked": breach and s["tolerance_behavior"] == "stop"}


async def validate(tx: dict) -> dict:
    s = await get_settings()
    await price(tx)
    t = tx["type"]
    budget = await _budget_check(tx, s)
    tolerance = await _tolerance_check(tx, s)
    errors, reasons = [], []
    if t == "equipment":
        rr = {h["code"] for h in await db.hour_types.find({"resource_type": "equipment", "requires_reason": True}, {"_id": 0}).to_list(50)}
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
    if not tx["lines"]:
        errors.append("Add at least one line")
    unmodified = tx.get("mode") == "plan" and bool(tx["lines"]) and all(
        ln.get("plan_line") and ln["present"] and ln["hours"] == ln.get("planned_hours") for ln in tx["lines"])
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
    hts = {(h["resource_type"], h["code"]): h for h in await db.hour_types.find({}, {"_id": 0}).to_list(100)}
    eq = {e["number"]: e for e in await db.equipment.find({}, {"_id": 0}).to_list(10000)}
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
    return out
