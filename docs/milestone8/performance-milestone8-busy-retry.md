# Milestone 8 first freshness improvement: busy references

## Change and compatibility boundary

This follow-up changes only the consumer worker's treatment of
`delivery_missing_or_busy`. The current Redis consumer revisits its original PEL
reference after 50, 100, 200, then 250 ms, with at most 20 short revisits. Before
each revisit it reloads the reference through the existing same-owner check.
Only one due busy reference runs before the ordinary bounded pending/new-message
pass. New-message blocking reads shorten to the next revisit deadline; zero
means omit Redis `BLOCK`, since Redis `BLOCK 0` would wait indefinitely.

Resident busy references are capped at the configured recovery batch size per
group (10 for these workloads). Overflow and exhausted references remain pending
for existing durable recovery. A missing subscribed delivery can produce the
same outcome as a lock; it receives the same bounded treatment, never an
unbounded fast retry. These local revisits are transport probes, not charged
processing failures. They do not acknowledge unfinished work or alter durable
attempt/due/claim state directly.

Execution still validates authoritative PostgreSQL facts, persisted due times,
claims and receipts and commits effects/receipt/success atomically. The relay
still sleeps 1,500 ms after each batch of ten claims; concurrency, 60-second
abandoned-owner/stalled-publication recovery, eight-attempt failure policy,
infrastructure backoff, successful-consumer isolation, replay and shutdown are
unchanged. No schema, API, producer, feature handler, frontend, dependency or
application-database operation is included.

## Reproduction and source identity

Compare with the retained [original report](performance-milestone8.md), whose
raw cells remain unchanged. Use the exact five commands in the
[benchmark procedure](../testing/event-freshness-benchmark.md), substituting
`test-results/busy-retry-<cell>.json` for each output path. Run three paced
40-bundle cells at 0.5 bundles/second (first with `--operations`), one 40-bundle
pressure cell at 2/second with the same 240-second watchdog, then one 20-bundle
light cell at 0.25/second. Concurrency remains four and observation polling 25 ms.
Cells run sequentially after validation ends, with no competing validation or
benchmark. Each uses fresh guarded disposable PostgreSQL/Redis services.

The benchmark script is unchanged, version `1.0.0`, SHA256
`e7b17362e66e8a2a1ea9c3997f2f208ec8a313b5751f04daf04386b8912f513a`.
Raw JSON records repository head
`3c0da95ffebcdd20b499d39cc2be9d9407a8833a`; the implementation and evidence in
this follow-up are uncommitted on top of that head. Measured source SHA256:

| File | SHA256 |
|---|---|
| `backend/app/modules/events/worker/runtime.py` | `5b9a6699a3bf60c36a820bdfcd00d5fd6de4dd399a80d3cc5c958ce7b1a2e207` |
| `backend/app/modules/events/worker/streams.py` | `652aa74a5004692d2d0b25ddfd839b5ff9bef4ad2aab9e5f57bbc5cce0363b2f` |

As before, percentiles use conservative commit-to-receipt visibility upper
bounds and nearest rank. A proven miss means its lower bound exceeds five
seconds. Upper exceedances and maxima are retained too. These are serial local
observations, not a randomized comparison or a guarantee for production load.

## Results

Measured 2026-10-19 on the same Windows 11 / Python 3.12.13 host, PostgreSQL
16.15 and Redis 7.4.11. Automated comparison confirms identical script version,
script SHA256, server versions, migration head, event mix, workload parameters,
polling and every recorded worker setting for each corresponding baseline cell.

All 1,440 events / 1,980 unique effects completed correctly with zero missing
effects, unfinished work, charged retries or failed deliveries. Each cell exited
gracefully and matched SQL reconciliation before/after initialize/rerun/rebuild.
The first paced cell also passed the unchanged CLI inspection/repair/replay,
successful-analytics isolation and queued-work forced-stop/stream-loss rehearsal.

