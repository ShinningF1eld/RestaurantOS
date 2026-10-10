# Catalog read caching

The existing menu and item response shapes and URLs are unchanged. Only
`GET /restaurants/{restaurant_id}/menus` and `GET /menus/{menu_id}/items` cache
catalog fields. Detail endpoints, dashboard analytics and order validation remain
uncached. See [Redis architecture](../architecture/redis.md) and
[operational procedure](../runbooks/redis-cache.md).

Every request resolves the current active membership, branch assignment, resource
existence/organization scope and `menu.read` capability **before** Redis lookup.
Owners cover their organization; Managers and Employees require assignments.
Foreign/unassigned resources return 404; forbidden capabilities return 403.
Cached payloads never grant access, and revocation takes effect on the next read.

Keys include environment, schema version, organization and restaurant/menu IDs.
Payloads contain typed catalog values, including fixed-precision prices; they do
not contain ORM objects, permission decisions, stock balances or available
portions. Item-list reads query recipe tracking and stock availability in
PostgreSQL on every hit. Missing cached items cause a source-list reload. Orders
always validate authoritative PostgreSQL prices and stock, retaining immutable
item snapshots and the existing acceptance locks/ledger.

## Age, invalidation and failure

The accepted maximum payload age at cache lookup is **10 seconds from source-read start**, strictly
under the roadmap's 15-second tolerance. Serialization and database time consume
that budget; `SET PX` receives only the remaining milliseconds. Slow fills are
discarded, hits never extend TTL, and invalid/schema-invalid/future-dated/expired
payloads are misses. This bounds an old fill even when it races a committed write
and repopulates an invalidated key. It does not promise immediate visibility of
every edit during that interval. Wall-clock consistency across API processes is
an operational assumption; maintain synchronized clocks.
The bound governs server cache reuse, not a response-delivery deadline or how
long a browser keeps an already returned value. Item stock/recipe reads follow
the lookup and remain live; transport/rendering time is outside the age check.

| Successful committed mutation | Targeted invalidation |
|---|---|
| Menu create/update | Restaurant's menu-list key |
| Menu delete | Restaurant's menu-list key and deleted menu's item-list key |
| Item create/update/hard delete/deactivation | Parent menu's item-list key |
| Recipe/tracking/stock change | None; availability is read live |

Invalidation runs after the service-owned PostgreSQL transaction commits.
Business/audit/constraint/commit failure produces no committed-change invalidation.
Redis invalidation failure emits `catalog_cache_invalidation_failed` with a safe
category and preserves the committed business result; the original absolute age
still bounds stale data. There is no outbox or event worker.

The Redis command budget is 100 ms in total, including pool acquisition and
connection. A transport/timeout/closed failure triggers a scoped PostgreSQL read
on the same request and opens the independent per-process catalog circuit. Reads
bypass Redis for five seconds. One subsequent real cache operation probes
recovery; concurrent requests keep reading PostgreSQL without waiting. A
successful probe restores cache use; a failed probe starts another cooldown.
Authentication has a separate three-probe recovery policy and cannot be declared
healthy from a successful catalog lookup. Startup and `/health` do not depend on
Redis; PostgreSQL is still required for authenticated business reads.

## Evidence

[Issue #27 evidence](../milestone7/verification-milestone7-issue27.md) records
the original uncached workload, cold/warm measurements, physical outage/restart
measurements, live SQL costs and the optional dashboard recommendation. These
measurements describe the recorded local workload; they are not deployment
capacity guarantees. Production dashboard caching remains deferred.
