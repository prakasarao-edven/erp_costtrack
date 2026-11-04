# Iteration 4: retest of iteration_3 fixes - bonus validation, foreman redaction, md delete/status rules, lookup order, plan dates
import time
import uuid

import pytest
from pymongo import MongoClient

mdb = MongoClient("mongodb://localhost:27017")["test_database"]
SUF = uuid.uuid4().hex[:6].upper()
TODAY = time.strftime("%Y-%m-%d")
CREATED = []  # (entity, id)


def body(bonuses=None, lines=None, **kw):
    b = {"type": "labor", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "date": TODAY, "notes": "TEST_iter4",
         "lines": lines or [{"resource_number": "E-10021", "hour_type": "REG", "hours": 8},
                            {"resource_number": "E-10021", "hour_type": "OT", "hours": 1}],
         "bonuses": bonuses or []}
    b.update(kw)
    return b


@pytest.fixture(scope="module", autouse=True)
def cleanup(c):
    yield
    a = c["admin"]
    for ent, rid in reversed(CREATED):
        if ent == "transactions":
            mdb.transactions.delete_one({"id": rid})
            mdb.cost_transactions.delete_many({"transaction_id": rid})
        elif ent == "plans":
            mdb.plans.delete_one({"id": rid})
        else:
            a.delete(f"/md/{ent}/{rid}")


# --- bonus validation
class TestBonusValidation:
    def test_bonus_resource_not_on_lines(self, c):
        for ep in ("/transactions/preview", "/transactions"):
            r = c["admin"].post(ep, body([{"resource_number": "E-10022", "bonus_type": "Safety", "amount": 10}]))
            assert r.status_code == 400, r.text
            assert "present row" in r.text

    def test_bonus_resource_absent_row(self, c):
        lines = [{"resource_number": "E-10021", "hour_type": "REG", "hours": 0, "present": False}]
        r = c["admin"].post("/transactions/preview", body([{"resource_number": "E-10021", "bonus_type": "Safety", "amount": 10}], lines))
        assert r.status_code == 400, r.text

    def test_bonus_unknown_type(self, c):
        for ep in ("/transactions/preview", "/transactions"):
            r = c["admin"].post(ep, body([{"resource_number": "E-10021", "bonus_type": "Bogus", "amount": 5}]))
            assert r.status_code == 400 and "Unknown bonus type" in r.text, r.text

    def test_bonus_inactive_type(self, c):
        a = c["admin"]
        r = a.post("/md/lookups", {"type": "BONUS_TYPE", "code": f"TESTB{SUF}", "meaning": f"TEST Bonus {SUF}", "order": "99"})
        assert r.status_code == 200, r.text
        lid = r.json()["id"]
        CREATED.append(("lookups", lid))
        assert r.json()["order"] == 99 and isinstance(r.json()["order"], (int, float))
        assert isinstance(mdb.lookups.find_one({"id": lid})["order"], (int, float))
        b = body([{"resource_number": "E-10021", "bonus_type": f"TEST Bonus {SUF}", "amount": 1}])
        assert a.post("/transactions/preview", b).status_code == 200
        assert a.post(f"/md/lookups/{lid}/status", {"status": "Inactive"}).status_code == 200
        r = a.post("/transactions/preview", b)
        assert r.status_code == 400 and "Unknown bonus type" in r.text

    def test_safety_within_cap_not_flagged(self, c):
        v = c["admin"].post("/transactions/preview", body([{"resource_number": "E-10021", "bonus_type": "Safety", "amount": 10}])).json()
        assert not any("above rate card" in x for x in v["validation"]["special"]["reasons"])
        assert v["totals"]["bonus"] == 10

    def test_safety_above_cap_flagged(self, c):
        v = c["admin"].post("/transactions/preview", body([{"resource_number": "E-10021", "bonus_type": "Safety", "amount": 10.5}])).json()
        assert v["validation"]["special"]["required"] is True
        assert any("above rate card" in x and "Safety" in x for x in v["validation"]["special"]["reasons"]), v["validation"]

    def test_bad_weather_cap_per_hour(self, c):
        a = c["admin"]
        ok = a.post("/transactions/preview", body([{"resource_number": "E-10021", "bonus_type": "Bad Weather", "amount": 22.5}])).json()
        assert not any("above rate card" in x for x in ok["validation"]["special"]["reasons"])
        hi = a.post("/transactions/preview", body([{"resource_number": "E-10021", "bonus_type": "Bad Weather", "amount": 23}])).json()
        assert hi["validation"]["special"]["required"] and any("22.5" in x for x in hi["validation"]["special"]["reasons"])

    def test_above_cap_create_accepted_and_routes_special(self, c):
        r = c["admin"].post("/transactions", body([{"resource_number": "E-10021", "bonus_type": "Safety", "amount": 50}], action="submit"))
        assert r.status_code == 200, r.text
        tx = r.json()
        CREATED.append(("transactions", tx["id"]))
        assert tx["validation"]["special"]["required"] is True
        assert tx["status"] not in ("approved", "draft")


