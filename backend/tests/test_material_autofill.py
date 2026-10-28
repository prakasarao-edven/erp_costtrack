# Material "Load from plan" autofill endpoint (iteration 2 bug fix)
import datetime

TODAY = datetime.date.today().isoformat()
Q = "/plans/material-autofill"


def test_autofill_requires_auth(c):
    r = c["anon"].get(Q, params={"project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "date": TODAY})
    assert r.status_code == 401


def test_autofill_civil_wbs3(c):
    r = c["store_manager"].get(Q, params={"project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "date": TODAY})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["plan"] and d["plan"]["kind"] == "material" and d["plan"]["status"] == "published"
    assert "_id" not in d["plan"]
    by = {x["item_number"]: x for x in d["lines"]}
    assert by["CEM-OPC53"]["planned_qty"] == 400
    assert by["REBAR-GR60-25MM"]["planned_qty"] == 15
    for x in d["lines"]:
        assert x["plan_line"] is True
        rem = max(round(x["planned_qty"] - x["used_qty"], 2), 0)
        assert x["qty_issued"] == (rem or None)


def test_autofill_foreman_allowed(c):
    r = c["foreman"].get(Q, params={"project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "date": TODAY})
    assert r.status_code == 200


def test_autofill_no_plan(c):
    r = c["store_manager"].get(Q, params={"project_number": "PRJ-1042", "task_number": "MEP-WBS-7", "date": TODAY})
    assert r.status_code == 200
    assert r.json() == {"plan": None, "lines": []}


def test_autofill_out_of_period(c):
    r = c["store_manager"].get(Q, params={"project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "date": "2001-01-01"})
    assert r.status_code == 200 and r.json()["plan"] is None


def test_autofill_missing_params(c):
    r = c["store_manager"].get(Q, params={"project_number": "PRJ-1042"})
    assert r.status_code == 422


def test_autofill_lines_preview(c):
    d = c["store_manager"].get(Q, params={"project_number": "PRJ-1042", "task_number": "Civil-WBS-3", "date": TODAY}).json()
    lines = [dict(x, qty_issued=x["qty_issued"] or 1) for x in d["lines"]]
    pv = c["store_manager"].post("/transactions/preview", {"type": "material", "project_number": "PRJ-1042", "task_number": "Civil-WBS-3",
                                                             "date": TODAY, "mode": "plan", "plan_id": d["plan"]["id"], "lines": lines})
    assert pv.status_code == 200, pv.text
    assert len(pv.json()["lines"]) == len(lines)
    assert all(x["cost"] > 0 for x in pv.json()["lines"])
