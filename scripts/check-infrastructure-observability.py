"""Issue #61 acceptance on owned PostgreSQL/Redis and the pinned five-service stack.

Never consumes application DATABASE_URL, Redis state, or monitoring volumes.
Credentials stay in private temporary files and are never printed on failure.
"""

import json
import secrets
import subprocess
import sys
import time
from threading import Event, Thread
from urllib.parse import urlencode

import psycopg
import yaml
from psycopg import sql
from redis import Redis
from redis.exceptions import RedisError
from test_support.disposable_postgres import disposable_database
from test_support.monitoring_environment import (
    ROOT,
    command,
    disposable_monitoring,
    wait_until,
)
from validate import services


def prom(stack, query):
    return stack.query("prometheus", "/api/v1/query?" + urlencode({"query": query}))[
        "data"
    ]["result"]


def provision(env, database, stack):
    password = secrets.token_urlsafe(40)
    redis_password = secrets.token_urlsafe(40)
    with psycopg.connect(database.sync_url) as connection:
        # Same reviewed grants as the operator SQL; no broad predefined role.
        source = (
            (ROOT / "monitoring/postgres-monitor.sql")
            .read_text()
            .replace(':"DBNAME"', sql.Identifier(database.name).as_string(connection))
        )
        connection.execute(source)
        connection.execute(
            sql.SQL("ALTER ROLE restaurantos_monitor PASSWORD {}").format(
                sql.Literal(password)
            )
        )
        connection.execute("CREATE TABLE private_canary (value text)")
        connection.execute("INSERT INTO private_canary VALUES ('INFRA_PRIVATE_CANARY')")
    from sqlalchemy.engine import make_url

    target = make_url(database.sync_url)
    monitor_url = target.set(
        username="restaurantos_monitor", password=password
    ).render_as_string(hide_password=False)
    with psycopg.connect(monitor_url, autocommit=True) as connection:
        assert (
            connection.execute("SELECT count(*) FROM pg_stat_database").fetchone()[0]
            > 0
        )
        assert (
            connection.execute("SELECT count(*) FROM pg_stat_activity").fetchone()[0]
            > 0
        )
        for statement in (
            "INSERT INTO private_canary VALUES ('forbidden')",
            "SELECT * FROM private_canary",
            "CREATE ROLE forbidden_monitor_role",
            "SELECT pg_read_file('postgresql.conf')",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename != current_user LIMIT 1",
        ):
            try:
                connection.execute(statement)
            except psycopg.Error:
                pass
            else:
                raise AssertionError(
                    "Restricted PostgreSQL operation unexpectedly succeeded"
                )
        # Default read-only alone is not the table privilege boundary.
        connection.execute("SET default_transaction_read_only = off")
        try:
            connection.execute("INSERT INTO private_canary VALUES ('forbidden')")
        except psycopg.errors.InsufficientPrivilege:
            pass
        else:
            raise AssertionError("Monitoring account has business write access")
    admin = Redis(host=env["TEST_REDIS_HOST"], port=int(env["TEST_REDIS_PORT"]))
    try:
        admin.execute_command(
            "ACL",
            "SETUSER",
            "restaurantos_monitor",
            "reset",
            "on",
            ">" + redis_password,
            "-@all",
            "+hello",
            "+info",
            "resetkeys",
            "resetchannels",
        )
        monitor = Redis(
            host=env["TEST_REDIS_HOST"],
            port=int(env["TEST_REDIS_PORT"]),
            username="restaurantos_monitor",
            password=redis_password,
        )
        try:
            assert monitor.info("all")["redis_version"].startswith("7.")
            for args in (
                ("GET", "INFRA_PRIVATE_CANARY"),
                ("SET", "INFRA_PRIVATE_CANARY", "private"),
                ("CONFIG", "GET", "*"),
                ("ACL", "LIST"),
                ("MONITOR",),
            ):
                try:
                    monitor.execute_command(*args)
                except RedisError:
                    pass
                else:
                    raise AssertionError(
                        "Restricted Redis operation unexpectedly succeeded"
                    )
        finally:
            monitor.close()
        admin.set("INFRA_PRIVATE_CANARY", "private")
    finally:
        admin.close()
    for name, value in (
        ("postgres_monitor_password", password),
        ("redis_monitor_password", redis_password),
    ):
        path = stack.directory / name
        path.write_text(value)
        path.chmod(0o444)
    # Receiver config is opt-in and remains on the original Collector service.
    config = yaml.safe_load((ROOT / "monitoring/compose.diagnostics.yaml").read_text())
    collector = config["services"]["collector"]
    collector["environment"] = {
        "MONITORING_POSTGRES_ENDPOINT": "postgres:5432",
        "MONITORING_POSTGRES_DATABASE": database.name,
        "MONITORING_REDIS_ENDPOINT": "redis:6379",
    }
    collector["volumes"][0]["source"] = str(ROOT / "monitoring/otel-diagnostics.yaml")
    for name, secret in config["secrets"].items():
        secret["file"] = str(stack.directory / name)
    (stack.directory / "override.yaml").write_text(yaml.safe_dump(config))
    print(
        "PASS: restricted PostgreSQL statistics reads and denied business/administrative access; Redis INFO-only ACL",
        flush=True,
    )


