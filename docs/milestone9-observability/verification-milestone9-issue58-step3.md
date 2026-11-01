# Issue #58 Step 3 — pipeline configuration verification

Recorded 2026-11-01 (Asia/Bangkok), above local Step 2 commit `1875fef`.
Step 3 changes are uncommitted at this inspection. No push, application migration
or application instrumentation was performed. This is partial T1 evidence, not
issue #58 or M9 acceptance.

## Implementation

Four service configurations install synthetic-only OTLP ingestion, sanitized
signal pipelines, Prometheus workload/self scrapes, native Loki OTLP logs, and
Tempo OTLP traces. Logs/traces use separate bounded in-memory export queues;
metrics use the Collector's pull exporter. Loki and Tempo configure three-day
retention with their Compactors and persistent local paths. Prometheus retains
seven days through the existing Compose argument.

The host overlay now attaches only Collector/Grafana to a second non-internal
bridge. Storage services remain on the internal monitoring bridge. This corrects
the published-port problem found in the first disposable runtime probe.

## Parser and component checks

The pinned ARM64 images were pulled by their existing immutable references.
No image source, version or digest was changed. The committed checker command is:

```sh
backend/.venv/bin/python scripts/check-monitoring-config.py
```

All four checks passed: Collector `validate`, Prometheus `promtool check config`,
Loki `-verify-config=true`, and Tempo `-config.verify=true`. Each runs in a
uniquely named network-disabled, read-only parser container with memory/process
limits and bounded command/cleanup timeouts. The checker removes only its own
container, including on timeout/error. Images may need fetching if not cached.
Parsing does not establish startup readiness or delivery.

Collector initially rejected mixed basic/advanced filter configuration styles;
the final configuration consistently uses advanced condition groups and passes.
Its real `components` command confirms the OTLP/PostgreSQL/Redis receivers,
memory limiter, batch/filter/transform processors, Prometheus/OTLP HTTP exporters
and health extension. See the [selected binary inventory](evidence/issue58/step3-collector-components.json).
PostgreSQL/Redis receivers remain disabled; permissions/runtime collection are #61.

## Small runtime smoke

A temporary Python harness (`/tmp/restaurantos-step3-smoke.py`) started only
Collector, Prometheus, Loki and Tempo under a unique disposable Compose project.
It used the tracked base configuration and a temporary random loopback OTLP port.
It sent one counter increment, one 0.010-second histogram observation, a
last-observation Unix-seconds gauge, one log and one two-span trace. Backend queries
ran over the internal network through the Prometheus container's `wget` command.
This temporary harness is not the permanent acceptance command; Step 7 must make
the broader scenarios reproducible. No Grafana, API, database, Redis or worker ran.

The [first run](evidence/issue58/step3-smoke-internal-bridge-failure.json) reached
all four internal readiness endpoints but failed host OTLP connection on the
internal-only network. The host received an unusable published port and
`Can't assign requested address`. The run remained failed and its project-owned
containers, volumes and networks were removed.
A separate Collector-only probe confirmed the cause independently of telemetry
or HTTP proxy behavior: Docker recorded a requested loopback binding but an empty
applied binding list, and Compose reported `:0`. That observation and its verified
cleanup are attached to the failed-run artifact.

After adding the host-ingress bridge, the [corrected run](evidence/issue58/step3-smoke.json)
passed the following assertions:

- Counter value 1, histogram sum 0.010 seconds, and freshness gauge queryable in
  Prometheus. All five scrape jobs reported `up`.
- Loki returned the expected trace/span IDs; Tempo returned both spans with the
  expected trace ID and parent-child relationship, verified explicitly in the
  final smoke repetition. The seeded private canary was absent from queried metrics, logs and trace
  output after sanitizing the tested body/attribute/status/event/tracestate paths.
- Workload metric series disappeared after their 30-second cache expiry and the
  next scrape, rather than becoming a new healthy zero.
- The four processes ran as nonroot users with read-only roots and the declared
  300/350/500/500 MB memory and equal memory-plus-swap limits. No OOM or restart
  was observed. This does not include Grafana's 350 MB share.
- Cleanup verified no remaining containers, volumes or networks bearing the
  exact disposable Compose project label.

The Docker engine reported native ARM64 and 8,319,770,624 memory bytes. This is a
current engine observation, separate from the design's user-reported 7.49 GB.
Neither establishes free capacity or the full five-service 2 GB fit. Configuration
fingerprints and detailed assertions are retained with each run.

## Boundaries and remaining verification

The pipeline deliberately accepts only `restaurantos-monitoring-synthetic` and
the documented fixture metric/span names. It replaces free-form log bodies and
removes arbitrary attributes/events; it is not an application log policy. Source
service names are not authenticated identities. Full application export privacy,
including framework/exception paths and arbitrary OTLP metadata, belongs to #59
and later instrumentation work. Collector diagnostics remain local JSON stderr;
there is no debug/raw-payload exporter or stdout ingestion.

Grafana provisioning and secret initialization are still pending. Retention
deletion, normal restart persistence, all destination outages, saturation/drop
behavior, full shutdown pressure, the declared sustained workload and CPU/memory/
disk measurements were not established by this smoke. Neither parser success nor
one successful operation satisfies those acceptance criteria. No time-based or
size-based cleanup was artificially claimed; the initial disk budget remains
measurement work.

## Shared validation

These partial commands passed with installed dependencies:

```sh
backend/.venv/bin/python scripts/validate.py --gate baseline --no-install
backend/.venv/bin/python scripts/validate.py --gate backend-static --no-install
backend/.venv/bin/python scripts/validate.py --gate backend-unit --no-install
```

The unit gate passed 425 tests, including five new configuration/cleanup checks
and the updated host-overlay regression. Static validation now includes the
parser checker. The first static attempt required an explicit `check=False` on
the inspected cleanup subprocess; the final lint/format/type run passed. Baseline
initially returned 3 because lock metadata additions moved existing reviewed hash
lines. Only those line references were refreshed; findings and detector policy
are unchanged. The subsequent baseline run passed.

Both base/host `docker compose ... config --quiet` checks passed with a placeholder
absolute `MONITORING_STATE_DIR`; they create no runtime secrets/resources.
`git diff --check` passed. Locked installation, backend-integration, frontend
tests/static/build, migrations, browser and the application image gate were omitted.
No application or image build source changed. Four locked monitoring binaries were
actually run for parser/smoke checks, but this is not the application image gate,
full ten-gate validation, Grafana verification or CI evidence. No gate names or
the `Milestone 6 acceptance` aggregate were changed.
