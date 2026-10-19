# Milestone 8 bounded busy-reference compatibility review

Reviewed: 2026-10-19 (Asia/Bangkok). Sources: the request to implement the first
busy-reference improvement, preserve other behavior and repeat the same benchmark;
[authoritative M8 design](milestone-8-design.md), particularly R3–R5/R11–R14;
[worker runbook](../runbooks/event-worker.md); and the
[dated measurement comparison](performance-milestone8-busy-retry.md).

Comparison base / repository head:
`3c0da95ffebcdd20b499d39cc2be9d9407a8833a`. Reviewed changes are uncommitted on
top of that baseline. The measurement report records both modified production
file SHA256s, the unchanged benchmark SHA256 and exact retained raw cells.
Environment: supported Python 3.12 / Node 24, Windows 11, real disposable
PostgreSQL 16 / Redis 7, production worker and production-built Chromium frontend.

## Result

No change-induced functional defect was found in the inspected paths and executed
regressions. All ten shared gates passed. The scheduling change preserves the
existing authoritative execution path and changes only short revisits of
`delivery_missing_or_busy`, with bounded residency/revisit count and normal
durable recovery as fallback.

The five-second target remains unmet at paced and pressure loads. The same five
workloads completed correctly, with improved worst-case tails and no light-load
five-second exceedances, but paced/pressure P95 and proven miss counts worsened.
This is not evidence that general performance stayed the same or improved.
No production deployment, application-database operation or new remote CI run was
performed. Local passing gates do not establish CI for uncommitted changes.

## Criteria and coverage

| Criterion | Status | Evidence | Limit |
|---|---|---|---|
| Brief busy references get short bounded revisits | Passed | Source inspection; real held delivery lock followed by same-reference completion without relay/recovery loop; retained light trace | Eligibility delay is 50–250 ms; bounded ordinary work/I/O can delay actual dispatch |
| Fresh work continues during contention | Passed | Real lock stays held until an unrelated diagnostic commits; pure full-queue/overflow and interleaving cases | One serial execution loop per group remains; no parallelism claim |
| Probe count and resident references are bounded | Passed | Unit cases: 20 revisits then fallback, overflow gets no local revisits; source cap at recovery batch size | Missing subscribed deliveries share the busy outcome and fall back after the same bound |
| Ownership, due times, claims and receipts remain authoritative (R3–R5) | Passed | New real Redis ownership-transfer and persisted-future-due branches; existing overlap, fencing, post-commit ACK/crash and duplicate suites | Same-owner metadata check reuses existing semantics; PostgreSQL fencing/receipts remain the correctness boundary |
| No charged processing attempt while row remains locked | Passed | Real concurrent lock test queries attempt rows before release; one effect/receipt/attempt after release; all 1,980 healthy benchmark effects have one successful attempt | A real started/failed handler retains the existing failure policy |
| Eight-attempt backoff, outage handling, successful-consumer isolation and replay (R3–R6) | Passed | Full real PostgreSQL/Redis integration, including real-clock poison-worker restart and existing transient PEL/XACK cases; unchanged operational benchmark rehearsal | No new outage completion-time guarantee |
| Business/security/projection/UI contracts (R1/R2/R7–R10) | Passed | No producer/domain/handler/auth/API/schema/frontend/config changes; full backend, component/client and Chromium gates | Regression evidence covers defined cases rather than all possible interleavings |
| Correlation, retention and maintenance (R11/R13) | Passed | Safe existing routing log fields reused; same IDs in trace; full maintenance/retention tests and five scoped CLI initialize/rerun/rebuild/reconcile checks | No pruning, external notifications or new operational permission |
| Same reproducible workload and honest reporting (R12) | Passed | Unchanged script SHA/version; automated equality of settings, versions, migration, event mix, parameters and polling across all five paired cells | Serial historical comparison, not a randomized/interleaved control |
| Five-second processing at paced/pressure loads | Failed | New paced pooled P95 18.670/20.094/19.447s; pressure 74.271/74.807/74.762s; 1,602 proven misses / 1,980 overall | Known target gap persists; observed percentile worsening cannot be attributed solely to the change from these serial runs |
| Full local shared gates (R14) | Passed | Locked-install full run, all ten gates, clean/legacy migration and cleanup probes; final retained-artifact baseline recheck | No local gate omitted |
| Attribution of worsened paced/pressure P95 | Untested | Serial before/after distributions are retained and reported | No interleaved unchanged-worker control was run |
| New-head CI | Untested | Changes remain uncommitted/unpushed; the earlier published baseline's CI is a separate result | Requires publication and a new workflow run |

## Findings and remaining performance work

No new functional blocker was identified. The performance limitation remains
actionable: `backend/app/modules/events/worker/runtime.py::_relay_loop` still
sleeps 1,500 ms after every batch of at most ten claims. At the paced 5.5 subscribed
deliveries/second, its theoretical 6.67-publications/second ceiling before actual
SQL/Redis work leaves little headroom. Backlog peaks at 94–102 in the new paced
cells and 361 under pressure. The next separate experiment should measure bounded
consecutive relay batches while backlog exists, retaining outage backoff and
claim fencing. That change was not implemented here.

Paced pooled P95 worsened from 16.268/18.168/17.352s to
18.670/20.094/19.447s. Pressure P95 worsened from 68–69s to 74–75s. The distribution
change is observed; attribution to the new probes versus host variation is
uncertain without a matched interleaved baseline. Do not present the lower maxima
as proof of an overall performance improvement. Light load now has zero upper
exceedances and max 3.809s versus two proven misses/max 63.967s before; no
five-second guarantee for other loads follows.

## Executed checks

| Command / procedure | Outcome |
|---|---|
| `./scripts/validate.ps1 -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe` | All ten gates passed: 301 unit, 336 integration, 10 client, 19 component and 29 Chromium tests; static/build/migrations/backup-restore/cleanup/image passed |
| Same five commands in `docs/testing/event-freshness-benchmark.md`, only output names changed | Five exit-zero cells; 1,440 events / 1,980 correct effects; zero healthy charged retries/failures/unfinished work; graceful exit and maintenance reconciliation in every cell |
| First paced `--operations` cell | CLI inspect/repair/replay, original event identity, successful analytics isolation, queued-work forced stop/stream loss and graceful recovery passed |
| Retained JSON comparison | Script hash/version, server versions, migration head, worker settings, event mix, rate/concurrency/polling/dataset equal to the corresponding original cell |
| `backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --no-install` | Post-measurement artifact check passed; exactly 15 reviewed non-secret revision/fingerprint metadata entries added without changing detectors, filters or prior entries |
| `git diff --check`, measured source SHA256 comparison and owned-resource inspection | Passed; production/benchmark sources still match measured manifest; all seven observed owned Compose projects have zero containers |

Ignored command logs use the `test-results/busy-retry-` prefix. The measurement
report discloses the initial ownership-test observer race, its explicit barrier
correction and the restricted Windows loopback unit-run interruption. Final full
validation passed with the corrected tests and recorded final production source.
No implementation changes were made as part of this report-only review.
