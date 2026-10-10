# Milestone 7 issue #24 verification

Date: 2026-10-09 (Asia/Bangkok). Branch: `milestone7`; implementation started at
`08a0fdc` with a clean tree. Issue #24 remains open at the user's request.
Sources: all Milestone 7 design/task/evidence documents, the live issue, auth and
Redis contracts, root engineering instructions and the testing strategy. Design
revision 13 records the user's additions to revision 12 before implementation.

## Implementation and acceptance evidence

| Required behavior | Evidence |
|---|---|
| Strict concurrent admission | One Redis Lua operation checks pair and IP failure-plus-reservation capacity before inserting either lease. Real Redis tests overlap eight requests at password verification and exercise IP exhaustion across distinct pairs, rejection without partial reservation and idempotent failure finalization. |
| Lease expiry | Redis server time drives 10-second sorted-set reservations and key expiry. Real Redis tests inspect lease TTL, expire stored leases deterministically and reacquire capacity; expired leases cannot finalize as failures. Fixed-window boundaries expire failures while preserving active reservations. Local clock tests cover the corresponding rules. |
| Equal failure classification | Direct service callers normalize email before HMAC keying. Wrong password, unknown (with real dummy verification) and disabled account each record five identical pair/IP failures and receive generic throttles. Successful logins consume no failure quota and clear neither existing bucket. PostgreSQL failures release admission. |
| Throttle privacy | HTTP checks assert exactly `Too many attempts`, positive Retry-After and no email/IP in responses. Unit checks inspect Redis commands to prove HMAC identifiers; logs are checked through the actual JSON formatter. Proxy trust/CSRF/error contracts remain unchanged. |
| Separate refresh accounting | Real rotation reaches 10 known-family attempts, with the next request throttled; IP accounting includes family-throttled attempts and missing/malformed/unknown tokens. Known expiry/replay retain the existing real PostgreSQL security tests. Storage failures release IP admission. Cancellation during finalization compensates only this attempt, retaining prior family/IP history. |
| Database isolation | Auth no longer calls the PostgreSQL increment repository. Tests assert zero limiter rows while real sessions/refresh digests persist and rotate. The legacy limiter model/table and CLI cleanup remain; no migration or data deletion is introduced. |
| Deadline and cancellation | Real native verification is blocked by events; the real 8-second timeout scope is expired deterministically, or the request is cancelled. Both return generic 503 without cookies, failures or session creation, including after the native result finishes. Session-creation cancellation rolls back. |
| Uncertain commit and delivery | A real PostgreSQL commit completes before its acknowledgement is blocked and the timeout fires. The response is 503 with no credentials; `/auth/me` rejects the credential-free client. Safe `auth_commit_uncertain` JSON is asserted, and normal expired-family cleanup deletes the orphan and its refresh digest. Direct-caller and ASGI header-boundary tests prevent late credential delivery. |

Redis errors immediately invoke the accepted stricter bounded process-local
policy, without PostgreSQL counters. The shared runtime includes atomic local
admission, fixed-window failure expiry, single-flight five-second probes requiring
three successes, and recovery guards for surviving local buckets. Unit tests cover
ambiguous admission/finalization, local overlap, memory rejection, expiry and
retained recovery history. This foundation is needed for #24's accepted ambiguity
contract; it does **not** complete #25's broader physical outage/restart,
two-process, flapping and production-sizing evidence.

## Executed commands

From the repository root, using the installed locked Python 3.12.13 environment:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --gate backend-unit --gate backend-static --gate backend-integration --no-install
```

Passed, exit 0: baseline configuration/dependency/secret checks, **198 unit tests**,
Ruff lint and format (164 files), mypy (123 sources), **218 PostgreSQL/Redis
integration tests**, and Alembic model-drift check. The disposable database was
upgraded through unchanged head `e68d9a24b537`; no new upgrade operations were
detected. The final owned Compose project `restaurantos-m6-0c2ee3b2a3e1`, both
containers and network were removed. Unit tests reported one existing deprecation
warning; integration reported 636 existing Starlette/datetime warnings.

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate browser --no-install
```

Passed, exit 0 on the final implementation: **24 Chromium journeys** (2.4 minutes),
the isolated production Next build and owned database/process/container cleanup.
Both containers and the network for `restaurantos-m6-2de05348d4aa` were removed.
An earlier run also passed 24 journeys before the final deadline/cancellation
follow-up guards. The final baseline-only rerun after documentation changes passed.

Execution required leaving the restricted sandbox for Docker and the installed
Python runtime. An initial local thread-cancellation probe stalled inside the
sandbox; its bounded external rerun confirmed late results do not continue auth.
The initial integration attempt exposed cross-loop Redis borrowing by overlapping
test clients; auth now selects the pool belonging to its lifespan event loop.
Two test assumptions were corrected (storage lookup requires a supplied refresh
token; RESP3 score pairs are nested). A later run concurrent with the production
frontend build hit the accepted 100 ms Redis deadline and safely entered local
mode, failing shared-mode test expectations and Redis teardown. Sequential final
backend verification passed without changing the operation budget or quotas.

Ignored logs: `test-results/issue24-final-verification.log`,
`test-results/issue24-browser-final.log` and `test-results/issue24-baseline-final.log`.
No actual account secrets or application database were used.

## Changes and limits

No API URLs, cookie names, JSON response contracts, session lifetime, refresh
replay protection, CSRF trust or database schema changed. The auth environment
example/runbook now contain the accepted pair/IP windows and refresh quotas;
older ignored local env files must be updated explicitly. No dependencies changed.

Native password workers cannot be forcibly terminated; their pure results are
discarded after abandonment and cannot create sessions or update failures. An
already committed orphan family is accepted, expires normally and is covered by
CLI cleanup. Deadline enforcement covers owned auth work and credential delivery;
database/limiter cleanup is best effort, and leases bound failed release. An
already disconnected transport may be unable to receive the generic 503.

`AUTH_LOCAL_MAX_ENTRIES=10000` is a finite development default, not measured
production sizing. Multi-process outage quotas, restart/history loss and weaker
distributed guessing protection remain accepted limitations. Full ten-gate
Milestone 7 acceptance, physical Redis restart/multi-process tests, benchmarks,
frontend-static/frontend-tests, the separate frontend-build gate, image,
clean/seeded-legacy migration rehearsal and remote CI were not executed here.
The browser gate includes its own isolated production build. Relevant issue
gates are partial repository validation; Milestone 7 is not marked complete.
