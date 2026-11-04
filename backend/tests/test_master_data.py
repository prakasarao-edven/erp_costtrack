# Iteration 3: Master data (source modes, ERP lock, local CRUD, deactivate, bulk), labor bonuses, RES rate override
import time
import uuid

import pytest
from pymongo import MongoClient

mdb = MongoClient("mongodb://localhost:27017")["test_database"]
SUF = uuid.uuid4().hex[:6].upper()
TODAY = time.strftime("%Y-%m-%d")
CREATED = []  # (entity, id)


@pytest.fixture(scope="module", autouse=True)
def cleanup(c):
    # restore the modes that were set before the run (never force hybrid: the owner may have chosen ERP mode)
    orig = {e["entity"]: e["mode"] for e in c["admin"].get("/md/summary").json()["entities"]}
    yield
    a = c["admin"]
    a.put("/md/source-modes", {"modes": orig})
    for ent, rid in reversed(CREATED):
        if ent in ("rate_cards", "transactions"):
            mdb[ent].delete_one({"id": rid})
            if ent == "transactions":
                mdb.cost_transactions.delete_many({"transaction_id": rid})
        else:
            a.delete(f"/md/{ent}/{rid}")


# --- summary & source modes
def test_summary(c):
    r = c["admin"].get("/md/summary")
    assert r.status_code == 200
    ents = {e["entity"]: e for e in r.json()["entities"]}
    assert set(ents) == {"projects", "tasks", "employees", "equipment", "items", "stores", "lookups"}
    assert ents["projects"]["erp"] >= 270 and ents["employees"]["erp"] >= 6000


def test_source_mode_erp_blocks_create(c):
    a = c["admin"]
    orig = {e["entity"]: e["mode"] for e in a.get("/md/summary").json()["entities"]}["stores"]
    try:
        r = a.put("/md/source-modes", {"modes": {"stores": "erp"}})
        assert r.status_code == 200 and r.json()["stores"] == "erp"
        r = a.post("/md/stores", {"code": f"TEST-ST{SUF}", "name": "x", "store_type": "Site Store"})
        assert r.status_code == 400, r.text
        r = a.post("/md/stores/bulk", {"rows": [{"code": f"TEST-ST{SUF}", "name": "x", "store_type": "Site Store"}]})
        assert r.json()["counts"]["error"] == 1
    finally:
        assert a.put("/md/source-modes", {"modes": {"stores": orig}}).json()["stores"] == orig


def test_source_mode_non_admin_forbidden(c):
    assert c["master_data_admin"].put("/md/source-modes", {"modes": {"stores": "erp"}}).status_code == 403
    assert c["foreman"].post("/md/stores", {"code": "X", "name": "x", "store_type": "Site Store"}).status_code == 403


# --- local CRUD
def test_create_local_project_and_task(c):
    a = c["master_data_admin"]
    r = a.post("/md/projects", {"number": f"test-p{SUF}", "name": "TEST project", "status": "Active"})
    assert r.status_code == 200, r.text
    p = r.json()
    CREATED.append(("projects", p["id"]))
    assert p["number"] == f"TEST-P{SUF}" and p["source"] == "local"
    assert a.post("/md/projects", {"number": f"TEST-P{SUF}", "name": "dup"}).status_code == 400
    assert a.post("/md/projects", {"number": "00009805", "name": "dup erp"}).status_code == 400
    assert a.post("/md/projects", {"number": "BAD KEY!!", "name": "x"}).status_code == 400
    r = a.post("/md/tasks", {"project_number": "NOPE-XYZ", "number": "T1", "name": "x"})
    assert r.status_code == 400 and "Unknown project" in r.text
    r = a.post("/md/tasks", {"project_number": f"TEST-P{SUF}", "number": "t-1", "name": "TEST task", "status": "Active"})
    assert r.status_code == 200, r.text
    CREATED.append(("tasks", r.json()["id"]))
    lst = a.get("/md/projects", params={"q": f"TEST-P{SUF}"}).json()
    assert lst["total"] == 1 and lst["rows"][0]["name"] == "TEST project"
    # local edit of any field
    r = a.put(f"/md/projects/{p['id']}", {"name": "TEST renamed"})
    assert r.status_code == 200 and r.json()["name"] == "TEST renamed"


