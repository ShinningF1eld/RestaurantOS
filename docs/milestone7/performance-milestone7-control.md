# Milestone 7 current uncached control

Generated from retained JSON by `scripts/report-menu-read-comparison.py`.
Each latency triple is P50 / P95 / P99 in milliseconds. Summary values are
medians of the three independently measured repetition percentiles, not pooled
request percentiles. Queries are means; hits are weighted over catalog GETs only.
Cold means cleared immediately before the measured batch; natural TTL
expiry and concurrent fills remain active. The first wave is reported separately.
SQL timings include driver/database wait and exclude Python/DTO/HTTP work.
HTTP percentiles include failed attempts; request errors are retained without automatic retries. SQL rates/timings use instrumented responses only; lost responses have unknown server work. Cache hit ratios likewise exclude lost responses. Per-repetition JSON records observation coverage and status/error categories.
Authorization and stock costs stay live; these timings are not additive HTTP percentiles.
The historical baseline and current runs differ in application revision and instrumentation; these are measured before/after observations, not a controlled claim that caching alone caused every latency difference.

## Environment and reproducibility

| Run | Commit | Script version / SHA256 | OS / CPU / logical CPUs | Python / PostgreSQL / Redis | Cells / measured requests / errors |
|---|---|---|---|---|---|
| disabled | `4ff9aee89588952dd381db6bc1589506f8ebe967` (dirty: True) | 2.3.0 / `f6a3c87ad50e11063b5bec312b698dc99b34cb92a84b3d47a7d3a7c5bda60353` | Windows-11-10.0.26200-SP0 / Intel64 Family 6 Model 151 Stepping 5, GenuineIntel / 12 | 3.12.13 / 16.15 (Debian 16.15-1.pgdg13+2) / Redis server v=7.4.11 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=40ff01a501d8e4b6 | 48 / 48000 / 0 |
| warm | `4ff9aee89588952dd381db6bc1589506f8ebe967` (dirty: True) | 2.3.0 / `f6a3c87ad50e11063b5bec312b698dc99b34cb92a84b3d47a7d3a7c5bda60353` | Windows-11-10.0.26200-SP0 / Intel64 Family 6 Model 151 Stepping 5, GenuineIntel / 12 | 3.12.13 / 16.15 (Debian 16.15-1.pgdg13+2) / Redis server v=7.4.11 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=40ff01a501d8e4b6 | 48 / 48000 / 0 |

Exact dataset, settings, available memory, timestamps and library versions are
retained in the adjacent JSON files. All catalog runs use one organization and
restaurant, an assigned Manager, four menus with 40 items each, four ingredients
and 40 tracked recipes. Each cell measures 1,000 calls after 50 excluded warm-ups.
Concurrency is 1/10/25/50 and there are three repetitions; supplemental failure
runs select a documented subset of the same cells.

## Warm results

