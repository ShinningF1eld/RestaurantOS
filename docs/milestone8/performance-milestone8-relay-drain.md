# Milestone 8 relay scheduling comparison

## Checkpoint and change

The busy-reference implementation and its full verification/benchmark evidence
were committed on branch `codex/m8-worker-throughput` as
`b9b6931ee0d5d97459974e70d25bd84e593eebda` before this experiment. That checkpoint
preserves the prior result independently of the relay change. That branch was
pushed at the user's subsequent request for a cloud handoff.
The [busy-reference report](performance-milestone8-busy-retry.md) and
[original measurement](performance-milestone8.md) remain unchanged.

Only production `backend/app/modules/events/worker/runtime.py` changes relative
to that checkpoint. After a successful nonempty relay batch, the loop yields
with `asyncio.sleep(0)`, checks stop, and claims the next bounded batch immediately.
This includes partial batches; an empty claim result retains the configured
1,500 ms idle wait. Publication failures retain the prior infrastructure backoff
and persisted transport cooldown. Batch size (10), publication concurrency (2),
30-second lease, 60-second stalled/abandoned recovery thresholds, eight-attempt
failure policy and busy-reference behavior are unchanged.

The existing expired-attempt recovery call still runs per relay pass, so it runs
more frequently under backlog too. The separate recovery loop retains its
1,500 ms interval. No extra worker, autoscaler, concurrent batch, new setting,
producer/handler/domain change, schema/API/UI/dependency change or application
database operation is part of this experiment.

## Reproduction and measurement identity

Use the unchanged five commands from the
[freshness procedure](../testing/event-freshness-benchmark.md), changing only
output names to `test-results/relay-drain-<cell>.json`: three 40-bundle paced
repetitions at 0.5 bundles/s (first with `--operations`), one 40-bundle pressure
cell at 2 bundles/s with the same 240-second watchdog, then a 20-bundle light
cell at 0.25 bundles/s. Producer concurrency remains four and observation polling
25 ms. Each cell uses a fresh guarded disposable PostgreSQL/Redis project, one
production worker and unchanged committed dependencies. Cells run sequentially
after validation ends, with no competing validation/build/benchmark.

The measurement script remains version `1.0.0`, SHA256
`e7b17362e66e8a2a1ea9c3997f2f208ec8a313b5751f04daf04386b8912f513a`.
Raw JSON records repository head `b9b6931ee0d5d97459974e70d25bd84e593eebda`;
the relay implementation and its new evidence are uncommitted on top of that
checkpoint. Production source SHA256s:

| File | SHA256 |
|---|---|
| `backend/app/modules/events/worker/runtime.py` | `fcb7a18e80a2e69174a4377d30b975ce86ccadfe3e8c58e3c7f8f32449db182f` |
| `backend/app/modules/events/worker/streams.py` (unchanged) | `652aa74a5004692d2d0b25ddfd839b5ff9bef4ad2aab9e5f57bbc5cce0363b2f` |

Percentiles remain nearest-rank conservative commit-to-receipt visibility upper
bounds. Proven misses require lower bounds above five seconds. These local
historical comparisons are serial, not randomized/interleaved controls; they
do not establish production capacity or isolate the value of busy-reference
retries under the new relay scheduling. A relay-without-busy-retries control is
not included in this experiment.

## Results

All five cells completed successfully on 2026-10-19: 1,440 events / 1,980 correct
unique effects, no healthy charged retries, failures, missing effects or pending
work after drain. Graceful shutdown and maintenance reconciliation passed in
every cell; the first paced cell also completed the unchanged operational rehearsal.
Automated comparison verified unchanged script/version/hash, server versions,
migration head, settings, workload, event mix, polling, expected effects and
retained database counts against both earlier versions.

**The result is mixed and this branch remains experimental.** Paced analytics
and alerts improve substantially, but the sink becomes markedly slower. The
five-second target is still unmet. These serial measurements do not identify
the bottleneck's exact cause.

P95 seconds, nearest-rank conservative upper bounds:

| Load | Consumer | Original | Busy retries only | Busy retries + relay draining |
|---|---|---:|---:|---:|
| Light | Analytics | 2.689 | 2.531 | 2.749 |
| Light | Alerts | 4.023 | 3.419 | 3.238 |
| Light | Sink | 3.489 | 3.138 | 3.449 |
| Paced pooled | Analytics | 16.268 | 18.670 | 3.952 |
| Paced pooled | Alerts | 18.168 | 20.094 | 6.293 |
| Paced pooled | Sink | 17.352 | 19.447 | 37.125 |
| Pressure | Analytics | 68.048 | 74.271 | 44.165 |
| Pressure | Alerts | 68.786 | 74.807 | 45.719 |
| Pressure | Sink | 69.052 | 74.762 | 61.717 |

New distributions and target breaches:

