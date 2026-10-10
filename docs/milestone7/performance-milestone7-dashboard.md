# Milestone 7 dashboard cache experiment

Generated from retained JSON by `scripts/report-menu-read-comparison.py`.
Each latency triple is P50 / P95 / P99 in milliseconds. Summary values are
medians of the three independently measured repetition percentiles, not pooled
request percentiles. Queries are means; hits are weighted over dashboard GETs (all four aggregate results reused).
Cold means cleared immediately before the measured batch; natural TTL
expiry and concurrent fills remain active. The first wave is reported separately.
SQL timings include driver/database wait and exclude Python/DTO/HTTP work.
HTTP percentiles include failed attempts; request errors are retained without automatic retries. SQL rates/timings use instrumented responses only; lost responses have unknown server work. Cache hit ratios likewise exclude lost responses. Per-repetition JSON records observation coverage and status/error categories.
Authorization and stock costs stay live; these timings are not additive HTTP percentiles.
The dashboard control and prototype use the same revision, seed and observers; production remains uncached.

## Environment and reproducibility

| Run | Commit | Script version / SHA256 | OS / CPU / logical CPUs | Python / PostgreSQL / Redis | Cells / measured requests / errors |
|---|---|---|---|---|---|
| disabled | `4ff9aee89588952dd381db6bc1589506f8ebe967` (dirty: True) | 2.3.0 / `f6a3c87ad50e11063b5bec312b698dc99b34cb92a84b3d47a7d3a7c5bda60353` | Windows-11-10.0.26200-SP0 / Intel64 Family 6 Model 151 Stepping 5, GenuineIntel / 12 | 3.12.13 / 16.15 (Debian 16.15-1.pgdg13+2) / Redis server v=7.4.11 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=40ff01a501d8e4b6 | 12 / 12000 / 0 |
| warm | `4ff9aee89588952dd381db6bc1589506f8ebe967` (dirty: True) | 2.3.0 / `f6a3c87ad50e11063b5bec312b698dc99b34cb92a84b3d47a7d3a7c5bda60353` | Windows-11-10.0.26200-SP0 / Intel64 Family 6 Model 151 Stepping 5, GenuineIntel / 12 | 3.12.13 / 16.15 (Debian 16.15-1.pgdg13+2) / Redis server v=7.4.11 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=40ff01a501d8e4b6 | 12 / 12000 / 0 |

Exact dataset, settings, available memory, timestamps and library versions are
retained in the adjacent JSON files. All catalog runs use one organization and
restaurant, an assigned Manager, four menus with 40 items each, four ingredients
and 40 tracked recipes. Each cell measures 1,000 calls after 50 excluded warm-ups.
Concurrency is 1/10/25/50 and there are three repetitions; supplemental failure
runs select a documented subset of the same cells.

## Experimental scope

A separate dataset adds 700 completed paid orders over seven days and 1,400
immutable order-item snapshots. Every response is checked against expected
sales/order/average/graph values. The prototype caches four aggregate results
in real Redis only after fresh authorization; it has no order-write invalidation.
It is not a production implementation or a permitted-freshness decision.

Experiment metadata: `{"limitations": "benchmark-only four aggregate Redis entries, 10-second absolute age, no write invalidation; not a production design or freshness approval", "production_behavior": "dashboard remains uncached", "prototype_enabled": true, "report_date": "2026-10-10", "response_assertions": "each response: 100 today orders, 2400 sales, 24 average, 700 orders over seven days", "script_sha256": "7a0bde92549f05d71b0cbf7a14ba74a097ed5e749fdd3b78a940199bacd3995e", "server_timezone": "SE Asia Standard Time", "version": "1.0.0"}`.

## Warm results

| Scenario | Concurrency | Baseline ms | Current ms | P95 change | Baseline / current queries per observed response | Hit ratio | Errors / attempts | Unknown SQL requests |
|---|---:|---|---|---:|---|---:|---|---:|
| dashboard | 1 | 22.28 / 28.71 / 34.86 | 17.68 / 22.97 / 27.57 | -20.0% | 10.0000 / 6.0063 | 99.43% | 0 / 3000 (0.000%) | 0 |
| dashboard | 10 | 111.01 / 229.49 / 357.98 | 113.85 / 259.26 / 354.73 | +13.0% | 10.0000 / 6.0057 | 99.50% | 0 / 3000 (0.000%) | 0 |
| dashboard | 25 | 320.10 / 1014.05 / 1563.95 | 306.32 / 988.05 / 1504.26 | -2.6% | 10.0000 / 6.0087 | 99.27% | 0 / 3000 (0.000%) | 0 |
| dashboard | 50 | 670.54 / 2809.93 / 4169.15 | 611.07 / 2493.40 / 3753.20 | -11.3% | 10.0000 / 6.0077 | 99.23% | 0 / 3000 (0.000%) | 0 |

### Live SQL costs and first measured wave

Each phase cell is mean statements / mean SQL milliseconds per instrumented response.