| Scenario | Concurrency | Baseline ms | Current ms | P95 change | Baseline / current queries per observed response | Hit ratio | Errors / attempts | Unknown SQL requests |
|---|---:|---|---|---:|---|---:|---|---:|
| menu-list | 1 | 25.10 / 34.11 / 39.77 | 24.72 / 34.47 / 43.49 | +1.0% | 6.0000 / 5.0023 | 99.77% | 0 / 3000 (0.000%) | 0 |
| menu-list | 10 | 179.57 / 408.07 / 614.19 | 206.06 / 418.57 / 542.04 | +2.6% | 6.0000 / 5.0587 | 94.13% | 0 / 3000 (0.000%) | 0 |
| menu-list | 25 | 506.78 / 1724.70 / 2488.39 | 534.65 / 1707.89 / 2542.54 | -1.0% | 6.0000 / 5.0027 | 99.73% | 0 / 3000 (0.000%) | 0 |
| menu-list | 50 | 897.73 / 4397.76 / 6304.40 | 962.13 / 4027.25 / 6544.39 | -8.4% | 6.0000 / 5.0033 | 99.67% | 0 / 3000 (0.000%) | 0 |
| menu-items | 1 | 28.75 / 38.55 / 49.54 | 29.80 / 41.30 / 51.32 | +7.1% | 7.0000 / 6.0120 | 98.80% | 0 / 3000 (0.000%) | 0 |
| menu-items | 10 | 166.93 / 373.29 / 520.72 | 190.07 / 420.12 / 569.18 | +12.5% | 7.0000 / 6.0287 | 97.13% | 0 / 3000 (0.000%) | 0 |
| menu-items | 25 | 518.63 / 1792.55 / 2477.79 | 524.07 / 1763.31 / 2547.66 | -1.6% | 7.0000 / 6.0343 | 96.57% | 0 / 3000 (0.000%) | 0 |
| menu-items | 50 | 1023.37 / 4073.82 / 6167.11 | 1016.68 / 4382.20 / 6908.51 | +7.6% | 7.0000 / 6.0627 | 93.73% | 0 / 3000 (0.000%) | 0 |
| mixed-read | 1 | 26.31 / 38.24 / 43.82 | 28.76 / 38.77 / 53.17 | +1.4% | 6.8000 / 5.8133 | 98.67% | 0 / 3000 (0.000%) | 0 |
| mixed-read | 10 | 129.35 / 274.70 / 416.21 | 181.23 / 421.30 / 591.63 | +53.4% | 6.8000 / 5.8107 | 98.93% | 0 / 3000 (0.000%) | 0 |
| mixed-read | 25 | 387.39 / 1243.95 / 2023.97 | 528.76 / 1765.85 / 2739.93 | +42.0% | 6.8000 / 5.8103 | 98.97% | 0 / 3000 (0.000%) | 0 |
| mixed-read | 50 | 615.83 / 2481.46 / 3694.79 | 1025.56 / 4315.67 / 5788.15 | +73.9% | 6.8000 / 5.8163 | 98.37% | 0 / 3000 (0.000%) | 0 |
| mixed-write | 1 | 17.39 / 24.21 / 28.19 | 29.71 / 44.23 / 56.50 | +82.7% | 7.5037 / 6.8037 | 87.50% | 0 / 3000 (0.000%) | 0 |
| mixed-write | 10 | 110.91 / 261.82 / 371.50 | 196.55 / 438.79 / 622.26 | +67.6% | 7.5000 / 6.8450 | 81.88% | 0 / 3000 (0.000%) | 0 |
| mixed-write | 25 | 328.57 / 1092.01 / 1652.55 | 551.06 / 1746.18 / 2414.94 | +59.9% | 7.5000 / 6.8737 | 78.29% | 0 / 3000 (0.000%) | 0 |
| mixed-write | 50 | 630.55 / 2689.28 / 4193.20 | 1110.63 / 4377.89 / 6486.73 | +62.8% | 7.5000 / 6.8733 | 78.33% | 0 / 3000 (0.000%) | 0 |

### Live SQL costs and first measured wave

Each phase cell is mean statements / mean SQL milliseconds per instrumented response.

