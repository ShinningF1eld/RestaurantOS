# Deferred: query and request-path performance optimization

**Status:** Future backlog — do not implement yet  
**Activation:** After the main RestaurantOS milestones are completed, unless the owner explicitly reprioritizes it  
**Recorded:** 2026-10-10  
**Reference revision:** main at 804f1872d8066402a41b12547d203b3d884e09a2  
**Scope:** Measure and improve SQL query counts, SQL execution cost, and authenticated catalog HTTP latency without changing behavior.

This is a planning document, **not an active milestone, a claim of improved performance, or permission to edit application code**. Do not reopen Milestone 7 or create implementation issues yet. Before starting later, review current code, instructions, acceptance evidence, and the owner's priorities.

## 1. Motivation and evidence

Milestone 7 caches scoped menu and menu-item catalog fields in Redis but deliberately keeps session, authorization, recipe tracking and stock checks live in PostgreSQL. This reduced database work without demonstrating a consistent HTTP response-time improvement.

The retained benchmark shows:

- Menu-list requests: approximately 6 SQL statements uncached versus 5 with a warm catalog hit.
- Menu-item requests: approximately 7 SQL statements uncached versus 6 with a warm catalog hit.
- Across all measured workloads, warm caching reduced SQL statements per observed response by approximately **8.3–16.6%**, with cache-hit ratios of **78.29–99.77%**.
- Historical baseline comparisons show warm P95 latency regressions of **14.0–90.2%**. A same-revision uncached control shows warm-cache P95 improvements in only 3 of 16 scenario/concurrency cells, with variation between serial repetitions.
- These comparisons **do not establish that Redis overhead caused the regressions**: topology, measurement differences and runtime variation can influence the observed results.

The original catalog benchmark used one restaurant, four menus / 160 items, 40 tracked items, 1,000 requests per workload/concurrency/repetition, three repetitions, and concurrency 1, 10, 25 and 50. A small local dataset may make the avoided catalog query inexpensive; this is a hypothesis to profile, not a proven root cause.

References:

- [Milestone 7 benchmark](../milestone7/performance-milestone7.md)
- [Same-revision uncached control](../milestone7/performance-milestone7-control.md)
- [Issue 27 verification and caveats](../milestone7/verification-milestone7-issue27.md)
- [Benchmark procedure](../testing/menu-read-benchmark.md)
- [Catalog cache contract](../api/catalog-cache.md)
- [Redis runbook](../runbooks/redis-cache.md)

## 2. Starting query inventory

Verified against the source at the recorded revision; inspect again before implementation.

| Phase | Current implementation | Typical SQL statements | Candidate |
| --- | --- | ---: | --- |
| Authentication | [auth/dependencies.py](../../backend/app/modules/auth/dependencies.py): separate user and AuthSession lookups | 2 | Prototype one joined, validated read |
| Live tenancy | [tenancy/repo/access.py](../../backend/app/modules/tenancy/repo/access.py): active membership/organization, then restaurant assignments | 2 | Prototype one read-only join/aggregation |
| Resource scope | [tenancy/access.py](../../backend/app/modules/tenancy/access.py) checks restaurant existence, or [catalog/repo/queries.py](../../backend/app/modules/catalog/repo/queries.py) loads a scoped menu | 1 | Retain live scope validation; profile joins |
| Recipe/stock availability (item list) | [recipes/service.py](../../backend/app/modules/recipes/service.py): joined item, recipe and live inventory information | 1 | Keep stock live; inspect query plan |
| Catalog list | [catalog/service.py](../../backend/app/modules/catalog/service.py): PostgreSQL on miss, Redis on valid hit | 1 on miss, approximately 0 on hit | Profile cache retrieval and response materialization |

**Illustrative hypothesis:** If both authentication and ordinary read-only tenancy each go from two SQL statements to one, a typical warm menu-item request could go from about 6 to about 4 SQL statements. This is not yet implemented or measured, and fewer statements do not guarantee shorter total execution time.

## 3. Goals and boundaries

**Goals:** Identify actual bottlenecks; reduce redundant PostgreSQL work where it is beneficial; compare SQL time, SQL count, Redis overhead, end-to-end HTTP latency and throughput; publish reproducible evidence for both successful and unsuccessful experiments.

**Non-goals:** Do not initially add caches for users, active sessions, memberships, roles, assignments, permissions, stock balances, or available portions. Do not change Redis's current 10-second source-age policy, 100 ms command budget, recovery semantics, rate limiter, API/response schemas, client behavior, or caching scope just to improve benchmark scores. No dashboard caching, new services/workers, unrelated refactors, or schema/index migration without separate justification and approval.