def test_erp_record_lock(c):
    a = c["admin"]
    p = a.get("/md/projects", params={"q": "00009805"}).json()["rows"][0]
    assert p["source"] == "oracle"
    r = a.put(f"/md/projects/{p['id']}", {"name": "hacked"})
    assert r.status_code == 400
    orig = p.get("site")
    try:
        r = a.put(f"/md/projects/{p['id']}", {"site": "TEST site"})
        assert r.status_code == 200 and r.json()["site"] == "TEST site"
        assert r.json()["name"] == p["name"]
    finally:
        mdb.projects.update_one({"id": p["id"]}, {"$set": {"site": orig}} if orig is not None else {"$unset": {"site": 1}})
    e = a.get("/md/employees", params={"source": "erp"}).json()["rows"][0]
    try:
        r = a.put(f"/md/employees/{e['id']}", {"badge_id": "TEST-B1"})
        assert r.status_code == 200 and r.json()["badge_id"] == "TEST-B1"
        assert a.put(f"/md/employees/{e['id']}", {"grade": "Foreman-XX"}).status_code == 400
    finally:
        mdb.employees.update_one({"id": e["id"]}, {"$set": {"badge_id": e["badge_id"]}} if "badge_id" in e else {"$unset": {"badge_id": 1}})


def test_delete_rules(c):
    a = c["admin"]
    erp = a.get("/md/projects", params={"q": "00009805"}).json()["rows"][0]
    assert a.delete(f"/md/projects/{erp['id']}").status_code == 409
    emp = a.get("/md/employees", params={"q": "E-10021"}).json()["rows"][0]
    assert a.delete(f"/md/employees/{emp['id']}").status_code == 409


def test_inactive_employee_hidden_and_rejected(c):
    a = c["admin"]
    if {e["entity"]: e["mode"] for e in a.get("/md/summary").json()["entities"]}["employees"] == "erp":
        pytest.skip("employees source mode is ERP (owner setting) - local create blocked")
    r = a.post("/md/employees", {"number": f"TEST-E{SUF}", "name": "TEST emp", "grade": "Skilled"})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    CREATED.append(("employees", eid))
    nums = lambda: {e["number"] for e in a.get("/master").json()["employees"]}
    assert f"TEST-E{SUF}" in nums()
    body = {"type": "labor", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "date": TODAY,
            "lines": [{"resource_number": f"TEST-E{SUF}", "hour_type": "REG", "hours": 8}]}
    assert a.post("/transactions/preview", body).status_code == 200
    assert a.post(f"/md/employees/{eid}/status", {"status": "Inactive"}).status_code == 200
    assert f"TEST-E{SUF}" not in nums()
    r = a.post("/transactions/preview", body)
    assert r.status_code == 400 and "inactive" in r.text.lower()
    assert a.post(f"/md/employees/{eid}/status", {"status": "Active"}).status_code == 200
    assert f"TEST-E{SUF}" in nums()


# --- bulk upload
def test_bulk_validate_commit(c):
    a = c["admin"]
    rows = [{"code": f"TEST-B{SUF}A", "name": "TEST bulk A", "store_type": "Site Store"},
            {"code": f"TEST-B{SUF}A", "name": "dup", "store_type": "Site Store"},
            {"code": f"TEST-B{SUF}B", "store_type": "Site Store"},
            {"code": f"TEST-B{SUF}C", "name": "TEST bulk C", "store_type": "Laydown Yard"}]
    v = a.post("/md/stores/bulk", {"rows": rows}).json()
    assert v["counts"] == {"new": 2, "update": 0, "error": 2}, v
    errs = [r["error"] for r in v["results"] if r["result"] == "error"]
    assert any("Duplicate" in e for e in errs) and any("Required" in e for e in errs)
    assert a.get("/md/stores", params={"q": f"TEST-B{SUF}"}).json()["total"] == 0
    cm = a.post("/md/stores/bulk", {"rows": rows, "commit": True}).json()
    assert cm["committed"] == 2
    got = a.get("/md/stores", params={"q": f"TEST-B{SUF}"}).json()["rows"]
    CREATED.extend(("stores", g["id"]) for g in got)
    assert len(got) == 2
    # second upload -> update
    v2 = a.post("/md/stores/bulk", {"rows": [{"code": f"TEST-B{SUF}C", "name": "TEST C2", "store_type": "Laydown Yard"}], "commit": True}).json()
    assert v2["counts"]["update"] == 1
    assert a.get("/md/stores", params={"q": f"TEST-B{SUF}C"}).json()["rows"][0]["name"] == "TEST C2"


