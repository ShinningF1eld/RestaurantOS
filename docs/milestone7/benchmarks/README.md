# Retained Milestone 7 measurements

These JSON files are successful, versioned benchmark outputs with runtime-only
credentials excluded. They preserve exact per-repetition measurements, dataset,
settings, hardware/runtime, source revision, dirty state and script SHA256.
Names are stable aliases; contents are copied without modification after successful
API/database/Redis/Compose cleanup. Numerical summaries and hashes are generated
by `scripts/report-menu-read-comparison.py`.
The scoped `.gitattributes` rules preserve exact JSON/source-snapshot bytes;
cross-platform Git newline normalization must not invalidate capture hashes.

`baseline.json` is the corrected existing uncached capture:
`artifacts/benchmarks/corrected/menu-read-baseline-20261007T130416Z-c6ac7674.json`,
version 1.1.0, implementation revision `aa01cde845ba5b780f6875abdca274fc452ad70c`.
It contains 48 cells/48,000 requests, with the corrected 80% reads/20% writes mix.
The original version 1.0.0 capture is superseded and is not used.

Cold/warm/outage/restart captures reuse that catalog workload. Dashboard live and
prototype captures are a separate experiment with 700 historical orders/1,400
snapshots; they are not substituted for the catalog baseline. A prototype result
does not ship dashboard caching or establish approved freshness/invalidation.

`current-control.json` is a supplemental uncached run using current production
code and instrumentation. Its complete 48 cells are compared with the unmodified
full warm artifact; it does not replace the requested historical baseline.

`warm-threaded.json` retains the earlier successful version 2.0.0 warm capture.
Its exact runner is retained as `benchmark-menu-reads-2.0.0.py.txt`; the snapshot
belongs in `scripts/` if reproduced. The [threaded comparison](../performance-milestone7-threaded.md)
discloses the measured regressions. Version 2.1.0 subsequently separates the API
and load generator into processes; final cold/warm/current-control captures use
that same topology and instrumentation. Cold uses version 2.2.0, whose exact
source is retained as `benchmark-menu-reads-2.2.0.py.txt`; remaining captures use
version 2.3.0's benchmark-only Windows idle-socket guard. Complete version 2.2+
captures retain request errors and explicitly unknown lost-response SQL work;
they do not select error-free retries. Incomplete earlier attempts produced no
result JSON and are disclosed in the verification report.

`dashboard-freshness.json` records the separate real Owner-authorized legacy-order
delete: Manager denial, immediate live visibility versus stale prototype values,
expiry visibility, unchanged stock and transactional audit. Its source hashes
identify the exact freshness/common/prototype scripts; it contains no credentials.

See [reproduction](../../testing/menu-read-benchmark.md),
[issue #27 evidence](../verification-milestone7-issue27.md),
[menu comparison](../performance-milestone7.md) and
[current control](../performance-milestone7-control.md) and
[dashboard experiment](../performance-milestone7-dashboard.md).