The correctness baseline is mandatory:

- JWT validation is not a substitute for fresh user/session checks. Preserve session ownership, active-user status, expiry, immediate logout/revocation visibility, login/refresh/cookie/CSRF/replay and rate-limiter behavior.
- Fetch active organization membership and branch assignments freshly on every relevant operation. Preserve Owner organization-wide access, Manager/Employee branch restrictions, 404 for foreign/unassigned resources and 403 for forbidden capabilities. Cached catalog entries must never grant permissions.
- Principal lookups use an independent short-lived SQLAlchemy session; preserve this separation from business transactions.
- Preserve read locks and ordering on locked write paths, transaction boundaries, audits, and rollback semantics. A read-only query optimization must not silently change a lock=True operation.
- Inventory availability, recipe tracking and stock balances remain authoritative and live for item-list responses. Preserve missing-item cache-miss fallback and order acceptance stock/price/ledger/idempotency rules.
- Preserve tenant-specific Redis keys, post-commit invalidation, age limits and PostgreSQL fallback on Redis outage, including documented degraded/recovery behavior.

## 4. Workstreams (separately measurable)

### Phase 0 — Instrument and benchmark before rewriting SQL

Build a request-local breakdown of auth user/session, membership, assignments, scoped resource existence, live recipe/stock and catalog source statements. Measure each phase's statement count, SQL execution duration (including driver/database wait), and how much of the overall HTTP request it accounts for. Profile Redis pool acquisition, command time, Pydantic payload validation, cached-to-response materialization, and final response serialization separately where possible.

Collect HTTP P50/P95/P99, RPS/throughput, errors, per-query and aggregate SQL time, DB connection pool pressure, Redis hits/misses/fallbacks, DB CPU/IO where measurable, and application resource use. Benchmark-only instrumentation must be isolated and its overhead disclosed. Avoid recording credentials, cookies, tokens, account identifiers or raw business data.

For expensive SELECT statements, inspect EXPLAIN (ANALYZE, BUFFERS) on a disposable PostgreSQL database with realistic seed data. Do not assume statement-count reduction also reduces work; verify elapsed time and query plans.

### Phase 1 — Authentication query consolidation

Current [get_current_principal](../../backend/app/modules/auth/dependencies.py) fetches User and AuthSession separately. Consider a single repository query joining the requested user to the claimed session family and returning only the fields needed to construct AuthenticatedPrincipal.

Acceptance hypothesis: one read instead of two for the same protected GET, **with unchanged** user/session existence, session ownership, active-user check, revocation, expiration, exceptions, and error contracts. Preserve the separate short-lived auth session. Do not change login, refresh or writes just to simplify the read.

### Phase 2 — Read-only tenancy query consolidation

Current [AccessRepository.current](../../backend/app/modules/tenancy/repo/access.py) separately loads an active membership/organization and assignments. Investigate a single correctly scoped outer join, aggregate or subquery, without mixing organizations or dropping a membership with zero assignments.

Check Owners without assignments, managers/employees with multiple assignments, membership/organization deactivation, assignment removal and foreign restaurant IDs. Preserve lock=True semantics on write paths; keeping the existing locked implementation is preferable to a risky lock rewrite unless separately proven safe.

Acceptance hypothesis: ordinary read-only membership/assignment checks use one rather than two SQL statements, while fresh authorization remains fully enforced.

### Phase 3 — Scope and live-stock query-plan review

Profile restaurant/menu existence and the existing joined live availability query before considering changes. That query already gets recipe components and inventory balances in one SQL statement. Splitting it into additional queries or caching recipe structure could be slower and would require new freshness/invalidation rules.

Explore projections, row cardinality, join/index plans and avoiding duplicate computations; keep authoritative stock and tracking live. An index addition needs measured evidence, a reviewed Alembic migration, and migration/legacy-preservation checks.

### Phase 4 — Redis and DTO overhead review

[CatalogService.list_menu_items](../../backend/app/modules/catalog/service.py) reconstructs temporary MenuItem models from validated Redis DTOs before attaching live availability. Measure Pydantic JSON validation, object construction, availability enrichment and response-model serialization.

Only prototype a DTO-oriented alternative if it preserves identical public response fields, Decimal precision, missing-item fallback and fresh stock. Do not remove validation or relax cache age/scope rules merely to improve the results.

## 5. Reproducible experiment design

