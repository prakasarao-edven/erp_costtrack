"""PostgreSQL schema and request-scoped transactions."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
from types import SimpleNamespace

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, ForeignKey, ForeignKeyConstraint,
    Index, Integer, MetaData, Numeric, Table, Text, UniqueConstraint, insert,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

metadata = MetaData()


def identity():
    return Column("id", Text, primary_key=True)


def money(name, **kwargs):
    # Preserve the numeric JSON API while PostgreSQL stores exact decimal values.
    return Column(name, Numeric(20, 6, asdecimal=False), **kwargs)


def task_reference():
    return ForeignKeyConstraint(["project_number", "task_number"], ["tasks.project_number", "tasks.number"])


Table("projects", metadata, identity(), Column("number", Text, nullable=False, unique=True),
      Column("name", Text, nullable=False), Column("client", Text), Column("status", Text),
      Column("erp_id", BigInteger), Column("source", Text), Column("synced_at", Text))
Table("tasks", metadata, identity(), Column("project_number", Text, ForeignKey("projects.number"), nullable=False),
      Column("number", Text, nullable=False), Column("name", Text), Column("source", Text), Column("synced_at", Text),
      UniqueConstraint("project_number", "number"))
Table("employees", metadata, identity(), Column("number", Text, nullable=False, unique=True),
      Column("name", Text), Column("grade", Text), Column("trade", Text), Column("source", Text), Column("synced_at", Text))
Table("equipment", metadata, identity(), Column("number", Text, nullable=False, unique=True),
      Column("name", Text), Column("type", Text), Column("cls", Text), Column("organization", Text),
      Column("source", Text), Column("synced_at", Text))
Table("items", metadata, identity(), Column("number", Text, nullable=False, unique=True),
      Column("description", Text), Column("uom", Text), money("unit_cost", nullable=False),
      Column("category", Text), Column("cost_org", Text), Column("currency", Text),
      Column("source", Text), Column("synced_at", Text), CheckConstraint("unit_cost >= 0"))
Table("crews", metadata, identity(), Column("name", Text, nullable=False),
      Column("project_number", Text, ForeignKey("projects.number"), nullable=False), Column("foreman", Text))
Table("hour_types", metadata, identity(), Column("resource_type", Text, nullable=False),
      Column("code", Text, nullable=False), Column("name", Text), Column("requires_reason", Boolean),
      Column("expenditure_type", Text), Column("order", Integer), UniqueConstraint("resource_type", "code"))
Table("reason_codes", metadata, identity(), Column("code", Text, nullable=False, unique=True),
      Column("name", Text), Column("resource_type", Text))
Table("budgets", metadata, identity(), Column("project_number", Text, nullable=False),
      Column("task_number", Text, nullable=False), Column("resource_type", Text, nullable=False),
      Column("item_number", Text, ForeignKey("items.number")), money("qty", nullable=False),
      Column("uom", Text), Column("source", Text), task_reference(), CheckConstraint("qty >= 0"),
      UniqueConstraint("project_number", "task_number", "resource_type", "item_number", postgresql_nulls_not_distinct=True))
Table("rate_cards", metadata, identity(), Column("resource_type", Text, nullable=False),
      Column("key", Text, nullable=False), Column("hour_type", Text, nullable=False),
      money("base_rate", nullable=False), money("multiplier", nullable=False), money("premium", nullable=False),
      Column("effective_from", Text), UniqueConstraint("resource_type", "key", "hour_type"),
      ForeignKeyConstraint(["resource_type", "hour_type"], ["hour_types.resource_type", "hour_types.code"]),
      CheckConstraint("base_rate >= 0 AND multiplier >= 0 AND premium >= 0"))
Table("users", metadata, Column("user_id", Text, primary_key=True), Column("role", Text),
      Column("email", Text), Column("name", Text), Column("env", Text), Column("created_at", Text))
Table("settings", metadata, identity(), Column("rate_source", JSONB, nullable=False),
      Column("budget_behavior", Text, nullable=False), money("budget_warning_pct", nullable=False),
      Column("tolerance_pct", JSONB, nullable=False), Column("tolerance_behavior", Text, nullable=False),
      Column("auto_approval", Text, nullable=False), Column("special_hour_types", JSONB, nullable=False),
      Column("special_on_wastage", Boolean, nullable=False), Column("special_approver_role", Text, nullable=False),
      Column("currency", Text, nullable=False, server_default="USD"), Column("oracle", JSONB, nullable=False))
# shortcut: plan and entry lines stay JSONB to preserve the API; normalize for SQL reports across individual lines.
Table("plans", metadata, identity(), Column("kind", Text, nullable=False), Column("status", Text, nullable=False),
      Column("project_number", Text, nullable=False), Column("task_number", Text, nullable=False),
      Column("crew_id", Text, ForeignKey("crews.id")), Column("shift", Text), Column("period_type", Text),
      Column("start_date", Text, nullable=False), Column("end_date", Text, nullable=False),
      Column("lines", JSONB, nullable=False), Column("created_by", Text), Column("created_by_id", Text),
      Column("created_at", Text), Column("updated_at", Text), Column("published_at", Text),
      task_reference(), CheckConstraint("end_date >= start_date"), CheckConstraint("kind IN ('crew', 'material')"))
Table("transactions", metadata, identity(), Column("ref", Text, nullable=False, unique=True),
      Column("type", Text, nullable=False), Column("project_number", Text, nullable=False),
      Column("task_number", Text, nullable=False), Column("date", Text, nullable=False),
      Column("crew_id", Text, ForeignKey("crews.id")), Column("plan_id", Text, ForeignKey("plans.id", ondelete="SET NULL")),
      Column("mode", Text), Column("source", Text), Column("notes", Text), Column("sample", Boolean, server_default="false"),
      Column("lines", JSONB, nullable=False), Column("totals", JSONB, nullable=False), Column("validation", JSONB, nullable=False),
      Column("status", Text, nullable=False), Column("approvals", JSONB, nullable=False), Column("rejection_reason", Text),
      Column("created_by", Text), Column("created_by_id", Text), Column("created_at", Text),
      Column("submitted_by", Text), Column("submitted_by_id", Text), Column("submitted_at", Text),
      Column("approved_at", Text), Column("posted_at", Text), task_reference(),
      CheckConstraint("type IN ('labor', 'equipment', 'material')"))
Table("erp_batches", metadata, identity(), Column("direction", Text, nullable=False), Column("entity", Text, nullable=False),
      Column("started_at", Text), Column("finished_at", Text), Column("by", Text), Column("status", Text),
      Column("count", Integer), Column("ok", Integer), Column("failed", Integer), Column("error", Text))
Table("erp_budget_versions", metadata, identity(), Column("project_number", Text, nullable=False),
      Column("erp_id", BigInteger, nullable=False), money("total_cost"), Column("source", Text), Column("synced_at", Text),
      UniqueConstraint("project_number", "erp_id"))
Table("cost_transactions", metadata, identity(), Column("ref", Text, nullable=False, unique=True),
      Column("transaction_id", Text, ForeignKey("transactions.id"), nullable=False), Column("transaction_ref", Text),
      Column("type", Text), Column("kind", Text, nullable=False), money("amount", nullable=False),
      Column("payload", JSONB, nullable=False), Column("status", Text, nullable=False), Column("created_at", Text),
      Column("attempts", Integer, nullable=False, server_default="0"), Column("response", JSONB),
      Column("batch_id", Text, ForeignKey("erp_batches.id", deferrable=True, initially="DEFERRED")), Column("sent_at", Text))
Table("audit", metadata, identity(), Column("entity", Text), Column("entity_id", Text, index=True),
      Column("action", Text), Column("by", Text), Column("by_id", Text), Column("role", Text),
      Column("at", Text), Column("detail", JSONB))
Table("counters", metadata, identity(), Column("n", BigInteger, nullable=False))

t = SimpleNamespace(**metadata.tables)
Index("ix_transactions_project_task", t.transactions.c.project_number, t.transactions.c.task_number)
Index("ix_transactions_status", t.transactions.c.status)
Index("ix_plans_project_task", t.plans.c.project_number, t.plans.c.task_number)
Index("ix_cost_transactions_queue", t.cost_transactions.c.status, t.cost_transactions.c.kind)


class Database:
    def __init__(self, url):
        parsed = make_url(url)
        if parsed.get_backend_name() not in ("postgresql", "postgres"):
            raise ValueError("DATABASE_URL must point to PostgreSQL")
        self.engine = create_async_engine(parsed.set(drivername="postgresql+asyncpg"), pool_pre_ping=True)
        self._connection = ContextVar("database_connection", default=None)

    @asynccontextmanager
    async def transaction(self, *, independent=False):
        connection = self._connection.get()
        if connection is not None and not independent:
            yield connection
            return
        async with self.engine.begin() as connection:
            token = self._connection.set(connection)
            try:
                yield connection
            finally:
                self._connection.reset(token)

    async def initialize(self):
        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)

    async def execute(self, statement, parameters=None):
        async with self.transaction() as connection:
            return await connection.execute(statement, parameters)

    async def scalar(self, statement):
        return (await self.execute(statement)).scalar_one()

    async def insert_many(self, table, documents):
        groups = {}
        for document in documents:
            groups.setdefault(tuple(sorted(document)), []).append(document)
        async with self.transaction():
            for group in groups.values():
                await self.execute(insert(table), group)

    async def all(self, statement):
        result = await self.execute(statement)
        return [dict(row) for row in result.mappings()]

    async def one(self, statement):
        result = await self.execute(statement.limit(1))
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def close(self):
        await self.engine.dispose()
