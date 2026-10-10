# Coverage as regression feedback

The shared validator collects branch coverage separately for four suites. It
does not set a blanket percentage threshold. A failed test still fails its gate;
report generation never changes that exit status.

| Suite | Command from its project directory | Local report | CI artifact |
|---|---|---|---|
| Backend unit | `python -m pytest tests/unit --cov=app` with the report options in [backend coverage](coverage-backend.md) | `backend/coverage/backend-unit/` | `m6-backend-unit` |
| Backend service integration | `python -m pytest tests --ignore=tests/unit --cov=app` with the same labelled report options | `backend/coverage/backend-integration/` | `m6-backend-integration` |
| Frontend API client | `npm run test:client:coverage` | `frontend/coverage/client/` | `m6-frontend-tests` |
| Frontend components | `npm run test:component:coverage` | `frontend/coverage/component/` | `m6-frontend-tests` |

Backend reports provide terminal missing-line summaries, XML, JSON and HTML.
Frontend reports provide terminal summaries, JSON branch maps and HTML. CI
uploads available reports even on failure and retains them for seven days.
Reports and raw coverage data are generated artifacts, excluded from Git.

Read the two reports for a platform together: a module missed by the client
suite may be exercised by components, and a PostgreSQL repository intentionally
has no unit execution. Reports include eligible unimported source modules so
that genuine gaps remain visible. Use the labelled boundaries rather than
combining percentages from different suite responsibilities.

For a business change, inspect the affected function and missed branches first.
Prioritize authorization denial, tenant scoping, rollback, retry/idempotency,
stock shortage and lifecycle outcomes. Add a focused regression when it protects
an observable behavior; do not write assertions merely to raise a count.

The unit report directly exposes order-state, tenancy-policy and quantity rules.
The service report shows real authentication, persistence and transaction paths.
Frontend reports exercise the browser transport, order entry/actions, login,
inventory and recipes while keeping other eligible forms and wrappers visible
as follow-up gaps. See [backend exclusions](coverage-backend.md) and
[frontend exclusions](coverage-frontend.md) for precise boundaries. Async Server
Component routes and the server-only request facade are covered by browser
journeys, outside Vitest instrumentation. Worker/event behavior remains deferred
to Milestone 8 and has no current coverage claim.

On 2026-10-06, real labelled suites generated reports, and isolated deliberately
failing tests retained their available reports while returning exit code 1.
The final [Milestone 6 verification](../milestone6/milestone-6-verification.md) records the
complete local/CI results and the inspected revision.