| Load | Consumer | N | P50 s | P99 s | Max s | Proven misses | Upper exceedances |
|---|---|---:|---:|---:|---:|---:|---:|
| Light | Analytics | 40 | 1.810 | 3.078 | 3.078 | 0 | 0 |
| Light | Alerts | 40 | 2.238 | 3.354 | 3.354 | 0 | 0 |
| Light | Sink | 140 | 2.348 | 3.734 | 3.805 | 0 | 0 |
| Paced pooled | Analytics | 240 | 3.059 | 4.102 | 4.303 | 0 | 0 |
| Paced pooled | Alerts | 240 | 4.466 | 6.839 | 6.981 | 70 | 80 |
| Paced pooled | Sink | 840 | 26.331 | 38.319 | 39.287 | 812 | 815 |
| Pressure | Analytics | 80 | 31.100 | 45.784 | 45.784 | 76 | 76 |
| Pressure | Alerts | 80 | 32.139 | 46.972 | 46.972 | 77 | 77 |
| Pressure | Sink | 280 | 50.176 | 62.440 | 62.708 | 273 | 273 |

Paced proven misses fall from 1,177/1,320 (busy only) to 882/1,320, despite the
sink regression. Pressure has 426/440 proven misses (previously 425); light has
zero/220. Overall proven misses are 1,308/1,980 versus 1,602 with busy retries
alone and 1,546 originally. Aggregate counts must accompany the consumer-level
regression; they do not justify calling this an unconditional improvement.

| Cell | Peak unfinished depth | Last drained elapsed seconds | Retained Stream entries |
|---|---:|---:|---:|
| Paced 1 | 146 | 101.204 | 440 |
| Paced 2 | 141 | 100.632 | 440 |
| Paced 3 | 136 | 99.821 | 440 |
| Pressure | 374 | 82.433 | 440 |
| Light | 11 | 79.708 | 220 |

Elapsed time includes production. Database retention counts match the earlier
corresponding datasets exactly; Stream entries differ and are retained transport,
not runnable queue depth. No pruning was added.

Raw per-cell distributions, individual bounds, backlog observations, settings,
effects, maintenance and operational results are retained in
[paced-1](benchmarks/relay-drain/paced-1.json),
[paced-2](benchmarks/relay-drain/paced-2.json),
[paced-3](benchmarks/relay-drain/paced-3.json),
[pressure](benchmarks/relay-drain/pressure.json) and
[light](benchmarks/relay-drain/light.json).

Per-repetition paced P95 seconds (analytics / alerts / sink) are
3.782 / 6.632 / 37.887, 4.045 / 6.028 / 37.225, and
3.582 / 4.498 / 36.056. All repetitions are retained; the pooled result is not a
selected favorable run.

The next work is to reproduce within one cloud environment, profile the sink
and shared database contention, then compare relay draining with/without busy
revisits in separate controlled variants. Do not assume more workers or removal
of busy retries fixes this result without measurement. See the
[cloud handoff](cloud-handoff-worker-freshness.md).

## Compatibility and verification

New pure orchestration regressions cover draining full and partial batches before
idle, sleeping on an empty queue, transport/PostgreSQL/internal failure backoff
and stopping between successful batches. The new real PostgreSQL/Redis regression
publishes five deliveries in 2/2/1 batches before the first idle wait, verifies
publication observations and cleared relay claims, and confirms no consumer
attempt is created by publication. Existing producer, business, consumer,
fencing, duplicate, poison-restart, outage, replay and browser suites remain
required. The focused worker unit file passed 17 cases before full validation.

The first locked-install full command passed baseline, backend-static,
frontend-static and all 307 unit tests. Its integration gate passed 336 cases,
including all 18 worker cases, and failed the existing
`auth/test_redis_admission.py::test_success_does_not_clear_either_failure_bucket`.
That test expected both earlier failure-bucket counts to remain one after a
successful login; one assertion returned false. No worker loop executes in that
case, and auth implementation/tests are unchanged from the checkpoint. A fixed
window boundary is consistent with the test's unguarded real-clock assumption,
but the retained output does not establish the exact cause. Do not attribute a
confirmed cause or hide the failed run.

The unchanged integration gate and the five not-yet-run gates passed with
`backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-integration --gate frontend-tests --gate frontend-build --gate migrations --gate browser --gate image --no-install`.
The original command installed committed locks; no dependency/source changes
were made for this retry. Logs are ignored
`test-results/relay-drain-full-validation.log` and
`test-results/relay-drain-retry-validation.log`. The unchanged rerun passed all
337 integration cases, including the earlier failing auth case, plus 10 client,
19 component and 29 Chromium cases, production build, clean/seeded-legacy
migrations, backup/restore/downgrade preservation, intentional-failure cleanup
and image smoke. Together the two commands supply passing evidence for all ten
shared gates on this source; the initial full command itself failed and the
second command is intentionally partial. No auth source/test change or timing
workaround was used for the rerun; exact attribution of the intermittent failure
remains unverified.

The measurement was made with uncommitted relay changes above the busy checkpoint.
At the user's subsequent request this implementation, all new raw evidence and
the cloud handoff are being published on a separate `codex/m8-relay-drain` branch.
Its CI is pending; no overall milestone acceptance is claimed. Ignored local
console logs are not included in the Git handoff. The tracked raw JSON and this
dated summary preserve the measurement evidence without exporting auth test logs.

The final retained-artifact baseline gate passed with
`backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --no-install`.
Exactly 15 reviewed non-secret repository/script/migration metadata entries were
added without changing detectors, filters or existing baseline entries.
`git diff --check` and measured production/benchmark SHA256 comparisons passed.
All seven owned validation/benchmark Compose projects have zero remaining
containers; no owned benchmark/worker process remains. Developer services were
not stopped or changed for the handoff.
