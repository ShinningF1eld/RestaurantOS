# Issue #63 implementation verification

Reviewed on 2026-11-08 (Asia/Bangkok) against
[GitHub Issue #63](https://github.com/ShinningF1eld/RestaurantOS/issues/63) and
Milestone 9 design R5, R11 and R12. The implementation is a local working-tree
change based on `ff3726e`, which includes issues #59 and #62. The
[metric contract](../api/business-observability.md) defines units, windows,
configuration and operator interpretation. Schema, HTTP permissions, event
contracts and infrastructure topology are unchanged.

| Issue criterion | Focused result | Evidence |
| --- | --- | --- |
| Committed lifecycle | Passed | The service records the transition after its existing transaction context exits. Integration tests inspect actual OTLP counters for submission, completion and cancellation. They exercise a validation failure, rollback after event insert, a PostgreSQL deferred-trigger failure at commit, unchanged states and creation replay. Collector rejection leaves order commands successful. |
| Separate stock signals | Passed | Repeated order shortages and waste rejections yield two attempts each, with zero openings. A committed threshold crossing opens one producer episode. Projection delivery, receipt replay and live recovery demonstrate the independent active-alert count. Baseline initialization preserves a separate suppressed opening and rerun identity. |
| Durable sales and period | Passed | The window uses daily projection rows and the UTC creation dates documented in the contract. Integration tests assert both midnight boundaries, exact SQL totals, new-ID duplicate deliveries, receipt replay, a deletion-first tombstone and a permitted delete decreasing the gauge after projection. |
| Precision and currency | Passed | Tests compare the PostgreSQL `Decimal("100000000.01")` with its exported conversion, and assert amounts are absent without the THB setting. The UI's existing THB assumption and the operator attestation are documented. |
| Collection and projection freshness | Passed | Tests export a valid zero, leave queued completion work while source collection succeeds, check increasing age without a worker, and exercise retry, in-flight, recovery and terminal states. Failed SQL, statement timeout and read-only enforcement use PostgreSQL. Repeated exports retain the old source timestamp while a source stalls. A successful read restores freshness. |
| Bounded, private collection | Passed | The snapshot uses a read-only repeatable-read transaction, a statement timeout and an application deadline. A native Collector probe strips seeded unapproved attributes and drops an invalid rejection category. The scoped analytics route rejects foreign and unauthenticated access, and there is no API metrics route. The seeded cost check below covers existing index use. |

## Seeded query comparison

The comparison ran on a disposable PostgreSQL 18.4 instance using the actual
four aggregate SELECT statements and their bound parameters. Both fixtures
held 32 branches across four organizations, 800 ingredients, 100 live low
ingredients, 50 matching projected alerts and five queued analytics deliveries.
The larger fixture added old sales and resolved episode rows plus completed
deliveries, while keeping rows inside the sales and opening windows constant.
Ran `ANALYZE` on the touched tables. Each value is the median server execution
time of six warm `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` executions after
one warm-up. Shared blocks are the hit-plus-read count in the final plan.

| Retained input | Small | Large |
| --- | ---: | ---: |
| Daily sales rows | 224 | 23,360 |
| Producer episode rows | 324 | 23,460 |
| Analytics deliveries | 37 | 20,037 |

| SELECT | Small median ms / blocks | Large median ms / blocks | Large fixture indexes used |
| --- | ---: | ---: | --- |
| Retained sales | 0.484 / 65 | 0.199 / 129 | Daily sales primary key |
| Inventory summary | 0.490 / 87 | 0.622 / 119 | Episode organization/restaurant/opened-at |
| Live-matching alerts | 0.293 / 308 | 0.237 / 260 | Open episode partial index and balance primary key |
| Analytics backlog | 0.031 / 1 | 0.031 / 2 | Unfinished and failed delivery observability index |

Both fixtures returned 672 orders, `26936.00` THB, 100 recent operational
openings, zero baseline openings, 100 active low ingredients, 50 active
alerts and five queued deliveries. The comparison measures retained-history
growth at a fixed live workload. Query cost can grow with the number of
branches, live ingredients, recent episode openings and outstanding work.

## Validation

- `./scripts/validate.ps1 -Gate backend-static -NoInstall` passed Ruff,
  formatting and mypy.
- `./scripts/validate.ps1 -Gate backend-static,backend-unit,baseline -NoInstall`
  passed using a workspace-owned temporary directory. The unit gate passed
  529 tests.
- From `backend/`, `.venv/Scripts/python.exe -m pytest tests/integration/test_business_metrics.py -q --tb=short`
  passed all six focused Issue #63 tests against a migrated, isolated PostgreSQL
  database and disposable Redis. `.venv/Scripts/python.exe -m alembic check`
  found no schema drift. The local fallback used Python 3.13.15, PostgreSQL 18.4
  and Redis 8.0.5.
- The digest-verified Windows binary for Collector Contrib 0.164.0 validated
  `monitoring/otel-collector.yaml`. A separate loopback-only native run
  exercised OTLP admission, the expected Prometheus exposition names and
  units, label stripping, stale source time across successful scrapes, empty
  data after Collector restart and recovery after new export.
- `./backend/.venv/Scripts/python.exe scripts/check-monitoring-config.py` passed
  all four locked-image parsers. A disposable monitoring stack also stored
  actual SDK observations and seeded PostgreSQL gauges in Prometheus. The
  authenticated Grafana data-source proxy returned the retained count and THB
  value, stock state, analytics backlog and source freshness.
- The initial Docker-backed gate could not start while Docker Desktop was
  unavailable. `./scripts/validate.ps1 -Gate backend-integration -NoInstall -ExternalServices`
  finished with 368 passed, 10 failed and one opt-in monitoring skip. That
  run started before two Issue #63 test corrections. The final focused run
  passed both cases. The other failures covered a Docker-dependent outage
  test, six worker cases and the legacy order/dashboard flow. Running
  `.venv/Scripts/python.exe -m pytest tests/integration/test_event_telemetry.py -q --tb=short`
  against an isolated archive of `ff3726e` reproduced the same six worker
  failures, including subprocess termination and incomplete span delivery.
  The base revision also reproduced the dashboard failure with
  `.venv/Scripts/python.exe -m pytest tests/test_order_flow_integration.py -q --tb=short`.
  That live API uses the host date to select a UTC-stored order creation range
  and returned zero while the host and UTC dates differed.
- After Docker recovered, `./scripts/validate.ps1 -Gate backend-integration -NoInstall`
  completed on Windows with Python 3.13.15 and disposable PostgreSQL 16 and
  Redis 7. It reported 372 passed, seven failed and one opt-in monitoring skip.
  All six Issue #63 tests and the physical Redis outage test passed. The seven
  failures matched the six worker failures and the legacy dashboard failure
  reproduced on the base. The runner removed its owned services and network.

Milestone acceptance still requires a passing full gate set.