**Light-load tails improved; paced/pressure P95 worsened.** No five-second upper
bound exceedance remains in the light cell (220 effects), whose overall maximum
fell from 63.967s to 3.809s. Paced pooled and pressure maxima fell substantially,
but their P95 and proven miss counts increased. These runs do not demonstrate a
throughput improvement or attainment of the five-second target at four or sixteen
events/second. Attribution of the percentile worsening to this change versus host
variation is uncertain without an interleaved baseline control; no such control
was run. Report the observed regression alongside the tail improvement.

Seconds below are upper bounds. Misses are proven lower-bound breaches of five
seconds. Paced pools all three repetitions (240 analytics, 240 alerts, 840 sink
effects); pressure has 80/80/280 effects and light 40/40/140.

| Load | Consumer | Baseline P95 | New P95 | Baseline max | New max | Proven misses: baseline → new |
|---|---|---:|---:|---:|---:|---:|
| Light, 2 events/s | Analytics | 2.689 | 2.531 | 3.040 | 3.187 | 0 → 0 |
| Light | Alerts | 4.023 | 3.419 | 63.967 | 3.540 | 1 → 0 |
| Light | Sink | 3.489 | 3.138 | 61.663 | 3.809 | 1 → 0 |
| Paced, 4 events/s | Analytics | 16.268 | 18.670 | 18.247 | 21.494 | 195 → 204 |
| Paced | Alerts | 18.168 | 20.094 | 19.921 | 22.051 | 211 → 223 |
| Paced | Sink | 17.352 | 19.447 | 73.511 | 22.245 | 719 → 750 |
| Pressure, 16 events/s | Analytics | 68.048 | 74.271 | 72.136 | 76.301 | 76 → 77 |
| Pressure | Alerts | 68.786 | 74.807 | 72.595 | 77.835 | 76 → 77 |
| Pressure | Sink | 69.052 | 74.762 | 121.475 | 77.913 | 267 → 271 |

Additional new distributions and upper exceedances (which include measurement
uncertainty at the boundary):

| Load | Consumer | P50 seconds | P99 seconds | Upper bounds above 5s |
|---|---|---:|---:|---:|
| Light | Analytics | 1.749 | 3.187 | 0/40 |
| Light | Alerts | 2.437 | 3.540 | 0/40 |
| Light | Sink | 2.349 | 3.674 | 0/140 |
| Paced pooled | Analytics | 11.480 | 20.594 | 207/240 |
| Paced pooled | Alerts | 13.298 | 21.782 | 225/240 |
| Paced pooled | Sink | 12.528 | 21.078 | 757/840 |
| Pressure | Analytics | 38.904 | 76.301 | 77/80 |
| Pressure | Alerts | 40.719 | 77.835 | 77/80 |
| Pressure | Sink | 40.885 | 77.632 | 271/280 |

Per-paced-cell P95s remain visible rather than selecting a favorable repetition:

| Cell | Analytics P95 s | Alerts P95 s | Sink P95 s | Proven misses / 440 |
|---|---:|---:|---:|---:|
| Paced 1 | 20.235 | 21.358 | 20.686 | 394 |
| Paced 2 | 17.909 | 19.714 | 18.845 | 385 |
| Paced 3 | 18.021 | 19.821 | 18.898 | 398 |

Paced pooled misses increase from 1,125/1,320 to 1,177/1,320; pressure from
419/440 to 425/440. Light decreases from 2/220 to zero. The overall proven miss
count increases from 1,546/1,980 to 1,602/1,980 despite the improved maxima.

The [safe same-reference trace](benchmarks/busy-retry/short-revisit-trace.json)
shows a light-cell sink reference routed as busy, then `consumer_committed`
1.560486s later under the identical Redis message ID. Its full commit-to-receipt
latency is bounded at 2.285–2.404s. Log elapsed time is not a producer commit
timestamp, and the trace does not identify the competing lock holder. Short
revisit eligibility does not guarantee dispatch within 250 ms: ordinary bounded
batch work and I/O still run between probes. The real-lock regression separately
proves this recovery without a relay/reclaim loop.

