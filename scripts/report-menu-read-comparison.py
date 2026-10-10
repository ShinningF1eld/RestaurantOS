"""Validate saved menu benchmark comparability and produce tracked evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

CONFIG_FIELDS = (
    "measured_requests_per_scenario_level_repetition",
    "warmup_requests_per_scenario_level_repetition",
    "percentile_method",
    "repetitions",
)


def validate_comparison(baseline: dict[str, Any], candidate: dict[str, Any]) -> None:
    """Refuse mismatched seed/mixes/sample sizes rather than imply equivalence."""
    if baseline["cache_mode"] != "disabled":
        raise ValueError("Comparison requires the corrected uncached baseline")
    before, after = baseline["metadata"], candidate["metadata"]
    if before.get("benchmark_script_version") == "1.0.0":
        raise ValueError("Superseded baseline has an incorrectly labeled write mix")
    for row in baseline["results"]:
        if row["successful_request_count"] + row["error_count"] != row["request_count"]:
            raise ValueError("Baseline has inconsistent error accounting")
    for field in CONFIG_FIELDS:
        if (
            before["benchmark_configuration"][field]
            != after["benchmark_configuration"][field]
        ):
            raise ValueError(f"Benchmark configuration differs: {field}")
    for field, value in before["dataset"].items():
        if after["dataset"].get(field) != value:
            raise ValueError(f"Benchmark dataset differs: {field}")
    if before["workloads"] != after["workloads"]:
        raise ValueError("Benchmark request mixes differ")
    baseline_cells = {
        (r["scenario"], r["concurrency"], r["repetition"]) for r in baseline["results"]
    }
    candidate_cells = {
        (r["scenario"], r["concurrency"], r["repetition"]) for r in candidate["results"]
    }
    if len(candidate_cells) != len(candidate["results"]):
        raise ValueError("Duplicate benchmark cells")
    if (
        candidate["cache_mode"] in {"warm", "cold"}
        and candidate_cells != baseline_cells
    ):
        raise ValueError("Full warm/cold comparison must cover every baseline cell")
    if not candidate_cells <= baseline_cells:
        raise ValueError("Supplemental cells are absent from the baseline")
    for row in candidate["results"]:
        if row["successful_request_count"] + row["error_count"] != row["request_count"]:
            raise ValueError("Inconsistent measurement error accounting")
        observed = row.get("sql_observed_response_count", row["request_count"])
        unknown = row.get("sql_unknown_request_count", 0)
        if (
            not 0 < observed <= row["request_count"]
            or observed + unknown != row["request_count"]
        ):
            raise ValueError("Invalid SQL observation coverage")
        if unknown > row["error_count"]:
            raise ValueError("Lost SQL observations exceed request errors")
        if row["request_count"] != after["benchmark_configuration"][CONFIG_FIELDS[0]]:
            raise ValueError("Recorded sample size differs from actual cell")
        if (
            abs(
                sum(p["queries_per_request"] for p in row["sql_phase_costs"].values())
                - row["queries_per_request"]
            )
            > 1e-9
        ):
            raise ValueError("SQL phases do not reconcile")
        hits, lookups = row["cache_hit_count"], row["cache_lookup_count"]
        if not 0 <= hits <= lookups <= observed:
            raise ValueError("Invalid cache hit accounting")
        if (
            "postgres_query_count" in row
            and abs(row["postgres_query_count"] / observed - row["queries_per_request"])
            > 1e-9
        ):
            raise ValueError("Query rate does not match observed response count")


def grouped(report: dict[str, Any]) -> dict[tuple[str, int], list[dict[str, Any]]]:
    result: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in report["results"]:
        result[row["scenario"], row["concurrency"]].append(row)
    return result


def triple(rows: list[dict[str, Any]], field: str = "latency_ms") -> str:
    return " / ".join(
        f"{statistics.median(r[field][p] for r in rows):.2f}"
        for p in ("p50", "p95", "p99")
    )


def render(baseline: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    dashboard = baseline["benchmark"] == "restaurantos-dashboard-evaluation"
    lines = [
        "# Milestone 7 dashboard cache experiment"
        if dashboard
        else "# Milestone 7 measured menu-read comparison",
        "",
        "Generated from retained JSON by `scripts/report-menu-read-comparison.py`.",
        "Each latency triple is P50 / P95 / P99 in milliseconds. Summary values are",
        "medians of the three independently measured repetition percentiles, not pooled",
        "request percentiles. Queries are means; hits are weighted over dashboard GETs (all four aggregate results reused)."
        if dashboard
        else "request percentiles. Queries are means; hits are weighted over catalog GETs only.",
        "Cold means cleared immediately before the measured batch; natural TTL",
        "expiry and concurrent fills remain active. The first wave is reported separately.",
        "SQL timings include driver/database wait and exclude Python/DTO/HTTP work.",
        "HTTP percentiles include failed attempts; request errors are retained without automatic retries. SQL rates/timings use instrumented responses only; lost responses have unknown server work. Cache hit ratios likewise exclude lost responses. Per-repetition JSON records observation coverage and status/error categories.",
        "Authorization and stock costs stay live; these timings are not additive HTTP percentiles.",
        "The dashboard control and prototype use the same revision, seed and observers; production remains uncached."
        if dashboard
        else "The historical baseline and current runs differ in application revision and instrumentation; these are measured before/after observations, not a controlled claim that caching alone caused every latency difference.",
        "",
        "## Environment and reproducibility",
        "",
        "| Run | Commit | Script version / SHA256 | OS / CPU / logical CPUs | Python / PostgreSQL / Redis | Cells / measured requests / errors |",
        "|---|---|---|---|---|---|",
    ]
    for report in [baseline, *candidates]:
        m = report["metadata"]
        h, runtime = m["host"], m["runtime"]
        rows = report["results"]
        lines.append(
            f"| {report['cache_mode']} | `{m['git_commit']}` (dirty: {m['git_worktree_dirty']}) | {m['benchmark_script_version']} / `{m['benchmark_script_sha256']}` | {h['os']} / {h['processor']} / {h['logical_cpu_count']} | {runtime['python']} / {runtime['postgresql']} / {runtime.get('redis', 'N/A')} | {len(rows)} / {sum(r['request_count'] for r in rows)} / {sum(r['error_count'] for r in rows)} |"
        )
    lines += [
        "",
        "Exact dataset, settings, available memory, timestamps and library versions are",
        "retained in the adjacent JSON files. All catalog runs use one organization and",
        "restaurant, an assigned Manager, four menus with 40 items each, four ingredients",
        "and 40 tracked recipes. Each cell measures 1,000 calls after 50 excluded warm-ups.",
        "Concurrency is 1/10/25/50 and there are three repetitions; supplemental failure",
        "runs select a documented subset of the same cells.",
        "",
    ]
    reference = grouped(baseline)
    if dashboard:
        lines += [
            "## Experimental scope",
            "",
            "A separate dataset adds 700 completed paid orders over seven days and 1,400",
            "immutable order-item snapshots. Every response is checked against expected",
            "sales/order/average/graph values. The prototype caches four aggregate results",
            "in real Redis only after fresh authorization; it has no order-write invalidation.",
            "It is not a production implementation or a permitted-freshness decision.",
            "",
            f"Experiment metadata: `{json.dumps(candidates[0]['metadata']['dashboard_experiment'], sort_keys=True)}`.",
            "",
        ]
    for report in candidates:
        lines += [
            f"## {report['cache_mode'].capitalize()} results",
            "",
            "| Scenario | Concurrency | Baseline ms | Current ms | P95 change | Baseline / current queries per observed response | Hit ratio | Errors / attempts | Unknown SQL requests |",
            "|---|---:|---|---|---:|---|---:|---|---:|",
        ]
        for cell, rows in grouped(report).items():
            previous = reference[cell]
            baseline_p95 = statistics.median(r["latency_ms"]["p95"] for r in previous)
            current_p95 = statistics.median(r["latency_ms"]["p95"] for r in rows)
            ratio = sum(r["cache_hit_count"] for r in rows) / sum(
                r["cache_lookup_count"] for r in rows
            )
            lines.append(
                f"| {cell[0]} | {cell[1]} | {triple(previous)} | {triple(rows)} | {(current_p95 / baseline_p95 - 1) * 100:+.1f}% | {statistics.mean(r['queries_per_request'] for r in previous):.4f} / {statistics.mean(r['queries_per_request'] for r in rows):.4f} | {ratio:.2%} | {sum(r['error_count'] for r in rows)} / {sum(r['request_count'] for r in rows)} ({sum(r['error_count'] for r in rows) / sum(r['request_count'] for r in rows):.3%}) | {sum(r.get('sql_unknown_request_count', 0) for r in rows)} |"
            )
        lines += [
            "",
            "### Live SQL costs and first measured wave",
            "",
            "Each phase cell is mean statements / mean SQL milliseconds per instrumented response.",
            "",
            "| Scenario | Concurrency | Authentication | Authorization | Live stock | Catalog source | Analytics | Other/write | First-wave ms | First-wave hits / requests |",
            "|---|---:|---|---|---|---|---|---|---|---|",
        ]
        for cell, rows in grouped(report).items():
            costs = []
            for phase in (
                "authentication",
                "authorization",
                "live_stock",
                "catalog_source",
                "analytics",
                "other",
            ):
                costs.append(
                    " / ".join(
                        f"{statistics.mean(r['sql_phase_costs'][phase][metric] for r in rows):.3f}"
                        for metric in (
                            "queries_per_request",
                            "mean_execution_ms_per_request",
                        )
                    )
                )
            lines.append(
                f"| {cell[0]} | {cell[1]} | {' | '.join(costs)} | {triple(rows, 'first_wave_latency_ms')} | {sum(r['first_wave_hit_count'] for r in rows)} / {sum(min(r['concurrency'], r['request_count']) for r in rows)} |"
            )
    lines += [
        "",
        "## Individual repetition measurements",
        "",
        "Full numerical values and phase breakdowns are retained in JSON; this table",
        "also preserves every repetition's latency, query count, hit ratio and error count.",
        "",
        "| Mode | Scenario | Concurrency | Repetition | P50 / P95 / P99 ms | SQL statements | Hits / lookups | Errors |",
        "|---|---|---:|---:|---|---:|---|---:|",
    ]
    for report in [baseline, *candidates]:
        for row in report["results"]:
            lines.append(
                f"| {report['cache_mode']} | {row['scenario']} | {row['concurrency']} | {row['repetition']} | {triple([row])} | {row['postgres_query_count']} | {row.get('cache_hit_count', 'N/A')} / {row.get('cache_lookup_count', 'N/A')} | {row['error_count']} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--shared-cells",
        action="store_true",
        help="compare only cells selected by a supplemental current uncached control; raw artifacts remain unchanged",
    )
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidates = [
        json.loads(path.read_text(encoding="utf-8")) for path in args.candidate
    ]
    if args.shared_cells:
        cells = {
            (r["scenario"], r["concurrency"], r["repetition"])
            for r in baseline["results"]
        }
        for candidate in candidates:
            candidate["results"] = [
                r
                for r in candidate["results"]
                if (r["scenario"], r["concurrency"], r["repetition"]) in cells
            ]
    for report in candidates:
        validate_comparison(baseline, report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lines = render(baseline, candidates)
    if args.shared_cells:
        lines = lines.replace(
            "# Milestone 7 measured menu-read comparison",
            "# Milestone 7 current uncached control",
        )
        lines += "\n## Control selection\n\nThis report selects the control's shared cells from the unmodified full warm artifact.\nThe current control and warm run use the same production revision and instrumentation;\nthey ran serially and are not randomized paired samples. The original historical\nbaseline remains the primary milestone comparison. Artifact hashes below identify\nthe complete original JSON, including warm cells outside this supplemental selection.\n"
    lines += "\n## Artifact hashes\n\n"
    for path in [args.baseline, *args.candidate]:
        lines += f"- [{path.name}](benchmarks/{path.name}): SHA256 `{hashlib.sha256(path.read_bytes()).hexdigest()}`.\n"
    args.output.write_text(lines, encoding="utf-8")


if __name__ == "__main__":
    main()
