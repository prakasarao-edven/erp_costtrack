import json
import os
import subprocess
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import requests


ROOT = Path(__file__).resolve().parents[2]
ROLES = ["admin", "master_data_admin", "project_manager", "cost_controller", "foreman", "store_manager", "pending"]


BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://127.0.0.1:8001").rstrip("/") + "/api"


@pytest.fixture(scope="session")
def local_client():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL/API integration tests in an isolated schema")
    os.environ.setdefault("DATABASE_URL", url)
    from fastapi import HTTPException, Request
    from fastapi.testclient import TestClient
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from sqlalchemy.schema import CreateSchema, DropSchema
    from backend.core import db, tables, ENV
    from backend.clerk_auth import require_user
    from backend.server import app
    from backend import server

    schema = "costbridge_test_" + uuid4().hex
    original_engine = db.engine
    db.engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"), poolclass=NullPool,
                                   execution_options={"schema_translate_map": {None: schema}})

    async def create_schema():
        async with db.engine.begin() as connection:
            await connection.execute(CreateSchema(schema))

    async def seed_users():
        await db.insert_many(tables.users, [{"user_id": "test-" + role, "role": role, "env": ENV,
                                            "name": "Test " + role, "email": role + "@example.test"} for role in ROLES])
        await db.insert_many(tables.projects, [{"id": "erp-test-project", "number": "00009805", "name": "ERP test project",
                                               "source": "oracle", "status": "Active"}])
        await db.insert_many(tables.employees, [{"id": "erp-test-employee", "number": "ERP-100", "name": "ERP test worker",
                                                "grade": "Skilled", "source": "oracle", "status": "Active"}])

    async def cleanup():
        async with db.engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await db.close()

    def identity(request: Request):
        role = request.headers.get("authorization", "").removeprefix("Bearer ")
        if role not in ROLES:
            raise HTTPException(401, "Not signed in")
        return {"user_id": "test-" + role}

    asyncio.run(create_schema())
    original_adapter = server.get_adapter
    server.get_adapter = lambda: None
    app.dependency_overrides[require_user] = identity
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.portal.call(seed_users)
            yield client
    finally:
        app.dependency_overrides.pop(require_user, None)
        server.get_adapter = original_adapter
        try:
            asyncio.run(cleanup())
        finally:
            db.engine = original_engine


@pytest.fixture(scope="session")
def tokens():
    if os.environ.get("TEST_DATABASE_URL"):
        return {role: {"token": role, "user_id": "test-" + role} for role in ROLES}
    if os.environ.get("RUN_LIVE_API_TESTS") != "1":
        pytest.skip("Set TEST_DATABASE_URL for isolated local tests, or RUN_LIVE_API_TESTS=1 for hosted tests")
    out = subprocess.run([sys.executable, str(ROOT / "scripts/test_users.py"), "--tokens"],
                         capture_output=True, text=True, timeout=120, check=True).stdout
    return json.loads(out)


@pytest.fixture(scope="session")
def sql(local_client):
    from backend.core import db

    def execute(statement):
        return local_client.portal.call(db.execute, statement)

    return execute


class Client:
    def __init__(self, token, transport=requests):
        self.h = {"Authorization": f"Bearer {token}"} if token else {}
        self.transport = transport
        self.base = "/api" if transport is not requests else BASE

    def get(self, p, **kw):
        return self.transport.get(self.base + p, headers=self.h, timeout=30, **kw)

    def post(self, p, json=None):
        return self.transport.post(self.base + p, headers=self.h, json=json, timeout=30)

    def put(self, p, json=None):
        return self.transport.put(self.base + p, headers=self.h, json=json, timeout=30)

    def patch(self, p, json=None):
        return self.transport.patch(self.base + p, headers=self.h, json=json, timeout=30)

    def delete(self, p):
        return self.transport.delete(self.base + p, headers=self.h, timeout=30)


@pytest.fixture(scope="session")
def c(tokens, request):
    transport = request.getfixturevalue("local_client") if os.environ.get("TEST_DATABASE_URL") else requests
    return {r: Client(v["token"], transport) for r, v in tokens.items()} | {"anon": Client(None, transport)}


@pytest.fixture(scope="session")
def master(c):
    return c["admin"].get("/master").json()


@pytest.fixture(scope="session")
def crew_a(master):
    return next(x["id"] for x in master["crews"] if x["name"].startswith("Crew-A"))


@pytest.fixture(scope="session")
def crew_b(master):
    return next(x["id"] for x in master["crews"] if x["name"].startswith("Crew-B"))
