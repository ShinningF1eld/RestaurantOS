# Issue #58 implementation checkpoints

These steps refer to the ten-step implementation plan for issue #58, not the
ten separate M9 issues. Work stays local; no push or issue closure is authorized.

## Step 4 — Grafana provisioning, 2026-11-01

Provisioned three stable data sources with internal proxy URLs and trace/log
links. Grafana's own provisioning expansion requires the escaped trace expression
`$${__value.raw}`. A temporary authenticated five-container smoke confirmed all
three source health checks and real metric/log/trace queries through Grafana.
Anonymous data-source access returned 401. All five nonroot processes retained
their declared memory/swap limits and had zero observed OOM/restarts on the final
run; its project-owned volumes/networks/containers were removed.

The original Grafana 350 MB allocation failed (exit 137; OOM confirmed on the
second run). Adding a 280 MB Go target alone also failed. Preserved failures and
the successful result are under `evidence/issue58/step4-*.json`. Before the final
run, the same 2 GB total was reallocated: Collector 250 MB, Prometheus 300 MB,
Grafana 650 MB, Loki/Tempo 400 MB each. Collector's limiter is now 160 MiB with a
200 MB Go target; Grafana's Go target is 420 MB. No image pins changed.

The targeted configuration suite passed six checks. The temporary smoke command
was `backend/.venv/bin/python -u /tmp/restaurantos-step4-smoke.py`; its durable
replacement follows in Step 7. Credentials existed only in a private temporary
directory. Persistent secret initialization follows in Step 6. Grafana Explore
was verified through authenticated source-proxy APIs; no rendered UI evidence or
four operational dashboards are claimed. Sustained capacity remains Step 9.

## Step 5 — deterministic generator, 2026-11-01

Added the standard-library OTLP/HTTP JSON generator and a nonroot image on the
same pinned Python base used by the backend. Dockerfile-specific ignore rules
restrict the repository-root build context to the generator script (9.65 kB at
the observed build); no application files or local environments are copied.
Requests split by actual encoded bytes at 64 KiB. Cumulative counter/histogram
values, deterministic trace/log identities, phase counts, pacing misses and
failed/uncertain acknowledgements are reported without replaying failed requests.
The generator bounds rate, duration, seed length and hold time.

The image built successfully with
`docker build -f monitoring/synthetic/Dockerfile -t restaurantos-monitoring-generator:local .`.
Three pure fixture/boundary tests passed. A five-service disposable smoke invoked
the same script from the host and the built container (private collector address),
each at five operations/second for three seconds: 15 operations, nine acknowledged
export requests, zero failures and zero pacing misses in each mode. See
`evidence/issue58/step5-generator.json`. This is transport smoke, not the sustained
workload. The existing script static gate now includes the generator.

## Step 6 — lifecycle and ownership, 2026-11-01

Added `scripts/local-monitoring.py` and the shared monitoring environment helper.
Initialization creates a private directory, stable random project identity and
independent Grafana password, and refuses to replace existing credentials.
Developer shutdown retains all volumes; even a direct helper call cannot request
development volume deletion. Disposable projects use a separate `test-` identity,
random ports and mandatory finally cleanup verified by exact project labels.
Remote Docker engines are rejected. Local file secrets are readable by Grafana's
UID inside the mount while the containing host directory is restricted.

Four pure ownership/error-path tests passed. The real temporary lifecycle check
started each connection mode, verified four volumes survived down/up and
authenticated Grafana after restart, then verified owned cleanup. Container mode
also deliberately raised after startup and still removed its resources. Results:
`evidence/issue58/step6-lifecycle.json`. No developer state was initialized or used.

## Step 7 — repeatable delivery/failure verifier, 2026-11-01

Added `scripts/check-monitoring.py`. Permanent smoke runs passed in host and
container modes with exact counter/histogram/log/trace reconciliation through
authenticated Grafana, a returned parent-child trace, correlated log IDs and
selected synthetic-canary exclusion. Windowed trace search rejects truncation.
The restart scenario preserved Prometheus history, all 15 logs and the trace
across down/up; Collector's in-memory metrics cache is expected to reset.

Loki and Tempo were each stopped for 180 seconds under ongoing generated traffic.
Their exporter failure counters rose, Collector stayed running without OOM, and
new linked data arrived after recovery. This does not claim exact accounting for
lost telemetry. A separate Prometheus stop produced a real gap in raw scrape
sample timestamps; missing samples were not reconstructed. A separate 1 KiB queue
fixture with one-record batches emitted enqueue failures without killing
Collector. It demonstrates bounded rejection, not saturation of the normal 4 MiB
queues. The explicit cleanup scenario returned nonzero as intended and verified
removal of only its project resources.

Commands use `--scenario smoke|restart|outage|scraper|saturation|cleanup` and
`--mode host|container`; all sanitized results are `evidence/issue58/step7-*.json`.
The shared backend-static gate passed, including the permanent verifier. The
normal producer's acknowledgements remain distinct from backend reconciliation.

## Step 8 — physical retention, 2026-11-01

Added the isolated retention checker and `monitoring/testing/retention.yaml`.
The final run passed: pre-existing eight-day Prometheus blocks were physically
removed under seven-day retention, while a recent control survived. Four-day-old
Loki/Tempo fixtures were first queryable and physically stored; their expired
chunk/block files were then removed, their queries became absent and recent
controls remained. Cleanup removed only the disposable project's resources.

The test preserves seven-day/72-hour production retention and never changes the
host clock. It accelerates compaction/index/WAL schedules and widens Tempo's
test-only WAL timestamp window so a backdated span produces a genuinely old
block. A normal two-minute WAL window had stamped the first fixture block with
current time, correctly failing the test. Another attempt exposed old query
visibility after Loki WAL replay. The final fixture waits for zero hot chunks
and a new atomically completed checkpoint before restarting; a checkpoint-start
counter alone is insufficient. Both failed attempts are retained alongside
`evidence/issue58/step8-retention.json`.

Command: `backend/.venv/bin/python scripts/check-monitoring-retention.py --report
docs/milestone9-observability/evidence/issue58/step8-retention.json`.
The two pure fixture/ownership checks passed. Production configuration and image
pins are unchanged by this step. Duration-based cleanup is proven for the stored
fixtures; it does not establish a disk byte ceiling or continuous capacity.
