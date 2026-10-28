"""Regression tests for bugs found in iteration 1 (expected to FAIL until fixed by main agent)."""
import concurrent.futures as cf


def _cleanup_plan(c, p):
    body = {k: p.get(k) for k in ["kind", "project_number", "task_number", "crew_id", "shift", "period_type", "start_date", "end_date"]}
    body["lines"] = []
    c["admin"].put(f"/plans/{p['id']}", body)
    c["admin"].delete(f"/plans/{p['id']}")


# Material plan line without planned_qty must be rejected (otherwise material preview/submit 500 KeyError planned_qty)
def test_material_plan_requires_qty(c):
    p = c["admin"].post("/plans", {"kind": "material", "project_number": "PRJ-2088", "task_number": "Piping-WBS-4", "period_type": "monthly",
                                   "start_date": "2031-01-01", "end_date": "2031-01-31", "lines": [{"item_number": "PIPE-CS-6IN"}]})
    try:
        if p.status_code == 200:
            r = c["admin"].post(f"/plans/{p.json()['id']}/publish")
            pv = c["admin"].post("/transactions/preview", {"type": "material", "project_number": "PRJ-2088", "task_number": "Piping-WBS-4",
                                                          "date": "2031-01-05", "lines": [{"item_number": "PIPE-CS-6IN", "qty_issued": 5}]})
            assert pv.status_code != 500, "material preview 500 when published plan line lacks planned_qty"
            assert r.status_code in (400, 422)
    finally:
        if p.status_code == 200:
            _cleanup_plan(c, p.json())


# Crew plan publish with a line missing resource_number returns 500 (KeyError) - should be 400/422
def test_crew_publish_missing_resource(c, crew_b):
    p = c["admin"].post("/plans", {"kind": "crew", "project_number": "PRJ-2088", "task_number": "Piping-WBS-4", "crew_id": crew_b,
                                   "shift": "Day Shift (06:00-14:00)", "start_date": "2031-01-01", "end_date": "2031-01-02",
                                   "lines": [{"resource_type": "labor", "hours": {"REG": 8}}]})
    try:
        if p.status_code == 200:
            r = c["admin"].post(f"/plans/{p.json()['id']}/publish")
            assert r.status_code in (400, 422), r.status_code
    finally:
        if p.status_code == 200:
            _cleanup_plan(c, p.json())


# Removing a plan row must not count as "unmodified from plan" (bypasses exception management / auto-approval)
def test_dropped_plan_row_not_unmodified(c, crew_b):
    af = c["foreman"].get("/plans/autofill", params={"type": "labor", "project_number": "PRJ-1042", "task_number": "Struct-WBS-2",
                                                   "crew_id": crew_b, "date": "2027-03-10"}).json()["lines"]
    assert len(af) >= 2
    d = c["foreman"].post("/transactions/preview", {"type": "labor", "project_number": "PRJ-1042", "task_number": "Struct-WBS-2", "date": "2027-03-10",
                                                   "crew_id": crew_b, "mode": "plan", "lines": af[:1]}).json()
    assert d["validation"]["unmodified_from_plan"] is False


# Client-supplied plan_line/planned_hours must be verified against a published plan server-side
def test_spoofed_plan_line_not_unmodified(c):
    d = c["foreman"].post("/transactions/preview", {"type": "labor", "project_number": "PRJ-2088", "task_number": "Piping-WBS-4", "date": "2026-10-28",
                                                   "mode": "plan", "lines": [{"resource_number": "E-10030", "hour_type": "OT", "hours": 12,
                                                                              "planned_hours": 12, "plan_line": True}]}).json()
    assert d["validation"]["unmodified_from_plan"] is False


# Concurrent approve clicks must not double-approve / duplicate ERP cost transactions
def test_concurrent_approve_single_costs(c):
    tid = c["foreman"].post("/transactions", {"type": "labor", "project_number": "PRJ-2088", "task_number": "Piping-WBS-4", "date": "2026-10-28",
                                              "lines": [{"resource_number": "E-10030", "hour_type": "REG", "hours": 1}], "action": "submit",
                                              "notes": "TEST_iter1_race"}).json()["id"]
    c["project_manager"].post(f"/transactions/{tid}/approve", {"comment": ""})
    with cf.ThreadPoolExecutor(4) as ex:
        codes = list(ex.map(lambda _: c["cost_controller"].post(f"/transactions/{tid}/approve", {"comment": ""}).status_code, range(4)))
    d = c["admin"].get(f"/transactions/{tid}").json()
    assert codes.count(200) == 1, codes
    assert len(d["cost_transactions"]) == 1