| Scenario | Concurrency | Authentication | Authorization | Live stock | Catalog source | Analytics | Other/write | First-wave ms | First-wave hits / requests |
|---|---:|---|---|---|---|---|---|---|---|
| dashboard | 1 | 2.000 / 2.168 | 4.000 / 3.123 | 0.000 / 0.000 | 0.000 / 0.000 | 0.006 / 0.009 | 0.000 / 0.000 | 22.57 / 22.57 / 22.57 | 3 / 3 |
| dashboard | 10 | 2.000 / 2.656 | 4.000 / 4.323 | 0.000 / 0.000 | 0.000 / 0.000 | 0.006 / 0.016 | 0.000 / 0.000 | 267.46 / 314.41 / 314.41 | 28 / 30 |
| dashboard | 25 | 2.000 / 2.927 | 4.000 / 4.568 | 0.000 / 0.000 | 0.000 / 0.000 | 0.009 / 0.050 | 0.000 / 0.000 | 318.76 / 931.13 / 1065.97 | 73 / 75 |
| dashboard | 50 | 2.000 / 5.411 | 4.000 / 8.913 | 0.000 / 0.000 | 0.000 / 0.000 | 0.008 / 0.103 | 0.000 / 0.000 | 743.55 / 2438.57 / 3016.04 | 149 / 150 |

## Individual repetition measurements

Full numerical values and phase breakdowns are retained in JSON; this table
also preserves every repetition's latency, query count, hit ratio and error count.

| Mode | Scenario | Concurrency | Repetition | P50 / P95 / P99 ms | SQL statements | Hits / lookups | Errors |
|---|---|---:|---:|---|---:|---|---:|
| disabled | dashboard | 1 | 1 | 24.19 / 38.73 / 67.28 | 10000 | 0 / 0 | 0 |
| disabled | dashboard | 10 | 1 | 111.01 / 238.00 / 412.12 | 10000 | 0 / 0 | 0 |
| disabled | dashboard | 25 | 1 | 354.90 / 1125.91 / 1589.03 | 10000 | 0 / 0 | 0 |
| disabled | dashboard | 50 | 1 | 670.54 / 2715.94 / 4169.15 | 10000 | 0 / 0 | 0 |
| disabled | dashboard | 1 | 2 | 22.28 / 28.71 / 34.86 | 10000 | 0 / 0 | 0 |
| disabled | dashboard | 10 | 2 | 99.61 / 227.79 / 356.92 | 10000 | 0 / 0 | 0 |
| disabled | dashboard | 25 | 2 | 312.99 / 991.37 / 1339.55 | 10000 | 0 / 0 | 0 |
| disabled | dashboard | 50 | 2 | 663.13 / 2833.21 / 4652.85 | 10000 | 0 / 0 | 0 |
| disabled | dashboard | 1 | 3 | 21.73 / 27.31 / 34.49 | 10000 | 0 / 0 | 0 |
| disabled | dashboard | 10 | 3 | 117.78 / 229.49 / 357.98 | 10000 | 0 / 0 | 0 |
| disabled | dashboard | 25 | 3 | 320.10 / 1014.05 / 1563.95 | 10000 | 0 / 0 | 0 |
| disabled | dashboard | 50 | 3 | 686.73 / 2809.93 / 4043.26 | 10000 | 0 / 0 | 0 |
| warm | dashboard | 1 | 1 | 17.68 / 22.00 / 25.11 | 6004 | 998 / 1000 | 0 |
| warm | dashboard | 10 | 1 | 119.10 / 282.05 / 440.40 | 6004 | 998 / 1000 | 0 |
| warm | dashboard | 25 | 1 | 325.59 / 988.05 / 1645.34 | 6009 | 995 / 1000 | 0 |
| warm | dashboard | 50 | 1 | 611.07 / 2493.40 / 3753.20 | 6010 | 990 / 1000 | 0 |
| warm | dashboard | 1 | 2 | 18.77 / 23.62 / 27.57 | 6008 | 992 / 1000 | 0 |
| warm | dashboard | 10 | 2 | 113.85 / 259.26 / 354.73 | 6007 | 993 / 1000 | 0 |
| warm | dashboard | 25 | 2 | 306.32 / 1042.92 / 1504.26 | 6007 | 993 / 1000 | 0 |
| warm | dashboard | 50 | 2 | 616.35 / 2551.96 / 4509.67 | 6007 | 993 / 1000 | 0 |
| warm | dashboard | 1 | 3 | 17.55 / 22.97 / 29.75 | 6007 | 993 / 1000 | 0 |
| warm | dashboard | 10 | 3 | 90.41 / 200.82 / 261.92 | 6006 | 994 / 1000 | 0 |
| warm | dashboard | 25 | 3 | 272.98 / 880.54 / 1289.59 | 6010 | 990 / 1000 | 0 |
| warm | dashboard | 50 | 3 | 563.82 / 2107.51 / 3090.05 | 6006 | 994 / 1000 | 0 |

## Artifact hashes

- [dashboard-live.json](benchmarks/dashboard-live.json): SHA256 `df077a8a2a8de90e57f6c7737596b4b434c12382b062915ac0504e20dbc1c2e3`.
- [dashboard-prototype.json](benchmarks/dashboard-prototype.json): SHA256 `7810b80d90e90011362333bd83785e396fa4912100e61e03ca436c9847fae0eb`.
