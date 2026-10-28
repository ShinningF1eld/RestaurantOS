# Liveness and database readiness

Both endpoints are public and expose only generic status. Gateway deployments
serve them at `/backend/health` and `/backend/ready`; direct API paths stay
unprefixed.

`GET /health` returns 200 with `{"status":"ok","service":"restaurantos-api"}`.
It identifies a running API process and does not contact PostgreSQL or Redis.

`GET /ready` returns 200 with `{"status":"ready"}` after a read-only `SELECT 1`
through the API's configured database pool. Acquisition, query and connection
return share a two-second budget. Failure or deadline expiry returns 503 with
`{"status":"unavailable"}`. Responses use `Cache-Control: no-store`; connection
details and exception messages are never returned. On expiry, an acquired
asyncpg connection is terminated before task cancellation so a suspended server
cannot prolong graceful cancellation or leave the connection reusable.
Termination is conditional on the probe's SQLAlchemy lease still being open:
a task delayed after connection return must not terminate a later borrower's
connection. The regression suite proves that handoff with the same real pooled
PostgreSQL connection.

Readiness does not authenticate a user, rotate cookies, write data, migrate,
verify schema revisions, contact Redis or prove worker progress. Those checks
remain separate. In local gateway Compose, the API healthcheck uses `/ready`
and the frontend waits for that healthcheck. The reusable image's default
healthcheck remains `/health`.

The integration suite checks success, a refused connection, real pool contention
and cancellation. The disposable HTTPS browser matrix suspends PostgreSQL,
requires a bounded generic 503 while liveness stays 200, resumes it, and requires
readiness to recover. It does not operate on the developer database.
