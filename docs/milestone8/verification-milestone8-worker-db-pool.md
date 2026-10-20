# Milestone 8 worker database-pool verification

Publication note: after this local review, the user authorized committing and
merging the stacked branches into main. The uncommitted/untested-PR-CI statuses
below describe the local review checkpoint; the associated GitHub PR records
subsequent publication checks. Local evidence does not substitute for those checks.

Review date: 2026-10-20 (Asia/Bangkok). Base: relay checkpoint f1d61c1;
uncommitted implementation on `codex/m8-worker-db-pool`. Authoritative sources:
[design revision 1](milestone-8-design.md), [issue #41](https://github.com/ShinningF1eld/RestaurantOS/issues/41),
T11 criteria, root AGENTS and the existing M8 regression map/runbooks. This is the
implementing agent's review using `review-verify`, not an independent review.
The measured source hashes, seven raw control/experiment files and all latency
results are in [the comparison](performance-milestone8-worker-db-pool.md).

## Scope and current evidence

Only the standalone worker's PostgreSQL resource ownership changes. API session
infrastructure, producer/handler code, consumer transaction boundaries, fencing,
eight attempts, due-time authority, receipt/ACK ordering, relay/busy scheduling,
schema/API/UI/dependencies remain unchanged. The worker owns and disposes one
bounded pool per invocation instead of importing the API's global factory.
The crash-process test helper uses that same pool factory. No migrations needed.

The fresh control reproduced the sink backlog; disabling busy revisits did not
improve it. All five pooled benchmark cells completed 1,980 correct effects,
zero healthy charged retries/failures/missing/unfinished deliveries and zero
five-second exceedances, maximum 2.009s. This removes a test-mode `NullPool`
penalty: normal-mode workers already pooled connections. An equivalent
production throughput gain is untested and is not claimed.

Initial unit validation found an incorrect `AsyncEngine.hide_parameters` access
in the new test (three parameter cases). It was corrected to the underlying
sync engine property. All 312 unit tests then passed. A separate static check
stopped on the modified process helper's formatting; formatting was corrected
and the full backend-static gate passed. Neither development failure changed
production behavior or justified weakening an assertion/gate.

## Final validation

The complete locked-install command passed on 2026-10-20 with exit zero and
`PASS: full validation`:

```powershell
./scripts/validate.ps1 -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
```

All ten gates passed: baseline; backend-static (Ruff/format/mypy); frontend-static
(ESLint/Prettier/TypeScript); 312 backend-unit tests; 339 backend-integration tests;
10 client and 19 component tests; production frontend build; clean/seeded legacy
migrations, model drift, backup/restore, maintenance and guarded downgrades;
29 Chromium workflows and intentional-failure cleanup; nonroot runtime-image
build, contents/secret inspection, health/DB connection and no-startup-migration
smoke checks. The previously intermittent auth admission case passed in this full
run; its historical cause remains unproven. No check was weakened or skipped.

Earlier partial commands, before the final full run:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-unit --gate backend-static --no-install
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-static --no-install
```

The first command's development failures and corrected rerun are described above;
the separate static command passed. Benchmark reproduction is the five exact
commands in [the procedure](../testing/event-freshness-benchmark.md), with output
prefix `worker-db-pool-`; all exited zero, including `--operations` on paced-1.
The two additional controls use the paced command without `--operations` and
separate output paths, with the exact temporary control edit/fingerprint retained
in the comparison. All seven raw cells have unique event/consumer samples and
ordered lower/upper timing bounds; counts/settings/effects match the baselines.

## Acceptance review

No actionable change-induced functional defect was found in the inspected and
executed paths. The five-second documented local workload target now passes for
all observed effects. This is not evidence of equivalent production speedup:
normal-mode workers already pooled connections. Final PR CI for this new source
is untested; prior checkpoint CI is independently confirmed passing and remains
distinct. Criterion 5 therefore stays open for publication/CI, not local gates.

| Issue #41 criterion | Status | Evidence / boundary |
|---|---|---|
| 1. Dataset, environment, tuning, revisions, latency distribution/misses and reproducible command | Passed locally | Same version 1.0.0 script, five cells, source hashes and settings; P50/P95/P99/max, lower-bound misses and upper exceedances retained; no warm-up discard |
| 2. Honest consumer outcomes, regression/backlog/age/storage/stream and UI distinction | Passed | Two fresh controls and historical reports preserved; seven raw cells plus aggregate traces; pooled target passes, production gain untested, UI remains 15 seconds, no outage-time guarantee |
| 3. Repair/replay, shutdown, Redis loss, reconcile/rebuild/initialization | Passed locally | New paced-1 operational JSON; every cell's maintenance identities/reconciliation; full actual crash/fencing/duplicate/eight-attempt/restart/physical-loss suites with pooled process helpers |
| 4. Selected settings/contracts and deferred/deployment/retention boundaries | Passed by inspection/execution | Worker runbook documents a default maximum of six DB connections, no overflow, five-second checkout/pre-ping/disposal; API/handlers/transactions unchanged; maintenance pause/backup, no pruning/external delivery/dashboard cutover retained |
| 5. R1-R14/three exits, final full local gates and complete final PR CI | Passed locally; Untested final PR CI | All ten locked-install gates passed on the measured source; existing evidence/regression map and mapping below; checkpoint CI does not cover this new uncommitted change |
| 6. Actual application revision/cutover distinct; omissions and scope honest | Passed by inspection | Only guarded disposable databases migrated/queried; no application revision or cutover claim; representative normal-mode capacity and final PR CI remain untested |

| Requirements / roadmap exits | Current local evidence |
|---|---|
| R1/R2 atomic facts and stock/money/auth/idempotency | Full producer, order, inventory, catalog and tenancy suites; no domain/service/handler changes |
| R3-R5 recoverability, duplicate safety and bounded failures | Full worker/execution/producer-process suites, actual crash barriers and poison restart; pooled helper sessions preserve separate transactions; new PostgreSQL reuse/termination/disposal cases pass across independent loops |
| R6/R11 operator recovery and correlation | Full CLI/redaction tests and paced-1 failed inspect/repair/replay preserving original event, new replay provenance and successful analytics; safe aggregate traces retained |
| R7-R9 analytics, episodes, stubs and diagnostics | Full analytics/alert/inventory suites, 1,980 matching measured receipts/effects, exact totals/episodes/stubs/diagnostics and maintenance reconciliation |
| R10 scoped reads and UI permissions | Full assignment/revocation/tenant/role integration suites and 29 real Chromium cases; API/UI contracts unchanged |
| R12 healthy freshness and separate UI cadence | All five measured cells have zero lower-bound misses and zero upper exceedances, worst 2.009s; component/browser tests preserve 15-second visible UI polling |
| R13/R14 initialization, retention and validation | All maintenance, clean/legacy backup/restore/downgrade guards and ten local gates pass; no pruning; final PR CI remains untested |
| Exit: no silently lost committed event at tested failures | Actual API/consumer deaths, ambiguous publish/ACK, physical Redis loss and new operational reconstruction, complete subscribed receipts |
| Exit: duplicate-safe analytics/notifications | Lock/barrier overlap, revision/tombstone/episode/stub uniqueness and receipt-checked crash recovery; no missing/duplicate benchmark samples |
| Exit: safe inspect and replay after repair | Real poison failure, scoped CLI inspection/repair/replay with unchanged successful consumer and retained original/replay identity |

The detailed test-to-requirement inventory remains in the
[regression map](../testing/milestone8.md) and
[original issue review](verification-milestone8-issue41.md); today's full run
re-executes those gates rather than treating historical passes as current proof.
No commit, push, merge, issue closure, deployment, application database operation
or M8 completion is claimed.

Final artifact baseline recheck passed:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --no-install
git diff --check
```

Exactly 21 new non-secret metadata findings (revision, script fingerprint and
migration revision in seven raw cells) were reviewed individually; previous
baseline entries, detectors and filters are unchanged. All four measured
production/script fingerprints still match. The eight owned Compose projects
(seven benchmark/control runs and full validation) have zero containers, and no
worker or freshness-benchmark Python process remains. Developer services were
left untouched. The post-report baseline-only command is an artifact recheck;
the separate complete locked-install command above establishes full local gates.
