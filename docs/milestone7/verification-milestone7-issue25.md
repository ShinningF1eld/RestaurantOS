# Milestone 7 issue #25 verification

Date: 2026-10-10 (Asia/Bangkok). Branch: `milestone7`; implementation started
at `befe42e` with a clean working tree. Source: live GitHub issue
[#25](https://github.com/ShinningF1eld/RestaurantOS/issues/25), Milestone 7 design
revision **13**, T7, T6 verification, Redis architecture and auth/API/runbook
contracts. The issue's revision 5 and former document path are superseded by the
user's explicit instruction to use revision 13. Issue #24's implementation is
present and previously verified even though its GitHub issue remains open.

## Implementation and acceptance evidence

Issue #24 supplied the atomic local foundation. This change completes its outage
verification and hardens recovery/finalization:

- Recovery records a failure generation. A successful probe started before a
  concurrent failed finalization cannot contribute stale stability evidence.
  Probe results must be the expected integer zero; malformed/nonzero results
  remain degraded. Invalid admission results likewise use conservative fallback.
- Recovering logs only the first stable probe. A subsequent failure records the
  transition back to degraded, resets successes and retains the outage start and
  local history. Probe failures remain observable without skipped-request logs.
- If Redis failure finalization is ambiguous while only the IP bucket has a local
  recovery guard, the new pair is now counted locally as well. Already counted
  buckets are skipped, preserving one failure per attempt and atomic capacity.
- No quotas, fixed windows, deadlines, leases, session semantics or PostgreSQL
  limiter history are changed. There is no schema migration, dependency update,
  new production endpoint, commit, push or GitHub issue modification.

| Issue criterion | Executable evidence |
|---|---|
| Immediate fallback and Redis bypass | Physical Redis stop triggers local admission for the same HTTP request; each API admits three pair failures and throttles the next. Test-owned command counts stay unchanged for open-circuit requests. Real PostgreSQL sessions persist; limiter table count stays zero. |
| Atomic, bounded local state | Existing admission tests plus event-coordinated recovery tests verify pair/IP reservations, release and ten-second lease expiry. One thousand new identities at capacity are rejected without eviction; later expiry frees capacity. The real API reaches an eight-entry test cap and retains live counters. Monotonic deadlines survive forward/backward wall clock changes. |
| Ambiguous operations | A real Redis admission or finalization executes before its acknowledgement is deliberately lost. Each is attempted once; local failure accounting and bounded Redis lease/TTL are asserted. The partial recovery-guard regression verifies new-pair accounting without double counting the guarded IP. |
| Single-flight stable recovery | Event barriers hold a probe while twenty admissions complete locally without waiting or touching Redis. An overlapping finalization failure invalidates its successful result. Deterministic and physical stop/start cases require three consecutive successful limiter operations; flapping resets successes and retains history. |
| Recovery guard and process limits | Existing local failures reject requests after healthy mode returns; new keys without surviving local buckets use Redis. Two separate Uvicorn processes share the normal five-failure pair quota but each admit three additional local failures during outage. Restarting one process admits again while the other remains limited. Nonpersistent Redis restart loses its own shared counters. |
| Safe transition events | Tests pass actual records through `JsonFormatter` and inspect real API-process logs for degraded/recovering/healthy/probe-failed events, process identity, safe reasons and durations. Account, IP, password and cookie/token material are absent from these events. |

The API-process helper lives only in `backend/tests/support/`: stdin advances
limiter test clocks and reads aggregate state. HTTP requests still exercise real
Uvicorn, password verification, cookies, PostgreSQL and refresh rotation. The test
container uses a random loopback port pinned across its physical restarts and is
removed in `finally`; test API processes are stopped or killed on failure. It does
not stop the gate's Redis/PostgreSQL or developer services.

## Validation

From the repository root with the locked Python 3.12.13 environment:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --gate backend-unit --gate backend-static --gate backend-integration --no-install
```

Passed, exit 0: baseline Compose/dependency/candidate-secret checks, **210 unit
tests**, Ruff lint/format (169 files), mypy (123 sources), **221 PostgreSQL/Redis
integration tests** and Alembic model drift. The disposable database upgraded
through unchanged head `e68d9a24b537`, with no new upgrade operations. The owned
Compose project `restaurantos-m6-7a757155f446`, both containers and network were
removed. Existing warnings: one unit and 636 integration deprecations.

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate browser --no-install
```

Passed, exit 0: **24 Chromium journeys** (2.8 minutes), including auth renewal,
permissions, catalog, inventory, orders and recipes, and the isolated production
Next build. Owned database/build/API cleanup passed; Compose project
`restaurantos-m6-96f072879694`, both containers and network were removed.

After the documentation updates, the final scan also passed:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --no-install
git diff --check
```

Container/process inspection found no remaining test-owned outage Redis
containers or API helper processes. The stalled sandbox-only focused test
attempt was terminated; executed gates used the installed runtime outside that
sandbox.

The new measurement script also passed standalone Ruff lint and format checks:

```powershell
backend/.venv-m6-dev/Scripts/python.exe -m ruff check scripts/measure-auth-local-memory.py
backend/.venv-m6-dev/Scripts/python.exe -m ruff format --check scripts/measure-auth-local-memory.py
```

Earlier runs exposed transport timeouts in two existing shared-quota concurrency
tests; they now prepare only test connections with safely repeatable PINGs before
overlapping admissions. Production commands and the 100 ms budget are unchanged.
The physical restart test initially used Docker's automatic port publication,
which selected a different port after restart. The corrected fixture pins a free
random loopback port and still tolerates failed recovery probes without counting
them as successes. The deliberate invalid test password is inline-allowlisted
after candidate-secret scanning flagged it; no real credentials are present.

Ignored evidence: `test-results/issue25-backend-complete.log`,
`test-results/issue25-browser.log`, `test-results/issue25-baseline-final.log`,
`test-results/issue25-local-memory.json`.

Memory measurement command (completed):

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/measure-auth-local-memory.py --entries 10000
```

Python 3.12.13 / Windows, retained Python allocations from `tracemalloc`:

| Full quota per entry | Bytes per entry | Retained bytes for 10,000 entries |
|---|---:|---:|
| 3 | 760.1 | 7,601,280 |
| 5 | 953.8 | 9,538,112 |
| 10 | 1526.8 | 15,268,352 |
| 50 | 6718.8 | 67,188,352 |

These exclude total runtime RSS, temporary cleanup and allocator overhead.
`AUTH_LOCAL_MAX_ENTRIES=10000` remains a development default. Production sizing
must budget per-process RAM, expected distinct outage identities and process
count; the runbook supplies the procedure, not a production recommendation.

## Limits and documentation reconciliation

Outage quotas are independent per process, lose history on restart and do not
inherit pre-outage Redis counters. Redis loss and distributed guessing across
IPs weaken aggregate protection as explicitly accepted by revision 13. The
100 ms Redis budget, five-second probe interval, three-success recovery guard,
eight-second auth deadline and ten-second leases are unchanged.

The root instructions' PostgreSQL-only limiter note and ADR 0003's original
PostgreSQL/fail-closed limiter paragraph describe the pre-M7 baseline. Current
runtime/auth docs and the approved Milestone 7 design describe Redis/local
behavior. The issue's generic retryable service-error wording is resolved by the
accepted design's generic 429/Retry-After policy at local memory capacity.

This is partial issue verification, not full Milestone 7 acceptance. Production
deployment sizing, performance benchmarks, the remaining milestone tasks and
remote CI remain separate. The application database is not a validation target.
The separate frontend-static, frontend-tests, frontend-build, migrations and
image gates were not executed for this backend-only change. Browser validation
includes its own production frontend build; no schema/image changes require
the migrations/image gates here. Locked installation was omitted without
resolving or upgrading dependencies. Git diff checks passed.
