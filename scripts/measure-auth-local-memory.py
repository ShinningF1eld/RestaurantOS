"""Measure bounded local bucket allocations, without services or credentials."""

import argparse
import gc
import json
import sys
import tracemalloc
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.modules.auth.rate_limit import LocalBucket


def measure(entries, quota):
    gc.collect()
    tracemalloc.start()
    baseline = tracemalloc.get_traced_memory()[0]
    buckets = {}
    for _ in range(entries):
        # Longest production kind prefix and 64-character HMAC digest. Fill the
        # entry to its quota; failures/reservations have identical value types.
        key = "refresh-family:" + uuid4().hex + uuid4().hex
        buckets[key] = LocalBucket(
            failures={uuid4().hex: float(900) for _ in range(quota)}
        )
    current, peak = tracemalloc.get_traced_memory()
    assert len(buckets) == entries
    tracemalloc.stop()
    return {
        "entries": entries,
        "attempts_per_entry": quota,
        "retained_bytes": current - baseline,
        "bytes_per_entry": round((current - baseline) / entries, 1),
        "peak_bytes": peak - baseline,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries", type=int, default=10000)
    args = parser.parse_args()
    if not 1 <= args.entries <= 100000:
        parser.error("entries must be between 1 and 100000")
    print(
        json.dumps(
            {
                "python": sys.version.split()[0],
                "platform": sys.platform,
                "method": "tracemalloc retained Python allocations; excludes runtime/RSS overhead",
                "scenarios": [measure(args.entries, quota) for quota in (3, 5, 10, 50)],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
