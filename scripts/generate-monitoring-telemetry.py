"""Bounded standard-library OTLP/HTTP JSON fixture; no application dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

SERVICE = "restaurantos-monitoring-synthetic"
BOUNDS = [0.005, 0.010, 0.025, 0.050, 0.100]
MAX_REQUEST = 65536


def identities(seed: str, index: int) -> tuple[str, str, str]:
    digest = hashlib.sha256(f"{seed}:{index}".encode()).hexdigest()
    return digest[:32], digest[32:48], digest[48:64]


def payload(signal: str, records: list, canary: bool = False) -> dict:
    attributes = [{"key": "service.name", "value": {"stringValue": SERVICE}}]
    if canary:
        attributes.append(
            {"key": "private", "value": {"stringValue": "SYNTHETIC_PRIVATE_CANARY"}}
        )
    singular = {"traces": "Spans", "logs": "Logs", "metrics": "Metrics"}[signal]
    field = {"traces": "spans", "logs": "logRecords", "metrics": "metrics"}[signal]
    return {
        f"resource{singular}": [
            {
                "resource": {"attributes": attributes},
                f"scope{singular}": [
                    {
                        "scope": {"name": "restaurantos.monitoring.synthetic"},
                        field: records,
                    }
                ],
            }
        ]
    }


def operation(
    seed: str, index: int, now: int, canary: bool = False
) -> tuple[list, dict]:
    trace, parent, child = identities(seed, index)
    duration = 10_000_000 if index % 2 else 25_000_000
    private = "SYNTHETIC_PRIVATE_CANARY" if canary else "synthetic operation completed"
    spans = [
        {
            "traceId": trace,
            "spanId": parent,
            "name": "synthetic.operation",
            "kind": 2,
            "startTimeUnixNano": str(now - duration),
            "endTimeUnixNano": str(now),
            "status": {"code": 1, "message": private},
        },
        {
            "traceId": trace,
            "spanId": child,
            "parentSpanId": parent,
            "name": "synthetic.child",
            "kind": 1,
            "startTimeUnixNano": str(now - duration + 1),
            "endTimeUnixNano": str(now - 1),
        },
    ]
    log = {
        "timeUnixNano": str(now),
        "observedTimeUnixNano": str(now),
        "traceId": trace,
        "spanId": parent,
        "severityText": "INFO",
        "severityNumber": 9,
        "body": {"stringValue": private},
    }
    return spans, log


def metrics(count: int, start: int, now: int) -> list:
    short = (count + 1) // 2
    long = count // 2
    point = {"startTimeUnixNano": str(start), "timeUnixNano": str(now)}
    return [
        {
            "name": "restaurantos.synthetic.operations",
            "unit": "1",
            "sum": {
                "aggregationTemporality": 2,
                "isMonotonic": True,
                "dataPoints": [{**point, "asInt": str(count)}],
            },
        },
        {
            "name": "restaurantos.synthetic.duration",
            "unit": "s",
            "histogram": {
                "aggregationTemporality": 2,
                "dataPoints": [
                    {
                        **point,
                        "count": str(count),
                        "sum": (short * 10 + long * 25) / 1000,
                        "explicitBounds": BOUNDS,
                        "bucketCounts": ["0", str(short), str(long), "0", "0", "0"],
                    }
                ],
            },
        },
        {
            "name": "restaurantos.synthetic.last_observation",
            "unit": "s",
            "gauge": {
                "dataPoints": [{"timeUnixNano": str(now), "asDouble": now / 1e9}]
            },
        },
    ]


def encode(signal: str, records: list, canary: bool = False) -> list[bytes]:
    """Split by encoded bytes, not an assumed records-to-bytes ratio."""
    result = []
    pending = []
    for record in records:
        candidate = json.dumps(payload(signal, [*pending, record], canary)).encode()
        if len(candidate) > MAX_REQUEST:
            if not pending:
                raise ValueError("Single synthetic record exceeds the receiver limit")
            result.append(json.dumps(payload(signal, pending, canary)).encode())
            pending = [record]
            if len(json.dumps(payload(signal, pending, canary)).encode()) > MAX_REQUEST:
                raise ValueError("Single synthetic record exceeds the receiver limit")
        else:
            pending.append(record)
    if pending:
        result.append(json.dumps(payload(signal, pending, canary)).encode())
    return result


def generate(
    endpoint: str, rate: int, duration: int, seed: str, canary: bool, warmup: int = 0
) -> dict:
    opener = build_opener(ProxyHandler({}))
    result = {
        "seed": seed,
        "rate": rate,
        "duration_seconds": duration,
        "expected_operations": rate * duration,
        "generated_operations": 0,
        "export_requests": 0,
        "acknowledged_requests": 0,
        "failed_or_uncertain_requests": 0,
        "schedule_misses": 0,
        "warmup_seconds": warmup,
    }
    start_ns, started = time.time_ns(), time.monotonic()
    result["started_unix_seconds"] = start_ns / 1e9
    due = started
    last_flush = started
    traces, logs = [], []

    def flush() -> None:
        signals = {"traces": traces, "logs": logs}
        signals["metrics"] = metrics(
            result["generated_operations"], start_ns, time.time_ns()
        )
        for signal, records in signals.items():
            for body in encode(signal, records, canary):
                result["export_requests"] += 1
                request = Request(
                    endpoint.rstrip("/") + "/v1/" + signal,
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with opener.open(request, timeout=2) as response:
                        acknowledgement = json.load(response)
                    if acknowledgement.get("partialSuccess"):
                        raise ValueError("Partial acknowledgement")
                    result["acknowledged_requests"] += 1
                except (OSError, ValueError):
                    # No replay after uncertain transport; report the uncertainty.
                    result["failed_or_uncertain_requests"] += 1
        traces.clear()
        logs.clear()

    for index in range(1, rate * duration + 1):
        time.sleep(max(0, due - time.monotonic()))
        now = time.monotonic()
        if now >= started + duration:
            break
        if now - due > 0.05:
            result["schedule_misses"] += 1
        spans, log = operation(seed, index, time.time_ns(), canary)
        traces.extend(spans)
        logs.append(log)
        result["generated_operations"] = index
        if index == rate * warmup:
            result["warmup_completed_unix_seconds"] = time.time()
        if now - last_flush >= 1 or index == rate * duration:
            flush()
            last_flush = time.monotonic()
        # Never create a catch-up burst after a slow/failed export.
        due = max(due + 1 / rate, time.monotonic())
    if traces or logs:
        flush()
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["warmup_operations"] = min(rate * warmup, result["generated_operations"])
    result["measurement_operations"] = (
        result["generated_operations"] - result["warmup_operations"]
    )
    result["complete"] = (
        result["generated_operations"] == result["expected_operations"]
        and result["failed_or_uncertain_requests"] == 0
        and result["schedule_misses"] == 0
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--rate", type=int, default=5)
    parser.add_argument("--duration", type=int, default=720)
    parser.add_argument("--seed", default="monitoring-fixture")
    parser.add_argument("--warmup", type=int, default=0)
    parser.add_argument("--canary", action="store_true")
    parser.add_argument("--hold-seconds", type=int, default=10)
    args = parser.parse_args()
    url = urlsplit(args.endpoint)
    if url.scheme != "http" or url.hostname not in {
        "127.0.0.1",
        "localhost",
        "collector",
    }:
        parser.error("endpoint must be local loopback or the private collector service")
    if (
        url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
    ):
        parser.error("endpoint must be an origin without credentials/query/path")
    if not 1 <= args.rate <= 50 or not 1 <= args.duration <= 3600:
        parser.error("rate must be 1..50 and duration 1..3600 seconds")
    if not 0 <= args.hold_seconds <= 30 or not 1 <= len(args.seed) <= 128:
        parser.error("hold must be 0..30 seconds and seed 1..128 characters")
    if not 0 <= args.warmup < args.duration:
        parser.error("warmup must be nonnegative and shorter than duration")
    result = generate(
        args.endpoint, args.rate, args.duration, args.seed, args.canary, args.warmup
    )
    print(json.dumps(result), flush=True)
    time.sleep(args.hold_seconds)
    raise SystemExit(0 if result["complete"] else 1)


if __name__ == "__main__":
    main()
