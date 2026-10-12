# Milestone 8 Issue #34 / T4 verification

Reviewed: 2026-10-12 (Asia/Bangkok).

**Result: Issue #34 is not ready for acceptance.** A reproduced acknowledgement
recovery defect strands current-consumer pending references after a transient
failure. A separate repository transaction-ownership violation needs correction.
Existing worker tests pass but do not cover the reproduced path. Full Milestone 8
acceptance remains open.

## Scope and sources

Reviewed latest commit: `8890661feb68829b839240df4e0d4d18c0f0d985`
(`feat(events): add standalone Redis Streams worker`), on
`milestone8/issue34-relay&worker`.
Comparison base: first parent `fb93d270bec765abe0bc7c57abb83cac8548e94d`.
Working tree was clean at review start. F1/F2 concern newly introduced code.
Only this report is rewritten; implementation, tests, configuration, other
documents and GitHub state are unchanged.

Sources:

- [GitHub #34](https://github.com/ShinningF1eld/RestaurantOS/issues/34), fetched
  live: open, six unchecked bullets, dependency
  [#31](https://github.com/ShinningF1eld/RestaurantOS/issues/31).
- Approved [M8 design revision 1](milestone-8-design.md),
  [task plan T4](milestone-8-task.md), and
  [master roadmap M8](../../RestaurantOS_Master_Roadmap.md#milestone-8--reliable-background-jobs-and-domain-events).
- [README](../../README.md), [current state](../current-state.md), root
  engineering instructions, ADRs
  [0001](../adr/0001-modular-monolith.md)/[0002](../adr/0002-feature-modules.md),
  [events](../api/events.md), [Redis architecture](../architecture/redis.md),
  [worker runbook](../runbooks/event-worker.md) and
  [testing commands](../testing/README.md).

Local T4 checkmarks and historical implementation results are not independent
acceptance. R3/R4/R5/R11/R13 are assessed within transport scope. Consumer effects,
receipt transactions, poison retry policy and replay belong to T5; projections,
alerts, initialization and freshness remain later work.

## Acceptance criteria and evidence

AC1-AC6 follow GitHub's six bullets in order. Coverage: **5 Passed, 1 Failed,
0 wholly Untested criteria**, with unexecuted subcases disclosed below. Passes
combine inspection and fresh execution; they do not erase the separate
architecture finding or establish full milestone acceptance.

| ID | Assessment and evidence |
|---|---|
| AC1: Redis 7 references, authoritative typed facts, independent groups and non-subscriptions | **Passed — inspection and healthy-path regression execution.** Streams use Redis 7-compatible commands; messages contain exactly UUID/type/version/correlation. `load_stored_delivery` reconstructs typed PostgreSQL facts; routing compares metadata against them and uses the fixed registry. Real entrypoint/group tests check minimal fields and alerts acknowledging an unsubscribed completion. Transient acknowledgement recovery fails AC4. Malformed/conflicting-reference rejection is inspected, not separately executed. |
| AC2: bounded short claims, leases/fencing, budgets and no business locks during network I/O | **Passed — functional inspection and regression execution.** Claims select due pending subscriptions, limit batches, use `FOR UPDATE SKIP LOCKED` on delivery rows and assign unique owner/token/expiry. Claim transaction ends before XADD; observation/cooldown updates require the same unexpired owner/token. Claimant test checks one winner and stale-token rejection after reclaim; backlog test claims 10 of 25. Config tests/runbook document bounded batch/concurrency/lease/read/scan/backoff/grace settings. Repository transaction ownership separately violates ADR 0002 (F2). Two complete concurrent workers and held-lock overlap are not demonstrated by the claimant test. |
| AC3: publication is not completion; bounded PostgreSQL/PEL/group/content-loss recovery | **Passed — inspection and real-process regression execution within T4.** Publication updates `published_at`, never delivery completion/attempt count. Bounded scans reset old observations after empty-stream detection; stall eligibility republishes the same UUID. Process tests cover claim crash, post-XADD crash, other-owner PEL reclaim, namespaced stream deletion and physical nonpersistent Redis restart. Required subscriptions remain pending for T5. Tests accelerate lease/scan/idle values; sustained default-budget load is unmeasured. |
| AC4: ambiguity/crash/fencing/due-time authority without lost or flooded recovery | **Failed — acknowledgement recovery subcase; other subcases passed.** Crash/stale-token tests preserve UUID/pending state; early-reference/outage tests preserve due times and zero event attempts. A failed XACK leaves the entry owned by the current consumer, which all later PEL scans exclude; new reads cannot return it again (F1). No PostgreSQL event loss was demonstrated: transport cleanup/recovery stalls until ownership changes. Batch/backoff controls and 25-row claim boundary have evidence; sustained flood behavior with overlapping workers is unmeasured. |
| AC5: separate startup/shutdown, forced recovery and API Redis isolation | **Passed — inspection and regression execution, with shutdown limits.** `app.worker` launches neither API nor migrations and owns its Redis pool. Tests run the actual entrypoint, gracefully stop it and kill/restart paused workers. Unit tests compare worker 2 s/eight connections with API 100 ms/20 connections. Developer Redis persistence is unchanged. Cancellation/close budgets are inspected; database-stalled and full-batch shutdown are untested. |
| AC6: retained visibility and no automatic deletion/trimming | **Passed — inspection and regression execution.** Recovery logs stream/PEL/unfinished and event/delivery/receipt/attempt counts through allowlisted JSON fields. No event/history deletion, XTRIM or capped XADD is introduced. Complete metric output and large-history counter performance are not separately asserted. |

Primary suites: `backend/tests/unit/test_event_worker.py` (eight cases) and
`backend/tests/integration/test_event_worker.py` (nine cases), alongside existing
event storage/producer, authorization/stock and Redis/auth regressions.

## Findings

### F1 — P2: retryable routing/ack failures strand the current owner's PEL

Locations: `backend/app/modules/events/worker/runtime.py:383`, `:389`, `:438`
and `:474`; `backend/app/modules/events/worker/streams.py:218`.
Requirements: issue AC4; design R3/R5 and durable-delivery recovery.

Trigger: XREADGROUP assigns an entry, then its PostgreSQL read or XACK fails
transiently. The outer loop logs/backoffs, but `_claim_abandoned` excludes entries
owned by the current consumer. Reads use `>`, so the entry never returns to routing
in that process, even after the idle threshold and infrastructure recovery.
This also affects a reclaimed entry when routing fails after ownership transfer.

Expected: bounded retry of retryable owned references, preserving persisted due
times and avoiding busy reprocessing of deliberately unfinished T4 subscriptions.
Actual: another worker or restart with a different identity must reclaim it.
Republishing creates a different Stream ID and cannot acknowledge the old entry;
non-subscriptions have no PostgreSQL delivery of their own to schedule cleanup.
Impact: repeated transient failures grow stale PEL entries and misleading pending
counts, while a lone healthy worker cannot complete their transport cleanup.
This is not evidence of lost PostgreSQL facts or duplicated business effects.

Reproduction: inline Python launched and removed a dedicated Redis 7 container
through `support.owned_redis.owned_redis`, inserted an order.submitted reference
and ran the actual alerts `_consumer_loop`. One connection failure was injected
before the first XACK. PostgreSQL loading was replaced only for this transport
scenario with a validated immutable non-subscription `StoredDelivery`; this is
not an end-to-end database/authorization test. Reads blocked 100 ms and the idle
threshold was 1 ms:

```text
After transient XACK failure: read iterations=4, XACK attempts=1,
pending=1, owner=review-worker.alerts, idle_ms=583
Other owner recovery: XACK attempts=2, pending=0
```

Assertions confirmed no same-owner retry and successful other-owner reclaim;
the scenario exited 0. No source/test files or application database were used.
Suggested correction: retain bounded retry state for routing/ack failures or
read eligible owned PEL entries with backoff and authoritative due checks.
Add same-worker recovery regressions for failed PostgreSQL reads, XACK failure
before server execution and ambiguous XACK responses, without restart or a new
publication.

### F2 — P3: worker repositories own and commit write transactions

Locations: `backend/app/modules/events/repo/worker_queries.py:77`, `:131`,
`:162` and `:196`.
Authority: root AGENTS.md, ADR 0002 and approved architecture;
`docs/api/events.md:133` says repositories do not commit.

These helpers accept a session factory, open sessions and enter `session.begin()`.
Normal exit commits inside the repository; exceptions roll back there. The claim
docstring explicitly promises a commit. This contradicts service-owned
transactions, although current transport transactions are short and correctly
precede network I/O. Persistence helpers now own use-case session/transaction
lifetime, preventing caller composition under the documented boundary and
providing a conflicting pattern for T5. No current business atomicity loss was
demonstrated.

Suggested correction: move transaction/session ownership to the events application
service or worker orchestration. Repository functions should accept an active
AsyncSession and query/update/flush without commit/rollback. Preserve short
claim transactions, ownership fencing and claim-before-network sequencing.

## Executed checks

Environment: Windows, Python 3.12.13 in `backend/.venv-m6-dev`, existing installed
locked dependencies; disposable PostgreSQL 16/Redis 7 with unique projects,
databases and namespaces. Commands from repository root:

```powershell
./scripts/validate.ps1 -PythonExecutable backend/.venv-m6-dev/Scripts/python.exe -Gate backend-static -NoInstall
./scripts/validate.ps1 -PythonExecutable backend/.venv-m6-dev/Scripts/python.exe -Gate backend-unit -NoInstall
./scripts/validate.ps1 -PythonExecutable backend/.venv-m6-dev/Scripts/python.exe -Gate backend-integration -NoInstall
```

| Check | Result |
|---|---|
| backend-static | Passed: Ruff lint, format check (199 files), mypy (139 source files). |
| backend-unit | Passed outside sandbox: 270 tests, including eight worker cases; one existing Starlette/httpx warning. Initial sandbox run stalled at the first async auth case and was interrupted, not counted as a pass. |
| backend-integration | **Failed: 267 passed, one failed**, 799 existing deprecation warnings. All nine worker cases passed. `auth/test_redis_admission.py::test_refresh_known_family_accounting_and_storage_error_release` failed at line 366: seven family-bucket entries versus ten expected. The gate stopped before its Alembic drift check; owned database/services/network were removed. |
| Manual acknowledgement recovery | Reproduced F1 with real disposable Redis and injected fact reader/one failed XACK; assertions passed, container removed. |
| Isolated auth rerun and Alembic drift | Passed: the single failed auth case passed in 2.25 s in a fresh disposable database; clean upgrade and `alembic check` passed with no new upgrade operations. Owned database, containers and network were removed. This focused rerun does not turn the full gate into a pass. |

Initial sandbox integration failed before tests because Docker named-pipe access
was denied; approved execution used only disposable resources. This environment
failure is distinct from the executed test failure. No code was changed to obtain
a pass.

The focused follow-up used the repository's existing disposable helpers and
committed interpreter, without writing a harness file:

```powershell
@'
import sys
sys.path.insert(0, 'scripts')
from validate import services, run, BACKEND
from test_support.disposable_postgres import disposable_database
with services(False) as env:
    with disposable_database(prefix='restaurantos_review34', test_url=env['TEST_DATABASE_URL']) as database:
        isolated = database.environment(env)
        run(sys.executable, '-m', 'alembic', 'upgrade', 'head', cwd=BACKEND, env=isolated)
        run(sys.executable, '-m', 'alembic', 'check', cwd=BACKEND, env=isolated)
        run(sys.executable, '-m', 'pytest', 'tests/integration/auth/test_redis_admission.py::test_refresh_known_family_accounting_and_storage_error_release', '-q', cwd=BACKEND, env=isolated)
'@ | backend/.venv-m6-dev/Scripts/python.exe -
```

Auth source and this test are unchanged from the comparison base, verified with
`git diff --exit-code HEAD^ HEAD -- backend/app/modules/auth
backend/tests/integration/auth/test_redis_admission.py`. The failed expectation
uses real fixed-window Redis accounting; expiry across a window boundary is a
possible explanation, not a proven diagnosis. No base-revision execution or
controlled Redis-time reproduction was performed, so exact failure attribution
remains uncertain. It is not a demonstrated T4 worker regression, and the full
integration gate is not reported as passed.

## Schema, interfaces and coverage limits

No migration, model/metadata change, HTTP endpoint/response, frontend, dependency
or runtime image change. T4 uses the existing T1/T2 schema and adds
`python -m app.worker`, relay/recovery operations, typed EVENT_WORKER settings
and structured logging. Application database revision was not inspected or
migrated; developer volumes were unchanged.

Untested subcases: two simultaneous complete worker processes; deterministic
held-lock overlap (the existing barrier precedes query entry); actual lost XACK
response; sustained default-budget backlog/flood load; busy/database-stalled
shutdown; and separate malformed/conflicting-reference rejection scenarios.
These gaps are not silently represented by the passing worker regressions.

Omitted: locked reinstall, baseline, frontend-static/tests/build, browser,
separate clean/seeded legacy migrations, image, final PR CI and full ten-gate
acceptance. No frontend/schema/image changes require their corresponding gates
for this slice. Consumer receipt/effect uniqueness, eight-attempt retries,
operator replay, projections, scoped alerts and five-second freshness belong to
later issues and are not judged complete here.

## Historical implementation verification

The replaced report recorded Python 3.13.15: 270 unit tests, 268 integration
tests with no Alembic drift, backend-static and eight focused worker unit cases
passed, following corrected formatting/synchronization attempts and sandbox
limitations. Those results are historical context, not this review's execution
or evidence against F1/F2. Python 3.12 was available for this independent review.

## Post-review implementation follow-up — 2026-10-12

The independent review above records its findings and assessment at review
time. This follow-up records later changes on
`milestone8/issue34-relay&worker`; it does not replace independent verification
or claim independent acceptance.

### F1 — addressed in implementation; independent rerun pending

`EventWorker._consumer_loop` now keeps a bounded retry schedule per consumer for
transient PostgreSQL reads and Redis transport/acknowledgement failures. Retries
use the existing infrastructure backoff bounds and stop new reads while a retry
is due, so the queue cannot grow beyond one bounded read batch. Before retrying,
the worker confirms the exact Redis ID remains in that group's PEL under the
same consumer and reloads its fields. If an XACK succeeded but its response was
lost, the absent PEL entry clears the retry without repeating the acknowledgement
or publishing another stream entry. Ordinary subscribed T4 work still remains
pending without repeated routing while Issue #35's handler/receipt lifecycle is
absent.

The integration regression runs the real worker loop against PostgreSQL 16 and
Redis 7 for three injected one-time failures: PostgreSQL fact loading, XACK before
server execution, and an XACK response lost after the Redis command succeeds.
It proves same-consumer recovery, an empty final PEL and exactly one existing
Stream entry (no republish). These tests passed in the full integration run.

### F2 — addressed in implementation; independent rerun pending

`repo/worker_queries.py` now takes an active `AsyncSession`, requires an active
caller transaction for writes, and only queries, updates and flushes. Session
lifetime and short write transactions are owned by
`worker/service.py` (`EventWorkerService`), outside the repository. The service
lives in the worker module so standalone process startup does not import the
producer service's `EventRepository` and partially initialize unrelated ORM
mappers. A real subprocess test caught and verified this isolation correction.
An integration regression proves writes require a caller transaction and remain
uncommitted until that caller commits.

### Follow-up validation

Available interpreter: Python 3.13.15. Commands from repository root:

```powershell
backend\.venv\Scripts\python.exe scripts\validate.py --gate backend-static --no-install
backend\.venv\Scripts\python.exe scripts\validate.py --gate backend-unit --no-install
backend\.venv\Scripts\python.exe scripts\validate.py --gate backend-integration --no-install
```

| Check | Follow-up result |
|---|---|
| backend-static | Passed: Ruff lint, format check (200 files), and mypy (140 source files). |
| backend-unit | Passed: 270 tests, including eight worker unit cases. The first restricted-sandbox attempt stalled in the existing Windows async auth socket test; rerunning outside that process sandbox passed. |
| backend-integration | Passed: 272 tests against disposable PostgreSQL 16 and Redis 7; the subsequent `alembic check` reported no new upgrade operations. 807 existing deprecation warnings. All worker integration cases passed. Disposable Compose resources and database were removed. |
| Targeted subprocess confirmation | Passed: `test_real_worker_entrypoint_relays_reference_and_shuts_down_gracefully` passed after isolating the worker service module. The full integration gate also passed all subprocess crash/restart cases. |

The first follow-up integration attempt, before moving `EventWorkerService` out
of the producer service module, failed six real-process cases because mapper
initialization could not resolve the `Menu` relationship. The worker-specific
service module fixed that regression; the targeted process test and subsequent
full integration gate passed. No schema, API, runtime image or dependency change
was made. Production logging contains no diagnostic exception detail.

The original independent AC4 failure and F1/F2 findings remain preserved above
as review-time results. The new regressions and gate results are implementation
evidence only; a separate verification rerun is still required before Issue #34
can be described as independently accepted. Other listed coverage limits and
full Milestone 8 acceptance remain open.
