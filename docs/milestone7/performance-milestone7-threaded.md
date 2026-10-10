# Milestone 7 measured menu-read comparison

Generated from retained JSON by `scripts/report-menu-read-comparison.py`.
Each latency triple is P50 / P95 / P99 in milliseconds. Summary values are
medians of the three independently measured repetition percentiles, not pooled
request percentiles. Queries are means; hits are weighted over catalog GETs only.
Cold means cleared immediately before the measured batch; natural TTL
expiry and concurrent fills remain active. The first wave is reported separately.
SQL timings include driver/database wait and exclude Python/DTO/HTTP work.
Authorization and stock costs stay live; these timings are not additive HTTP percentiles.
The historical baseline and current runs differ in application revision and instrumentation; these are measured before/after observations, not a controlled claim that caching alone caused every latency difference.

## Environment and reproducibility

| Run | Commit | Script version / SHA256 | OS / CPU / logical CPUs | Python / PostgreSQL / Redis | Cells / measured requests / errors |
|---|---|---|---|---|---|
| disabled | `aa01cde845ba5b780f6875abdca274fc452ad70c` (dirty: False) | 1.1.0 / `a2ece698fbfdc2e9dea184c44feea5fcfde42de0af2e136dcd20c51d439216fe` | Windows-11-10.0.26200-SP0 / Intel64 Family 6 Model 151 Stepping 5, GenuineIntel / 12 | 3.12.13 / 16.15 (Debian 16.15-1.pgdg13+2) / N/A | 48 / 48000 / 0 |
| warm | `4ff9aee89588952dd381db6bc1589506f8ebe967` (dirty: True) | 2.0.0 / `292b1e2021a83efcee4b0c8d42be15ab4339a12a0d0ab721380c443a5c0f8d81` | Windows-11-10.0.26200-SP0 / Intel64 Family 6 Model 151 Stepping 5, GenuineIntel / 12 | 3.12.13 / 16.15 (Debian 16.15-1.pgdg13+2) / Redis server v=7.4.11 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=40ff01a501d8e4b6 | 48 / 48000 / 0 |

Exact dataset, settings, available memory, timestamps and library versions are
retained in the adjacent JSON files. All catalog runs use one organization and
restaurant, an assigned Manager, four menus with 40 items each, four ingredients
and 40 tracked recipes. Each cell measures 1,000 calls after 50 excluded warm-ups.
Concurrency is 1/10/25/50 and there are three repetitions; supplemental failure
runs select a documented subset of the same cells.

## Warm results

