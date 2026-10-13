# Milestone 8 Issue #34 / T4 verification

Reviewed: 2026-10-12 (Asia/Bangkok), independent post-fix review.

**Result: Issue #34 satisfies all six acceptance criteria within T4 scope at
`d3130e3`; both previous findings are resolved.** Inspection and fresh worker
regressions establish same-consumer reference recovery and service-owned
transactions. No new actionable T4 defect was identified. All three required
backend gates passed. Full Milestone 8 acceptance remains open; consumer effects
and receipts are outside this transport slice.

## Scope and sources

Reviewed HEAD: `d3130e3725ad5570dcd21838b8f243251fa0afef`
(`fix(events): recover pending references safely`), on
`milestone8/issue34-relay&worker`. Working tree was clean at review start.
Fix comparison: first parent `8890661feb68829b839240df4e0d4d18c0f0d985`, the
previously reviewed T4 implementation. Overall T4 baseline remains
`fb93d270bec765abe0bc7c57abb83cac8548e94d`.
Only this verification report is rewritten; source, tests, configuration, other
documents and GitHub state are unchanged by the review.

Sources:

- [GitHub #34](https://github.com/ShinningF1eld/RestaurantOS/issues/34), fetched
  again: open, six unchecked acceptance bullets, dependency
  [#31](https://github.com/ShinningF1eld/RestaurantOS/issues/31).
- Approved [M8 design revision 1](milestone-8-design.md),
  [task plan T4](milestone-8-task.md), and
  [master roadmap M8](../../RestaurantOS_Master_Roadmap.md#milestone-8--reliable-background-jobs-and-domain-events).
- [README](../../README.md), [current state](../current-state.md), root
  engineering instructions, ADRs
  [0001](../adr/0001-modular-monolith.md)/[0002](../adr/0002-feature-modules.md),
  [event contract](../api/events.md), [Redis architecture](../architecture/redis.md),
  [worker runbook](../runbooks/event-worker.md), and
  [testing commands](../testing/README.md).

Task-plan checkmarks and the appended implementation follow-up are not used as
independent execution evidence. R3/R4/R5/R11/R13 are assessed only within T4's
transport scope. T5 owns effects/receipt transactions, poison retries and replay;
projections, alerts, maintenance initialization and freshness remain later work.

## Acceptance criteria and evidence

AC1-AC6 follow GitHub's six bullets in order. **6 Passed, 0 Failed,
0 wholly Untested criteria within T4 scope**, based on inspection, fresh worker
regressions and the manual checks below. Unexecuted subcases remain disclosed;
this is not full Milestone 8 acceptance.

| ID | Assessment and evidence |
|---|---|
| AC1: Redis 7 references, typed PostgreSQL facts, independent groups and non-subscriptions | **Passed — inspection and regression execution.** Streams use Redis 7-compatible commands and exactly UUID/type/version/correlation fields. PostgreSQL envelopes are reconstructed and validated before fixed-registry routing; transport metadata cannot select handlers or replace payloads. Real entrypoint/group tests check minimal fields and alerts acknowledging unsubscribed completion events. New read/ack failure tests prove eventual acknowledgement by the same consumer. Malformed/conflicting-reference rejection remains inspection evidence. |
| AC2: bounded short claims, leases/fencing, budgets and no business locks during I/O | **Passed — inspection, regression execution and held-lock scenario.** Due pending subscriptions use limited `FOR UPDATE SKIP LOCKED` selection and unique owner/token/expiry. `EventWorkerService` owns short transactions and returns only after commit; repositories query/update/flush an active caller session. Redis publication happens afterward. Existing stale-token/backlog tests pass. The new caller-transaction test proves a claim remains invisible to another connection before commit. A manual second transaction skips a delivery while its row lock is held and claims it after release. Config tests/runbook retain bounded batch/concurrency/lease/read/scan/backoff/grace budgets. |
| AC3: publication is not completion; bounded PostgreSQL/PEL/group/content-loss recovery | **Passed — inspection and real-process regression execution.** Publication updates only observation state; required subscriptions remain unfinished for T5. Claim/post-XADD crash, other-owner PEL reclaim, stream deletion and physical nonpersistent Redis restart tests pass. Recovery preserves UUIDs, resets observations in bounded batches and republishes after loss/stall. Additional two-process checks observe distinct claims, recover both after forced termination and publish exactly the original two UUID references. Tests use accelerated timing values; sustained default-budget load is unmeasured. |
| AC4: ambiguous publish/ack, crash/fencing, due-time authority and bounded recovery | **Passed — inspection and regression execution; previous failure resolved.** Three new same-consumer cases cover PostgreSQL fact-read failure, XACK failure before execution and lost response after successful XACK. Retry reconciles the exact PEL ID/owner, reloads fields/facts and clears already-acknowledged entries without another XACK or publication. Tests prove empty final alerts PEL and one unchanged Stream entry. Existing publication-crash, stale-token, early-reference and outage tests pass. Retry memory is bounded by one read/reclaim batch; exponential delay stays within existing infrastructure bounds. Sustained flood behavior is not separately measured. |
| AC5: separate startup/shutdown, forced recovery and API Redis isolation | **Passed — inspection and real-process/unit execution.** Worker starts neither API nor migrations and owns an independent Redis pool. Actual module startup, graceful stop and forced restart cases pass after service isolation. Unit tests preserve worker 2 s/eight connections versus API 100 ms/20 connections. Two-process manual checks also stop restarted workers gracefully. Local Redis persistence is unchanged. Database-stalled/full-batch shutdown remains untested. |
| AC6: retained visibility and no deletion/trimming | **Passed — inspection and regression execution.** Recovery reports stream/PEL/unfinished and retained event/delivery/receipt/attempt counts using allowlisted JSON fields; retry adds a safe delay field. No automatic event/history deletion, XTRIM or capped XADD exists. Complete metric-field output and counter performance at large retained history are not separately asserted. |

Primary suites: `backend/tests/unit/test_event_worker.py` (eight cases) and
`backend/tests/integration/test_event_worker.py` (13 cases), alongside event
storage/producer, authorization/stock and Redis/auth regression suites.

## Findings and fix verification

No new actionable T4 behavior finding was identified. Both earlier findings are
resolved by the latest commit, with the following evidence.

### F1 — resolved: same-owner pending reference recovery

Locations: `backend/app/modules/events/worker/runtime.py:137`, `:419`, `:434`,
`:475`, `:497`; `backend/app/modules/events/worker/streams.py:228`.

Previously, a PostgreSQL-read or XACK failure left a reference in this consumer's
PEL, while pending scans selected only other owners and new reads used `>`.
The same process never retried it. An earlier real-Redis manual reproduction
observed four reads, one acknowledgement attempt and one stale pending entry.

Now each consumer maintains a retry schedule for transient routing/ack failures.
It drains that bounded schedule before accepting another batch, uses monotonic
ready times and bounded exponential infrastructure delay, and confirms the exact
reference still belongs to this consumer before retrying. Fields and typed
PostgreSQL facts are reloaded. If XACK completed but its response was lost, the
missing PEL reference removes the retry; an ownership change also removes it.
Ordinary unfinished subscribed T4 work is still left pending without busy retries.

`test_same_consumer_retries_transient_pending_reference_failures` runs the actual
consumer loop with real migrated PostgreSQL and Redis. It injects one failure
at each of three boundaries: fact loading, XACK before execution and XACK after
execution. Expected acknowledgement calls are respectively one, two and one;
all cases finish with an empty alerts PEL and exactly one original Stream ID.
The read-failure case reloads facts twice. Injection wraps the real adapter/service;
it does not replace authoritative facts with a mocked envelope. All three cases
passed in this review's integration execution.

### F2 — resolved: repository transaction ownership

Locations: `backend/app/modules/events/repo/worker_queries.py:59`, `:75`,
`:136`, `:167`, `:200`; `backend/app/modules/events/worker/service.py:38`,
`:48`, `:58`, `:71`.

Previously, repository helpers accepted session factories and committed/rolled
back their own transactions. They now accept an AsyncSession, require an active
transaction for writes, and only query/update/flush. The worker-specific service
owns session lifetime and explicit short transactions. Runtime publication remains
after the committed claim, preserving fencing and network isolation.

`test_worker_repository_stages_claim_inside_caller_transaction` proves a write
without a caller transaction is rejected, a staged claim remains invisible to an
independent connection, and the token/owner become visible only after the caller
commits. It passed. The other write helpers have the same inspected ownership
pattern; their rollback branches were not separately injected in this review.
Actual worker-process tests also pass with the isolated service import, avoiding
the intermediate mapper-initialization failure recorded by implementation.

## Executed checks

Environment: Windows, Python 3.12.13 in `backend/.venv-m6-dev`, existing installed
locked dependencies. PostgreSQL 16 and Redis 7 checks use unique disposable
projects/databases/namespaces. Commands from the repository root:

```powershell
./scripts/validate.ps1 -PythonExecutable backend/.venv-m6-dev/Scripts/python.exe -Gate backend-static -NoInstall
./scripts/validate.ps1 -PythonExecutable backend/.venv-m6-dev/Scripts/python.exe -Gate backend-unit -NoInstall
./scripts/validate.ps1 -PythonExecutable backend/.venv-m6-dev/Scripts/python.exe -Gate backend-integration -NoInstall
```

| Check | Result |
|---|---|
| backend-static | Passed: Ruff lint, format check (200 files), mypy (140 source files). |
| backend-unit | Passed: 270 tests, including eight worker cases; one existing Starlette/httpx deprecation warning. Ran outside the sandbox to avoid the previously confirmed Windows async socket limitation. |
| backend-integration | Passed: all 272 cases, including all 13 worker cases, against disposable PostgreSQL 16/Redis 7. Clean upgrades and the subsequent `alembic check` passed with no new upgrade operations. Existing deprecation warnings remain. Allocated database and owned Compose containers/network were removed; command exited 0. The previous auth accounting failure did not recur. |
| Two live worker processes, forced recovery and graceful stop | Two processes paused at the existing after-claim hooks held distinct event IDs/tokens under two owners. Both were alive simultaneously, forcibly killed, and allowed to expire. Two restarted actual `app.worker` processes published exactly two original UUID references with PostgreSQL observations, then both exited gracefully with code 0. |
| Held-row-lock overlap | Passed in a fresh disposable database: hold a due delivery with FOR UPDATE; invoke `EventWorkerService.claim_due_deliveries` on another session under a two-second assertion deadline; observe no claim while the lock is held, then exactly that delivery after release. No sleep is used to infer lock overlap. |

Manual checks used inline Python through the same interpreter, the existing
`scripts/validate.py::services` and `test_support.disposable_postgres` helpers,
and `test_event_worker` process/seed helpers. Migrations targeted only allocated
unique test databases. No harness/test source was written. Each manual service
project/database/container/network was removed.

The first combined manual harness completed all two-worker assertions, then
failed in its separate lock scenario because a synchronous seed helper invoked
`asyncio.run()` from inside an active async loop. This was a reviewer harness
error, not a worker failure. The lock scenario was rerun with seeding before
entering the async loop; it exited 0 after both locked/unlocked assertions and
cleanup. No production or test code was changed.

## Schema, interfaces and coverage limits

No schema/migration, model/metadata, HTTP endpoint/response, frontend, dependency
or runtime image changes are introduced by this fix. Internal worker repository
write signatures now require caller-owned AsyncSession transactions; the runtime
uses `EventWorkerService`. Application database revision was not inspected or
migrated; developer volumes were untouched.

The earlier two-worker and held-lock coverage gaps are addressed by the manual
checks. A lost XACK response is injected after real Redis execution, not induced
with a network proxy. Remaining unexecuted subcases include repeated-failure
backoff/batch saturation under sustained default-budget load, database-stalled or
full-batch shutdown, lost XREADGROUP responses, malformed/conflicting-reference
rejection, metric-field output and large retained-history query performance.
These limits are not replaced by test counts.

Omitted: locked reinstall, baseline, frontend-static/tests/build, browser,
separate clean/seeded legacy migrations, image, final PR CI and full ten-gate
acceptance. No frontend/schema/image changes require their corresponding gates
for this slice. Later consumer receipt/effect uniqueness, poison retries, replay,
projections, scoped alerts and five-second freshness remain unverified here.

## Historical review and implementation evidence

At `8890661`, the independent review recorded 5 Passed/1 Failed criteria and
F1 (P2 acknowledgement recovery) / F2 (P3 repository-owned transactions).
Static and 270 unit cases passed. Integration recorded 267 passed/one unchanged
auth fixed-window accounting failure; its isolated rerun and a separate drift
check passed. That full integration run was not reported as passed. The original
implementation had recorded Python 3.13.15 with 268 integration cases passing.

The fix implementation follow-up recorded Python 3.13.15: static, 270 unit cases,
272 integration cases and Alembic drift passed. An intermediate producer-service
import caused six worker subprocess mapper-initialization failures; isolating the
worker service fixed those before its final passing run. Those are historical
implementation results, distinct from this independent Python 3.12 execution.
The earlier F1/F2 conclusions and pending-rerun wording are superseded by this
post-fix review; full Milestone 8 acceptance remains open.
