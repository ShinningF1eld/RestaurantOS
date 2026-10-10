# Redis cache and limiter operations

Redis contains disposable catalog payloads and ephemeral authentication limits;
PostgreSQL remains authoritative for business data and cookie sessions. Developer
Redis is nonpersistent on loopback 6379; API/frontend run on localhost 8000/3000.
Normal shutdown is `docker compose down`, preserving `postgres_data`.
There is no deployed environment or production capacity claim.

## Configuration and sizing

| Setting/policy | Current value and operational meaning |
|---|---|
| `REDIS_URL` | Secret connection URL; use trusted TLS/credentials in a shared environment; never include it in diagnostics |
| `REDIS_OPERATION_BUDGET_MS` | Default/maximum 100 ms for a complete attempted command; driver retries disabled |
| `REDIS_MAX_CONNECTIONS` | 20 per API process; exhaustion fails promptly rather than forming an unbounded queue |
| Catalog absolute age | 10 seconds from source read, including fill/serialization; checked at lookup and never renewed by hits |
| Catalog recovery | Five-second cooldown; one real operation probes while other reads bypass |
| Auth recovery | One nonblocking limiter-operation probe per process every five seconds; three consecutive successes |
| `AUTH_LOCAL_MAX_ENTRIES` | Development default 10,000; explicitly size a finite cap before deployment |

Tune process/pool sizing against measured traffic and resources, rerunning the
benchmark and correctness gates. The accepted 100 ms budget, stale-age policy,
quotas and recovery rules are not silently relaxed to improve benchmarks.
Ensure synchronized API clocks because payload age is validated across processes.

[Authentication operations](authentication.md#limiter-outage-and-recovery-operations)
contains the reproducible local-memory measurement. At the largest local quota,
10,000 occupied buckets retained about 64.1 MiB of Python allocations on the
recorded runtime, excluding total RSS, in-flight work and allocator/cleanup
overhead. Budget per process, allow those costs, and measure the actual deployment
runtime and distinct pairs/IPs/families before selecting a cap. At capacity, new
untrackable keys receive generic 429/Retry-After; live counters are never evicted.

## Authentication semantics

| Operation | Redis quota | Process-local outage quota | Accounting |
|---|---|---|---|
| Login email/IP pair | 5 / 60 seconds | 3 / 60 seconds | Credential failures |
| Login source IP | 30 / 900 seconds | 10 / 900 seconds | Credential failures |
| Refresh known family | 10 / 60 seconds | 5 / 60 seconds | Client attempts resolving to the family |
| Refresh source IP | 100 / 60 seconds | 50 / 60 seconds | All client refresh attempts |

Windows are fixed. Normalize email with trim/casefold, use the validated source
IP and HMAC keys, and reserve both buckets atomically before password work.
Confirmed failures plus active reservations cannot exceed a bucket's quota.
Reservations expire after ten seconds without renewal; the auth operation has an
eight-second deadline. Unknown accounts use dummy verification and have the same
failure accounting as wrong-password/disabled accounts. Successful logins release
capacity without incrementing or clearing failures. Genuine server/storage errors
and cancellation are not credential failures and release capacity best effort.
Ambiguous Redis admission/finalization is conservative; do not blindly replay an
uncertain operation. First Redis failure activates local limits on the same
request, without PostgreSQL shadow counters or a rejection waiting period.

Refresh accounting includes successful rotation and known-family expiry/replay;
unknown/malformed/missing tokens have no family charge but consume the IP quota.
Storage errors are excluded. Preserve cookie/CSRF/session/replay contracts and
bounded browser renewal: do not automatically repeat refresh after transport
failure. A timeout may leave an undisclosed family following an uncertain commit;
no cookies/tokens are delivered, and normal expiry/operator cleanup removes it.

## Diagnose an outage and verify recovery

1. Check Redis connectivity and resource pressure through approved operator
   tooling. `/health` is only API liveness and cannot establish Redis/DB readiness.
2. Check catalog warnings for circuit opening and safe failure category;
   `catalog_cache_invalidation_failed` means a write committed but cache deletion
   failed. Continue scoped PostgreSQL reads; source age bounds stale payloads.
3. Group `auth_limiter_degraded`, `auth_limiter_recovering`,
   `auth_limiter_probe_failed` and `auth_limiter_healthy` by `process_id`.
   Inspect safe reason/duration fields to distinguish sustained outage from
   flapping. Skipped requests do not generate per-request limiter logs.
4. Restore Redis and verify actual catalog reads and auth limiter operations.
   Catalog recovery is independent of auth's three stable probes. Probe failures
   reset stability; surviving local history remains enforced alongside Redis
   until natural expiry. A successful `PING` alone does not establish recovery.
5. Use [isolated benchmark commands](../testing/menu-read-benchmark.md) and the
   browser/integration gates to reproduce failure/recovery. Stop/start only the
   benchmark-owned Redis container; do not interrupt developer/shared services.

Collect request IDs, process IDs, categories, durations and HTTP statuses. Never
collect raw Redis URLs/keys, email/IP identifiers, passwords, cookies or tokens.
Auth traces stay disabled. Never use global Redis flushes to clear a benchmark;
the harness deletes only its exact catalog keys and removes its owned container.

## Accepted limitations

Outage quotas are independent per API process and grow in aggregate with process
count; local history is lost on process restart and does not inherit earlier
Redis failures. Redis restart/eviction can also lose shared limiter history.
Restarting API processes to clear throttles discards security history. Surviving
local counters remain during recovery/flapping, but this is not a global outage
quota. Pair-scoped login keys avoid cross-IP victim lockout while providing weaker
protection against distributed guessing than an email-global hard limit.
PostgreSQL remains necessary for real session storage and business operations.

Dashboard caching is a measurement experiment only. Shipping it requires reviewed
freshness, cross-query coherence, date/timezone and order-change invalidation
scope. AI endpoints and workers/events remain deferred.