| Scenario | Concurrency | Baseline ms | Current ms | P95 change | Baseline / current queries per request | Hit ratio |
|---|---:|---|---|---:|---|---:|
| menu-list | 1 | 15.60 / 19.13 / 22.57 | 23.85 / 29.58 / 37.17 | +54.6% | 6.0000 / 5.0017 | 99.83% |
| menu-list | 10 | 144.85 / 352.59 / 396.90 | 203.35 / 465.14 / 650.43 | +31.9% | 6.0000 / 5.0023 | 99.77% |
| menu-list | 25 | 342.64 / 1153.58 / 1593.20 | 566.60 / 1980.57 / 2951.67 | +71.7% | 6.0000 / 5.0030 | 99.70% |
| menu-list | 50 | 678.85 / 2805.44 / 4392.76 | 1018.94 / 4486.53 / 6684.00 | +59.9% | 6.0000 / 5.0027 | 99.73% |
| menu-items | 1 | 17.50 / 21.71 / 26.00 | 28.77 / 38.88 / 49.28 | +79.1% | 7.0000 / 6.0107 | 98.93% |
| menu-items | 10 | 166.02 / 335.87 / 405.91 | 212.76 / 419.52 / 661.14 | +24.9% | 7.0000 / 6.0093 | 99.07% |
| menu-items | 25 | 414.44 / 1387.29 / 2040.94 | 644.12 / 2045.63 / 2986.68 | +47.5% | 7.0000 / 6.0107 | 98.93% |
| menu-items | 50 | 796.22 / 3243.19 / 5028.69 | 1030.35 / 4547.55 / 7502.76 | +40.2% | 7.0000 / 6.0130 | 98.70% |
| mixed-read | 1 | 18.66 / 23.94 / 26.95 | 28.08 / 34.88 / 39.94 | +45.7% | 6.8000 / 5.8117 | 98.83% |
| mixed-read | 10 | 146.89 / 329.75 / 415.13 | 239.52 / 454.23 / 630.33 | +37.8% | 6.8000 / 5.8117 | 98.83% |
| mixed-read | 25 | 417.18 / 1337.41 / 1959.55 | 659.36 / 2130.92 / 3212.68 | +59.3% | 6.8000 / 5.8150 | 98.50% |
| mixed-read | 50 | 719.37 / 2873.78 / 4516.45 | 1190.95 / 4829.62 / 7594.21 | +68.1% | 6.8000 / 5.8140 | 98.60% |
| mixed-write | 1 | 18.73 / 25.43 / 28.93 | 30.12 / 42.77 / 51.74 | +68.2% | 7.5037 / 6.8037 | 87.50% |
| mixed-write | 10 | 170.17 / 384.98 / 534.59 | 254.41 / 583.84 / 835.87 | +51.7% | 7.5000 / 6.7907 | 88.67% |
| mixed-write | 25 | 439.94 / 1450.75 / 2099.95 | 676.39 / 2341.25 / 3312.51 | +61.4% | 7.5000 / 6.7853 | 89.33% |
| mixed-write | 50 | 825.54 / 3383.16 / 5074.40 | 1307.68 / 5716.15 / 8897.91 | +69.0% | 7.5000 / 6.7900 | 88.75% |

### Live SQL costs and first measured wave

Each phase cell is mean statements / mean SQL milliseconds per request.

| Scenario | Concurrency | Authentication | Authorization | Live stock | Catalog source | Analytics | Other/write | First-wave ms | First-wave hits / requests |
|---|---:|---|---|---|---|---|---|---|---|
| menu-list | 1 | 2.000 / 3.295 | 3.000 / 3.970 | 0.000 / 0.000 | 0.002 / 0.002 | 0.000 / 0.000 | 0.000 / 0.000 | 23.67 / 23.67 / 23.67 | 3 / 3 |
| menu-list | 10 | 2.000 / 4.100 | 3.000 / 5.181 | 0.000 / 0.000 | 0.002 / 0.006 | 0.000 / 0.000 | 0.000 / 0.000 | 218.26 / 296.82 / 296.82 | 30 / 30 |
| menu-list | 25 | 2.000 / 3.973 | 3.000 / 5.031 | 0.000 / 0.000 | 0.003 / 0.006 | 0.000 / 0.000 | 0.000 / 0.000 | 552.44 / 1403.56 / 1947.06 | 75 / 75 |
| menu-list | 50 | 2.000 / 3.811 | 3.000 / 4.894 | 0.000 / 0.000 | 0.003 / 0.005 | 0.000 / 0.000 | 0.000 / 0.000 | 1320.66 / 4064.65 / 9163.63 | 150 / 150 |
| menu-items | 1 | 2.000 / 3.440 | 3.000 / 4.255 | 1.000 / 1.581 | 0.011 / 0.015 | 0.000 / 0.000 | 0.000 / 0.000 | 33.48 / 33.48 / 33.48 | 3 / 3 |
| menu-items | 10 | 2.000 / 4.033 | 3.000 / 5.027 | 1.000 / 1.906 | 0.009 / 0.017 | 0.000 / 0.000 | 0.000 / 0.000 | 288.00 / 325.56 / 325.56 | 30 / 30 |
| menu-items | 25 | 2.000 / 4.438 | 3.000 / 5.643 | 1.000 / 1.998 | 0.011 / 0.023 | 0.000 / 0.000 | 0.000 / 0.000 | 713.90 / 2075.23 / 2654.25 | 75 / 75 |
| menu-items | 50 | 2.000 / 4.409 | 3.000 / 5.724 | 1.000 / 1.949 | 0.013 / 0.022 | 0.000 / 0.000 | 0.000 / 0.000 | 1072.63 / 4585.45 / 5684.76 | 150 / 150 |
| mixed-read | 1 | 2.000 / 3.363 | 3.000 / 4.079 | 0.800 / 1.229 | 0.012 / 0.014 | 0.000 / 0.000 | 0.000 / 0.000 | 27.14 / 27.14 / 27.14 | 3 / 3 |
| mixed-read | 10 | 2.000 / 3.980 | 3.000 / 5.004 | 0.800 / 1.494 | 0.012 / 0.021 | 0.000 / 0.000 | 0.000 / 0.000 | 253.91 / 296.89 / 296.89 | 30 / 30 |
| mixed-read | 25 | 2.000 / 4.488 | 3.000 / 5.816 | 0.800 / 1.588 | 0.015 / 0.027 | 0.000 / 0.000 | 0.000 / 0.000 | 624.60 / 1660.57 / 1757.29 | 75 / 75 |
| mixed-read | 50 | 2.000 / 4.579 | 3.000 / 5.881 | 0.800 / 1.571 | 0.014 / 0.025 | 0.000 / 0.000 | 0.000 / 0.000 | 1257.15 / 4107.00 / 7347.16 | 150 / 150 |
| mixed-write | 1 | 2.000 / 3.430 | 3.100 / 4.300 | 1.000 / 1.509 | 0.100 / 0.135 | 0.000 / 0.000 | 0.604 / 0.705 | 44.14 / 44.14 / 44.14 | 0 / 3 |
| mixed-write | 10 | 2.000 / 4.280 | 3.100 / 5.525 | 1.000 / 1.849 | 0.091 / 0.147 | 0.000 / 0.000 | 0.600 / 1.011 | 351.66 / 426.37 / 426.37 | 20 / 30 |
| mixed-write | 25 | 2.000 / 4.580 | 3.100 / 6.093 | 1.000 / 2.001 | 0.085 / 0.153 | 0.000 / 0.000 | 0.600 / 0.991 | 680.74 / 1758.68 / 2539.59 | 46 / 75 |
| mixed-write | 50 | 2.000 / 4.739 | 3.100 / 6.305 | 1.000 / 2.093 | 0.090 / 0.169 | 0.000 / 0.000 | 0.600 / 1.024 | 1670.31 / 5429.91 / 6118.18 | 104 / 150 |

