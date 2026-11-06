"""Owned pinned Collector for native worker metric regression, no developer state."""

import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

import yaml

from test_support.monitoring_environment import (
    ROOT,
    command,
    require_local_engine,
    wait_until,
)


@contextmanager
def worker_collector() -> Iterator[tuple[str, str]]:
    require_local_engine()
    config = yaml.safe_load((ROOT / "monitoring/otel-collector.yaml").read_text())
    config["exporters"] = {"prometheus": config["exporters"]["prometheus"]}
    config["service"] = {
        "pipelines": {
            name: config["service"]["pipelines"][name]
            for name in ("metrics/worker", "metrics/diagnostics")
        }
    }
    image = json.loads((ROOT / "monitoring/images.lock.json").read_text())["images"][
        "collector"
    ]["reference"]
    name = "restaurantos-worker-metrics-test-" + uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="restaurantos-worker-metrics-") as folder:
        path = Path(folder) / "collector.yaml"
        path.write_text(yaml.safe_dump(config))
        try:
            command(
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--memory",
                "256m",
                "--cpus",
                "1",
                "-p",
                "127.0.0.1::4318",
                "-p",
                "127.0.0.1::8889",
                "-v",
                f"{path}:/config.yaml:ro",
                image,
                "--config=/config.yaml",
            )

            def port(number: int) -> int:
                return int(
                    command("docker", "port", name, str(number)).rsplit(":", 1)[1]
                )

            endpoint = f"http://127.0.0.1:{port(4318)}/v1/metrics"
            scrape = f"http://127.0.0.1:{port(8889)}/metrics"
            wait_until(lambda: scrape_metrics(scrape) is not None, timeout=20)
            yield endpoint, scrape
        finally:
            command("docker", "rm", "-f", name)


def scrape_metrics(url: str) -> str:
    with build_opener(ProxyHandler({})).open(url, timeout=2) as response:
        return response.read().decode()