# --- foreman redaction
class TestForemanRedaction:
    def test_preview_create_list_get(self, c):
        f = c["foreman"]
        b = body([{"resource_number": "E-10021", "bonus_type": "Safety", "amount": 10}])
        pv = f.post("/transactions/preview", b)
        assert pv.status_code == 200, pv.text
        pv = pv.json()
        assert all("rate" not in l and "cost" not in l for l in pv["lines"])
        assert "cost" not in pv["totals"] and pv["totals"]["qty"] == 9
        r = f.post("/transactions", b)
        assert r.status_code == 200, r.text
        tx = r.json()
        CREATED.append(("transactions", tx["id"]))
        assert "cost" not in tx["totals"] and all("cost" not in l and "rate" not in l for l in tx["lines"])
        lst = f.get("/transactions", params={"type": "labor"}).json()
        mine = [t for t in lst if t["id"] == tx["id"]]
        assert mine and "cost" not in mine[0]["totals"]
        assert all("cost" not in (t.get("totals") or {}) for t in lst)
        g = f.get(f"/transactions/{tx['id']}").json()
        assert "cost" not in g["totals"] and all("rate" not in l for l in g["lines"]) and g["cost_transactions"] == []
        # stored doc still has cost; admin sees it
        assert mdb.transactions.find_one({"id": tx["id"]})["totals"]["cost"] > 0
        ga = c["admin"].get(f"/transactions/{tx['id']}").json()
        assert ga["totals"]["cost"] > 0 and "rate" in ga["lines"][0]

    def test_pm_sees_costs(self, c):
        pv = c["project_manager"].post("/transactions/preview", body()).json()
        assert "cost" in pv["totals"] and "rate" in pv["lines"][0]

    def test_foreman_gets_bonus_amounts(self, c):
        br = c["foreman"].get("/master").json()["bonus_rates"]
        s = next(b for b in br if b["bonus_type"] == "Safety")
        assert s["amount"] == 10


# --- master data delete/status rules
class TestMasterDataRules:
    def test_delete_project_with_tasks_409(self, c):
        a = c["admin"]
        p = a.post("/md/projects", {"number": f"TEST-P4{SUF}", "name": "TEST p4"})
        assert p.status_code == 200, p.text
        pid = p.json()["id"]
        CREATED.append(("projects", pid))
        t = a.post("/md/tasks", {"project_number": f"TEST-P4{SUF}", "number": "T1", "name": "TEST t"})
        assert t.status_code == 200, t.text
        tid = t.json()["id"]
        assert a.delete(f"/md/projects/{pid}").status_code == 409
        assert a.delete(f"/md/tasks/{tid}").status_code == 200
        assert a.delete(f"/md/projects/{pid}").status_code == 200
        CREATED.remove(("projects", pid))
        assert a.get("/md/projects", params={"q": f"TEST-P4{SUF}"}).json()["total"] == 0

    def test_delete_employee_in_plan_409(self, c):
        a = c["admin"]
        if {e["entity"]: e["mode"] for e in a.get("/md/summary").json()["entities"]}["employees"] == "erp":
            pytest.skip("employees source mode is ERP (owner setting)")
        e = a.post("/md/employees", {"number": f"TEST-E4{SUF}", "name": "TEST emp4", "grade": "Skilled"})
        assert e.status_code == 200, e.text
        eid = e.json()["id"]
        CREATED.append(("employees", eid))
        crew = next(x for x in a.get("/master").json()["crews"] if x["project_number"] == "PRJ-1042")
        pl = a.post("/plans", {"kind": "crew", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "crew_id": crew["id"],
                               "start_date": "2030-01-01", "end_date": "2030-01-02",
                               "lines": [{"resource_type": "labor", "resource_number": f"TEST-E4{SUF}", "hours": {"REG": 8}}]})
        assert pl.status_code == 200, pl.text
        plid = pl.json()["id"]
        CREATED.append(("plans", plid))
        assert a.delete(f"/md/employees/{eid}").status_code == 409
        assert a.delete(f"/plans/{plid}").status_code == 200
        CREATED.remove(("plans", plid))
        assert a.delete(f"/md/employees/{eid}").status_code == 200
        CREATED.remove(("employees", eid))

    def test_status_on_erp_record_400(self, c):
        a = c["admin"]
        p = a.get("/md/projects", params={"source": "erp"}).json()["rows"][0]
        before = mdb.projects.find_one({"id": p["id"]}).get("status")
        r = a.post(f"/md/projects/{p['id']}/status", {"status": "Inactive"})
        assert r.status_code == 400, r.text
        assert mdb.projects.find_one({"id": p["id"]}).get("status") == before


# --- sample plans cover current month
def test_load_from_plan_today(c):
    a = c["admin"]
    crew = next(x for x in a.get("/master").json()["crews"] if x["name"] == "Crew-A (Civil)")
    r = a.get("/plans/autofill", params={"type": "labor", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "crew_id": crew["id"], "date": TODAY})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["plan"] and len({l["resource_number"] for l in d["lines"]}) >= 3
