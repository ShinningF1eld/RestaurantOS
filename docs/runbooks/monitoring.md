# Optional local monitoring

This runbook covers the optional local monitoring stack, its telemetry sources
and its provisioned Grafana dashboards. Final alert objectives belong to later
M9 issues. Starting monitoring does not migrate the application database.

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

Synthetic signals must use the declared service, metric and span names.
Application signals have separate admission policies and explicit opt-ins.
In Grafana Explore,
select RestaurantOS Metrics, Logs or Traces. Workload metrics include
`restaurantos_synthetic_operations_total` and the seconds histogram. Loki uses
`{service_name="restaurantos-monitoring-synthetic"}`. Trace/log IDs are metadata,
not metric/index labels. Provisioning includes stable IDs and correlation links.

## Operator dashboards

Sign in to local Grafana and open the **RestaurantOS** folder. The four
dashboards are managed from the repository and link to one another with the
current time range. Service Overview is the starting point for incidents.

- **Service Overview** separates expected HTTP outcomes, such as authentication,
  forbidden, validation, conflict and rate limit, from unexpected server errors.
  Error share requires positive measured traffic. Latency percentiles estimate
  the distribution from histogram buckets. Last completed request age grows
  during inactivity. Check the API observation-series status and Collector scrape
  targets before interpreting gaps. A fresh stack with no recorded request has
  no API counter. A sampled counter that stays flat can show measured zero
  activity. Send a known request if you need to distinguish a quiet startup from
  an unavailable API exporter.
- **Database & Redis** separates SQL cursor time, pool acquisition time and Redis
  command time. Acquisition includes connecting and pre-ping. A missing pool
  gauge can mean an unsupported pool such as NullPool. The PostgreSQL lock count
  includes held and requested locks. Redis command duration comes from the
  application adapter. The cache ratio uses catalog hits divided by hits plus
  misses per cache, with bypasses shown separately. Check receiver series
  presence and scraper diagnostics when server statistics go missing. The
  Collector may re-serve a previous observation until its 30-second expiry.
- **Background Processing** shows PostgreSQL delivery depth and age. An event
  may have multiple deliveries. Each delivery can have several attempts across
  retries and replay. Queued, in-flight, retry-delayed and recovery-due work
  count as unfinished. Terminal failures are separate. Receipt-window gauges
  measure durable progress, including skipped receipts. Retries and duplicate
  ACKs do not count as additional business events. Assign distinct worker slots
  to see process-local attempt and diagnostic rates. If all workers stop, the
  worker snapshot becomes stale or disappears. While the API business sampler
  runs, Business Activity continues to show increasing age for waiting analytics
  deliveries.
- **Business Activity** shows observed post-commit order transition rates and
  stock rejection attempts separately from durable low-stock state and episode
  openings. Sales cover seven UTC dates grouped by **order creation date**. The
  period starts at 00:00 UTC six calendar dates before the snapshot date and ends
  at 00:00 UTC the following date. The current UTC date is partial. Permitted
  deletion can lower retained totals. THB amounts require the existing opt-in
  and verified THB-only retained prices. PostgreSQL NUMERIC and Python Decimal
  remain authoritative for the operational projection. A fresh source collection
  can report unfinished or terminal analytics work, so check the delivery panels
  and use scoped reconciliation for discrepancies.

Process counter rates use a one-minute window and handle resets before
aggregation. Gaps mean unavailable or insufficient samples. For aggregate
panels, the worker freshness budget is 45 seconds. Business Activity reads the
API-reported budget, which is 75 seconds at the default collection and export
intervals. Restart the API and Collector when rolling out this dashboard change
so the API publishes the budget and the Collector admits it. A successful
collection without the budget shows **Freshness budget unavailable** and
suppresses the aggregate values. A failed collection suppresses previous
business values immediately once the failure signal is exported. A successful
scrape only proves the scrape succeeded. Collector send failures, enqueue
failures and refusals show reported pipeline failures with different
denominators. The counts can overlap and upstream SDK losses may be invisible.

### Exercise the dashboards with real local orders

Use a dedicated **local development or test** API, PostgreSQL database, Redis
instance and test account. The loopback API must point to those test services.
Use one runner at a time and keep the fixture free of other writers during the
exercise. The script requires explicit test-data confirmation and checks the
restaurant and fixture before writing orders or stock.

