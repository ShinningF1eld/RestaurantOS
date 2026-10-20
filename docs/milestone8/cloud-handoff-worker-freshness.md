# Cloud handoff: finish Milestone 8 worker freshness

Continuation note, 2026-10-20: the user cancelled cloud transfer and continued
locally. Both preserved checkpoint CI runs passed. The busy-removal control and
bounded worker-pool follow-up are now recorded in
[the local comparison](performance-milestone8-worker-db-pool.md) and
[verification](verification-milestone8-worker-db-pool.md). Use those newer results
before repeating the historical plan below; final PR CI/M8 acceptance remain open.

Prepared 2026-10-19 (Asia/Bangkok). The user is shutting down the local PC and
wants this work continued in cloud mode. Everything needed to reproduce the
workload is in Git; do not depend on local Docker Desktop, local databases,
ignored `test-results/`, or this chat's live processes.

Local cleanup was verified before publication: all seven owned validation/benchmark
Compose projects have zero containers and no owned worker or benchmark process
remains. Developer services were left alone. Final retained-artifact baseline and
diff checks passed; no source changed after validation/measurement.

## 1. Start from the correct branches

Repository: `ShinningF1eld/RestaurantOS`.

- `codex/m8-worker-throughput` is the preserved busy-reference checkpoint:
  `b9b6931ee0d5d97459974e70d25bd84e593eebda`. It is pushed. Do not move/rewrite it.
- `codex/m8-relay-drain` is the experimental continuation branch containing the
  six-line relay scheduling change, new regressions, all five new raw benchmark
  reports and this handoff. Start from its current remote HEAD. Its parent is
  the busy-reference checkpoint. Inspect Git to obtain the published commit ID.
- Original issue #41 baseline branch: `codex/m8-issue41-evidence`, head
  `3c0da95ffebcdd20b499d39cc2be9d9407a8833a`, draft PR #53. Do not overwrite it.

Read root/nested `AGENTS.md`, `README.md`, `docs/current-state.md`, then:

1. `docs/milestone8/milestone-8-design.md` (authoritative).
2. `docs/milestone8/milestone-8-task.md` and issue #41 acceptance criteria.
3. `docs/milestone8/performance-milestone8.md` (original baseline).
4. `docs/milestone8/performance-milestone8-busy-retry.md`.
5. `docs/milestone8/performance-milestone8-relay-drain.md`.
6. `docs/milestone8/verification-milestone8-relay-drain.md`.
7. `docs/testing/event-freshness-benchmark.md`, `docs/testing/README.md`,
   `docs/testing/milestone8.md`, and `docs/runbooks/event-worker.md`.

Use the managed-cloud environment skill if applicable. Install the committed
locks on Python 3.12 / Node 24; use disposable PostgreSQL 16 / Redis 7 through the
existing runner. Never migrate or benchmark the application database. If required
services are unavailable, report the limitation; do not substitute SQLite or
invent passing results.

## 2. Understand the implementation already present

The busy-reference checkpoint keeps temporarily locked subscribed deliveries in
a bounded local queue for at most 20 same-owner revisits with 50/100/200/250 ms
eligibility delays. It interleaves new work, preserves persisted due times,
claims/receipts and charged failure limits, and falls back to durable recovery.

The relay experiment changes only production
`backend/app/modules/events/worker/runtime.py` relative to that checkpoint:
after a successful nonempty batch, `await asyncio.sleep(0)` then immediately check
for more work. Empty claims retain the 1,500 ms wait. Batch size 10, publication
concurrency 2, leases, outage backoff/cooldown and failure limits are unchanged.
Expired-attempt recovery still runs per relay pass, thus more often under load;
the separate recovery loop retains its interval. There is still only one worker.

Source references: `worker/runtime.py`, `worker/streams.py`, `execution.py`,
`repo/worker_queries.py`, `repo/delivery_queries.py` under
`backend/app/modules/events/`; notification, analytics and alert handlers in
their respective modules. Preserve the modular monolith and public feature
interfaces. No schema/API/UI/dependency change has been made for these experiments.

## 3. Check CI first

Both new branches were pushed for this handoff. Inspect CI for the exact current
remote heads; CI was not awaited before the local PC shutdown. All ten shared
gates and the required `Milestone 6 acceptance` aggregate must pass. Do not relax
or skip gates and do not treat old PR #53 CI as validation of these branches.

Local evidence on the relay source:

- Initial locked-install full command passed baseline, both static gates and
  all 307 unit tests. Its integration gate had 336 passes / one failure in
  existing `auth/test_redis_admission.py::test_success_does_not_clear_either_failure_bucket`.
- The unchanged retry passed all 337 integration tests, 10 client, 19 component,
  29 Chromium, production build, migrations/backup-restore/downgrade checks,
  intentional-failure cleanup and image checks. Across the two commands, all ten
  gates have passing evidence. The first full command itself failed.
- Auth implementation/tests were not changed. The assertion expected previous
  failure-bucket counts to remain one after successful login. A real fixed-window
  boundary is plausible but unproven. If CI reproduces this, diagnose it properly;
  do not silently retry until green, weaken quotas/assertions, or blame the worker.
- Ignored local console logs are not pushed; the tracked reports retain these
  outcomes. Re-run gates in cloud for independently accessible evidence.

Linux full command after environment setup:

```bash
backend/.venv/bin/python scripts/validate.py
```

## 4. Interpret the completed benchmark accurately

All five relay benchmark cells **already completed** on the local PC. There is
no unfinished measurement process to resume. Raw JSON is in
`docs/milestone8/benchmarks/relay-drain/`; the original and busy-only directories
remain intact. The benchmark script was not edited (version 1.0.0).

Every version completed 1,440 events / 1,980 correct effects with zero healthy
charged retries, failures, missing effects or pending work after drain.

