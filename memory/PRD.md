# CostBridge - PRD

## Original problem statement
"Please find attached design documents and indicative wireframes. Build app for capturing actual costs for projects for customers (especially EPC customers) who are using ERP (oracle or SAP). This is for capturing the details of costs such as Resource tiomesheet details, equipment usage details and material consumption details"
Attachments: CostBridge_BRD.docx (v0.2), CostBridge_Wireframes.docx (9 screens).
User choices: Real Oracle Fusion connection; all 9 screens incl. Material (Phase 2); Email+password login with roles; USD.

## Architecture
- FastAPI + MongoDB backend: core.py (db, roles, Clerk member), engine.py (pricing, budget + plan-tolerance validation, server-side plan comparison, approval routing, Oracle payload builder), erp.py (adapter: OracleFusionAdapter; SAP plugs into same interface), seed.py (sample master data), server.py (routes, /api prefix)
- Auth: Emergent-managed Clerk (email+password). Roles in DB: admin, cost_controller, project_manager, store_manager, foreman, pending (default, no access). ADMIN_EMAIL=krishna.adalath@gmail.com
- React frontend (dark industrial theme, Outfit/Inter/JetBrains Mono), pages: Dashboard, Planning (crew + material), Labor Entry, Equipment Entry, Material Entry, Approvals, Rate Cards, Setup, Reports, ERP Integration, Users & Roles
- Oracle: env ORACLE_FUSION_BASE / ORACLE_USER / ORACLE_PASSWORD (basic auth). Pull projects, tasks, HCM workers, item costs, budget versions; push to unprocessedProjectCosts

## User personas
Foreman/Site Manager, Store Manager, Project Manager (Step 1), Cost Controller (Special + Step 2), Admin, Client Finance (reports)

## Core requirements (static)
Planning per Project#/Task#; plan auto-fill + exception mgmt; Budget check + Plan tolerance (warn/stop); 2-step approval + special approval (downtime/maintenance/wastage); auto-approval scope; rate cards per hour type; material RTS; audit trail; batch ERP integration; configurable per deployment.

## Implemented (2026-10-28)
- All 9 wireframe screens + ERP page + Users page; sample EPC data (labelled sample)
- Crew plan conflict check (409), publish gating, material plan with ERP unit cost
- Server-side plan comparison for auto-approval; atomic approvals (no duplicate cost lines); input validation
- Oracle adapter + cost queue + batch log + payload view (NOT yet connected - credentials pending)
- Testing: iteration_1 backend 22/22 + 5 bug repros fixed; frontend flows pass

## Implemented (2026-10-28, session 2) - Oracle connected
- Oracle creds saved (test tenant fa-eubg-test-saasfademo1). Adapter strips stray whitespace from URL
- Connection test 200; master-data pull runs as background job with batch log polling
- Pulled: 270 active projects, ~3,380 tasks, 6,552 workers, 271 items (TotalUnitCost/UOMName, latest per item), 603 budget versions; closed projects excluded
- Type-to-search pickers for employees/equipment/items (datalist)
- NOT yet done: cost push to Oracle (awaiting user go-ahead + Transaction Source/Document config), task-level budget lines, equipment (non-labor resources) pull, worker grade mapping (defaults to "Skilled")

## Implemented (2026-10-28, session 3) - bug fixes
- Hid native number spinners app-wide (dark color-scheme); quantity fields render blank
- Material Entry "Load from plan" (GET /api/plans/material-autofill): issued = remaining planned qty in period, Planned/used column
- In progress (paused by user): first Oracle cost posting (UPC describe fetched; need valid Transaction Source/Document/ExpenditureType from tenant), task-level budget pull

## Backlog
- P0: Connect Oracle tenant (credentials) and validate payload fields/Document Entry against tenant; map budget lines to task-level qty
- P1: IoT/telematics + swipe/biometric auto-fill feeds; offline capture for site; Oracle inventory API for Return-to-Store; per-task tolerance overrides
- P2: SAP PM adapter; multi-tenant org isolation; scheduled batch sync; PDF/Excel exports

## Next tasks
Collect Oracle credentials -> test connection -> sync master data -> push first batch.