def main():
    with (
        services(False) as env,
        disposable_database(
            prefix="issue61", test_url=env["TEST_DATABASE_URL"]
        ) as database,
        disposable_monitoring() as stack,
    ):
        isolated = database.environment(env)
        provision(env, database, stack)
        stack.up()
        # Only the Collector joins the uniquely owned test network.
        pg = env["TEST_POSTGRES_CONTAINER"]
        networks = json.loads(command("docker", "inspect", pg))[0]["NetworkSettings"][
            "Networks"
        ]
        network = next(iter(networks))
        assert network.startswith("restaurantos-m6-")
        command("docker", "network", "connect", network, stack.container("collector"))
        wait_until(
            lambda: prom(
                stack, 'postgresql_backends{service_name="restaurantos-postgresql"}'
            )
        )
        wait_until(
            lambda: prom(
                stack, 'redis_memory_used_bytes{service_name="restaurantos-redis"}'
            )
        )
        print("PASS: stored PostgreSQL and Redis receiver metrics", flush=True)
        # SDK producers run as fresh processes on real pooled resources, exporting
        # through the same privacy policy that admits HTTP diagnostics.
        endpoint = f"http://localhost:{stack.port('collector', 4318)}"

        def workload(role, *, quick=False, collector_absent=False):
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/infrastructure-workload.py"),
                    role,
                ],
                cwd=ROOT / "backend",
                env={
                    **isolated,
                    "PYTHONPATH": str(ROOT / "backend"),
                    "MONITORING_ENABLED": "true",
                    "MONITORING_ENDPOINT": endpoint,
                    "INFRASTRUCTURE_QUICK": "1" if quick else "0",
                    "INFRASTRUCTURE_COLLECTOR_ABSENT": "1" if collector_absent else "0",
                },
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if result.returncode:
                frames = [
                    line.strip()
                    for line in result.stderr.splitlines()
                    if line.strip().startswith('File "')
                ]
                print("Workload failed at: " + " | ".join(frames[-4:]), flush=True)
                raise RuntimeError(
                    f"Infrastructure {role} workload failed (details withheld)"
                )

        samples = []
        complete = Event()

        def sample_resources():
            while not complete.is_set():
                try:
                    samples.append(
                        {
                            "seconds": round(time.monotonic() - started, 2),
                            "stats": [
                                json.loads(row)
                                for row in command(
                                    "docker",
                                    "stats",
                                    "--no-stream",
                                    "--format",
                                    "{{json .}}",
                                    *[
                                        stack.container(name)
                                        for name in (
                                            "collector",
                                            "prometheus",
                                            "grafana",
                                            "loki",
                                            "tempo",
                                        )
                                    ],
                                ).splitlines()
                            ],
                        }
                    )
                except (RuntimeError, ValueError, subprocess.SubprocessError):
                    pass
                complete.wait(3)

        started = time.monotonic()
        sampler = Thread(target=sample_resources, daemon=True)
        sampler.start()
        try:
            for role in ("api", "worker"):
                print("START: SDK workload " + role, flush=True)
                workload(role)
        finally:
            complete.set()
            sampler.join(timeout=30)
        assert samples
        print("RESOURCE_SAMPLES " + json.dumps(samples), flush=True)
        containers = [
            stack.container(name)
            for name in ("collector", "prometheus", "grafana", "loki", "tempo")
        ]
        states = json.loads(command("docker", "inspect", *containers))
        assert all(
            item["State"]["Running"]
            and not item["State"]["OOMKilled"]
            and item["RestartCount"] == 0
            for item in states
        ), "Monitoring resource failure"

        for role in ("api", "worker"):
            wait_until(
                lambda role=role: prom(
                    stack, f'restaurantos_sql_duration_seconds_count{{role="{role}"}}'
                )
            )
            wait_until(
                lambda role=role: prom(
                    stack, f'restaurantos_redis_operations_total{{role="{role}"}}'
                )
            )
        for role in ("api", "worker"):
            pool = prom(
                stack, f'max_over_time(restaurantos_pool_used{{role="{role}"}}[10m])'
            )
            assert pool, "Missing stored pool usage for " + role
            failures = prom(
                stack,
                f'restaurantos_pool_acquire_failures_total{{role="{role}",outcome="timeout"}}',
            )
            assert failures, "Missing stored pool timeout for " + role
        exported = stack.internal("http://collector:8889/metrics")
        assert "INFRA_PRIVATE_CANARY" not in exported, "Canary in exported telemetry"
        assert "private_canary" not in exported, "Relation in exported telemetry"
        print(
            "PASS: stored API/worker SQL, pool and Redis diagnostics; exported canary exclusion",
            flush=True,
        )
        # Freeze ONLY owned targets; preserve the disposable tmpfs database for recovery.
        # No queries can finish while paused; failed collection expires instead of zero.
        redis_id = command(
            "docker",
            "ps",
            "-q",
            "--filter",
            "label=com.docker.compose.project=" + network.removesuffix("_default"),
            "--filter",
            "label=com.docker.compose.service=redis",
        )
        assert redis_id
        paused = []
        try:
            for container in (pg, redis_id):
                command("docker", "pause", container)
                paused.append(container)
            wait_until(
                lambda: (
                    not prom(
                        stack,
                        'postgresql_backends{service_name="restaurantos-postgresql"}',
                    )
                    and not prom(
                        stack,
                        'redis_memory_used_bytes{service_name="restaurantos-redis"}',
                    )
                ),
                timeout=90,
            )
            self_metrics = stack.internal("http://collector:8888/metrics")
            assert "scraper_errored_metric_points" in self_metrics
        finally:
            for container in paused:
                command("docker", "unpause", container)
        wait_until(
            lambda: (
                prom(
                    stack, 'postgresql_backends{service_name="restaurantos-postgresql"}'
                )
                and prom(
                    stack, 'redis_memory_used_bytes{service_name="restaurantos-redis"}'
                )
            )
        )
        print(
            "PASS: stopped receivers expose errors and missing series; recovery",
            flush=True,
        )
        collector_id = stack.container("collector")
        command("docker", "stop", collector_id)
        try:
            for role in ("api", "worker"):
                workload(role, quick=True, collector_absent=True)
        finally:
            command("docker", "start", collector_id)
        wait_until(lambda: stack.internal("http://collector:13133/"))
        # Docker may assign a new random published host port after stop/start.
        endpoint = f"http://localhost:{stack.port('collector', 4318)}"
        for role in ("api", "worker"):
            workload(role, quick=True)
            wait_until(
                lambda role=role: prom(
                    stack, f'restaurantos_sql_duration_seconds_count{{role="{role}"}}'
                )
            )
        print(
            "PASS: Collector-absent API/worker startup, SQL/Redis work, bounded shutdown and re-export after recovery",
            flush=True,
        )
        stats = command(
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            *[
                stack.container(name)
                for name in ("collector", "prometheus", "grafana", "loki", "tempo")
            ],
        )
        # Stats contain only owned container names and aggregate resource readings.
        print(stats, flush=True)
        print(
            "PASS: owned teardown follows (no developer resources selected)", flush=True
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001
        # Driver exceptions and exporter stderr can contain endpoints/credentials.
        print(
            "FAIL: infrastructure acceptance (" + type(error).__name__ + ")",
            file=sys.stderr,
        )
        sys.exit(1)
