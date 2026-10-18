# Milestone 8 regression map

The authoritative scope is [approved design revision 1](../milestone8/milestone-8-design.md).
This map identifies executable coverage, not a claim that every gate or milestone
exit criterion has passed. See [issue #40 verification](../milestone8/verification-milestone8-issue40.md)
for dated commands, outcomes and omissions.

All paths below are relative to `backend/tests/` unless stated otherwise.

| Requirements / failure boundary | Required gate and coverage |
|---|---|
| R1/R2 atomic business/audit/event/delivery rollback, no-op/replay, stock/money/authorization | `backend-unit` and `backend-integration`: `test_event_producers.py`, `test_inventory_episodes.py`, existing order/inventory/tenancy transaction suites. Real insert/flush/audit failures roll back complete writes. |
| R3/R4 API killed after commit, including ambiguous publish and stream loss | `backend-integration`: `test_event_producer_process.py` kills an authenticated real API at its commit barrier; a standalone production worker completes all retained subscriptions. Receipts match every delivery; actual alert, notification and diagnostic effects are checked. |
| R3/R4 relay ambiguity, pending reclaim, physical Redis restart/loss | `backend-integration`: `test_event_worker.py` uses worker processes, owned nonpersistent Redis, independent groups and original event identities. The physical-restart case finishes through the production consumer and asserts one receipt/diagnostic. |
| R4 crash before consumer commit / after commit before ACK | `backend-integration`: `test_event_execution.py`, `test_analytics_projection.py`, `test_alert_projection.py` kill real processes at explicit barriers and verify atomic actual effects and receipt-checked recovery. ACK ambiguity covers failure before execution and a lost response after actual XACK. |
| R5/R6 eight attempts, persisted due times, poison isolation/replay | `backend-integration`: `test_event_execution.py` includes controlled-clock boundary tests and a real-clock worker process restarted during backoff. Eight failures remain inspectable; the other consumer succeeds once; replay after handler repair adds one receipt/effect while retaining ten total attempts across both consumers and replay. |
| R5 infrastructure outage, unsupported version/payload, expired claim fencing | `backend-unit` / `backend-integration`: event execution/worker suites, real PostgreSQL connection termination, physical Redis outage/restart, immediate retained version/payload failures, stale-token fencing and allowance refunds. |
| R7 daily-row overlap, tombstones and rebuild watermarks | `backend-integration`: `test_analytics_projection.py`, `test_event_maintenance.py`; exact decimal/creation-date SQL reconciliation, real lock overlap, deletion permutations, queued stale events and retained receipts. Dashboard remains live SQL. |
| R8/R9 close-before-open, new episode, replenishment/stub boundary | `backend-integration`: `test_inventory_episodes.py`, `test_alert_projection.py`; producer episode identity, revision-fenced current state, immutable history, deduplicated outcomes and both stock-lock timing boundaries observed in PostgreSQL. |
| R10 current tenant/role/assignment/revocation | `backend-integration`: `test_alert_reads.py`; collections/counts/pages, foreign/unassigned 404 and forbidden/revoked 403. `browser`: `frontend/tests/alerts.spec.ts`. |
| R11 safe inspection, correlation and replay provenance | `backend-unit` / `backend-integration`: contracts, producers, worker and execution CLI tests; original event/correlation retained, database role provenance, safe failure categories and redaction. |
| R12 visible cadence, stale/error/retry, pages and editor preservation | `frontend-tests`: `InventoryAlerts.test.tsx`, `InventoryManager.test.tsx`. `browser`: real API/worker inventory journeys in `alerts.spec.ts`; auth traces remain off. The measured five-second processing target belongs to #41. |
| R13 initialization, suppressed baselines/reruns, retained history | `backend-integration`: `test_event_maintenance.py`, alert projection suite. `migrations`: clean/seeded upgrades, backup/restore CLI rehearsal, stock/replay/history preservation and downgrade guards in `scripts/verify-migrations.py`. |
| R14 required coverage and cleanup | `backend-unit`: `test_validation_policy.py` checks actual CI structure, all ten gates, aggregate enforcement, broad integration selection and failure cleanup. `backend-integration`: `test_validation_cleanup.py` raises after real worker startup and verifies owned process/database/Compose teardown. `browser` additionally requires a deliberately failing Chromium assertion and verifies the intended failure plus container/source-copy cleanup. |

Use the existing full command; worker coverage is included rather than opt-in:

```powershell
./scripts/validate.ps1 -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
```

The supported interpreter is Python 3.12 and Node is 24. The full command installs
committed locks and runs all ten gates. Selected gates or `-NoInstall` are partial
verification. No validation migrates the application database. Test services use
unique Compose projects/random loopback ports; suites allocate guarded `_test`
databases. Cleanup acts only on owned resources. Concurrency evidence uses
barriers/observed locks; bounded polling observes state and is not proof of overlap.

The real poison regression deliberately waits through the production one-second
exponential schedule to its 60-second cap (about two minutes). Only the test
entrypoint selects the failing sink and zero jitter. Production has no test flags.
Existing controlled-clock tests cover early delivery and exact due boundaries.

The refresh-family accounting regression uses real Redis server time to choose
a known open fixed window ending ten minutes after observation. It asserts all
ten charge expiries equal that endpoint, then retains the original exact count,
throttle and storage-error release assertions. This avoids assuming ten real
rotations cannot cross a minute boundary; the independent lease/fixed-window
expiry test remains unchanged. No production auth clock, limits or deadlines are
modified.

The browser gate runs its ordinary production-copy workflow first, then a
separate `--inject-failure` run. The latter must return 1, generate exactly the
`diagnostic failure` JUnit failure, and leave no newly owned containers or source
copies. It also requires a fresh `cleanup-complete.json` attestation written only
after the intended test failure unwinds all successful cleanup contexts. Process
wait, database drop, Docker teardown and source-copy cleanup errors cannot attest
success. A build/startup/unrelated failure cannot satisfy the probe. Normal safe
artifacts remain under `test-results/browser`; expected-failure evidence is under
`test-results/browser-cleanup`. The CI artifact upload already retains both for
seven days. Process cleanup attempts every child, waits after terminate/kill, and
reports cleanup errors after all children have been attempted.

`image` continues checking locked/nonroot image contents, API liveness and startup
without migration. T10 changes no runtime image or entrypoint; it adds no image
behavior or deployment claim. Final PR CI under unchanged `Milestone 6 acceptance`
and #41's freshness/operational evidence are separate requirements; local passes
cannot substitute for either.
