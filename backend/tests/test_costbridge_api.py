"""CostBridge backend regression: auth, roles, planning, capture (labor/equipment/material), approvals, setup, rates, dashboard, ERP, users."""
import copy
from datetime import date

import pytest

TODAY = date.today().isoformat()
FUT = "2027-03-10"  # isolated date used for self-created plans/entries
NOTE = "TEST_iter1"


def tx(type_, proj, task, lines, action="draft", **kw):
    return {"type": type_, "project_number": proj, "task_number": task, "date": kw.pop("date", TODAY), "lines": lines,
            "action": action, "notes": NOTE, **kw}


# ---------- Auth / role gating ----------
class TestAuth:
    def test_401_without_token(self, c):
        for p in ["/me", "/master", "/transactions", "/dashboard"]:
            assert c["anon"].get(p).status_code == 401, p

    def test_pending_403_master(self, c):
        assert c["pending"].get("/me").json()["role"] == "pending"
        assert c["pending"].get("/master").status_code == 403

    def test_role_gating(self, c):
        assert c["foreman"].get("/approvals").status_code == 403
        s = c["admin"].get("/settings").json()
        s.pop("id", None); s.pop("currency", None)
        assert c["foreman"].put("/settings", s).status_code == 403
        for r in ["project_manager", "cost_controller", "foreman", "store_manager"]:
            assert c[r].get("/users").status_code == 403, r
        assert c["store_manager"].post("/transactions/preview", tx("labor", "PRJ-1042", "Civil-WBS-3", [])).status_code == 403
        assert c["foreman"].get("/erp/cost-transactions").status_code == 403
        assert c["admin"].get("/users").status_code == 200


# ---------- Planning ----------
class TestPlanning:
    def test_conflict_409(self, c, crew_b):
        body = {"kind": "crew", "project_number": "PRJ-1042", "task_number": "MEP-WBS-7", "crew_id": crew_b,
                "shift": "Day Shift (06:00-14:00)", "period_type": "weekly", "start_date": TODAY, "end_date": TODAY,
                "lines": [{"resource_type": "labor", "resource_number": "E-10021", "hours": {"REG": 8}}]}
        r = c["project_manager"].post("/plans", body)
        assert r.status_code == 200 and r.json()["status"] == "draft"
        pid = r.json()["id"]
        r = c["project_manager"].post(f"/plans/{pid}/publish")
        assert r.status_code == 409 and "E-10021" in r.json()["detail"]
        assert c["project_manager"].delete(f"/plans/{pid}").status_code == 200

    def test_crew_plan_publish_and_autofill_unmodified_to_step2(self, c, crew_b):
        body = {"kind": "crew", "project_number": "PRJ-1042", "task_number": "Struct-WBS-2", "crew_id": crew_b,
                "shift": "Night Shift (22:00-06:00)", "period_type": "weekly", "start_date": FUT, "end_date": FUT,
                "lines": [{"resource_type": "labor", "resource_number": "E-10027", "hours": {"REG": 8, "OT": 2}}]}
        pid = c["foreman"].post("/plans", body).json()["id"]
        r = c["foreman"].post(f"/plans/{pid}/publish")
        assert r.status_code == 200 and r.json()["status"] == "published"
        af = c["foreman"].get("/plans/autofill", params={"type": "labor", "project_number": "PRJ-1042", "task_number": "Struct-WBS-2",
                                                       "crew_id": crew_b, "date": FUT}).json()
        assert len(af["lines"]) == 2
        r = c["foreman"].post("/transactions", tx("labor", "PRJ-1042", "Struct-WBS-2", af["lines"], "submit", date=FUT, crew_id=crew_b,
                                                  plan_id=pid, mode="plan", source="plan"))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "pending_step2"
        # Skilled: REG 36*8=288, OT 54*2=108
        assert d["totals"]["cost"] == 396.0

    def test_material_plan(self, c):
        body = {"kind": "material", "project_number": "PRJ-2088", "task_number": "Piping-WBS-4", "period_type": "monthly",
                "start_date": "2027-03-01", "end_date": "2027-03-31", "lines": [{"item_number": "PIPE-CS-6IN", "planned_qty": 100}]}
        r = c["store_manager"].post("/plans", body)
        assert r.status_code == 200
        pid = r.json()["id"]
        r = c["store_manager"].post(f"/plans/{pid}/publish")
        assert r.status_code == 200 and r.json()["status"] == "published"
        assert any(p["id"] == pid for p in c["admin"].get("/plans", params={"kind": "material"}).json())