Paced pooled P95 seconds (analytics / alerts / sink):

| Version | Analytics | Alerts | Sink |
|---|---:|---:|---:|
| Original | 16.268 | 18.168 | 17.352 |
| Busy retries only | 18.670 | 20.094 | 19.447 |
| Busy retries + relay draining | 3.952 | 6.293 | 37.125 |

New light maxima are all below 3.805s, with zero five-second exceedances.
New pressure P95 is 44.165 / 45.719 / 61.717s. New paced sink median is 26.331s,
max 39.287s, with 812 proven five-second misses / 840 effects. The sink regression
is a central unresolved problem; do not call the relay experiment an overall win.
Paced total proven misses decreased to 882/1,320, but the five-second target is
still unmet. Full distributions, maxima, uncertainty bounds and backlog are in
the comparison report and JSON. These are serial Windows-host observations,
not randomized/interleaved controls or production capacity claims.

## 5. Reproduce on one cloud environment before comparing optimizations

Use the unchanged workload and all five cells, serially with no concurrent tests,
builds or other benchmarks. Compare variants on the same cloud resources; do not
attribute Windows-to-cloud differences to code changes. Keep the same parameters,
settings and dataset; record source commits/hashes and versions for every run.

```bash
PY=backend/.venv/bin/python
$PY scripts/benchmark-event-freshness.py --bundles 40 --rate 0.5 --concurrency 4 --operations --output test-results/cloud-paced-1.json
$PY scripts/benchmark-event-freshness.py --bundles 40 --rate 0.5 --concurrency 4 --output test-results/cloud-paced-2.json
$PY scripts/benchmark-event-freshness.py --bundles 40 --rate 0.5 --concurrency 4 --output test-results/cloud-paced-3.json
$PY scripts/benchmark-event-freshness.py --bundles 40 --rate 2 --concurrency 4 --timeout 240 --output test-results/cloud-pressure.json
$PY scripts/benchmark-event-freshness.py --bundles 20 --rate 0.25 --concurrency 4 --output test-results/cloud-light.json
```

Each 40-bundle cell contains 320 events / 440 required effects; light contains
160 / 220. Paced schedules 4 events / 5.5 required effects per second, pressure
16 / 22, light 2 / 2.75. These are producer/projection fixtures, not full HTTP
order-throughput tests. Consumer effects and receipts commit atomically.
Use the existing monotonic commit/receipt bounds; database timestamps and routing
logs are not commit timestamps. The UI's 15-second refresh is a separate metric.

## 6. Diagnose the sink before choosing another optimization

Measure where time accumulates: unpublished due PostgreSQL work, unread Redis
group work, owned pending references, consumer start, database lock/connection
waits and effect completion. Examine consumer-group fairness and the extra
recovery/claim activity under continuous relay draining. Measure SQL/query
cost and database/Redis/CPU pressure rather than guessing the exact cause.

Use due unfinished PostgreSQL deliveries and oldest runnable age as backlog
signals. Retained Stream length includes completed/duplicate references and is
not runnable queue depth. Retain safe IDs/correlation only, without credentials,
customer payloads or auth traces. Inspect whether unrelated-group/reference
handling contributes to the sink bottleneck; that is a hypothesis, not a finding.

## 7. Run controlled, separate follow-up variants

First compare the relay experiment with versus without busy-reference revisits
on the same environment, preferably with interleaved repetitions. That control
has **not** been run. Preserve all authoritative execution/receipt/retry checks.
Use separate small commits/branches; do not blindly revert the whole busy
checkpoint, which also contains benchmark evidence and documentation.

Then choose a focused fix based on profiling. If concurrency is justified,
compare one versus two fixed workers before autoscaling. Prove duplicate safety
and actual lock overlap, bound connections and measure contention. Do not add
queue-size autoscaling or speculative infrastructure without evidence and an
agreed scope. Keep producer/stock/auth/money/tenancy semantics unchanged.

## 8. Finish with evidence, not only lower P95

- Aim for the documented healthy paced workload to meet five seconds for all
  three consumers. Report P50/P95/P99/max, lower-bound proven misses and upper
  exceedances. Keep light and pressure results visible; disclose remaining
  capacity limits rather than lowering the load or weakening the watchdog.
- All expected effects, receipts, totals/episodes/stubs/diagnostics and maintenance
  checks must remain correct, with no unexplained charged retries/failures/loss.
- Re-run affected regression/static gates and the complete required gate set for
  the final implementation. Preserve eight attempts, persisted backoff, claim
  fencing, atomic receipts, same-transaction audit and safe replay.
- Retain reviewed raw JSON and comparative reports; update relevant current-state,
  runbook and regression-map evidence. Review entropy findings as exact non-secret
  revision/fingerprint metadata; never disable detectors or broad-ignore reports.
- Commit proven steps separately, push the working branch for CI and report exact
  tested head/gates/outcomes/omissions. Keep the checkpoint branch unchanged.
- Do not merge, close issue #41, mark M8 complete, deploy, migrate an application
  database or introduce external notifications as part of this handoff without
  the applicable user authorization and verified exit criteria.

## Suggested cloud task prompt

Continue RestaurantOS worker freshness from `codex/m8-relay-drain`. Read
`docs/milestone8/cloud-handoff-worker-freshness.md` and follow its ordered steps.
Preserve the pushed `codex/m8-worker-throughput` checkpoint. Check exact-head CI,
reproduce comparable cloud baselines, diagnose the paced sink regression, and
measure controlled follow-up changes toward five-second healthy-load freshness.
Preserve all design invariants and regression gates, retain honest benchmark
evidence, and keep changes separable. Do not rely on the shut-down local PC or
claim M8 complete while requirements or CI remain unverified.
