# Monitoring foundation verification

All commands run from the root with the supported Python 3.12 test environment.
They use local Docker only and never select the application database or developer
monitoring project. No credentialed browser traces are collected.

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