# ---------- Labor ----------
class TestLabor:
    def test_autofill_seeded_4_rows(self, c, crew_a):
        af = c["foreman"].get("/plans/autofill", params={"type": "labor", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3",
                                                       "crew_id": crew_a, "date": TODAY}).json()
        assert len(af["lines"]) == 4
        assert {ln["resource_number"] for ln in af["lines"]} == {"E-10021", "E-10022", "E-10023"}

    def test_preview_breach_and_absent(self, c, crew_a):
        af = c["foreman"].get("/plans/autofill", params={"type": "labor", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3",
                                                       "crew_id": crew_a, "date": TODAY}).json()["lines"]
        af[0]["hours"] = 10  # 8 -> 10 = +25%
        af[1]["present"] = False
        d = c["foreman"].post("/transactions/preview", tx("labor", "PRJ-1042", "Civil-WBS-3", af, mode="plan", crew_id=crew_a)).json()
        assert d["lines"][0]["tolerance_status"] == "breach"
        assert d["lines"][1]["tolerance_status"] == "absent" and d["lines"][1]["cost"] == 0
        assert d["validation"]["tolerance"]["breach"] is True
        assert d["validation"]["unmodified_from_plan"] is False

    def test_breach_submit_routes_step1(self, c, crew_a):
        af = c["foreman"].get("/plans/autofill", params={"type": "labor", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3",
                                                       "crew_id": crew_a, "date": TODAY}).json()["lines"]
        af[0]["hours"] = 10
        r = c["foreman"].post("/transactions", tx("labor", "PRJ-1042", "Civil-WBS-3", af, "submit", mode="plan", crew_id=crew_a))
        assert r.status_code == 200 and r.json()["status"] == "pending_step1"

    def test_manual_rate_math(self, c):
        lines = [{"resource_number": "E-10021", "hour_type": "OT", "hours": 2}, {"resource_number": "E-10024", "hour_type": "HW", "hours": 3},
                 {"resource_number": "E-10026", "hour_type": "IDLE", "hours": 1}]
        d = c["foreman"].post("/transactions/preview", tx("labor", "PRJ-2088", "Piping-WBS-4", lines)).json()
        assert [ln["rate"] for ln in d["lines"]] == [54.0, 25.0, 24.0]
        assert d["totals"]["cost"] == 108 + 75 + 24


# ---------- Equipment chain ----------
class TestEquipment:
    def test_down_without_reason_blocked(self, c):
        lines = [{"resource_number": "CRN-022", "hour_type": "DOWN", "hours": 1}]
        d = c["foreman"].post("/transactions/preview", tx("equipment", "PRJ-1042", "Struct-WBS-2", lines)).json()
        assert d["validation"]["blocked"] and any("reason code" in e for e in d["validation"]["errors"])
        assert c["foreman"].post("/transactions", tx("equipment", "PRJ-1042", "Struct-WBS-2", lines, "submit")).status_code == 422

    def test_full_chain_with_special(self, c):
        lines = [{"resource_number": "CRN-022", "hour_type": "REG", "hours": 2},
                 {"resource_number": "CRN-022", "hour_type": "DOWN", "hours": 1, "reason_code": "BRK-ENG"}]
        r = c["foreman"].post("/transactions", tx("equipment", "PRJ-1042", "Struct-WBS-2", lines, "submit"))
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "pending_step1" and d["validation"]["special"]["required"]
        assert d["totals"]["cost"] == 2 * 210 + 30
        tid = d["id"]
        assert c["cost_controller"].post(f"/transactions/{tid}/approve", {"comment": ""}).status_code == 403  # wrong step
        assert c["project_manager"].post(f"/transactions/{tid}/approve", {"comment": "ok"}).json()["status"] == "pending_special"
        assert c["cost_controller"].post(f"/transactions/{tid}/approve", {"comment": "ok"}).json()["status"] == "pending_step2"
        assert c["cost_controller"].post(f"/transactions/{tid}/approve", {"comment": "ok"}).json()["status"] == "approved"
        full = c["admin"].get(f"/transactions/{tid}").json()
        cts = full["cost_transactions"]
        assert len(cts) == 2 and all(x["status"] == "queued" for x in cts)
        p = cts[0]["payload"]
        for k in ["ProjectNumber", "TaskNumber", "ExpenditureType", "NonlaborResource", "Quantity", "OriginalTransactionReference"]:
            assert k in p
        assert len(full["audit"]) >= 4


