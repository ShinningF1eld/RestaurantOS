# Issue #64 Grafana dashboard verification

Reverified on 2026-11-09 in the Windows workspace with Python 3.12.13. This report covers the uncommitted Issue #64 implementation and freshness fix on `main` at `1d760b4`. Checks used pinned monitoring images and disposable monitoring, PostgreSQL and Redis projects with synthetic data.

Sources include [Issue #64](https://github.com/ShinningF1eld/RestaurantOS/issues/64), [T7 in the task plan](milestone-9-observability-task.md#t7-provision-four-linked-grafana-operator-dashboards), [design requirements R5, R7, R11 and R12](milestone-9-observability-design.md#requirements-and-observable-acceptance), the [business metric contract](../api/business-observability.md#freshness-and-query-bounds) and the [worker metric contract](../api/events.md#worker-metrics).

## Result

All six Issue #64 dashboard acceptance groups passed their focused checks. The business freshness finding is resolved. Business Activity uses the budget exported by the API, so a valid longer collection interval no longer makes healthy snapshots appear stale after 75 seconds.

## Acceptance criteria

| Issue #64 group | Status | Evidence |
| --- | --- | --- |
| 1. Four provisioned dashboards with stable identities | Passed | The pinned stack provisioned four file-managed dashboards in the RestaurantOS folder, resolved the three existing data sources, denied anonymous dashboard access and provisioned the same dashboards after restart. |
| 2. Service, infrastructure and background processing signals | Passed | Authenticated Grafana queries matched seeded results for request rates, outcome classification, latency quantiles, pool and cache signals, and durable backlog, age, retry and terminal status. Earlier native infrastructure checks exercised restricted receiver access and API and worker exports. |
| 3. Scoped Loki and Tempo links and expired origin behavior | Passed | The preceding browser review opened Explore from the API route and worker retry/failure charts. Both carried the selected absolute time range and the relevant filters. The earlier real SSR/API and worker run verified trace ancestry and the independent linked attempt. The retention run physically removed the original trace and found the recent retry through the provisioned query. |
| 4. Business metric semantics, replay and projection freshness | Passed | Source checks and seven focused regressions cover the seven UTC creation dates, the partial current day, opt-in THB, order and stock observation counters, retained gauges and replay. The pinned stack exposed a 615-second budget from an OTLP fixture for a five-minute cadence and showed four retained orders from a successful snapshot older than 75 seconds. |
| 5. Zero activity, missing and stale sources, and expected outcomes | Passed | The fixtures distinguish sampled zero, missing sources, failed collection and expired source timestamps. They check expiry at the API-reported budget and the unavailable state for historical snapshots without a budget. Expected authentication, authorization, validation, conflict and rate-limit outcomes remain separate from unexpected server errors. Runtime checks exercised Collector and store outages. |
| 6. Sanitized evidence for queries, units and filters | Passed | All 95 targets returned their seeded values and label sets through authenticated Grafana. The fixtures also verify the configured units. The budget metric carries no application dimensions. The evidence uses synthetic values and normalized route templates. |

## Resolved finding · Business Activity freshness

The previous review found that a healthy five-minute sampler could lose its dashboard data for roughly three quarters of each cycle because every aggregate query used a 75-second cutoff. The API now exports a seconds gauge when aggregate collection is enabled. The budget is twice the configured collection interval plus the SDK export interval and ten seconds for Collector batching and Prometheus scraping. This gives 75 seconds at the default settings and 615 seconds at a five-minute collection interval with five-second exports. [API collector](../../backend/app/core/business_collection.py#L128) · [Metric contract](../api/business-observability.md#freshness-and-query-bounds)

The provisioned dashboard compares the age of the last successful source transaction with that budget. A failed collection suppresses aggregates as soon as its failure status arrives. A successful snapshot without a budget shows **Freshness budget unavailable** and leaves the aggregate values unavailable. The age series is still shown when present. This applies to older exports and historical samples recorded before the metric was added. The rollout requires reloading the API and Collector. [Operator runbook](../runbooks/monitoring.md#operator-dashboards)

## Checks and evidence

Commands used `backend/.venv-observability/Scripts/python.exe` from the repository root unless noted.

| Command or procedure | Result |
| --- | --- |
| `scripts/check-monitoring-config.py` | Passed the locked Collector, Prometheus, Loki and Tempo parsers. |
| `scripts/check-operator-dashboards.py --runtime --report test-results/monitoring/operator-dashboards.json` | Passed 142 pinned PromQL checks, the native OTLP freshness probe, 95 authenticated query targets, restart, source outages and cleanup. |
| `scripts/validate.py --gate baseline --gate backend-static --gate backend-unit --no-install` | Passed baseline, Ruff, mypy and all 529 unit tests. |
| `python -m pytest -q tests/integration/test_business_metrics.py tests/integration/test_event_telemetry.py::test_retry_terminal_replay_duplicate_and_backlog_export` | Seven passed from `backend/` after upgrading a disposable database to head. The tests confirm the budget survives a failed collection and reaches the OTLP wire without attributes. |
| `git diff --check` | Passed. |

The current sanitized query and OTLP results are in `test-results/monitoring/operator-dashboards.json`. The earlier retention run is in `test-results/monitoring/operator-dashboard-retention.json`. The Service Overview and Background Processing navigation checks are retained from the preceding review. Reproduction commands are in the [monitoring test guide](../testing/monitoring.md#operator-dashboard-verification-64).

Integration verification for this fix was limited to the seven affected service-backed tests. The earlier full Windows backend integration run ended with 371 passed, eight failed and one skipped, with failures in two authentication tests and six worker process tests. The cause of those broader failures remains outside this focused verification.
