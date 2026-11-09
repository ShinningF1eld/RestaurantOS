"""Known PromQL inputs and expected outputs for the four operator dashboards."""

from __future__ import annotations


def labels(values):
    return "{" + ",".join(f'{key}="{value}"' for key, value in values.items()) + "}"


class Scenario:
    def __init__(self, name, evaluation="2m"):
        self.name = name
        self.evaluation = evaluation
        self.series = []
        self.checks = {}

    def add(self, metric, values, *, service="api", **dimensions):
        identity = {"job": "collector-telemetry", "instance": "fixture:8889"}
        if service:
            identity["service_name"] = "restaurantos-" + service
        identity.update(dimensions)
        if isinstance(values, (int, float)):
            values = f"{values}x12"
        self.series.append({"series": metric + labels(identity), "values": values})

    def expect(self, panel, unit, *samples, target="A"):
        self.checks[panel, target] = (unit, samples)


def activity():
    s = Scenario("known active inputs")
    for job in ("collector-telemetry", "collector-self", "prometheus", "loki", "tempo"):
        s.add("up", 1, service=None, job=job)
    api = "restaurantos_http_"
    route = "/api/orders/{order_id}"
    for outcome, status, per_second in (
        ("success", 200, 6),
        ("authentication", 401, 1),
        ("forbidden", 403, 1),
        ("validation", 422, 1),
        ("conflict", 409, 1),
        ("rate_limit", 429, 1),
        ("server_error", 503, 1),
    ):
        s.add(
            api + "requests_total",
            f"0+{10 * per_second}x12",
            http_route=route,
            http_request_method="PATCH",
            http_response_status_code=status,
            outcome=outcome,
        )
    # One uniform finite bucket and its +Inf bucket make interpolation unambiguous.
    for le in ("0.1", "+Inf"):
        s.add(
            api + "duration_seconds_bucket",
            "0+120x12",
            http_route=route,
            http_request_method="PATCH",
            http_response_status_code=200,
            outcome="success",
            le=le,
        )
    for method, active in (("PATCH", 3), ("GET", 1)):
        s.add(api + "inflight", active, http_route=route, http_request_method=method)
    s.add(api + "last_observation_seconds", 110)
    s.expect("API requests", "suffix: req/s", (12, {}))
    s.expect("Requests by route", "suffix: req/s", (12, {"http_route": route}))
    s.expect(
        "Request outcomes",
        "suffix: req/s",
        (6, {"outcome": "success"}),
        *(
            (1, {"outcome": o})
            for o in (
                "authentication",
                "forbidden",
                "validation",
                "conflict",
                "rate_limit",
                "server_error",
            )
        ),
    )
    s.expect("Unexpected server errors", "suffix: req/s", (1, {}))
    s.expect(
        "Unexpected server errors as a share of traffic", "percentunit", (1 / 12, {})
    )
    s.expect("Server errors by route", "suffix: req/s", (1, {"http_route": route}))
    s.expect("In-flight API requests", "suffix: requests", (4, {}))
    s.expect(
        "In-flight requests by route and method",
        "suffix: requests",
        (3, {"http_route": route, "http_request_method": "PATCH"}),
        (1, {"http_route": route, "http_request_method": "GET"}),
    )
    s.expect(
        "Prometheus scrape targets",
        "none",
        *(
            (1, {"job": job})
            for job in (
                "collector-telemetry",
                "collector-self",
                "prometheus",
                "loki",
                "tempo",
            )
        ),
    )
    s.expect("API observation series", "none", (1, {}))
    s.expect("Last completed API request age", "s", (10, {}))
    for ref, (component, direction, signal) in zip(
        "ABCDEFG",
        (
            ("exporter", "send_failed", "spans"),
            ("exporter", "send_failed", "log_records"),
            ("exporter", "enqueue_failed", "spans"),
            ("exporter", "enqueue_failed", "log_records"),
            ("receiver", "refused", "spans"),
            ("receiver", "refused", "log_records"),
            ("receiver", "refused", "metric_points"),
        ),
        strict=True,
    ):
        component_name = "otlp_http/tempo" if component == "exporter" else "otlp"
        dimensions = {component: component_name}
        s.add(
            f"otelcol_{component}_{direction}_{signal}",
            "0+20x12",
            service=None,
            job="collector-self",
            **dimensions,
        )
        s.expect(
            "Telemetry failures reported by Collector",
            "suffix: items/s",
            (2, dimensions),
            target=ref,
        )
    roles = (
        ("api", {"role": "api"}),
        ("worker", {"role": "worker", "worker_slot": "4"}),
    )
    for service, role in roles:
        for name, operation, outcome in (
            ("sql", "SELECT", "success"),
            ("pool_acquire", None, "success"),
            ("redis", "PING", "timeout"),
        ):
            operation_label = {"operation": operation} if operation else {}
            for le in ("0.1", "+Inf"):
                s.add(
                    f"restaurantos_{name}_duration_seconds_bucket",
                    "0+40x12",
                    service=service,
                    **role,
                    **operation_label,
                    outcome=outcome,
                    le=le,
                )
        s.add(
            "restaurantos_sql_duration_seconds_count",
            "0+40x12",
            service=service,
            **role,
            operation="SELECT",
            outcome="success",
        )
        s.add(
            "restaurantos_sql_slow_total",
            "0+20x12",
            service=service,
            **role,
            operation="SELECT",
            outcome="success",
        )
        s.add(
            "restaurantos_sql_failures_total",
            "0+10x12",
            service=service,
            **role,
            operation="INSERT",
            outcome="constraint",
        )
        s.add(
            "restaurantos_transaction_failures_total",
            "0+10x12",
            service=service,
            **role,
            outcome="constraint",
        )
        s.add(
            "restaurantos_pool_acquire_failures_total",
            "0+10x12",
            service=service,
            **role,
            outcome="timeout",
        )
        s.add(
            "restaurantos_redis_operations_total",
            "0+40x12",
            service=service,
            **role,
            operation="PING",
            outcome="timeout",
        )
        for name, value in (
            ("capacity", 7),
            ("limit", 10),
            ("used", 3),
            ("idle", 1),
            ("overflow", 0),
            ("acquiring", 2),
        ):
            s.add("restaurantos_pool_" + name, value, service=service, **role)
    dims = [role for _, role in roles]
    for title, number, dimensions, ref in (
        (
            "SQL executions by operation and outcome",
            4,
            {"operation": "SELECT", "outcome": "success"},
            "A",
        ),
        (
            "Slow SQL and failed SQL executions",
            2,
            {"operation": "SELECT", "outcome": "success"},
            "A",
        ),
        (
            "Slow SQL and failed SQL executions",
            1,
            {"operation": "INSERT", "outcome": "constraint"},
            "B",
        ),
        (
            "Redis command attempts by outcome",
            4,
            {"operation": "PING", "outcome": "timeout"},
            "A",
        ),
        ("Database transaction failures", 1, {"outcome": "constraint"}, "A"),
        ("Pool acquisition failures and timeouts", 1, {"outcome": "timeout"}, "A"),
    ):
        unit = (
            "suffix: failures/s"
            if "failures" in title and not title.startswith("Slow")
            else "suffix: ops/s"
        )
        s.expect(
            title, unit, *((number, {**r, **dimensions}) for r in dims), target=ref
        )
    for ref, value in zip("ABCDE", (7, 10, 3, 1, 0), strict=True):
        s.expect(
            "SQLAlchemy pool size and use",
            "suffix: connections",
            *((value, r) for r in dims),
            target=ref,
        )
    s.expect(
        "Pool acquisitions in progress", "suffix: acquisitions", *((2, r) for r in dims)
    )
    for cache, outcomes in (
        ("menus", (("hit", 3), ("miss", 1), ("bypass", 5))),
        ("menu_items", (("miss", 2), ("bypass", 1))),
    ):
        for outcome, per_second in outcomes:
            s.add(
                "restaurantos_catalog_cache_lookups_total",
                f"0+{per_second * 10}x12",
                cache=cache,
                outcome=outcome,
            )
    s.expect(
        "Catalog cache hit share",
        "percentunit",
        (0.75, {"cache": "menus"}),
        (0, {"cache": "menu_items"}),
    )
    s.expect(
        "Catalog cache outcomes",
        "suffix: lookups/s",
        *(
            (n, {"cache": c, "outcome": o})
            for c, o, n in (
                ("menus", "hit", 3),
                ("menus", "miss", 1),
                ("menus", "bypass", 5),
                ("menu_items", "miss", 2),
                ("menu_items", "bypass", 1),
            )
        ),
    )
    s.expect("Server diagnostic series", "none", (1, {}), target="A")
    s.expect("Server diagnostic series", "none", (1, {}), target="B")
    for ref, kind, rate in (("A", "scraped", 4), ("B", "errored", 1)):
        dimensions = {"receiver": "postgresql/diagnostics", "scraper": "postgresql"}
        s.add(
            f"otelcol_scraper_{kind}_metric_points",
            f"0+{rate * 10}x12",
            service=None,
            job="collector-self",
            **dimensions,
        )
        s.expect(
            "Collector scraper activity",
            "suffix: points/s",
            (rate, dimensions),
            target=ref,
        )
    for service, name, value, title, unit, target in (
        (
            "postgresql",
            "postgresql_backends",
            5,
            "PostgreSQL connections",
            " connections",
            "A",
        ),
        (
            "postgresql",
            "postgresql_connection_max",
            100,
            "PostgreSQL connections",
            " connections",
            "B",
        ),
        (
            "postgresql",
            "postgresql_commits_total",
            "0+40x12",
            "PostgreSQL transactions and deadlocks",
            " events/s",
            "A",
        ),
        (
            "postgresql",
            "postgresql_rollbacks_total",
            "0+20x12",
            "PostgreSQL transactions and deadlocks",
            " events/s",
            "B",
        ),
        (
            "postgresql",
            "postgresql_deadlocks_total",
            "0+10x12",
            "PostgreSQL transactions and deadlocks",
            " events/s",
            "C",
        ),
        (
            "postgresql",
            "postgresql_temp_io_bytes_total",
            "0+320x12",
            "PostgreSQL temporary I/O",
            " B/s",
            "A",
        ),
        (
            "redis",
            "redis_memory_used_bytes",
            10000,
            "Redis server memory",
            "bytes",
            "A",
        ),
        ("redis", "redis_memory_rss_bytes", 12000, "Redis server memory", "bytes", "B"),
        ("redis", "redis_maxmemory_bytes", 0, "Redis server memory", "bytes", "C"),
        (
            "redis",
            "redis_keys_evicted_total",
            "0+10x12",
            "Redis evictions and rejected connections",
            " events/s",
            "A",
        ),
        (
            "redis",
            "redis_connections_rejected_total",
            "0+20x12",
            "Redis evictions and rejected connections",
            " events/s",
            "B",
        ),
        ("redis", "redis_clients_connected", 6, "Redis clients", " clients", "A"),
        ("redis", "redis_clients_blocked", 2, "Redis clients", " clients", "B"),
        (
            "redis",
            "redis_commands_per_second",
            23,
            "Redis commands per second",
            " ops/s",
            "A",
        ),
    ):
        s.add(name, value, service=service)
        expected = (
            int(value.split("+")[1].split("x")[0]) / 10
            if isinstance(value, str)
            else value
        )
        s.expect(
            title,
            ("suffix:" + unit) if unit.startswith(" ") else unit,
            (expected, {}),
            target=target,
        )
    lock = {
        "collection_scope": "database",
        "mode": "accesssharelock",
        "lock_type": "relation",
    }
    s.add("postgresql_database_locks", 4, service="postgresql", **lock)
    s.expect("PostgreSQL locks by scope and mode", "suffix: locks", (4, lock))
    s.add("redis_uptime_seconds_total", 600, service="redis")

    s.add("restaurantos_worker_collected_seconds", 111, service="worker")
    consumer = {"consumer": "analytics"}
    states = [
        ("queued", 2, 28),
        ("in_flight", 1, 4),
        ("retry_delayed", 3, 45),
        ("recovery_due", 0, 0),
        ("terminal", 7, 80),
    ]
    s.add("up", 1, service=None, instance="replica:8889")
    for state, depth, age in states:
        for instance in ("fixture:8889", "replica:8889"):
            s.add(
                "restaurantos_worker_deliveries",
                depth,
                service="worker",
                **consumer,
                state=state,
                instance=instance,
            )
            s.add(
                "restaurantos_worker_oldest_seconds",
                age,
                service="worker",
                **consumer,
                state=state,
                instance=instance,
            )
    s.expect("Unfinished delivery depth", "suffix: deliveries", (6, consumer))
    s.expect(
        "Unfinished deliveries by state",
        "suffix: deliveries",
        *((depth, {**consumer, "state": state}) for state, depth, _ in states[:-1]),
    )
    s.expect("Oldest unfinished delivery", "s", (45, consumer))
    s.expect(
        "Oldest delivery age by unfinished state",
        "s",
        *((age, {**consumer, "state": state}) for state, _, age in states[:-1]),
    )
    s.expect("Terminal delivery failures", "suffix: deliveries", (7, consumer))
    s.expect("Oldest terminal delivery age", "s", (80, consumer))
    s.add("restaurantos_worker_receipts_window", 6, service="worker", **consumer)
    s.expect("Recent durable receipts", "suffix: receipts", (6, consumer))
    s.expect("Recent receipt throughput", "suffix: receipts/s", (0.02, consumer))
    attempts = (
        ("publish", "published", "0+20x12", 2),
        ("consumer", "consumer_committed", "0+20x12", 2),
        ("consumer", "consumer_retry_scheduled", "0+10x12", 1),
        ("consumer", "consumer_failed", "0+10x12", 1),
    )
    for op, outcome, values, _ in attempts:
        s.add(
            "restaurantos_worker_operations_total",
            values,
            service="worker",
            **consumer,
            worker_slot="4",
            operation=op,
            outcome=outcome,
        )
    for op in ("publish", "consumer"):
        for le in ("0.1", "+Inf"):
            s.add(
                "restaurantos_worker_duration_seconds_bucket",
                "0+20x12",
                service="worker",
                **consumer,
                worker_slot="4",
                operation=op,
                outcome="published" if op == "publish" else "consumer_committed",
                le=le,
            )
    s.expect(
        "Publication attempts by outcome",
        "suffix: attempts/s",
        (2, {**consumer, "outcome": "published"}),
    )
    s.expect(
        "Consumer attempts by outcome",
        "suffix: attempts/s",
        *((n, {**consumer, "outcome": o}) for _, o, _, n in attempts[1:]),
    )
    s.expect(
        "Scheduled retries and failed attempts",
        "suffix: attempts/s",
        *((n, {**consumer, "outcome": o}) for _, o, _, n in attempts[2:]),
    )
    s.add(
        "restaurantos_worker_routes_total",
        "0+30x12",
        service="worker",
        **consumer,
        worker_slot="4",
        outcome="duplicate",
    )
    s.expect(
        "Routing checks without a new claim",
        "suffix: checks/s",
        (3, {**consumer, "outcome": "duplicate"}),
    )
    s.add(
        "restaurantos_worker_collection_failures_total",
        "0+10x12",
        service="worker",
        worker_slot="4",
    )
    s.expect(
        "Worker snapshot collection failures",
        "suffix: failures/s",
        (1, {"worker_slot": "4"}),
    )
    s.expect("Worker snapshot source age", "s", (9, {}))
    s.expect("Worker snapshot status", "none", (1, {}))
    for ref, quantile in zip("ABC", (0.05, 0.095, 0.099), strict=True):
        s.expect("HTTP request duration", "s", (quantile, {}), target=ref)
        for panel in (
            "SQL cursor execution duration",
            "Pool acquisition duration",
            "Redis command duration",
        ):
            s.expect(panel, "s", *((quantile, role) for role in dims), target=ref)
        s.expect(
            "Worker attempt duration",
            "s",
            (quantile, {"operation": "consumer"}),
            (quantile, {"operation": "publish"}),
            target=ref,
        )
    s.expect("P95 duration by route", "s", (0.095, {"http_route": route}))

    biz = "restaurantos_business_"
    for transition, per_second in (
        ("SUBMITTED", 3),
        ("COMPLETED", 2),
        ("CANCELLED", 1),
    ):
        s.add(
            biz + "orders_transitions_total",
            f"0+{per_second * 10}x12",
            transition=transition,
        )
    s.expect(
        "Committed order transitions",
        "suffix: transitions/s",
        (3, {"transition": "SUBMITTED"}),
        (2, {"transition": "COMPLETED"}),
        (1, {"transition": "CANCELLED"}),
    )
    s.add(
        biz + "stock_rejections_total", "0+50x12", category="order_stock_insufficient"
    )
    s.expect(
        "Stock command rejection attempts",
        "suffix: attempts/s",
        (5, {"category": "order_stock_insufficient"}),
    )
    for name, value, panel, unit, target in (
        (
            "collection_last_success_seconds",
            109,
            "Last successful business source collection age",
            "s",
            "A",
        ),
        (
            "collection_freshness_budget_seconds",
            75,
            "Last successful business source collection age",
            "s",
            "B",
        ),
        ("collection_success", 1, "Business snapshot collection", "none", "A"),
        (
            "stock_active_ingredients",
            5,
            "Active low-stock ingredients and alerts",
            "short",
            "A",
        ),
        (
            "stock_active_alerts",
            4,
            "Active low-stock ingredients and alerts",
            "short",
            "B",
        ),
        (
            "sales_retained_orders_7d",
            "20x11 18",
            "Retained completed orders · seven UTC creation dates",
            "suffix: orders",
            "A",
        ),
        (
            "sales_retained_amount_7d_THB",
            "250.25x11 200.75",
            "Retained completed sales · seven UTC creation dates",
            "suffix: THB",
            "A",
        ),
    ):
        s.add(biz + name, value)
        expected = (
            120 - value
            if "last_success" in name
            else float(value.split()[-1])
            if isinstance(value, str)
            else value
        )
        s.expect(panel, unit, (expected, {}), target=target)
    for kind, count in (("operational", 5), ("baseline", 2)):
        s.add(biz + "stock_episode_openings_24h", count, kind=kind)
    s.expect(
        "Low-stock episode openings in the preceding 24 hours",
        "suffix: episodes",
        (5, {"kind": "operational"}),
        (2, {"kind": "baseline"}),
    )
    for state, depth, age in states:
        s.add(biz + "analytics_deliveries", depth, state=state)
        s.add(biz + "analytics_oldest_seconds", age, state=state)
    s.expect(
        "Outstanding analytics deliveries by state",
        "suffix: deliveries",
        *((depth, {"state": state}) for state, depth, _ in states),
    )
    s.expect("Oldest unfinished analytics delivery", "s", (45, {}))
    s.expect("Oldest terminal analytics delivery", "s", (80, {}))
    return s