1. **Pin a new baseline:** Run both uncached and warm-cache paths at the same current code revision using the same server/load-generator topology and instrumentation; keep original Milestone 7 raw artifacts unchanged. Record script hash, commit, dirty state, Python/PostgreSQL/Redis versions and nonsecret effective settings.
2. **Keep a comparable seed:** Retain the original 4-menu/160-item scenario, 1,000 measured requests after 50 excluded warm-ups, three repetitions, concurrency 1/10/25/50, and the original menu-list, menu-items, mixed-read and 80%-read/20%-write mixes. Do not silently relabel an altered workload.
3. **Add realistic separate experiments:** Test larger catalog fixtures (e.g., 2,000 and 10,000 total items), more restaurants/tenants, varied number of assignments and recipes, and read-heavy mixes (e.g., 99%/1% and 95%/5% reads/writes). These are additions, not replacements for the original baseline.
4. **Control variation:** Alternate or randomize before/after runs (e.g., ABBA), repeat enough to characterize variability, and disclose database buffer warm-up, Redis warm/cold state, TTL expiry, write invalidations, concurrency and CPU/memory contention.
5. **Report both SQL and HTTP:** For every scenario include statements per observed response, SQL mean/tail duration or total server SQL cost, redis/payload time, HTTP P50/P95/P99, throughput, errors, cache hits and resource pressure. Report individual repetitions and uncertainty. Do not add SQL phase percentiles to HTTP percentiles.
6. **Preserve failure accounting:** The baseline and candidate should use real authenticated HTTP, migrated disposable PostgreSQL and owned Redis. Record failures and unknown SQL observations honestly; never retry/select only error-free runs to improve figures. Never migrate, reset or benchmark the application database.
7. **Isolate changes:** Compare baseline to each individual candidate, with caching either consistently enabled or consistently disabled for that comparison. Measure the final composed change separately; do not attribute all gains to Redis or to the most recent query modification.

Once activated, store new reproducibility instructions and versioned raw/comparison evidence under a future docs/performance/query-optimization/ directory. Never overwrite retained historical captures.

## 6. Required regression and completion checklist

- [ ] Record current baseline and per-phase SQL timing with code revision and measurement overhead.
- [ ] Test missing/deactivated users; incorrect session ownership; missing, expired, revoked and replayed sessions; logout/refresh, safe 401 behavior and current cookie/CSRF contracts.
- [ ] Test active/inactive memberships/organizations, zero/multiple assignments, Owner/Manager/Employee permissions, cross-tenant lookups, immediate revocation and assignment-removal visibility on the next request, and exact 403 versus 404 behavior.
- [ ] Verify write-path locks, explicit transaction/rollback/audit behavior and concurrent operations when any shared query changes.
- [ ] Verify live stock/recipe availability following order acceptance, receipts, waste, counts and recipe edits; preserve item deletion/invalidation races, immutable snapshots and idempotency.
- [ ] Verify Redis miss/outage/restart, stale payload rejection, post-commit invalidation and fallback have unchanged results.
- [ ] Quantify SQL count, SQL execution time and HTTP P50/P95/P99 per candidate, including regressions, throughput and failure rates, with comparable datasets and retained JSON.
- [ ] Run relevant backend unit/integration tests and static checks, real browser/security workflows, and affected migrations checks. Full ten-gate local validation and required remote PR CI must pass before claiming completion.
- [ ] Update contracts/current-state/ADRs only when an implemented change has verified evidence. No undocumented API, schema or permission changes.

### Go/no-go rules

- Correctness is a **hard gate**. Reject any candidate that changes security, tenancy, session freshness, stock, transactional locking, failure recovery or response behavior, regardless of speed.
- Establish an acceptable latency non-regression band and practical benefit threshold based on measured run-to-run noise **when this work starts**; do not invent a speedup objective now.
- Reducing SQL statements, reducing total database execution time, improving HTTP latency, and raising throughput are **different successes**. Report each independently.
- Prefer a small query rewrite to new distributed cache state if it produces similar measured benefit. Drop or defer changes that add complexity without robust improvement.

## 7. Future Codex handoff

After all main roadmap milestones are completed (or the owner explicitly reprioritizes this work):

> Read docs/backlog/post-milestone-query-optimization.md, root AGENTS.md, the current auth/tenancy/catalog/stock code, Milestone 7 benchmark evidence and the latest branch state. First reproduce a current benchmark and identify actual SQL/Redis/request bottlenecks. **Do not implement immediately**: discuss proposed SQL changes, security and locking risks, measurement methodology and acceptance thresholds with the owner. Then use the existing project-design and GitHub task-planning workflow to create separately verifiable work items. Preserve all existing behavior and use disposable services.

**Creation of this document itself changes no application code, settings, schema, benchmarks, roadmap milestone status or GitHub issues.**
