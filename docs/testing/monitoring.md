# Monitoring foundation verification

All commands run from the root with the supported Python 3.12 test environment.
They use local Docker only and never select the application database or developer
monitoring project. No credentialed browser traces are collected.

## Next.js SSR acceptance (#60)

After the `image` gate builds both production images:

```powershell
backend/.venv/Scripts/python.exe scripts/check-frontend-observability.py --mode host
backend/.venv/Scripts/python.exe scripts/check-frontend-observability.py --mode container
```

These reuse the existing test service/database/monitoring owners, seed two private
synthetic tenants and query actual Tempo traces for server/client/API ancestry.
Host mode builds and starts real production Next.js; container mode runs the
actual standalone image and API image using internal DNS and exact trusted peer
configuration. Both check rendered synthetic private data, absent telemetry
canaries, malformed/missing context, SSR renewal redirects, foreign access and
Collector-absent cold startup/requests/shutdown. The developer database is never
selected. Full Chromium renewal/permission journeys remain in `browser`; run it
with `MONITORING_ENABLED=true` and an unavailable local Collector to verify the
same flows under monitoring failure. Authentication browser traces remain off.

`frontend-tests` also runs the Node server suite, including actual OTLP serialization
to a local synthetic receiver, propagation trust and SSR cookie/401 contracts.
The image checker rejects telemetry markers in browser bundles. The focused
checks supplement the shared gates and do not establish full M9 acceptance.

## API HTTP acceptance (#59)

```powershell
backend/.venv/Scripts/python.exe scripts/check-api-observability.py
backend/.venv/Scripts/python.exe scripts/check-api-observability.py --container-smoke
```

On Linux/macOS use `backend/.venv/bin/python`. The helper owns fresh monitoring
and PostgreSQL/Redis projects and a guarded unique `_test` database; it never
selects the developer application database. It runs the real API workload, checks
committed orders, one stock movement and audit replay semantics, then queries
stored Prometheus counters/histogram quantiles/in-flight/freshness, Loki logs and
Tempo spans with a distinctive canary. An independent spoofed-service probe checks
Collector sanitization, including schema/scope metadata and exception/status text.
The workload also records the registered business route/method operations across
six approved outcomes, then checks every combination after a quiet cumulative
re-export. This is a label-capacity and recovery check, not a load benchmark.
It prints results and verifies owned teardown; it does not write an issue report.

The container smoke requires the locally built `restaurantos-backend:m6` image
from the image gate (override with `--image`). It starts that nonroot API runtime
on the owned private network and verifies all three stores via `collector:4318`,
with no published API port. Its deliberately unused `_test` URL proves only the
health/export path; the host workload supplies the real database/business checks.

`backend-unit` includes SDK in-memory privacy/correlation, normalized labels,
trusted/malformed context, cancellation and overlapping lifecycle tests.
`unit/test_telemetry_recovery.py` adds real SDK large-snapshot/idle-export,
shared-deadline/recovery and partial-construction resource-ownership regressions.
`backend-integration` includes actual OTLP HTTP exporters, pre-start absence,
mid-workload failure, repeated rejection, slow consumption/queue overflow and
PostgreSQL order/inventory/audit checks. The stored-workload test is skipped in
ordinary integration runs because it requires this explicit five-service runner.
Never point `TEST_MONITORING_ENDPOINT` at a shared environment. SDK force-flush
calls exist only in acceptance after transaction completion, not in business code.

Run the #58 host/container synthetic checks below after changing either policy;
parser success and successful OTLP admission alone do not prove stored signals.

## Configuration and fast regressions

```sh
backend/.venv/bin/python scripts/check-monitoring-config.py
backend/.venv/bin/python scripts/validate.py --gate baseline --no-install
backend/.venv/bin/python scripts/validate.py --gate backend-static --no-install
backend/.venv/bin/python scripts/validate.py --gate backend-unit --no-install
```

The parser checker uses immutable images with network-disabled bounded containers.
Pure tests protect budget/isolation, strict mounts, source links, payload sizing,
counter/histogram semantics, lifecycle ownership and failure cleanup. Parser
success alone is not runtime acceptance. `--no-install` is partial evidence.

## Runtime matrix