### Backlog and retained facts

| Cell | Peak unfinished depth | Last drained observation, elapsed seconds | Retained Stream entries |
|---|---:|---:|---:|
| Paced 1 | 102 | 100.563 | 406 |
| Paced 2 | 96 | 98.181 | 403 |
| Paced 3 | 94 | 98.458 | 404 |
| Pressure | 361 | 97.785 | 405 |
| Light | 11 | 79.503 | 210 |

Elapsed time includes production, not just post-production drain. Pressure's last
drained observation improves from 138.041s, despite its higher P95. Each 40-bundle
cell retains 320 events, 440 deliveries/receipts/attempts, 80 contribution rows,
one daily aggregate, 40 episodes/states/stubs and 240 diagnostics; light retains
half except the single daily aggregate. No history was deleted. Rehearsal writes
are separate from these healthy measurement counts.

Raw samples, full latency intervals, settings, backlog/age observations, retained
counts, CLI results and provenance are preserved in
[paced-1.json](benchmarks/busy-retry/paced-1.json),
[paced-2.json](benchmarks/busy-retry/paced-2.json),
[paced-3.json](benchmarks/busy-retry/paced-3.json),
[pressure.json](benchmarks/busy-retry/pressure.json) and
[light.json](benchmarks/busy-retry/light.json).

The next separate experiment remains relay scheduling under backlog. Its
unchanged ten-claim batch and mandatory 1.5-second sleep impose a theoretical
6.67-publications/s ceiling before SQL/Redis work, against 5.5 subscribed
deliveries/s at the paced load. This follow-up deliberately leaves that behavior
intact. No overall Milestone 8 completion is claimed.

## Regression evidence

`unit/test_event_worker.py` adds bounded-revisit/interleaving and full-queue
overflow cases, plus the zero-block Redis command regression.
`integration/test_event_worker.py` holds a real PostgreSQL delivery lock until
unrelated work commits, proves no attempt while locked, then checks short
completion without a relay/reclaim loop. Its other branches preserve a future
persisted due time and refuse a reference transferred to another Redis owner.
Exactly one durable diagnostic, attempt and receipt must result after release.
The concurrency barrier establishes actual overlap rather than relying on sleeps.

The initial backend run passed 335 integration cases and failed the newly added
ownership-transfer test: its observer asserted transfer before the test performed
it, losing the local retry through a test assertion. The corrected test gates
that observation on an explicit transfer barrier. The production change was not
altered to accommodate that assertion. A separate restricted Windows unit run
stalled in asyncio loopback socket creation; it was stopped and rerun with
loopback access while retaining the unit fixture's outbound/service socket guard.

The final locked-install command
`./scripts/validate.ps1 -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe`
passed all ten gates on 2026-10-19: 301 unit, 336 integration, 10 client,
19 component and 29 Chromium tests; backend/frontend static checks, production
build, clean/seeded-legacy migrations, downgrade preservation, backup/restore,
expected-failure cleanup and image checks passed too. Evidence remains in ignored
`test-results/busy-retry-full-validation.log`. The full run includes the corrected
barrier test and final production source recorded above.

The final retained-artifact baseline recheck passed with
`backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --no-install`
(`test-results/busy-retry-final-artifacts.log`). Exactly 15 reviewed non-secret
repository/script/migration metadata findings were added to the existing secrets
baseline; detector rules, filters and prior entries are unchanged. Measured
production/benchmark source hashes still match the manifest, `git diff --check`
passes, and all seven observed owned validation/benchmark Compose projects have
zero remaining containers. No new commit, push or CI result is claimed
by this report. The [compatibility review](verification-milestone8-busy-retry.md)
distinguishes functional passes from the remaining performance target failure.