1. Use the development Python environment from the
   [Windows quick start](../../README.md#windows-quick-start) and the
   [authentication runbook](authentication.md#local-setup). Point
   `DATABASE_URL` and `REDIS_URL` at dedicated local services before applying
   migrations or provisioning the test account. Use a separate database from
   the automated test suite, which truncates its target. A fresh account needs
   a test organization and an Owner membership. See
   [organization setup](../api/tenancy.md).
2. With that test Owner, create a restaurant named exactly
   **Dashboard Exercise (TEST)**. Record its numeric ID from its URL or from
   `GET /api/restaurants`. In that restaurant create only these fixture records:

   | Fixture | Setup |
   | --- | --- |
   | Ingredient **Dashboard Test Stock** | Active, unit `piece`, opening quantity `1`, reorder threshold `1` |
   | Menu **Dashboard Test Menu** | One menu in the test restaurant |
   | Menu item **Dashboard Test Order** | Available, positive price (for example `20.00`) |
   | Item recipe | Enable inventory tracking and add exactly `1` piece of **Dashboard Test Stock** |

   Use the restaurant, inventory and menu screens, including the item's recipe
   editor. The same setup is available through the
   [inventory](../api/inventory.md) and [recipe](../api/recipes.md) APIs.
3. Start local monitoring and keep it running. Set `MONITORING_ENABLED=true`,
   `MONITORING_ENDPOINT=http://localhost:4318` (or the configured loopback
   OTLP port), and `DATABASE_ECHO=false` for the API and worker. Set
   `MONITORING_BUSINESS_AGGREGATES_ENABLED=true` on one API process and start
   or restart it to apply the settings. To see API pool gauges, run the
   dedicated test data in development mode so the API uses its regular pool.
4. Start the [standalone worker](event-worker.md#start-and-stop) with the
   same test database and Redis settings. In a separate PowerShell window
   from the repository root, with the same service settings available:

   ```powershell
   Set-Location backend
   $env:MONITORING_WORKER_SLOT = "0"
   .\.venv\Scripts\python.exe -m app.worker
   ```

   Use an unused worker slot if another worker is already exporting to that
   Collector.

From the repository root, substitute your fixture's ID for `123` and run in
an interactive PowerShell window:

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\exercise-dashboards.py --restaurant-id 123 --confirm-test-data
```

The script prompts for the test email and hides the password. The API defaults
to `http://localhost:8000`; set `--base-url` for another direct loopback API.
`--origin` defaults to `http://localhost:3000` and must match an entry in
`AUTH_TRUSTED_ORIGINS`. The script uses the normal login cookie and CSRF
headers throughout the run.

The default is 20 serial workflows with a three-second pause between them,
about a minute plus request and worker time. Each workflow reads the menu and
items twice, drafts and submits one order, receives one piece of stock, and
accepts the order to consume that piece. The order moves through Preparing and
Ready to Completed, then the script reads the restaurant's analytics. Each
receipt lifts stock above the threshold and each acceptance takes it back to
one piece, opening a real low-stock episode. The script waits up to 60 seconds
for the worker's projected episode history and reports how many orders it
could match. Use `--count 1` for a smoke run or `--help` for the bounded options.

Save the printed run ID. After an interruption, rerun with
`--run-id <printed-id>` and the original restaurant, API and count. Do this
before starting a new run. The script reuses receipt and order creation keys
and reads each order's current status before advancing it. A new run ID adds
new test records. Completed orders, ledger movements and projected history
are retained in the test database. Projection verification checks the latest
100 history rows, so inspect the dashboard's historical time range for older
runs.

#### Check the workload in Grafana

Open the **RestaurantOS** folder at `http://localhost:3001` (or your Grafana
port) and choose **Last 15 minutes**. Leave the API and worker running through
at least one business collection interval (30 seconds by default), plus the
export and scrape intervals.

| Dashboard | What to check |
| --- | --- |
| **Service Overview** | Order, inventory and analytics routes in request rate and latency. In Explore, check `restaurantos_http_requests_total` and use the request panel links for logs and traces. |
| **Database & Redis** | SQL query and Redis command observations, then cache outcomes in `restaurantos_catalog_cache_lookups_total`. Look for hits from paired reads and misses as entries expire. `restaurantos_pool_used` is an instantaneous gauge and can stay at zero between scrapes. PostgreSQL and Redis server panels require their [optional receivers](../../monitoring/database-redis.md). |
| **Background Processing** | Look for consumer commits in `restaurantos_worker_operations_total{outcome="consumer_committed"}` and progress in `restaurantos_worker_receipts_window`. A drained queue can have zero depth after the worker catches up. |
| **Business Activity** | Look for `restaurantos_business_orders_transitions_total{transition="COMPLETED"}`, `restaurantos_business_stock_episode_openings_24h` and, after analytics delivery and sampling, `restaurantos_business_sales_retained_orders_7d`. Retained orders are stack-wide across seven UTC creation dates. The THB amount panel requires the separate verified-currency opt-in. |

If the script reports completed orders but times out waiting for history,
check the worker's delivery panels and confirm it uses the same database and
Redis instance as the API. Reusing the run ID checks those orders again.
Healthy traffic can leave error, retry and terminal-failure panels idle.
This exercise verifies dashboard activity. The separate [paired application baseline](../milestone9-observability/performance-milestone9-issue65.md)
compares telemetry on and off with disposable data. Its local numeric alert
settings were approved on 2026-11-19 for the T9 rule and incident exercises.

### Follow an investigation

1. Narrow the dashboard time range around the incident. Click a data point on
   **Requests by route**, **Request outcomes**, **Server errors by route** or
   **P95 duration by route** and choose **Open matching API request logs**.
   Explore uses the selected dashboard range and the matching route or outcome
   where the panel carries it. Route and outcome are Loki structured metadata.
2. Pick a matching sanitized request log and use its **TraceID** link to open
   the exact Tempo trace. The aggregate point can cover several requests. In
   Tempo, inspect the API span and related Next.js server, render and API-client
   spans when the request came from SSR. SQL and Redis timing in the current
   contract is metric-based. Use Database & Redis for those signals.
3. For a request that wrote an event, note the API request ID and the span's
   trace and span IDs. Use trusted database inspection to locate the matching
   outbox row by correlation ID. Use its delivery UUID with the
   [event inspect command](event-worker.md#operational-inspection) to inspect
   attempts and receipts. Compare the worker attempt's span link with the
   originating API span.
4. For retries or worker failures, use the Background Processing attempt
   panel link to search Tempo for the selected operation, consumer and outcome.
   Compare with the worker's structured JSON diagnostics on local stdout/stderr.
   Each attempt has its own trace root and can link to the original request
   context. For older work, use
   the [authorized event status and inspect commands](event-worker.md).

Tempo and Loki retain about three days. The original HTTP trace can expire
before a delayed attempt or replay. Search the recent attempt window directly
to find an available worker trace. Retained event and correlation metadata
cannot reconstruct an expired trace.

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

## PostgreSQL/Redis collection and pool pressure (#61)

Follow the [infrastructure contract](../../monitoring/database-redis.md) for dedicated
identity provisioning, opt-in host/container setup, exact metric mappings, timeouts
and receiver limitations. Application startup never provisions or requires collection.
When SQL latency rises, compare execution histograms with pool acquiring/used/limit
and acquisition-timeout counts, then PostgreSQL backends/max-connections, locks and
deadlocks. Idle counts are actual connections; acquiring is not a queue-waiter count.
Do not increase application pool limits as an observability fix. Check transaction
failures separately from read-session cleanup and expected business rejection.

For Redis degradation, compare API and worker command duration/failure categories
with server memory/maxmemory/evictions/rejected-connections. Catalog effectiveness
uses feature hit/miss/bypass observations; server keyspace hits/misses and auth
limiter commands are separate denominators. Preserve cache source-age and circuit
cooldown and worker retry/replay keys; monitoring does not authorize cache flushes
or business repairs. A missing receiver series or failed scrape is collection loss,
not a healthy zero. Check both Collector scrape targets and rotated Collector logs.
The Redis scraper timeout is not enforced as a command deadline by the pinned
receiver; use the documented finite driver bounds and missing-series checks.

Rehearse only with `scripts/check-infrastructure-observability.py` and its owned
service/network/volume identities. Never pause/restart developer containers or
delete their volumes to test collection. Existing maintenance/backup procedures
remain authoritative for any separately authorized live database operation.

## Local alerts

The provisioned incident rules and notification grouping are documented in the
[local incident runbook](local-incidents.md). Run the
[disposable rehearsal](../testing/monitoring.md#local-alerts-and-incident-verification-66)
to capture notifications and exercise recovery.