# ---------- Material ----------
class TestMaterial:
    def test_validation_rules(self, c):
        bad = [{"item_number": "RMC-M30", "qty_issued": 10, "qty_wasted": 6, "qty_returned": 5}]
        d = c["store_manager"].post("/transactions/preview", tx("material", "PRJ-1042", "Struct-WBS-2", bad)).json()
        errs = " ".join(d["validation"]["errors"])
        assert "cannot exceed issued" in errs and "reason code is required" in errs

    def test_chain_and_return_to_store(self, c):
        lines = [{"item_number": "RMC-M30", "qty_issued": 10, "qty_wasted": 1, "qty_returned": 2, "reason_code": "WASTE-SPL"}]
        r = c["store_manager"].post("/transactions", tx("material", "PRJ-1042", "Struct-WBS-2", lines, "submit"))
        assert r.status_code == 200, r.text
        d = r.json()
        ln = d["lines"][0]
        assert ln["qty_consumed"] == 8 and ln["cost"] == 8 * 115
        assert d["validation"]["special"]["required"] and d["status"] == "pending_step1"
        tid = d["id"]
        for who, st in [("project_manager", "pending_special"), ("cost_controller", "pending_step2"), ("cost_controller", "approved")]:
            assert c[who].post(f"/transactions/{tid}/approve", {"comment": ""}).json()["status"] == st
        kinds = sorted(x["kind"] for x in c["admin"].get(f"/transactions/{tid}").json()["cost_transactions"])
        assert kinds == ["project_cost", "return_to_store"]

    def test_vs_plan_tolerance(self, c):
        lines = [{"item_number": "REBAR-GR60-25MM", "qty_issued": 20}]
        d = c["store_manager"].post("/transactions/preview", tx("material", "PRJ-1042", "Civil-WBS-3", lines)).json()
        assert d["lines"][0]["planned_qty"] == 15 and d["lines"][0]["tolerance_status"] == "breach"


# ---------- Approvals: reject / resubmit / own entry ----------
class TestApprovals:
    def test_reject_and_resubmit(self, c):
        lines = [{"resource_number": "E-10028", "hour_type": "REG", "hours": 4}]
        tid = c["foreman"].post("/transactions", tx("labor", "PRJ-2088", "Piping-WBS-4", lines, "submit")).json()["id"]
        assert c["project_manager"].post(f"/transactions/{tid}/reject", {"reason": "no"}).status_code == 422
        r = c["project_manager"].post(f"/transactions/{tid}/reject", {"reason": "Wrong task"})
        assert r.json()["status"] == "rejected"
        mine = [t for t in c["foreman"].get("/transactions", params={"mine": "true"}).json() if t["id"] == tid][0]
        assert mine["rejection_reason"] == "Wrong task"
        r = c["foreman"].put(f"/transactions/{tid}", tx("labor", "PRJ-2088", "Piping-WBS-4", lines, "submit"))
        assert r.status_code == 200 and r.json()["status"] == "pending_step1"
        assert any(a["step"] == "resubmit" for a in r.json()["approvals"])
        assert "rejection_reason" not in r.json()

    def test_cannot_approve_own(self, c):
        lines = [{"resource_number": "E-10029", "hour_type": "REG", "hours": 2}]
        tid = c["project_manager"].post("/transactions", tx("labor", "PRJ-2088", "Piping-WBS-4", lines, "submit")).json()["id"]
        r = c["project_manager"].post(f"/transactions/{tid}/approve", {"comment": ""})
        assert r.status_code == 403 and "own" in r.json()["detail"]

    def test_approvals_list_per_role(self, c):
        pm = c["project_manager"].get("/approvals").json()
        cc = c["cost_controller"].get("/approvals").json()
        assert all(t["status"] == "pending_step1" for t in pm)
        assert all(t["status"] in ("pending_special", "pending_step2") for t in cc)


# ---------- Setup ----------
@pytest.fixture
def settings_restore(c):
    orig = c["admin"].get("/settings").json()
    yield copy.deepcopy(orig)
    body = {k: v for k, v in orig.items() if k not in ("id", "currency")}
    body.update(budget_behavior="warning", budget_warning_pct=90, tolerance_behavior="warning",
                tolerance_pct={"labor": 15, "equipment": 15, "material": 10}, auto_approval="step1")
    assert c["admin"].put("/settings", body).status_code == 200