| Scenario | Concurrency | Authentication | Authorization | Live stock | Catalog source | Analytics | Other/write | First-wave ms | First-wave hits / requests |
|---|---:|---|---|---|---|---|---|---|---|
| menu-list | 1 | 2.000 / 4.116 | 3.000 / 5.123 | 0.000 / 0.000 | 0.002 / 0.005 | 0.000 / 0.000 | 0.000 / 0.000 | 30.40 / 30.40 / 30.40 | 3 / 3 |
| menu-list | 10 | 2.000 / 5.737 | 3.000 / 7.519 | 0.000 / 0.000 | 0.059 / 0.354 | 0.000 / 0.000 | 0.000 / 0.000 | 417.03 / 483.99 / 483.99 | 30 / 30 |
| menu-list | 25 | 2.000 / 6.715 | 3.000 / 7.157 | 0.000 / 0.000 | 0.003 / 0.009 | 0.000 / 0.000 | 0.000 / 0.000 | 593.33 / 2039.15 / 3641.77 | 75 / 75 |
| menu-list | 50 | 2.000 / 4.951 | 3.000 / 6.384 | 0.000 / 0.000 | 0.003 / 0.008 | 0.000 / 0.000 | 0.000 / 0.000 | 1171.49 / 4985.46 / 6911.41 | 150 / 150 |
| menu-items | 1 | 2.000 / 3.974 | 3.000 / 4.885 | 1.000 / 2.064 | 0.012 / 0.020 | 0.000 / 0.000 | 0.000 / 0.000 | 33.40 / 33.40 / 33.40 | 3 / 3 |
| menu-items | 10 | 2.000 / 7.919 | 3.000 / 9.949 | 1.000 / 3.110 | 0.029 / 0.114 | 0.000 / 0.000 | 0.000 / 0.000 | 369.30 / 505.83 / 505.83 | 30 / 30 |
| menu-items | 25 | 2.000 / 4.802 | 3.000 / 6.063 | 1.000 / 2.228 | 0.034 / 0.063 | 0.000 / 0.000 | 0.000 / 0.000 | 602.03 / 1439.03 / 2101.55 | 51 / 75 |
| menu-items | 50 | 2.000 / 7.792 | 3.000 / 9.770 | 1.000 / 3.303 | 0.063 / 0.517 | 0.000 / 0.000 | 0.000 / 0.000 | 1156.04 / 5286.90 / 7320.11 | 150 / 150 |
| mixed-read | 1 | 2.000 / 3.909 | 3.000 / 4.815 | 0.800 / 1.601 | 0.013 / 0.020 | 0.000 / 0.000 | 0.000 / 0.000 | 22.93 / 22.93 / 22.93 | 3 / 3 |
| mixed-read | 10 | 2.000 / 5.997 | 3.000 / 7.840 | 0.800 / 2.211 | 0.011 / 0.079 | 0.000 / 0.000 | 0.000 / 0.000 | 424.88 / 481.32 / 481.32 | 30 / 30 |
| mixed-read | 25 | 2.000 / 5.858 | 3.000 / 7.031 | 0.800 / 2.065 | 0.010 / 0.023 | 0.000 / 0.000 | 0.000 / 0.000 | 539.11 / 1244.49 / 1548.73 | 75 / 75 |
| mixed-read | 50 | 2.000 / 11.291 | 3.000 / 13.695 | 0.800 / 3.601 | 0.016 / 0.127 | 0.000 / 0.000 | 0.000 / 0.000 | 1048.38 / 4765.03 / 7058.91 | 150 / 150 |
| mixed-write | 1 | 2.000 / 3.903 | 3.100 / 4.967 | 1.000 / 1.827 | 0.100 / 0.155 | 0.000 / 0.000 | 0.604 / 0.827 | 49.10 / 49.10 / 49.10 | 0 / 3 |
| mixed-write | 10 | 2.000 / 7.567 | 3.100 / 9.968 | 1.000 / 3.254 | 0.145 / 0.549 | 0.000 / 0.000 | 0.600 / 2.218 | 443.44 / 605.94 / 605.94 | 21 / 30 |
| mixed-write | 25 | 2.000 / 12.518 | 3.100 / 16.842 | 1.000 / 4.883 | 0.174 / 1.113 | 0.000 / 0.000 | 0.600 / 4.338 | 501.43 / 1539.78 / 1805.04 | 46 / 75 |
| mixed-write | 50 | 2.000 / 16.217 | 3.100 / 20.345 | 1.000 / 5.875 | 0.173 / 2.725 | 0.000 / 0.000 | 0.600 / 7.220 | 1304.65 / 3644.36 / 5092.20 | 85 / 150 |

## Individual repetition measurements

Full numerical values and phase breakdowns are retained in JSON; this table
also preserves every repetition's latency, query count, hit ratio and error count.

