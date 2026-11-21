# Issue #67 observability acceptance evidence

Verified on 2026-11-21 ICT against `f6379eb` plus the Issue #67 working-tree
changes. The published issue matches T10 in the task plan
and depends on #66. See [GitHub issue #67](https://github.com/ShinningF1eld/RestaurantOS/issues/67)
and [design requirements](milestone-9-observability-design.md#requirements-and-observable-acceptance).

## Candidate check results

Windows, Python 3.12.13, Node 24.14.1 and Docker 29.6.2 (Linux AMD64).
Commands below use `backend/.venv-observability/Scripts/python.exe` as the
interpreter. Reports and build logs are under the ignored `test-results/`
directory.

| Command | Result on 2026-11-21 ICT |
| --- | --- |
| `./scripts/validate.ps1 -PythonExecutable backend/.venv-observability/Scripts/python.exe` | Committed Python and npm locks installed. The first Docker-enabled run stopped at Windows' command-line limit in the secret hook and cleaned up its Compose services. The rerun with the stdin file list passed baseline, backend static and frontend static, then stopped at four unit fixture failures. The fixture corrections passed the unit gate below. The rerun used `npm_config_prefer_offline=true` and `npm_config_audit=false`. |
| Same locked command after corrections, with the same npm settings | **Passed all ten gates in one run**, ending at 14:43 ICT with `PASS: full validation` after disposable Compose cleanup. Backend integration passed 379 tests with the single explicit opt-in workload skipped. The stored API workload passed separately below. |
| `scripts/validate.py --gate image --gate migrations --no-install` | Passed both production images, four native configuration parsers, native alert rules, 142 exact dashboard query checks and stored API telemetry correlation and canary exclusion across all three stores. The smoke verified owned cleanup. Clean and seeded upgrades, backup/restore, history guards and schema drift checks passed on disposable databases. |
| `scripts/validate.py --gate backend-static --gate backend-unit --gate frontend-tests --gate frontend-build --gate browser --no-install` | Passed Ruff and mypy, 536 backend unit tests, 36 frontend tests and the standalone build. Chromium passed 29 host journeys and 15 HTTPS gateway cases. Both intentional browser failures propagated and verified owned-resource cleanup. |
| `scripts/validate.py --gate backend-integration --no-install` | Initial partial run reported 377 passed, 1 opt-in skip, 2 failures and 3 teardown errors. Redis timed out during admission/finalization or fixture cleanup. The worker terminal/replay test received one of three expected attempt spans because early process termination skipped exporter drain. |
| `python -m pytest -q tests/unit/test_validation_policy.py tests/unit/test_local_observability_objectives.py` | Passed all 25 focused tests after adding the ambient telemetry endpoint isolation assertion. |
| `scripts/check-frontend-observability.py --mode host --dashboard-links` | Passed live authenticated SSR ancestry and the Grafana-to-Loki-to-Tempo investigation with a committed worker attempt link. Passed malformed/missing context, canary exclusion, renewal redirect, tenant isolation, Collector-absent operation and owned cleanup. |
| `scripts/check-frontend-observability.py --mode container` | Passed the authenticated SSR/API trace, privacy, isolation, renewal and Collector-loss checks with the production images. Owned monitoring, database, services and processes were removed. |
| `scripts/check-operator-dashboards.py --runtime --report test-results/monitoring/issue67-dashboards.json` | Passed live provisioning and authentication, 95 authenticated query results, source outages, normal restart and owned cleanup. [Retained report](evidence/issue67/dashboards-2026-11-21.json.gz) |
| `scripts/check-api-observability.py` | Passed the opt-in stored API workload separately. Verified 242 series, 228 capacity groups after quiet re-export, correlated Loki/Tempo, body and identifier canary exclusion, independent Collector filtering, and owned cleanup. |
| `scripts/check-monitoring-retention.py --dashboard-links --report test-results/monitoring/issue67-retention.json` | Passed physical removal of the old Prometheus block, Loki chunks and Tempo block with fresh controls retained. The retry search found a worker attempt after the original trace expired. Verified cleanup and the seven-day metrics and three-day logs/traces settings. [Retained report](evidence/issue67/retention-2026-11-21.json.gz) |
| `scripts/check-monitoring.py --mode host --scenario restart --report test-results/monitoring/issue67-restart.json` | Passed persistence across a normal restart and verified removal of the disposable resources. [Retained report](evidence/issue67/restart-2026-11-21.json.gz) |
| `scripts/check-infrastructure-observability.py` | Passed restricted PostgreSQL stats access and Redis INFO-only access, denial checks, stored receiver and SDK diagnostics, canary exclusion, missing-source detection, Collector-absent application operation, and recovery. Recorded per-container resource samples for the bounded exercise and removed owned resources. |
| `python -m pytest -q tests/integration/test_event_telemetry.py::test_http_command_to_restarted_worker_all_consumers` | Passed on an owned database migrated to head and isolated Redis. The test matched the committed PostgreSQL request/trace/span identifiers to the HTTP spans and checked the re-exported publication and consumer links after worker restart. |

After switching the terminal/replay test to the existing graceful worker stop,
20 focused tests passed on fresh disposable PostgreSQL and Redis. The selection
was `tests/integration/auth/test_redis_admission.py`,
`test_alert_projection.py::test_diagnostic_sink_stores_only_safe_deduplicated_event_facts`,
and the terminal/replay and HTTP-to-restarted-worker tests in
`test_event_telemetry.py`.

Re-evaluating the historical #65 archive with the new objective checker passed
all thresholds in enabled repetitions 2, 3 and 6. This checks the interpretation
of the approved limits against known data.

## Final paired baseline

`scripts/benchmark-local-observability.py --report test-results/monitoring/issue67-baseline.json.gz`
passed all six repetitions from 14:43 to 15:00 ICT on an otherwise idle Docker
engine. The workload reconciled 200 succeeded deliveries per repetition.
Every enabled repetition passed all 17 objective and budget checks. The
command used the two production images built by the shared image gate, tagged
for the existing benchmark runner. [Retained baseline](evidence/issue67/baseline-2026-11-21.json.gz)

| Enabled repetition | Slowest read P95 (ms) | Slowest command P95 (ms) | Menu SSR P95 (ms) | Unexpected attempts | Slowest consumer P95 (s) | Maximum processed effect (s) | Peak monitoring working set (GB) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 26.95 | 35.33 | 47.58 | 0 / 306 | 1.518 | 1.577 | 0.585 |
| 3 | 25.30 | 33.40 | 37.74 | 0 / 306 | 1.556 | 1.624 | 0.576 |
| 6 | 26.65 | 37.10 | 52.35 | 0 / 306 | 1.522 | 1.574 | 0.586 |

The largest sampled sum of monitoring CPU across services was 13.78% of one
logical core. Monitoring volumes occupied at most 4,411,392 allocated bytes
in the post-workload measurements. The enabled runs recorded zero container
restarts, OOM kills, and SDK warning lines. Per-service memory, CPU, disk,
exporter signals, source hashes and the image pins are in the archive. The
memory result is below the 2 GB local budget for this workload.

## Final incident rehearsal

`scripts/check-local-incidents.py --report test-results/monitoring/issue67-incidents.json`
passed all six cases on 2026-11-21 from 13:51 to 14:29 ICT. The archive includes
the exact production image IDs, monitoring config hashes, local notification
fields, reconciliation and owned-resource teardown. [Incident evidence](evidence/issue67/incidents-2026-11-21.json.gz)

| Exercise | Observed result |
| --- | --- |
| API failure | 298 injected writes returned 500 and persisted zero orders. The sanitized failure appeared in Loki and Tempo. Grafana delivered the firing and resolved notifications. |
| Database exhaustion | Two live PostgreSQL connections overlapped. Readiness returned 503 in a 1.015-second recorded API span. The pool alert resolved and the existing authenticated session recovered. |
| Redis outage | Catalog reads and authentication continued through fallback. The oldest-queued-work alert fired and resolved as durable work recovered. |
| Worker stop | The backlog alerted while the worker was stopped and remained actionable during an additional Collector gap. Worker restart processed the retained deliveries and cleared the alert. |
| Repeated job failure | The run observed retries and terminal failure, repaired the fault and replayed through the trusted operator command. The alert resolved with preserved attempt history and one committed effect. |
| Monitoring outage | Collector, Loki/Tempo and Grafana loss left business operations available. The run retained bounded exporter queues, resumed telemetry and reconciled 64 deliveries with 64 receipts and seven stock consumptions for seven completed orders across the rehearsal. |

The separate `--inject-failure --report test-results/monitoring/issue67-cleanup.json`
run returned 1 at the intentional stage and verified that owned resources were
removed. Retained incident and cleanup reports were checked for credential,
cookie, raw body and log fields and the injected canary. [Cleanup evidence](evidence/issue67/cleanup-2026-11-21.json.gz)

## Requirement and exit checks

The slice records below provide dated historical evidence. Candidate validation
results are recorded separately here.

| Requirement | Executable checks and dated evidence |
| --- | --- |
| R1 · Five-service foundation | `baseline` renders both Compose models. `image` checks pinned native parsers and starts all five services for a private runtime API smoke. The [2026-11-01 #58 pre-merge recheck](recheck-milestone9-issue58.md) records pinned images, data sources and lifecycle. |
| R2 · Resource budget | `benchmark-local-observability.py` enforces the 2 GB aggregate working-set ceiling in each measured telemetry-on repetition. `benchmark-monitoring.py --mode host` and `--mode container` measure memory, CPU, disk, drops and restarts for the monitoring-only workload. The [#58 resource experiment](performance-milestone9-issue58.md) and [#65 baseline](performance-milestone9-issue65.md#cpu-memory-disk-and-telemetry-volume) document historical limits and peak samples. |
| R3 · Server request tracing | `frontend-tests` exercises OTLP, context trust and SSR transport. `check-frontend-observability.py` verifies stored SSR/API ancestry in both modes. `image` verifies direct API traces and correlated Loki logs. The [#60 evidence](verification-milestone9-issue60.md) covers the SSR/API scope. The design describes correlated SQL/Redis investigation. Current SQL/Redis timing is metric-based and per-operation SQL/Redis trace correlation remains open. |
| R4 · Durable async correlation | `backend-integration` runs `test_event_telemetry.py` for atomic persistence/rollback, legacy events, and exact origin and worker restart links. `migrations` checks additive metadata upgrades and history preservation. See the [2026-11-06 #62 recheck](verification-milestone9-issue62.md). |
| R5 · Privacy and best effort | `backend-unit`, `backend-integration`, `frontend-tests` and `image` cover source/Collector canaries, bounded export failure, drops and recovery. The [#59 follow-up](verification-milestone9-issue59.md) covers the stored API workload. The [#66 outage exercise](verification-milestone9-issue66.md#alerts-and-incident-results) documents service-loss observations. |
| R6 · Private access and retention | `baseline` and `backend-unit` check network bindings, retention and persistence configuration. `check-monitoring.py --scenario restart` verifies retained records after restart. `check-monitoring-retention.py --dashboard-links` proves physical deletion and survival of fresh controls. See [#58 verification](recheck-milestone9-issue58.md) and [#64 verification](verification-milestone9-issue64.md). |
| R7 · Four dashboards | `image` runs `check-operator-dashboards.py` against exact PromQL fixtures for all four dashboard models and parses links. `--runtime` checks authenticated provisioning, stored data and missing sources. `check-frontend-observability.py --dashboard-links` opens the real filtered links. See [2026-11-09 #64 results](verification-milestone9-issue64.md). |
| R8 · Local alerts | `image` runs `check-alert-rules.py` with pinned Prometheus and the provisioned Grafana expressions. `check-local-incidents.py` observes notification firing, recovery, grouping and missing-source behavior via a private receiver. See [2026-11-20 #66 results](verification-milestone9-issue66.md). |
| R9 · Two development modes | `check-monitoring.py --mode host` and `--mode container` prove the two monitoring network models on owned services. The frontend observability runner exercises real API/Next.js in each mode on disposable PostgreSQL. See the [#58 recheck](recheck-milestone9-issue58.md) and [#60 evidence](verification-milestone9-issue60.md). |
| R10 · Operational proof | Run [full locked validation and the acceptance matrix](../testing/monitoring.md#final-m9-observability-acceptance-67). The [2026-11-19 objective approval](performance-milestone9-issue65.md#reproduction-and-approval-record) and [2026-11-20 incident results](verification-milestone9-issue66.md) predate this candidate. |
| R11 · Honest business signals | Required backend business collection and event projection tests exercise commits, replays, windows and freshness. Native dashboard fixtures cover stale/disabled data; the paired baseline reconciles durable receipts, stock movements and retained sales. See [2026-11-08 #63 evidence](verification-milestone9-issue63.md). |
| R12 · Restricted infrastructure diagnostics | Required configuration, pooled API/worker and worker-export tests check bounded source signals. `check-infrastructure-observability.py` verifies least-privilege read-only PostgreSQL/Redis collection, denied operations, resource samples and recovery on disposable services. See [2026-11-03 #61 evidence](verification-milestone9-issue61.md). |
| Roadmap exit · Follow a request through API, database, outbox and worker | Required `test_http_command_to_restarted_worker_all_consumers` joins echoed request IDs and API span IDs to actual PostgreSQL outbox rows, then checks linked worker exports after restart. The [operator investigation](../runbooks/monitoring.md#follow-an-investigation) reproduces that join using the request log, trusted database inspection and worker traces. |
| Roadmap exit · A deliberate failure appears in dashboards/logs and has a documented response | `check-local-incidents.py --incident api-failure` injects a real test database write failure, correlates the sanitized Loki log to Tempo, verifies error telemetry and alert delivery, and checks that the write rolled back and recovery resolved the alert. The [runbook](../runbooks/local-incidents.md) documents the response. The [#66 evidence](verification-milestone9-issue66.md#alerts-and-incident-results) records the prior execution. |

## Acceptance boundaries

All ten gate definitions and the exact `Milestone 6 acceptance` aggregate are
preserved. The workflow and branch enforcement policy are unchanged. Final
candidate PR CI requires separately authorized publication.
Local validation, incident and numerical objectives passed. Milestone acceptance
remains open for candidate PR CI and R3's per-operation SQL/Redis trace coverage.

Issue #67 adds no application schema or API change. The repository migration
head is `d4e9f2a63b85`, the existing additive nullable outbox trace-context
revision. The actual developer application database revision was not inspected
or advanced. Validation uses disposable databases.

Browser tracing, external alert delivery, a dedicated error-tracking lifecycle,
M10 analytics, and hosted deployment, resource and reliability guarantees are
deferred. The historical deployment M9 references retain their M15 history.