def test_bulk_erp_rows(c):
    a = c["admin"]
    v = a.post("/md/projects/bulk", {"rows": [{"number": "00009805", "name": "changed via bulk"}]}).json()
    assert v["counts"]["error"] == 1, v
    p = a.get("/md/projects", params={"q": "00009805"}).json()["rows"][0]
    v = a.post("/md/projects/bulk", {"rows": [{"number": "00009805", "name": p["name"], "site": p.get("site", "")}]}).json()
    assert v["counts"]["update"] == 1, v


# --- labor bonuses, RES override, foreman hiding
def test_foreman_bonus_amount_visible(c):
    # iteration 4: bonus amounts are sent to foreman for pre-fill (labor rates are still redacted)
    br = c["foreman"].get("/master").json()["bonus_rates"]
    assert br and all("amount" in b for b in br)


def test_bonus_in_totals_and_cost_lines(c):
    a = c["admin"]
    body = {"type": "labor", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "date": TODAY, "action": "submit",
            "notes": "TEST_bonus", "lines": [{"resource_number": "E-10021", "hour_type": "REG", "hours": 1}],
            "bonuses": [{"resource_number": "E-10021", "bonus_type": "Safety", "amount": 10}]}
    pv = a.post("/transactions/preview", body).json()
    assert pv["totals"]["bonus"] == 10
    assert pv["totals"]["cost"] == round(pv["lines"][0]["cost"] + 10, 2)
    r = a.post("/transactions", body)
    assert r.status_code == 200, r.text
    tx = r.json()
    CREATED.append(("transactions", tx["id"]))
    for _ in range(4):
        if tx["status"] == "approved":
            break
        tx = a.post(f"/transactions/{tx['id']}/approve", {"comment": "TEST"}).json()
    assert tx["status"] == "approved"
    cts = list(mdb.cost_transactions.find({"transaction_id": tx["id"]}, {"_id": 0}))
    b = [x for x in cts if x["ref"].endswith("-B1")]
    assert len(b) == 1 and b[0]["amount"] == 10 and "Bonus" in b[0]["payload"]["ExpenditureType"]


def test_res_rate_override(c):
    a = c["admin"]
    body = {"type": "labor", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "date": TODAY,
            "lines": [{"resource_number": "E-10021", "hour_type": "REG", "hours": 2}, {"resource_number": "E-10022", "hour_type": "REG", "hours": 2}]}
    before = a.post("/transactions/preview", body).json()["lines"]
    r = a.post("/rate-cards", {"resource_type": "labor", "key": "RES:E-10021", "hour_type": "REG", "base_rate": 77.77, "effective_from": "2025-01-01"})
    assert r.status_code == 200, r.text
    CREATED.append(("rate_cards", r.json()["id"]))
    after = a.post("/transactions/preview", body).json()["lines"]
    assert after[0]["rate"] == 77.77 and after[0]["cost"] == 155.54
    assert after[1]["rate"] == before[1]["rate"]


def test_weekend_holiday_rates_present(c):
    rc = c["admin"].get("/rate-cards").json()
    hts = {r["hour_type"] for r in rc if r["resource_type"] == "labor"}
    assert {"WKD", "HOL"} <= hts


def test_bonus_rate_edit_restore(c):
    a = c["admin"]
    b = next(x for x in a.get("/master").json()["bonus_rates"] if x["bonus_type"] == "Safety")
    payload = {k: b[k] for k in ("bonus_type", "basis", "amount", "effective_from")}
    try:
        r = a.put(f"/bonus-rates/{b['id']}", {**payload, "amount": 11})
        assert r.status_code == 200 and r.json()["amount"] == 11
    finally:
        assert a.put(f"/bonus-rates/{b['id']}", payload).json()["amount"] == b["amount"]


def test_equipment_down_requires_reason(c):
    a = c["admin"]
    eq = a.get("/master").json()["equipment"][0]["number"]
    body = {"type": "equipment", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "date": TODAY,
            "lines": [{"resource_number": eq, "hour_type": "DOWN", "hours": 2}]}
    v = a.post("/transactions/preview", body).json()["validation"]
    assert any("reason code is required" in e for e in v["errors"])
