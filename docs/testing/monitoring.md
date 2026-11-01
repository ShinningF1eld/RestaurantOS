# Monitoring foundation verification

All commands run from the root with the supported Python 3.12 test environment.
They use local Docker only and never select the application database or developer
monitoring project. No credentialed browser traces are collected.

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
