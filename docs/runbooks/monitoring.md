# Optional local monitoring

This runbook covers issue #58's monitoring foundation and issue #59's optional
API HTTP telemetry. Frontend/infrastructure/worker tracing, operational dashboards
and final alert objectives belong to later M9 issues. No application migration
is involved.

API HTTP signals are optional through `MONITORING_ENABLED=true` and
`MONITORING_ENDPOINT=http://localhost:4318` (or the chosen loopback port).
For an API container on the isolated monitoring network, use
`http://collector:4318`. Keep `DATABASE_ECHO=false`. See the
[API contract](../api/observability.md) for all bounded settings and metrics.
Start the API with `--no-proxy-headers` before trusting exact upstream peer IPs.
The default trusts no incoming trace headers. Never expose OTLP publicly or
interpret trace context/service names as authentication. `/health` and `/ready`
remain independent of the monitoring stack.

In Explore, API logs use `{service_name="restaurantos-api"}` and metrics start
with `restaurantos_http_`. Inspect `telemetry_queue_full`,
`telemetry_export_diagnostic` and shutdown/startup diagnostics in local JSON when
remote collection is broken. Logs deliberately suppress raw messages/stacks.
Check `restaurantos_http_last_observation_seconds` age and scrape/export health;
missing or old data is not healthy zero activity. Do not replay business commands
because an associated trace is absent. Remote logs use only OTLP, not stdout.

## Start and stop

Use the supported Python 3.12 test environment, Docker Desktop/Compose and the
committed dependencies. Run from the repository root:

```sh
backend/.venv/bin/python scripts/local-monitoring.py init
backend/.venv/bin/python scripts/local-monitoring.py config
backend/.venv/bin/python scripts/local-monitoring.py up
backend/.venv/bin/python scripts/local-monitoring.py status
backend/.venv/bin/python scripts/local-monitoring.py down
```

Initialization refuses existing state. Choose alternate ports at initialization
with `--grafana-port` and `--otlp-port`. Grafana defaults to
`http://localhost:3001`; OTLP/HTTP defaults to `http://localhost:4318`.
Only loopback UI/ingestion listeners are published. The stores stay internal;
Grafana and Collector additionally attach to a host-ingress bridge.

The ignored `.local-monitoring/` directory holds private credential files and the
project ownership manifest. Obtain the username/password locally from those files
when logging in; do not include their contents in screenshots, reports or chats.
The parent directory is restricted; read-only secret mounts must be readable by
Grafana's container UID. Local Compose file secrets are not an encrypted vault.

Normal shutdown retains the four data volumes. Never use a generic volume-prune
command for this workflow. Keep the state manifest so the project remains
identifiable. The helper intentionally provides no developer volume-delete action.
The test harness uses separate random `restaurantos-monitoring-test-*` projects,
private temporary secrets and owned cleanup on success/failure.

## Send synthetic data

```sh
backend/.venv/bin/python scripts/generate-monitoring-telemetry.py --endpoint http://localhost:4318 --duration 10
```

Synthetic signals must use the declared service/metric/span names. API signals
have a separate admission policy and require the explicit opt-in above; database
receivers and workers remain uninstrumented. In Grafana Explore,
select RestaurantOS Metrics, Logs or Traces. Workload metrics include
`restaurantos_synthetic_operations_total` and the seconds histogram. Loki uses
`{service_name="restaurantos-monitoring-synthetic"}`. Trace/log IDs are metadata,
not metric/index labels. Provisioning includes stable IDs and correlation links.

## Diagnose missing signals

Check lifecycle `status`, then the relevant Grafana data-source health. Use the
[repeatable checks](../testing/monitoring.md) to reproduce failures in isolated
resources. Collector diagnostics remain local JSON stderr; no raw debug exporter
or stdout collection duplicates application log ingestion.

Collector self-health is not destination health or freshness. Prometheus scrapes
Collector self-metrics separately from workload metrics. Inspect export/enqueue
failures and queue occupancy/capacity along with target `up`. An unavailable
source and an expired workload series must not be interpreted as current zero
activity. The last-observation gauge is Unix time, not a duration or progress SLO.

Queues are bounded and disposable. Export retries expire; a forced shutdown or
process loss can lose buffered records and evidence of that loss. Do not retry
business commands because telemetry is missing. A stopped Prometheus leaves gaps
in stored scrape samples; a later scrape cannot reconstruct historical samples.

## Storage and resource limits

The five containers have hard memory limits totaling 2,000,000,000 decimal bytes.
Their current split is Collector 250 MB, Prometheus 300 MB, Grafana 650 MB, Loki
400 MB and Tempo 400 MB. Do not silently increase the sum. Container logs rotate;
Collector queues have no persistent backup. Temporary producer/inspection tools
consume additional resources outside that five-container sum.

Metrics use seven-day time retention. Loki/Tempo use 72-hour retention with
asynchronous cleanup; this is not an exact per-record deletion deadline. WAL,
active heads, compaction, deletion delays and caches can extend physical or query
visibility. Retention durations do not cap byte growth. Before long unattended
use, review the measured disk budget and available Docker storage in the
performance report. Docker image cache/build storage is separate from telemetry
volume growth. Monitoring data is disposable and has no backup commitment.

If resource pressure or disk constraints prevent retention, retain the failed
measurement and explicitly document loss/shortened retention or propose an
adjustment. Do not delete application volumes, broaden telemetry labels or add
permanent infrastructure to hide a failing experiment.