def edge_cases():
    biz = "restaurantos_business_"
    sales = "Retained completed orders · seven UTC creation dates"
    amount = "Retained completed sales · seven UTC creation dates"
    for name, up, last_success, success, expected, status in (
        ("healthy idle and sales amount disabled", 1, 110, 1, ((0, {}),), ((1, {}),)),
        ("stale collection despite healthy scrape", 1, 30, 1, (), ((2, {}),)),
        ("failed collection retains previous gauges", 1, 110, 0, (), ((0, {}),)),
        ("future collection timestamp", 1, 130, 1, (), ((2, {}),)),
        ("collector stopped with prior observations", 0, 110, 1, (), ()),
    ):
        s = Scenario(name)
        s.add("up", up, service=None)
        s.add(biz + "collection_success", success)
        s.add(biz + "collection_last_success_seconds", last_success)
        s.add(biz + "collection_freshness_budget_seconds", 75)
        s.add(biz + "sales_retained_orders_7d", 0)
        s.add(
            "restaurantos_http_requests_total",
            60,
            outcome="forbidden",
            http_route="/health",
        )
        s.expect(sales, "suffix: orders", *expected)
        s.expect(amount, "suffix: THB")
        s.expect("Business snapshot collection", "none", *status)
        s.expect("API requests", "suffix: req/s", *(((0, {}),) if up else ()))
        s.expect("Unexpected server errors as a share of traffic", "percentunit")
        yield s

    for name, evaluation, repeats, last_success, budget, samples, status in (
        (
            "healthy five-minute cadence at 90 seconds of age",
            "2m",
            12,
            30,
            615,
            ((4, {}),),
            1,
        ),
        ("five-minute cadence expires at its budget", "12m", 72, 105, 615, (), 2),
        ("legacy snapshot without a freshness budget", "2m", 12, 110, None, (), 3),
    ):
        s = Scenario(name, evaluation)
        s.add("up", f"1x{repeats}", service=None)
        s.add(biz + "collection_success", f"1x{repeats}")
        s.add(biz + "collection_last_success_seconds", f"{last_success}x{repeats}")
        s.add(biz + "sales_retained_orders_7d", f"4x{repeats}")
        if budget is not None:
            s.add(biz + "collection_freshness_budget_seconds", f"{budget}x{repeats}")
        s.expect(sales, "suffix: orders", *samples)
        s.expect("Business snapshot collection", "none", (status, {}))
        yield s

    s = Scenario("never seen, expired series, or collection disabled")
    s.add("up", 1, service=None)
    s.add("restaurantos_http_requests_total", "0+10x10 stale _", outcome="success")
    s.expect("API requests", "suffix: req/s")
    s.expect("API observation series", "none", (0, {}))
    s.expect("SQLAlchemy pool size and use", "suffix: connections")
    s.expect("Business snapshot collection", "none")
    s.expect("Worker snapshot status", "none")
    yield s

    s = Scenario("unexpected failures absent, expected 4xx present")
    s.add("up", 1, service=None)
    s.add("restaurantos_http_requests_total", "0+10x12", outcome="conflict")
    s.expect("Unexpected server errors", "suffix: req/s", (0, {}))
    s.expect("Unexpected server errors as a share of traffic", "percentunit", (0, {}))
    yield s

    s = Scenario("api and worker process counters reset")
    s.add("up", 1, service=None)
    reset = "1000+10x7 10+10x4"
    s.add("restaurantos_http_requests_total", reset, outcome="success")
    s.add(biz + "orders_transitions_total", reset, transition="COMPLETED")
    s.add(
        "restaurantos_worker_operations_total",
        reset,
        service="worker",
        worker_slot="4",
        operation="consumer",
        outcome="consumer_committed",
        consumer="analytics",
    )
    s.add(
        "restaurantos_worker_operations_total",
        "1000+20x12",
        service="worker",
        worker_slot="5",
        operation="consumer",
        outcome="consumer_committed",
        consumer="analytics",
    )
    s.expect("API requests", "suffix: req/s", (1, {}))
    s.expect(
        "Committed order transitions",
        "suffix: transitions/s",
        (1, {"transition": "COMPLETED"}),
    )
    s.expect(
        "Consumer attempts by outcome",
        "suffix: attempts/s",
        (3, {"consumer": "analytics", "outcome": "consumer_committed"}),
    )
    yield s

    for time, age in (("1m", 40), ("2m", 100)):
        s = Scenario(
            "stopped worker with waiting analytics deliveries at " + time, time
        )
        s.add("up", 1, service=None)
        s.add(
            "restaurantos_worker_collected_seconds",
            "10x7 stale _ _ _ _",
            service="worker",
        )
        s.add(
            "restaurantos_worker_deliveries",
            0,
            service="worker",
            state="queued",
            consumer="analytics",
        )
        s.add(biz + "collection_success", 1)
        s.add(biz + "collection_last_success_seconds", "0+10x12")
        s.add(biz + "collection_freshness_budget_seconds", 75)
        s.add(biz + "analytics_oldest_seconds", "0 0 0+10x10", state="queued")
        s.expect("Unfinished delivery depth", "suffix: deliveries")
        s.expect(
            "Worker snapshot status", "none", *(((0, {}),) if time == "1m" else ())
        )
        s.expect("Oldest unfinished analytics delivery", "s", (age, {}))
        yield s
