# CostBridge

Project cost capture for labor, equipment and materials, with plan/budget checks,
approvals, audit history and Oracle Fusion integration.

React frontend, FastAPI backend, PostgreSQL 17. Clerk provides sign-in.

## Run locally on Windows

Prerequisites: Python 3.10+, Node.js, Docker Desktop running with Linux containers,
and valid Clerk keys in `backend/.env`. The existing `.venv` is used by the launcher.

From PowerShell:

```powershell
cd C:\Projects\erp_costtrack
.\scripts\start-local.ps1
```

The launcher installs missing database/auth and frontend packages, starts PostgreSQL
using `compose.yaml`, then starts the backend and frontend on loopback addresses.
Open http://localhost:3000. API documentation is at http://127.0.0.1:8001/docs.
Server logs are in `.local/logs`. The launcher prints the server process IDs.

The generated database password stays in ignored `.local/postgres.env` and
`backend/.env.local`. PostgreSQL data persists in the Docker Compose volume.
To stop PostgreSQL without removing its data:

```powershell
docker compose --env-file .local/postgres.env stop postgres
```

For an existing PostgreSQL server, set `DATABASE_URL` in the environment or
`backend/.env.local` instead of using the Docker launcher. See `backend/.env.example`.
Run `python -m uvicorn backend.server:app --host 127.0.0.1 --port 8001` from the root;
start the frontend with `REACT_APP_BACKEND_URL=http://127.0.0.1:8001` and `WDS_SOCKET_PORT=0`.

## PostgreSQL migration

The backend uses SQLAlchemy Core and asyncpg directly. Master data, plans, entries,
approvals, ERP batches and audit records are saved in PostgreSQL tables. Foreign keys,
unique constraints and decimal rate/amount columns protect the main relationships.
Nested plan/entry lines, validation details and ERP payloads retain their JSON structure.
Existing Python cost calculations and the frontend API remain compatible.

Requests commit their database changes together. Failed approvals roll back their
status, cost lines and audit writes. Reference counters and ERP upserts are atomic.
Schema creation and sample seeding run on startup; repeated startup preserves data.

No MongoDB data is deleted or automatically imported. The new local database starts
with the existing sample dataset. A rollback requires restoring the previous backend
code/dependencies and its original MongoDB configuration. Keep both databases until
any real-data migration has been verified. Future schema changes need explicit migrations;
startup creates missing tables and applies the idempotent `002_master_data` upgrade
for master fields, bonuses, dated rates and fractional hour-type ordering. The upgrade
preserves existing rows and allows multiple rate versions with different effective dates.

## Verification

Offline checks:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_postgresql.py -n 0
```

With PostgreSQL running, run the full suite against an automatically created temporary
schema. Authentication is replaced only inside tests; Clerk users are not created.
Run serially because older regression cases share state:

```powershell
$env:TEST_DATABASE_URL = $env:DATABASE_URL
.\.venv\Scripts\python.exe -m pytest backend/tests -n 0
```

`DATABASE_URL` is set in the PowerShell session by the local launcher. If using a new
terminal, load it from your local configuration first. Without `TEST_DATABASE_URL`,
database/API integration tests are skipped. Hosted tests require explicit
`RUN_LIVE_API_TESTS=1` and may modify hosted test data.