```sh
backend/.venv/bin/python scripts/check-monitoring.py --mode host --report test-results/monitoring/host.json
backend/.venv/bin/python scripts/check-monitoring.py --mode container --report test-results/monitoring/container.json
backend/.venv/bin/python scripts/check-monitoring.py --scenario restart --report test-results/monitoring/restart.json
backend/.venv/bin/python scripts/check-monitoring.py --scenario outage --report test-results/monitoring/outage.json
backend/.venv/bin/python scripts/check-monitoring.py --scenario scraper --report test-results/monitoring/scraper.json
backend/.venv/bin/python scripts/check-monitoring.py --scenario saturation --report test-results/monitoring/saturation.json
backend/.venv/bin/python scripts/check-monitoring.py --scenario cleanup --report test-results/monitoring/cleanup.json
```

All ordinary cases require exit zero, `status: passed` and verified cleanup. The
intentional cleanup case must return nonzero with the intended interruption and
`cleanup_verified: true`; unrelated startup failures do not satisfy that check.
Destination outages last 180 seconds each unless an explicitly partial shorter
regression is selected. The final full scraper check uses the same default 180-second fault duration
(`--fault-seconds 180`); its earlier 30-second fixture is retained separately.
The saturation case uses a labeled 1 KiB test queue and
single-record batches; it does not establish saturation of normal queues.

Reconciliation distinguishes cumulative metric snapshots from individual logs
and traces. Trace search uses bounded windows and rejects result truncation.
Canary checks cover the stated synthetic fixture, not every future framework or
application field. No tenant-facing authorization or financial-total claim is
established by these synthetic checks.

## Retention and resources

```sh
backend/.venv/bin/python scripts/check-monitoring-retention.py --report test-results/monitoring/retention.json
backend/.venv/bin/python scripts/benchmark-monitoring.py --mode host --report test-results/monitoring/host-resources.json
backend/.venv/bin/python scripts/benchmark-monitoring.py --mode container --report test-results/monitoring/container-resources.json
```

Retention requires old stored fixtures, physical cleanup and surviving recent
controls. It never changes the host clock or application data. Test-only schedules
and backdated admission are separate from production retention durations.

Each declared resource run is 120 seconds warmup plus 600 seconds measurement at
five operations/second, with all generated traces emitted. Run one host cell and
three fresh container repetitions sequentially, with no other monitoring stack.
Record all failures. Memory uses Docker's cache-adjusted displayed working set,
with its rounding retained; sampled peaks are not continuous maxima. CPU percent
uses one logical CPU as 100 percent. Report observer/generator overhead separately.
Allocated and logical volume sizes differ, especially for WAL files. A short-run
retention extrapolation is an initial planning budget, not guaranteed capacity.

The application image gate remains separate:
`backend/.venv/bin/python scripts/validate.py --gate image --no-install`.
Issue #58 checks do not establish all ten gates, M9's application trace/incident
exit criteria, hosted capacity, external alert delivery or AMD64 runtime evidence.

## PostgreSQL, Redis and pools (#61)

```sh
backend/.venv/bin/python scripts/check-monitoring-config.py
backend/.venv/bin/python scripts/check-infrastructure-observability.py
backend/.venv/bin/python scripts/validate.py --gate backend-unit --gate backend-integration --gate backend-static --gate baseline --gate image --no-install
```

The configuration checker now validates both the base Collector policy and the
opt-in receiver config with the **pinned native binary**, dummy secret mounts and
network disabled. `unit/test_monitoring_config.py` enforces the added pipeline,
receiver allowlists, single database, restricted-secret mounts and connection cap.

`unit/test_infrastructure_diagnostics.py` uses the real in-memory SDK for safe
Redis outcomes (including cancellation and closed transport) and exactly-once
catalog hit/miss/bypass semantics, authorization exclusion and circuit recovery.
The unchanged catalog suites protect age/invalidation/live-stock contracts.
`integration/test_infrastructure_diagnostics.py` starts **separate real API and
worker processes**, with pooled PostgreSQL engines rather than the HTTP NullPool.
API fixture limits are two base/one overflow/one-second timeout; the worker factory
retains its normal computed size and five-second timeout. Both synchronize an
extra acquire while all slots are held, assert acquiring > 0 before timeout,
cancel another waiting acquire, release a slot and execute real SQL again. Tests
also cover duplicate-hook prevention, slow SQL, failure/cancellation privacy and
ordinary read rollback without a failed-transaction increment. Fixture pool
settings do not change application defaults or increase production limits.