| Mode | Scenario | Concurrency | Repetition | P50 / P95 / P99 ms | SQL statements | Hits / lookups | Errors |
|---|---|---:|---:|---|---:|---|---:|
| disabled | menu-list | 1 | 1 | 25.60 / 34.11 / 39.77 | 6000 | 0 / 1000 | 0 |
| disabled | menu-list | 10 | 1 | 179.57 / 408.07 / 615.21 | 6000 | 0 / 1000 | 0 |
| disabled | menu-list | 25 | 1 | 506.78 / 1973.80 / 2687.77 | 6000 | 0 / 1000 | 0 |
| disabled | menu-list | 50 | 1 | 963.01 / 4397.76 / 6304.40 | 6000 | 0 / 1000 | 0 |
| disabled | menu-items | 1 | 1 | 28.75 / 38.55 / 50.37 | 7000 | 0 / 1000 | 0 |
| disabled | menu-items | 10 | 1 | 166.93 / 373.29 / 520.72 | 7000 | 0 / 1000 | 0 |
| disabled | menu-items | 25 | 1 | 573.01 / 1832.82 / 2680.34 | 7000 | 0 / 1000 | 0 |
| disabled | menu-items | 50 | 1 | 1023.37 / 4073.82 / 6167.11 | 7000 | 0 / 1000 | 0 |
| disabled | mixed-read | 1 | 1 | 28.38 / 38.24 / 43.82 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-read | 10 | 1 | 184.53 / 405.32 / 603.51 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-read | 25 | 1 | 533.78 / 1689.78 / 2310.29 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-read | 50 | 1 | 1055.14 / 4363.28 / 6254.34 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-write | 1 | 1 | 32.35 / 48.27 / 59.65 | 7511 | 0 / 800 | 0 |
| disabled | mixed-write | 10 | 1 | 198.16 / 500.24 / 698.51 | 7500 | 0 / 800 | 0 |
| disabled | mixed-write | 25 | 1 | 533.43 / 1878.51 / 2943.67 | 7500 | 0 / 800 | 0 |
| disabled | mixed-write | 50 | 1 | 1140.83 / 4726.19 / 7454.20 | 7500 | 0 / 800 | 0 |
| disabled | menu-list | 1 | 2 | 25.10 / 34.72 / 47.90 | 6000 | 0 / 1000 | 0 |
| disabled | menu-list | 10 | 2 | 196.36 / 436.74 / 614.19 | 6000 | 0 / 1000 | 0 |
| disabled | menu-list | 25 | 2 | 513.74 / 1724.70 / 2488.39 | 6000 | 0 / 1000 | 0 |
| disabled | menu-list | 50 | 2 | 897.73 / 4470.56 / 6382.19 | 6000 | 0 / 1000 | 0 |
| disabled | menu-items | 1 | 2 | 31.20 / 41.56 / 49.54 | 7000 | 0 / 1000 | 0 |
| disabled | menu-items | 10 | 2 | 226.65 / 429.09 / 601.45 | 7000 | 0 / 1000 | 0 |
| disabled | menu-items | 25 | 2 | 518.63 / 1792.55 / 2477.79 | 7000 | 0 / 1000 | 0 |
| disabled | menu-items | 50 | 2 | 1145.23 / 4673.28 / 6703.55 | 7000 | 0 / 1000 | 0 |
| disabled | mixed-read | 1 | 2 | 26.31 / 38.69 / 49.04 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-read | 10 | 2 | 129.35 / 274.70 / 416.21 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-read | 25 | 2 | 387.39 / 1243.95 / 2023.97 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-read | 50 | 2 | 597.32 / 2481.46 / 3540.49 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-write | 1 | 2 | 16.72 / 22.90 / 27.69 | 7500 | 0 / 800 | 0 |
| disabled | mixed-write | 10 | 2 | 91.47 / 203.75 / 316.60 | 7500 | 0 / 800 | 0 |
| disabled | mixed-write | 25 | 2 | 276.55 / 850.48 / 1332.71 | 7500 | 0 / 800 | 0 |
| disabled | mixed-write | 50 | 2 | 523.49 / 2188.99 / 3355.40 | 7500 | 0 / 800 | 0 |
| disabled | menu-list | 1 | 3 | 14.41 / 18.96 / 23.53 | 6000 | 0 / 1000 | 0 |
| disabled | menu-list | 10 | 3 | 130.53 / 264.24 / 315.40 | 6000 | 0 / 1000 | 0 |
| disabled | menu-list | 25 | 3 | 322.28 / 1056.12 / 1439.98 | 6000 | 0 / 1000 | 0 |
| disabled | menu-list | 50 | 3 | 548.56 / 2480.10 / 4066.96 | 6000 | 0 / 1000 | 0 |
| disabled | menu-items | 1 | 3 | 18.69 / 26.04 / 40.73 | 7000 | 0 / 1000 | 0 |
| disabled | menu-items | 10 | 3 | 112.28 / 258.26 / 349.90 | 7000 | 0 / 1000 | 0 |
| disabled | menu-items | 25 | 3 | 329.16 / 1082.89 / 1574.78 | 7000 | 0 / 1000 | 0 |
| disabled | menu-items | 50 | 3 | 687.53 / 3104.73 / 4541.40 | 7000 | 0 / 1000 | 0 |
| disabled | mixed-read | 1 | 3 | 20.43 / 29.70 / 39.34 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-read | 10 | 3 | 113.58 / 268.99 / 377.16 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-read | 25 | 3 | 345.09 / 1085.32 / 1466.98 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-read | 50 | 3 | 615.83 / 2339.73 / 3694.79 | 6800 | 0 / 1000 | 0 |
| disabled | mixed-write | 1 | 3 | 17.39 / 24.21 / 28.19 | 7500 | 0 / 800 | 0 |
| disabled | mixed-write | 10 | 3 | 110.91 / 261.82 / 371.50 | 7500 | 0 / 800 | 0 |
| disabled | mixed-write | 25 | 3 | 328.57 / 1092.01 / 1652.55 | 7500 | 0 / 800 | 0 |
| disabled | mixed-write | 50 | 3 | 630.55 / 2689.28 / 4193.20 | 7500 | 0 / 800 | 0 |
| warm | menu-list | 1 | 1 | 24.42 / 55.93 / 75.49 | 5003 | 997 / 1000 | 0 |
| warm | menu-list | 10 | 1 | 269.42 / 722.61 / 1023.13 | 5172 | 828 / 1000 | 0 |
| warm | menu-list | 25 | 1 | 580.48 / 2107.30 / 2872.07 | 5003 | 997 / 1000 | 0 |
| warm | menu-list | 50 | 1 | 1016.26 / 4327.93 / 6544.39 | 5005 | 995 / 1000 | 0 |
| warm | menu-items | 1 | 1 | 30.13 / 41.85 / 53.62 | 6012 | 988 / 1000 | 0 |
| warm | menu-items | 10 | 1 | 193.87 / 392.88 / 569.18 | 6070 | 930 / 1000 | 0 |
| warm | menu-items | 25 | 1 | 515.15 / 1694.27 / 2541.76 | 6083 | 917 / 1000 | 0 |
| warm | menu-items | 50 | 1 | 1010.92 / 4341.47 / 6381.10 | 6014 | 986 / 1000 | 0 |
| warm | mixed-read | 1 | 1 | 28.76 / 41.23 / 53.17 | 5815 | 985 / 1000 | 0 |
| warm | mixed-read | 10 | 1 | 178.04 / 421.30 / 598.70 | 5810 | 990 / 1000 | 0 |
| warm | mixed-read | 25 | 1 | 528.76 / 1720.55 / 2438.59 | 5810 | 990 / 1000 | 0 |
| warm | mixed-read | 50 | 1 | 1025.56 / 4335.21 / 5788.15 | 5816 | 984 / 1000 | 0 |
| warm | mixed-write | 1 | 1 | 29.71 / 44.23 / 56.50 | 6811 | 700 / 800 | 0 |
| warm | mixed-write | 10 | 1 | 190.81 / 430.57 / 647.29 | 6789 | 711 / 800 | 0 |
| warm | mixed-write | 25 | 1 | 551.06 / 1746.18 / 2414.94 | 6784 | 716 / 800 | 0 |
| warm | mixed-write | 50 | 1 | 1110.63 / 4225.69 / 6486.73 | 6793 | 707 / 800 | 0 |
| warm | menu-list | 1 | 2 | 24.72 / 33.01 / 39.54 | 5002 | 998 / 1000 | 0 |
| warm | menu-list | 10 | 2 | 206.06 / 418.57 / 542.04 | 5002 | 998 / 1000 | 0 |
| warm | menu-list | 25 | 2 | 493.99 / 1707.89 / 2509.25 | 5003 | 997 / 1000 | 0 |
| warm | menu-list | 50 | 2 | 905.93 / 4013.64 / 6286.28 | 5002 | 998 / 1000 | 0 |
| warm | menu-items | 1 | 2 | 29.80 / 41.30 / 51.08 | 6012 | 988 / 1000 | 0 |
| warm | menu-items | 10 | 2 | 190.07 / 449.52 / 646.61 | 6008 | 992 / 1000 | 0 |
| warm | menu-items | 25 | 2 | 524.07 / 1779.99 / 2591.75 | 6008 | 992 / 1000 | 0 |
| warm | menu-items | 50 | 2 | 1016.68 / 4382.20 / 7040.63 | 6019 | 981 / 1000 | 0 |
| warm | mixed-read | 1 | 2 | 29.02 / 38.77 / 53.43 | 5815 | 985 / 1000 | 0 |
| warm | mixed-read | 10 | 2 | 181.23 / 435.89 / 581.01 | 5810 | 990 / 1000 | 0 |
| warm | mixed-read | 25 | 2 | 506.16 / 1787.95 / 2773.16 | 5811 | 989 / 1000 | 0 |
| warm | mixed-read | 50 | 2 | 1027.17 / 4315.67 / 6468.48 | 5818 | 982 / 1000 | 0 |
| warm | mixed-write | 1 | 2 | 31.34 / 46.62 / 59.67 | 6800 | 700 / 800 | 0 |
| warm | mixed-write | 10 | 2 | 198.70 / 462.91 / 622.26 | 6791 | 709 / 800 | 0 |
| warm | mixed-write | 25 | 2 | 540.77 / 1717.02 / 2342.43 | 6790 | 710 / 800 | 0 |
| warm | mixed-write | 50 | 2 | 1212.97 / 4522.60 / 6766.80 | 6918 | 582 / 800 | 0 |
| warm | menu-list | 1 | 3 | 25.00 / 34.47 / 43.49 | 5002 | 998 / 1000 | 0 |
| warm | menu-list | 10 | 3 | 184.71 / 400.75 / 492.37 | 5002 | 998 / 1000 | 0 |
| warm | menu-list | 25 | 3 | 534.65 / 1707.87 / 2542.54 | 5002 | 998 / 1000 | 0 |
| warm | menu-list | 50 | 3 | 962.13 / 4027.25 / 6883.95 | 5003 | 997 / 1000 | 0 |
| warm | menu-items | 1 | 3 | 28.66 / 40.07 / 51.32 | 6012 | 988 / 1000 | 0 |
| warm | menu-items | 10 | 3 | 187.04 / 420.12 / 567.08 | 6008 | 992 / 1000 | 0 |
| warm | menu-items | 25 | 3 | 536.03 / 1763.31 / 2547.66 | 6012 | 988 / 1000 | 0 |
| warm | menu-items | 50 | 3 | 1077.73 / 4398.41 / 6908.51 | 6155 | 845 / 1000 | 0 |
| warm | mixed-read | 1 | 3 | 27.37 / 35.21 / 40.38 | 5810 | 990 / 1000 | 0 |
| warm | mixed-read | 10 | 3 | 185.78 / 390.86 / 591.63 | 5812 | 988 / 1000 | 0 |
| warm | mixed-read | 25 | 3 | 536.05 / 1765.85 / 2739.93 | 5810 | 990 / 1000 | 0 |
| warm | mixed-read | 50 | 3 | 993.74 / 4184.01 / 5520.74 | 5815 | 985 / 1000 | 0 |
| warm | mixed-write | 1 | 3 | 29.42 / 43.49 / 54.83 | 6800 | 700 / 800 | 0 |
| warm | mixed-write | 10 | 3 | 196.55 / 438.79 / 600.12 | 6955 | 545 / 800 | 0 |
| warm | mixed-write | 25 | 3 | 564.48 / 1784.44 / 2868.96 | 7047 | 453 / 800 | 0 |
| warm | mixed-write | 50 | 3 | 1105.90 / 4377.89 / 6049.35 | 6909 | 591 / 800 | 0 |

## Control selection

This report selects the control's shared cells from the unmodified full warm artifact.
The current control and warm run use the same production revision and instrumentation;
they ran serially and are not randomized paired samples. The original historical
baseline remains the primary milestone comparison. Artifact hashes below identify
the complete original JSON, including warm cells outside this supplemental selection.

## Artifact hashes

- [current-control.json](benchmarks/current-control.json): SHA256 `6209b3c99a12f14c340838a9d840298aff2f3784f22d646e0a6c8b968199fd75`.
- [warm.json](benchmarks/warm.json): SHA256 `d92bdcb916f10a998d791462f8799a725bcb254ce4eaf82283bb544eda0b290a`.