class TestSetup:
    def _put(self, c, s, **kw):
        body = {k: v for k, v in s.items() if k not in ("id", "currency")} | kw
        r = c["admin"].put("/settings", body)
        assert r.status_code == 200, r.text

    def test_stoppers_and_full_auto(self, c, settings_restore, crew_b):
        s = settings_restore
        over = [{"resource_number": "E-10027", "hour_type": "REG", "hours": 2}]
        self._put(c, s, budget_behavior="stop")
        r = c["foreman"].post("/transactions", tx("labor", "PRJ-1042", "MEP-WBS-7", over, "submit"))  # MEP labor already >100%
        assert r.status_code == 422 and "Budget" in r.json()["detail"]
        self._put(c, s, tolerance_behavior="stop")
        af = c["foreman"].get("/plans/autofill", params={"type": "labor", "project_number": "PRJ-1042", "task_number": "Struct-WBS-2",
                                                       "crew_id": crew_b, "date": FUT}).json()["lines"]
        af[0]["hours"] = 12
        r = c["foreman"].post("/transactions", tx("labor", "PRJ-1042", "Struct-WBS-2", af, "submit", date=FUT, crew_id=crew_b, mode="plan"))
        assert r.status_code == 422 and "tolerance" in r.json()["detail"].lower()
        self._put(c, s, auto_approval="full")
        af[0]["hours"] = af[0]["planned_hours"]
        r = c["foreman"].post("/transactions", tx("labor", "PRJ-1042", "Struct-WBS-2", af, "submit", date=FUT, crew_id=crew_b, mode="plan"))
        assert r.status_code == 200 and r.json()["status"] == "approved"


# ---------- Rate cards / hour types ----------
class TestRates:
    def test_edit_rate_and_hour_type(self, c, master):
        rc = next(r for r in c["admin"].get("/rate-cards").json() if r["resource_type"] == "labor" and r["key"] == "Helper" and r["hour_type"] == "REG")
        body = {k: rc[k] for k in ("resource_type", "key", "hour_type", "base_rate", "multiplier", "premium", "effective_from")}
        r = c["admin"].put(f"/rate-cards/{rc['id']}", body | {"base_rate": 23})
        assert r.json()["base_rate"] == 23
        assert c["foreman"].put(f"/rate-cards/{rc['id']}", body).status_code == 403
        c["admin"].put(f"/rate-cards/{rc['id']}", body)
        ht = next(h for h in master["hour_types"] if h["resource_type"] == "labor" and h["code"] == "IDLE")
        hb = {"name": ht["name"], "expenditure_type": ht["expenditure_type"], "requires_reason": ht["requires_reason"]}
        assert c["admin"].put(f"/hour-types/{ht['id']}", hb | {"expenditure_type": "TEST_x"}).json()["expenditure_type"] == "TEST_x"
        c["admin"].put(f"/hour-types/{ht['id']}", hb)


# ---------- Dashboard ----------
class TestDashboard:
    def test_kpis_and_filter(self, c):
        d = c["cost_controller"].get("/dashboard").json()
        assert {"actual_cost", "pending_count", "flagged_count", "erp_queue", "over_budget"} <= set(d["kpis"])
        assert {r["status"] for r in d["rows"]} <= {"ok", "warning", "stopped"}
        f = c["cost_controller"].get("/dashboard", params={"project_number": "PRJ-2088"}).json()
        assert f["rows"] and all(r["project_number"] == "PRJ-2088" for r in f["rows"])


# ---------- ERP ----------
class TestErp:
    def test_not_configured(self, c):
        assert c["admin"].get("/erp/status").json()["connected"] is False
        for p, b in [("/erp/push", None), ("/erp/test", None), ("/erp/sync", {"entities": ["projects"]})]:
            r = c["admin"].post(p, b)
            assert r.status_code == 400 and "not configured" in r.json()["detail"], p
        cts = c["cost_controller"].get("/erp/cost-transactions").json()
        assert isinstance(cts, list)


# ---------- Users ----------
class TestUsers:
    def test_role_change_and_last_admin(self, c, tokens):
        uid = tokens["pending"]["user_id"]
        assert c["admin"].patch(f"/users/{uid}/role", {"role": "foreman"}).json()["role"] == "foreman"
        assert c["admin"].patch(f"/users/{uid}/role", {"role": "pending"}).json()["role"] == "pending"
        users = c["admin"].get("/users").json()["users"]
        admins = [u for u in users if u["role"] == "admin"]
        if len(admins) == 1:
            r = c["admin"].patch(f"/users/{admins[0]['user_id']}/role", {"role": "foreman"})
            assert r.status_code == 409
        else:
            pytest.skip("more than one admin present")