The explicit acceptance helper owns unique PostgreSQL/Redis projects, a guarded
`*_test` database, private synthetic credentials and the existing five-service
monitoring stack. It provisions the reviewed minimum PostgreSQL grants and Redis
INFO-only ACL, checks read success and denied table/administrative/key access,
then inspects **stored Prometheus** application/receiver signals and exported
canary exclusion. Only its Collector joins its private service network. It
pauses/unpauses its targets (so the disposable tmpfs database survives the outage),
requires expired/missing series, observes scrape failures, and proves recovery.
Collector-absent API/worker cold startup, SQL/Redis work, bounded shutdown and
re-export are tested separately in that same environment. No developer resource
is selected, restarted, migrated or removed. All normal/failure exits run the
existing ownership-checked teardown. No raw driver exception/credentials are
printed by the acceptance helper.

Resource samples use Docker's rounded, cache-adjusted working set and CPU percent
(one CPU = 100%), every approximately three seconds plus observer-command cost,
during sequential API/worker SQL/Redis and pool-fault workloads. This is a bounded
smoke cost, not the ten-minute M9 baseline or an instrumentation speed guarantee.
See [the operational contract](../../monitoring/database-redis.md) for exact
metrics/units/mappings, source pins, grants, cadence, unavailable measurements and
the pinned Redis receiver's unenforced scraper-context timeout limitation.
The existing API acceptance and #58 runtime matrix remain the HTTP/synthetic/
log/trace/Collector interruption regressions; this check does not replace them.

### Issue #62 worker verification

Run the required worker gates from the repository root:

```sh
backend/.venv/bin/python scripts/validate.py --gate backend-unit --no-install
backend/.venv/bin/python scripts/validate.py --gate backend-static --no-install
backend/.venv/bin/python scripts/validate.py --gate backend-integration --no-install
backend/.venv/bin/python scripts/validate.py --gate migrations --no-install
backend/.venv/bin/python scripts/validate.py --gate baseline --no-install
backend/.venv/bin/python scripts/validate.py --gate image --no-install
```

`test_event_telemetry.py` adds real SDK/privacy unit coverage and service-backed
transactional context, linked retry/terminal/replay/duplicate observations, durable
backlog and recent-receipt snapshots, including every operational state and
expired-lease recovery. Integration tests capture decoded protobuf
from a local isolated HTTP collector, including real `app.worker` processes after
restart, real failed/retried/terminal attempts, authorized repair, duplicate ACKs
and rejecting collector responses. Sales/receipt reconciliation checks the actual
projection during collector rejection. Source-export canaries are checked
before collector filtering. Existing event execution/projection suites retain
receipt atomicity, crash/ACK windows, replay authorization and business totals
coverage. The disposable migrations verifier exercises metadata-only downgrade
and re-upgrade with retained event/delivery/attempt/receipt/replay and business
facts. These gates do not establish full M9 dashboard/failure-exercise acceptance.


Issue #62 follow-up adds a native Collector regression in
`backend/tests/integration/test_event_metric_export.py`, selected by
`backend-integration`. It starts only an owned, pinned Collector with worker and
infrastructure metric pipelines on random loopback ports; it checks independent
5/9 counter and histogram streams, quiet re-export, one-slot restart, no-slot
suppression and unslotted durable gauge deduplication. The fixed producer label
range is tested at settings/source creation and validated at Collector admission.
`test_event_telemetry.py` additionally checks authenticated HTTP creation through
worker restart for all three consumers, non-NULL rollback, trace/span IDs and
remote bits, publication failure outcomes, pre-column insert/upgrade/processing,
real SQL collection timeout/recovery, closed/rejecting/slow Collector modes,
queue-full local diagnostics and post-outage export/ACK recovery. A pure metrics
loop test confirms failed collection does not advance freshness, then success does.
The test-only pressure barrier emits synthetic SDK spans outside transactions;
it does not add production fault endpoints or business-effect attempts.