## Individual repetition measurements

Full numerical values and phase breakdowns are retained in JSON; this table
also preserves every repetition's latency, query count, hit ratio and error count.

| Mode | Scenario | Concurrency | Repetition | P50 / P95 / P99 ms | SQL statements | Hits / lookups | Errors |
|---|---|---:|---:|---|---:|---|---:|
| disabled | menu-list | 1 | 1 | 15.60 / 19.42 / 22.57 | 6000 | N/A / N/A | 0 |
| disabled | menu-list | 10 | 1 | 150.72 / 304.02 / 367.66 | 6000 | N/A / N/A | 0 |
| disabled | menu-list | 25 | 1 | 421.57 / 1350.36 / 1945.53 | 6000 | N/A / N/A | 0 |
| disabled | menu-list | 50 | 1 | 722.15 / 3008.78 / 4392.76 | 6000 | N/A / N/A | 0 |
| disabled | menu-items | 1 | 1 | 18.61 / 22.83 / 26.59 | 7000 | N/A / N/A | 0 |
| disabled | menu-items | 10 | 1 | 166.02 / 305.22 / 350.56 | 7000 | N/A / N/A | 0 |
| disabled | menu-items | 25 | 1 | 438.65 / 1441.21 / 2330.58 | 7000 | N/A / N/A | 0 |
| disabled | menu-items | 50 | 1 | 796.22 / 3243.19 / 5339.96 | 7000 | N/A / N/A | 0 |
| disabled | mixed-read | 1 | 1 | 18.66 / 23.94 / 26.95 | 6800 | N/A / N/A | 0 |
| disabled | mixed-read | 10 | 1 | 162.66 / 303.37 / 415.13 | 6800 | N/A / N/A | 0 |
| disabled | mixed-read | 25 | 1 | 417.18 / 1337.41 / 1959.55 | 6800 | N/A / N/A | 0 |
| disabled | mixed-read | 50 | 1 | 792.05 / 3214.82 / 4815.96 | 6800 | N/A / N/A | 0 |
| disabled | mixed-write | 1 | 1 | 18.73 / 25.43 / 28.93 | 7511 | N/A / N/A | 0 |
| disabled | mixed-write | 10 | 1 | 170.17 / 384.98 / 534.59 | 7500 | N/A / N/A | 0 |
| disabled | mixed-write | 25 | 1 | 440.80 / 1450.75 / 2099.95 | 7500 | N/A / N/A | 0 |
| disabled | mixed-write | 50 | 1 | 829.50 / 3383.16 / 5623.13 | 7500 | N/A / N/A | 0 |
| disabled | menu-list | 1 | 2 | 15.68 / 19.13 / 22.77 | 6000 | N/A / N/A | 0 |
| disabled | menu-list | 10 | 2 | 144.85 / 370.47 / 450.19 | 6000 | N/A / N/A | 0 |
| disabled | menu-list | 25 | 2 | 322.47 / 990.50 / 1593.20 | 6000 | N/A / N/A | 0 |
| disabled | menu-list | 50 | 2 | 616.11 / 2378.71 / 3817.58 | 6000 | N/A / N/A | 0 |
| disabled | menu-items | 1 | 2 | 16.36 / 20.63 / 24.99 | 7000 | N/A / N/A | 0 |
| disabled | menu-items | 10 | 2 | 157.73 / 335.87 / 486.73 | 7000 | N/A / N/A | 0 |
| disabled | menu-items | 25 | 2 | 361.41 / 1250.85 / 1692.34 | 7000 | N/A / N/A | 0 |
| disabled | menu-items | 50 | 2 | 675.79 / 2936.87 / 4483.44 | 7000 | N/A / N/A | 0 |
| disabled | mixed-read | 1 | 2 | 18.35 / 29.33 / 36.26 | 6800 | N/A / N/A | 0 |
| disabled | mixed-read | 10 | 2 | 146.89 / 356.38 / 419.56 | 6800 | N/A / N/A | 0 |
| disabled | mixed-read | 25 | 2 | 379.20 / 1257.52 / 1898.50 | 6800 | N/A / N/A | 0 |
| disabled | mixed-read | 50 | 2 | 719.37 / 2801.37 / 4516.45 | 6800 | N/A / N/A | 0 |
| disabled | mixed-write | 1 | 2 | 17.24 / 22.66 / 25.60 | 7500 | N/A / N/A | 0 |
| disabled | mixed-write | 10 | 2 | 153.24 / 350.97 / 479.20 | 7500 | N/A / N/A | 0 |
| disabled | mixed-write | 25 | 2 | 394.04 / 1235.83 / 1869.28 | 7500 | N/A / N/A | 0 |
| disabled | mixed-write | 50 | 2 | 730.72 / 3224.97 / 4676.63 | 7500 | N/A / N/A | 0 |
| disabled | menu-list | 1 | 3 | 14.42 / 17.41 / 21.02 | 6000 | N/A / N/A | 0 |
| disabled | menu-list | 10 | 3 | 131.11 / 352.59 / 396.90 | 6000 | N/A / N/A | 0 |
| disabled | menu-list | 25 | 3 | 342.64 / 1153.58 / 1565.79 | 6000 | N/A / N/A | 0 |
| disabled | menu-list | 50 | 3 | 678.85 / 2805.44 / 4546.14 | 6000 | N/A / N/A | 0 |
| disabled | menu-items | 1 | 3 | 17.50 / 21.71 / 26.00 | 7000 | N/A / N/A | 0 |
| disabled | menu-items | 10 | 3 | 169.10 / 359.41 / 405.91 | 7000 | N/A / N/A | 0 |
| disabled | menu-items | 25 | 3 | 414.44 / 1387.29 / 2040.94 | 7000 | N/A / N/A | 0 |
| disabled | menu-items | 50 | 3 | 818.55 / 3307.10 / 5028.69 | 7000 | N/A / N/A | 0 |
| disabled | mixed-read | 1 | 3 | 19.06 / 23.03 / 26.19 | 6800 | N/A / N/A | 0 |
| disabled | mixed-read | 10 | 3 | 126.86 / 329.75 / 406.33 | 6800 | N/A / N/A | 0 |
| disabled | mixed-read | 25 | 3 | 421.55 / 1413.98 / 2102.32 | 6800 | N/A / N/A | 0 |
| disabled | mixed-read | 50 | 3 | 683.22 / 2873.78 / 4229.31 | 6800 | N/A / N/A | 0 |
| disabled | mixed-write | 1 | 3 | 20.54 / 31.28 / 45.38 | 7500 | N/A / N/A | 0 |
| disabled | mixed-write | 10 | 3 | 173.63 / 408.54 / 570.51 | 7500 | N/A / N/A | 0 |
| disabled | mixed-write | 25 | 3 | 439.94 / 1522.77 / 2280.15 | 7500 | N/A / N/A | 0 |
| disabled | mixed-write | 50 | 3 | 825.54 / 3479.92 / 5074.40 | 7500 | N/A / N/A | 0 |
| warm | menu-list | 1 | 1 | 23.94 / 29.58 / 38.82 | 5002 | 998 / 1000 | 0 |
| warm | menu-list | 10 | 1 | 203.35 / 465.14 / 650.43 | 5002 | 998 / 1000 | 0 |
| warm | menu-list | 25 | 1 | 566.60 / 1980.57 / 2995.26 | 5004 | 996 / 1000 | 0 |
| warm | menu-list | 50 | 1 | 1018.94 / 4486.53 / 7371.00 | 5003 | 997 / 1000 | 0 |
| warm | menu-items | 1 | 1 | 28.77 / 39.67 / 58.51 | 6012 | 988 / 1000 | 0 |
| warm | menu-items | 10 | 1 | 212.76 / 419.52 / 661.14 | 6008 | 992 / 1000 | 0 |
| warm | menu-items | 25 | 1 | 662.17 / 2045.63 / 3483.81 | 6012 | 988 / 1000 | 0 |
| warm | menu-items | 50 | 1 | 1030.35 / 4547.55 / 7530.00 | 6012 | 988 / 1000 | 0 |
| warm | mixed-read | 1 | 1 | 28.08 / 35.60 / 46.99 | 5813 | 987 / 1000 | 0 |
| warm | mixed-read | 10 | 1 | 239.52 / 454.23 / 630.33 | 5810 | 990 / 1000 | 0 |
| warm | mixed-read | 25 | 1 | 659.36 / 2130.92 / 3212.68 | 5815 | 985 / 1000 | 0 |
| warm | mixed-read | 50 | 1 | 1190.95 / 5182.74 / 7936.20 | 5815 | 985 / 1000 | 0 |
| warm | mixed-write | 1 | 1 | 30.12 / 43.55 / 51.74 | 6811 | 700 / 800 | 0 |
| warm | mixed-write | 10 | 1 | 276.91 / 583.84 / 992.12 | 6790 | 710 / 800 | 0 |
| warm | mixed-write | 25 | 1 | 655.23 / 2265.00 / 3284.72 | 6788 | 712 / 800 | 0 |
| warm | mixed-write | 50 | 1 | 1307.68 / 5757.59 / 8897.91 | 6791 | 709 / 800 | 0 |
| warm | menu-list | 1 | 2 | 23.85 / 30.07 / 37.17 | 5002 | 998 / 1000 | 0 |
| warm | menu-list | 10 | 2 | 226.08 / 603.37 / 658.19 | 5003 | 997 / 1000 | 0 |
| warm | menu-list | 25 | 2 | 596.34 / 2068.43 / 2951.67 | 5003 | 997 / 1000 | 0 |
| warm | menu-list | 50 | 2 | 1134.19 / 4783.18 / 6684.00 | 5003 | 997 / 1000 | 0 |
| warm | menu-items | 1 | 2 | 30.11 / 38.88 / 49.28 | 6012 | 988 / 1000 | 0 |
| warm | menu-items | 10 | 2 | 263.63 / 543.50 / 723.56 | 6012 | 988 / 1000 | 0 |
| warm | menu-items | 25 | 2 | 644.12 / 2168.63 / 2986.68 | 6012 | 988 / 1000 | 0 |
| warm | menu-items | 50 | 2 | 1228.26 / 5652.31 / 7502.76 | 6015 | 985 / 1000 | 0 |
| warm | mixed-read | 1 | 2 | 28.17 / 34.88 / 39.94 | 5812 | 988 / 1000 | 0 |
| warm | mixed-read | 10 | 2 | 271.13 / 572.35 / 698.93 | 5815 | 985 / 1000 | 0 |
| warm | mixed-read | 25 | 2 | 670.94 / 2235.99 / 3270.34 | 5815 | 985 / 1000 | 0 |
| warm | mixed-read | 50 | 2 | 1261.08 / 4829.62 / 7594.21 | 5817 | 983 / 1000 | 0 |
| warm | mixed-write | 1 | 2 | 30.54 / 42.77 / 51.95 | 6800 | 700 / 800 | 0 |
| warm | mixed-write | 10 | 2 | 254.41 / 602.02 / 835.87 | 6790 | 710 / 800 | 0 |
| warm | mixed-write | 25 | 2 | 676.39 / 2426.60 / 3635.66 | 6786 | 714 / 800 | 0 |
| warm | mixed-write | 50 | 2 | 1247.10 / 5195.78 / 7822.93 | 6790 | 710 / 800 | 0 |
| warm | menu-list | 1 | 3 | 16.55 / 20.32 / 24.24 | 5001 | 999 / 1000 | 0 |
| warm | menu-list | 10 | 3 | 140.40 / 403.30 / 479.03 | 5002 | 998 / 1000 | 0 |
| warm | menu-list | 25 | 3 | 413.33 / 1383.22 / 2109.64 | 5002 | 998 / 1000 | 0 |
| warm | menu-list | 50 | 3 | 787.58 / 3235.57 / 4875.12 | 5002 | 998 / 1000 | 0 |
| warm | menu-items | 1 | 3 | 20.64 / 25.55 / 29.07 | 6008 | 992 / 1000 | 0 |
| warm | menu-items | 10 | 3 | 206.95 / 414.20 / 466.64 | 6008 | 992 / 1000 | 0 |
| warm | menu-items | 25 | 3 | 511.40 / 1773.84 / 2901.74 | 6008 | 992 / 1000 | 0 |
| warm | menu-items | 50 | 3 | 932.38 / 4266.48 / 5704.00 | 6012 | 988 / 1000 | 0 |
| warm | mixed-read | 1 | 3 | 20.05 / 25.94 / 31.07 | 5810 | 990 / 1000 | 0 |
| warm | mixed-read | 10 | 3 | 188.74 / 394.04 / 480.31 | 5810 | 990 / 1000 | 0 |
| warm | mixed-read | 25 | 3 | 555.58 / 2064.54 / 2850.09 | 5815 | 985 / 1000 | 0 |
| warm | mixed-read | 50 | 3 | 880.90 / 4114.49 / 6060.33 | 5810 | 990 / 1000 | 0 |
| warm | mixed-write | 1 | 3 | 21.01 / 29.49 / 35.16 | 6800 | 700 / 800 | 0 |
| warm | mixed-write | 10 | 3 | 191.22 / 435.43 / 625.58 | 6792 | 708 / 800 | 0 |
| warm | mixed-write | 25 | 3 | 704.57 / 2341.25 / 3312.51 | 6782 | 718 / 800 | 0 |
| warm | mixed-write | 50 | 3 | 1413.35 / 5716.15 / 9133.87 | 6789 | 711 / 800 | 0 |

## Artifact hashes

- [baseline.json](benchmarks/baseline.json): SHA256 `e67372a44af4908d56c016fc1109364e2cfa92cfdd7ad18c1b74f586523e79f7`.
- [warm-threaded.json](benchmarks/warm-threaded.json): SHA256 `e22465225e43348e47c8b3067a1068dba50194c980eee967c358cf31e24e725a`.
