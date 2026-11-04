"""PostgreSQL migration checks; integration cases use the isolated local test schema."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import insert, select
from sqlalchemy.sql.dml import Insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from backend.database import Database, metadata, t


def test_postgresql_schema_compiles():
    for table in metadata.sorted_tables:
        statement = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert statement.startswith("\nCREATE TABLE ")


def test_non_postgresql_url_rejected():
    with pytest.raises(ValueError, match="PostgreSQL"):
        Database("sqlite:///costbridge.db")


def test_transaction_context_rolls_back_and_does_not_leak_connections():
    events = []

    class Engine:
        @asynccontextmanager
        async def begin(self):
            connection = object()
            events.append("begin")
            try:
                yield connection
            except RuntimeError:
                events.append("rollback")
                raise
            else:
                events.append("commit")

    async def check():
        database = Database("postgresql://localhost/test")
        original = database.engine
        database.engine = Engine()
        try:
            with pytest.raises(RuntimeError):
                async with database.transaction() as outer:
                    async with database.transaction() as nested:
                        assert nested is outer
                    async with database.transaction(independent=True) as background:
                        assert background is not outer
                    assert database._connection.get() is outer
                    raise RuntimeError("failed cost insert")
            assert database._connection.get() is None
            assert events == ["begin", "begin", "commit", "rollback"]
        finally:
            await original.dispose()

    asyncio.run(check())


def test_seed_sql_and_sample_costs(monkeypatch):
    from backend import core, engine, seed

    class Recorder:
        def __init__(self):
            self.rows = {}
            self.counter = 0

        async def execute(self, statement):
            compiled = statement.compile(dialect=postgresql.dialect())
            if isinstance(statement, Insert):
                self.rows.setdefault(statement.table.name, []).append(compiled.params)

        async def insert_many(self, table, documents):
            for document in documents:
                await self.execute(insert(table).values(document))

        async def scalar(self, statement):
            statement.compile(dialect=postgresql.dialect())
            self.counter += 1
            return self.counter if isinstance(statement, Insert) else 0

        async def one(self, statement):
            statement.compile(dialect=postgresql.dialect())
            table = statement.get_final_froms()[0].name
            if table == "settings":
                return engine.DEFAULT_SETTINGS
            if table == "budgets":
                return {"qty": 600, "uom": "hrs"}
            return None

        async def all(self, statement):
            statement.compile(dialect=postgresql.dialect())
            table = statement.get_final_froms()[0].name
            return [] if table == "transactions" else self.rows.get(table, [])

    database = Recorder()
    for module in (core, engine, seed):
        monkeypatch.setattr(module, "db", database)
    asyncio.run(seed.seed())
    assert len(database.rows["transactions"]) == 12
    assert database.rows["transactions"][0]["totals"]["cost"] == 15067
    assert database.rows["transactions"][-1]["totals"]["cost"] == 1102


def _pending(c):
    response = c["foreman"].post("/transactions", {
        "type": "labor", "project_number": "PRJ-2088", "task_number": "Piping-WBS-4",
        "date": "2032-02-01", "lines": [{"resource_number": "E-10027", "hour_type": "REG", "hours": 1}],
        "action": "submit",
    })
    assert response.status_code == 200, response.text
    entry = response.json()
    first = c["project_manager"].post(f"/transactions/{entry['id']}/approve", {})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "pending_step2"
    return entry["id"]


def test_approval_and_cost_lines_roll_back_together(c, monkeypatch):
    from backend import server
    entry_id = _pending(c)
    original = server._create_costs

    async def fail_after_cost_insert(tx, settings):
        await original(tx, settings)
        raise RuntimeError("Intentional migration rollback check")

    monkeypatch.setattr(server, "_create_costs", fail_after_cost_insert)
    response = c["cost_controller"].post(f"/transactions/{entry_id}/approve", {})
    assert response.status_code == 500
    saved = c["admin"].get(f"/transactions/{entry_id}").json()
    assert saved["status"] == "pending_step2"
    assert saved["cost_transactions"] == []
    assert not any(a["step"] == "pending_step2" for a in saved["approvals"])


def test_concurrent_approval_creates_cost_lines_once(c):
    entry_id = _pending(c)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: c["cost_controller"].post(f"/transactions/{entry_id}/approve", {}), range(2)))
    statuses = [response.status_code for response in responses]
    assert statuses.count(200) == 1
    assert all(status in (200, 404, 409) for status in statuses)
    saved = c["admin"].get(f"/transactions/{entry_id}").json()
    assert len(saved["cost_transactions"]) == 1
    assert saved["cost_transactions"][0]["amount"] == 36


def test_counter_is_unique_under_concurrent_requests(c):
    body = {"type": "labor", "project_number": "PRJ-2088", "task_number": "Piping-WBS-4",
            "date": "2032-03-01", "lines": [{"resource_number": "E-10027", "hour_type": "REG", "hours": 1}]}
    with ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(executor.map(lambda _: c["foreman"].post("/transactions", body), range(10)))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["ref"] for response in responses}) == 10


def test_unknown_project_rejected_by_database(local_client):
    from backend.core import db
    from sqlalchemy.exc import IntegrityError

    async def check():
        with pytest.raises(IntegrityError):
            async with db.transaction():
                await db.execute(insert(t.tasks).values(id="invalid-task", project_number="missing", number="TASK", name="Invalid"))
        assert await db.one(select(t.tasks).where(t.tasks.c.id == "invalid-task")) is None

    local_client.portal.call(check)


def test_erp_sync_upsert_preserves_master_ids(c, monkeypatch):
    from backend import server

    class Adapter:
        async def pull(self, entity):
            assert entity == "projects"
            return [{"number": "PRJ-1042", "name": "Synced project", "client": "Test", "erp_id": 1234, "status": "Active"}]

    monkeypatch.setattr(server, "get_adapter", lambda: Adapter())
    original = next(p for p in c["admin"].get("/master").json()["projects"] if p["number"] == "PRJ-1042")
    for _ in range(2):
        response = c["admin"].post("/erp/sync", {"entities": ["projects"]})
        assert response.status_code == 200, response.text
        batch_id = response.json()[0]["id"]
        batch = next(b for b in c["admin"].get("/erp/batches").json() if b["id"] == batch_id)
        assert batch["status"] == "success", batch
    updated = next(p for p in c["admin"].get("/master").json()["projects"] if p["number"] == "PRJ-1042")
    assert updated["id"] == original["id"]
    assert updated["name"] == "Synced project"


def test_auto_approval_inserts_parent_before_cost_lines(c, crew_b):
    settings = c["admin"].get("/settings").json()
    try:
        changed = {**settings, "auto_approval": "full"}
        assert c["admin"].put("/settings", changed).status_code == 200
        plan = c["foreman"].post("/plans", {
            "kind": "crew", "project_number": "PRJ-1042", "task_number": "Struct-WBS-2", "crew_id": crew_b,
            "shift": "Day Shift (06:00-14:00)", "start_date": "2033-01-01", "end_date": "2033-01-01",
            "lines": [{"resource_type": "labor", "resource_number": "E-10027", "hours": {"REG": 1}}],
        })
        assert plan.status_code == 200, plan.text
        plan_id = plan.json()["id"]
        assert c["foreman"].post(f"/plans/{plan_id}/publish").status_code == 200
        response = c["foreman"].post("/transactions", {
            "type": "labor", "project_number": "PRJ-1042", "task_number": "Struct-WBS-2", "crew_id": crew_b,
            "date": "2033-01-01", "plan_id": plan_id, "mode": "plan", "source": "plan", "action": "submit",
            "lines": [{"resource_number": "E-10027", "hour_type": "REG", "hours": 1}],
        })
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "approved"
        saved = c["admin"].get(f"/transactions/{response.json()['id']}").json()
        assert len(saved["cost_transactions"]) == 1
    finally:
        assert c["admin"].put("/settings", settings).status_code == 200
