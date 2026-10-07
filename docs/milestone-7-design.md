# Milestone 7: Redis caching and rate limiting

Status: Approved, revision 7 (cache and login limiter tuning recorded)
Updated: 2026-10-07  
Inspection: repository HEAD `a1acf44`; working tree clean before this document.  
Approval: user accepted the completed plan on 2026-10-07 ("The plan is done then"). Remaining tuning is identified below; implementation and verification have not been performed.

## Goal and scope

Deliver measured menu-read caching and Redis authentication limits within the
existing modular monolith. PostgreSQL remains authoritative. Dashboard caching
is optional pending measurements; AI endpoints and background workers are outside
this milestone's initial scope.

Sources: [master roadmap](../RestaurantOS_Master_Roadmap.md#milestone-7--redis-caching-and-rate-limiting),
[current state](current-state.md), [module ADR](adr/0002-feature-modules.md),
[authentication contract](api/authentication.md), and inspected
`backend/app/modules/catalog/service.py`, `backend/app/modules/auth/rate_limit.py`,
`backend/app/modules/auth/service.py`, `backend/app/core/config.py`.

## Requirements

| ID | Requirement | Acceptance criteria |
|---|---|---|
| R1 | Menu edits may appear with a stale window strictly under 15 seconds | An accepted 10-second absolute TTL, measured from source-read start, bounds stale data even if invalidation fails; slow fills cannot reset the age |
| R2 | Authorization remains fresh | Membership, assignment, resource scope and capability are checked before every cache hit; cross-tenant and revoked-access regressions pass |
| R3 | Cache catalog data without caching stock availability | Availability is queried live; orders continue validating authoritative prices and stock in PostgreSQL |
| R4 | Cache failure falls back to PostgreSQL | Redis timeout, restart, corrupt payload and invalidation failure preserve correct reads and committed writes |
| R5 | Authentication uses shared Redis normally and stricter process-local limits during outages | First Redis failure activates local enforcement immediately; subsequent requests skip Redis until a bounded recovery probe; no PostgreSQL limiter writes or rejection waiting period |
| R6 | Backend transitions have explicit degraded guarantees | Tests prove local atomicity, stricter quotas, bounded memory, single-flight probes, recovery stability, ambiguous increments and transition behavior; separate process quotas and counter loss on restart are documented accepted limitations |
| R7 | Demonstrate performance and correctness | Reproducible workloads report P50/P95/P99, query count, hit ratio, error rate, dataset, hardware and environment; full relevant repository gates pass |
| R8 | Login quotas count failed authentication, not successful login | Invalid password, unknown account and disabled account use the same failure accounting; successful logins do not increment failure quotas; storage/transport errors are not credential failures |
| R9 | Login keys and responses avoid account enumeration | Reuse trim/casefold normalization and validated source IP before building HMAC-protected email/IP keys; unknown accounts follow identical limiter handling; all triggered buckets return the same generic 429 body |
| R10 | Mode transitions are observable without secrets | Structured events record Redis healthy/degraded/recovering transitions, process identity, safe reason and duration; no raw email/IP, password, cookie or token is logged |

R1's tolerance and R5's Redis/local fallback policy were accepted by the user on
2026-10-07. The earlier timed rejection/PostgreSQL fallback policy is superseded.
The user explicitly accepted weaker protection across multiple API processes
during outages, favoring login availability and avoiding limiter database writes.
Cache scope and TTL are accepted below. Remaining limiter tuning is identified
in the implementation tuning section; previously accepted limiter settings remain
accepted.

## Accepted cache decisions (issue #19)

Recorded on 2026-10-07 following the user's request to save these decisions.
This records policy for [issue #19](https://github.com/ShinningF1eld/RestaurantOS/issues/19),
not implementation or verification evidence. The limiter portion of that issue
remains open.

| Endpoint | Initial caching | Key |
|---|---|---|
| `GET /restaurants/{restaurant_id}/menus` | Menu list | `restaurantos:{env}:catalog:v1:org:{org_uuid}:restaurant:{restaurant_id}:menus` |
| `GET /menus/{menu_id}/items` | Item list | `restaurantos:{env}:catalog:v1:org:{org_uuid}:menu:{menu_id}:items` |
| `GET /menus/{menu_id}` | Not initially cached | None |
| `GET /menu-items/{menu_item_id}` | Not initially cached | None |

The absolute maximum cache age is **10 seconds from source-read start**.
Store only the remaining TTL after the source read and serialization; discard
already expired fills. Hits do not renew expiry. A concurrent old fill, including
one racing a committed write and invalidation, retains its original deadline.
Validate payload schema, parent IDs and age before use.

Menu-list data contains `menu_id`, `restaurant_id`, `name` and `description`.
Item-list data contains `menu_item_id`, parent IDs (`menu_id`, `restaurant_id`),
`name`, `description`, `price` and `is_available`. Prices retain fixed precision
without floating-point conversion. Cache typed serialized data, not ORM instances.

Read `inventory_tracking`, `out_of_stock` and `available_portions` live from
PostgreSQL on every item-list request, including cache hits. If a cached item is
missing during that read, treat the payload as a miss and reload the scoped list.
Orders continue validating authoritative PostgreSQL prices and stock.

Before every cache serve, freshly resolve active membership, branch assignments,
capability, and the requested restaurant/menu's existence and tenant scope.
Derive `org_uuid` from the verified access context, never from supplied access
authority. Preserve foreign/unassigned 404 and forbidden-capability 403 behavior;
cache no authorization decisions.

### Post-commit invalidation matrix

| Successful committed mutation | Keys to invalidate |
|---|---|
| Menu create/update | Restaurant menu-list key |
| Menu delete | Restaurant menu-list key and deleted menu's item-list key |
| Item create/update/delete/deactivate | Parent menu's item-list key |
| Recipe/tracking or inventory stock changes | None; their response fields are read live |

Invalidate only after successful PostgreSQL commit. Failed or rolled-back writes
produce no committed-change invalidation. Both existing `delete_menu_item`
outcomes (hard deletion and historical-item deactivation) must reach post-commit
invalidation despite their current early returns.

Redis failure never causes a catalog request to fail solely because of the cache.
Bound Redis operations; timeout, restart, corrupt payload and fill failure fall
back to scoped PostgreSQL reads. A failed invalidation leaves the committed write
successful and is logged safely; the absolute age limit bounds stale cache data.
This permits brief stale catalog fields after a successful edit, including a fill
racing invalidation. PostgreSQL failures retain the normal request error behavior.

## Proposed architecture and interactions

Add a shared Redis adapter and lifecycle/configuration support outside business
modules. Catalog and authentication own their use cases. Cache serialized typed
catalog payloads rather than ORM objects; preserve public URLs and response shapes.
Keys include environment, organization, restaurant/menu identity and payload schema
version. Authentication identifiers retain existing HMAC protection.

Read flow: current authorization, cache lookup, database fill on miss, live stock
availability, existing response. Bound payload age from the source-read start;
discard expired/slow fills. Menu/item mutations invalidate affected keys after
commit. Failed invalidation is logged and bounded by TTL. Concurrent stale fills
must remain within the same age bound, not receive a fresh full TTL.

Accepted auth flow: shared Redis -> stricter process-local limiter -> controlled
recovery -> shared Redis. First failure marks Redis unhealthy in that process and
enforces local limits for the same request. An ambiguous Redis increment may also
be counted locally; availability does not imply guaranteed quota continuity.
Requests in degraded mode skip Redis. One periodic probe per process tests recovery,
without blocking other requests on the probe. Recovery must exercise the limiter
operation rather than relying only on ping. Preserve existing 429/Retry-After and
error bodies, cookies, bounded browser renewal and uncertain-refresh retry policy.

Accepted tuning: 100 ms total Redis operation budget, probes every 5 seconds,
and three consecutive successful probes before recovery. Login limits count only
failed authentication outcomes (wrong password, unknown account or disabled
account), identically for all accounts; successful login does not clear either
bucket. Normal Redis mode allows 5 failures per 60 seconds for the normalized
email plus source-IP pair, and 30 failures per 900 seconds for the source IP.
Local degraded mode applies stricter limits: 3 per 60 seconds for the pair and
10 per 900 seconds for the IP. The pair keying prevents another IP from exhausting
the victim's pair bucket; shared-IP users still share the IP-wide quota. Without
an email-global hard limit, distributed guessing across many IPs has weaker
protection; this limitation is accepted. When implemented, this policy will
replace the current PostgreSQL-backed pre-verification attempt-counting
implementation with failed-login accounting in Redis and local degraded modes.
Refresh family 10 and IP 40 per 60 seconds remain proposals. Concurrent local
increments must be atomic.

The current PostgreSQL policy also has an email-global hard limit (5 per 900
seconds), so moving it unchanged to Redis retains this concern. Evidence:
[OWASP authentication guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
explicitly cautions that account lockout can enable denial of service. Pair-scoped
limits are a project tradeoff, not a claim that OWASP prescribes them.

### Login failure accounting and response behavior

Reuse `normalize_email` (`strip().casefold()`) at the service boundary, including
direct service callers; key construction cannot depend on account lookup success.
Use the existing validated source-IP mechanism, without broadening proxy trust.
Unknown, disabled and wrong-password outcomes increment the same failure buckets.
Successful logins do not increment either bucket. Keep the existing dummy password
verification for unknown accounts. Login storage failures do not increment
credential-failure counters. Login rules do not automatically redefine refresh
quotas, whose semantics remain a separate decision.

All throttle outcomes use one generic 429 body and the existing Retry-After header;
never expose the triggering bucket or account existence. Use a consistent retry
calculation independent of whether the account exists. A pre-verification throttle
can reject even correct credentials once the source's failure budget is exhausted.

Accepted: do not clear any failure bucket on successful login, in either normal
Redis or local degraded mode. Keeping both avoids extra recovery/clear races.

Concurrency needs explicit admission before costly password checks: atomically
check failure counts and acquire short-lived in-flight capacity for both keys,
then finalize as failure or release on success. Reservations are temporary capacity,
not successful-login failure counts. Use bounded leases for process loss and
ambiguous Redis responses; avoid account-dependent acquisition or cleanup paths.
Exact reservation capacity and generic overload behavior are unresolved. Tests
must prove overlapping password checks cannot create unlimited quota overshoot,
and that success, storage failure and cancellation release capacity safely.

Emit structured mode-transition logs, including safe reason category, process
identity and degraded duration. Avoid logging every skipped Redis request; log
transitions and aggregated measurements. Probe failures and transition metrics
must reveal flapping without identifying accounts.

Local state uses monotonic expiry, bounded entries and automatic cleanup. At
capacity, reject untrackable new keys with a retryable service error rather than
evicting active counters and silently allowing requests. Existing valid access
sessions continue; PostgreSQL remains necessary for actual auth/session storage.

Proposed recovery guard: keep enforcing existing local buckets alongside Redis
until those buckets expire; new keys use Redis once recovery is stable. Do not
clear local counters on a mode change. Flapping must not grant fresh local quotas.

## Accepted degraded guarantees

Local counters are independent per API process and are lost on process restart.
They do not inherit pre-outage Redis attempt history. Redis restart or eviction may
also lose counters. Stricter local quotas reduce exposure but do not provide a
global quota or prevent aggregate quotas growing with process count. These weaker
outage guarantees are explicitly accepted; no PostgreSQL shadow accounting or
fallback limiter is proposed. Cross-process mode synchronization is unnecessary
for this selected policy. Refresh numerical settings and the recovery guard remain proposals.

## Validation and delivery

First capture an uncached baseline using disposable seeded PostgreSQL. Benchmark
the same dataset, concurrency and endpoints with cold/warm caches and mixed writes.
No performance result or passing test is claimed by this design.

Add regressions for authorization on hits, stock changes, write rollback,
post-commit invalidation failure, concurrent fills, absolute age bounds, Redis loss,
limiter transitions, independent process quotas, recovery flapping, memory capacity
and process restart. Test actual Redis outage/restart as well as deterministic
local timing; verify requests avoid Redis during the open circuit.
Run backend-unit, backend-integration, backend-static, browser and the full
acceptance gate set for milestone completion. Dependency changes update source and
hashed locks together. If coordination needs a schema change, use a new migration
and the disposable migrations gate; never migrate the application DB for validation.

Likely affected areas: backend core/external adapter, catalog and auth services,
settings/examples, dependency locks, Compose development Redis configuration,
validation infrastructure, benchmark scripts, tests, API/runbook and measured
current-state/README evidence. No frontend behavior change is assumed.

## Implementation tuning and assumptions

The overall plan is accepted. The following details remain tuning tasks or
disclosed defaults; material changes to the accepted behavior require review.

1. Cache scope, keys, payload split, 10-second absolute TTL and post-commit
   invalidation are accepted in the issue #19 decision section above.
2. Login thresholds/windows and failed-login accounting are accepted above;
   review refresh accounting and thresholds and finalize the recovery guard.
3. Finalize bounded-memory capacity against expected workload before implementation.
4. Initial cache scope is the two catalog lists above; evaluate optional dashboard
   caching after measurements.
5. Specify concurrent admission capacity/lease behavior and response before coding.

## Decision history

| Date | Decision | Evidence |
|---|---|---|
| 2026-10-07 | Menu edits may have a stale window under 15 seconds | User discussion |
| 2026-10-07 | Redis auth outage temporarily rejects, then falls back to PostgreSQL | Superseded by user's Redis/local policy |
| 2026-10-07 | Draft revision 1 created | No overall design approval or implementation authorization claimed |
| 2026-10-07 | Shared Redis normally; stricter local limiter during outage; periodic probes and return to Redis | User proposed policy and explicitly accepted weaker multi-process protection |
| 2026-10-07 | Draft revision 2 records accepted policy and proposed tuning | Overall design remains draft |
| 2026-10-07 | Accept 100 ms timeout, 5-second probes, three successful probes and local login IP quota 10; question email-global lockout | User discussion; replacement email policy pending |
| 2026-10-07 | Failed-login accounting, normalized email/IP keys for all accounts, generic 429 and observable Redis mode transitions; never clear IP failures on success | User's six explicit requirements; overall design and remaining tuning pending |
| 2026-10-07 | Approve completed plan and rename to milestone-7-design.md | User: "The plan is done then"; revision 5 records approval and preserves tuning tasks |
| 2026-10-07 | Accept two catalog list endpoints, scoped v1 keys, static item fields with live tracking/stock, 10-second source-start age, fresh authorization and fail-open post-commit invalidation | User supplied cache decisions and requested saving them; revision 6 records the invalidation matrix and implementation edge cases; limiter tuning and verification remain open |
| 2026-10-07 | Accept normal Redis login limits (email+IP 5/60s, IP 30/900s), degraded local limits (email+IP 3/60s, IP 10/900s), failed-login-only accounting, and no clearing on successful login; accept distributed-guessing limitation | User supplied accepted login limiter decisions and deferred implementation; revision 7 records settings consistently; refresh limiter tuning and implementation remain open |
