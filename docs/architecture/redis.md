# Shared Redis infrastructure

Milestone 7 T3 implements transport only, following approved design revision 12.
`app/redis/adapter.py` owns a redis-py asyncio client/pool. FastAPI lifespan
allocates it once as `app.state.redis`, reuses it across requests, and closes it
on shutdown. Pool construction performs no network I/O and startup does not PING,
connect or migrate PostgreSQL. `/health` remains process liveness during outages.
The adapter has no shared health boolean or business cache/limiter policy.
Overlapping test lifespans track their active adapter owners so out-of-order
shutdown cannot restore a closed pool. A short lifecycle lock protects only
in-memory ownership changes; no Redis I/O occurs while holding it.

The catalog menu-list consumer owns a separate per-process outage circuit in
`app/modules/catalog/menu_cache.py`; authentication owns its separate degraded
state in `app/modules/auth/rate_limit.py`. A successful cache operation does not
establish health for another use case.

Auth selects the adapter owned by the current lifespan's event loop, avoiding
cross-loop sockets in overlapping test clients. Requests without an opened
adapter enter the same local policy as a closed Redis transport. The pool remains
lifespan-owned; no limiter-specific pool is introduced.

## Configuration and deadline

Settings declares `REDIS_URL` as `SecretStr`, accepting `redis://` and TLS
`rediss://` with an optional database number. Query options and fragments are
rejected to prevent URL overrides of transport guards. Use TLS/credentials in
shared environments; the localhost default is only for development.

`REDIS_OPERATION_BUDGET_MS` defaults to 100 and accepts positive integers no
greater than 100. One outer `asyncio.timeout` surrounds the complete attempted
command, including pool acquisition, DNS, connect, handshake, send and response.
Driver socket/connect guards each use the same value but do not extend the outer
deadline. Driver retries and maintenance notifications are disabled. The
nonblocking pool is capped by `REDIS_MAX_CONNECTIONS` (default 20, range 1–1000);
pool exhaustion is a connection failure rather than an unbounded queue.
As with all asynchronous deadlines, cancellation is scheduled by the event loop;
blocking the loop can delay scheduling. No synchronous Redis client is used.

The adapter preserves bytes, missing keys (`None`) and command results without
payload parsing. `RedisFailure.kind` distinguishes `timeout`, `connection`,
`command` (server rejection) and `closed` (lifecycle misuse). Exceptions contain
only the category and retain no raw exception context. Cancellation propagates.
Connection/timeout failures may have completed a write: future use cases must
own idempotency/recovery and must not blindly retry ambiguous commands.
Malformed JSON and application schema errors belong to callers, not transport.
Shutdown also has a bounded close and reports only a safe category on failure.

The adapter never logs URLs, commands, keys or values. Do not log raw settings
validation `errors()` input, driver exceptions, client/pool repr or connection
kwargs. Settings repr/JSON redact the secret URL; string validation diagnostics
hide inputs. Catalog circuit transitions log only process identity, safe failure
category and degraded duration.

## Keys and validation ownership

`adapter.namespace(use_case, version)` returns `restaurantos:{env}:{use_case}:vN:`.
In test mode it includes `REDIS_TEST_NAMESPACE` before the use case. Callers append
verified safe identifiers; future auth callers must reuse normalized identifier
HMAC protection rather than append raw emails, IPs, cookies or tokens. Catalog
caches `GET /restaurants/{restaurant_id}/menus` under
`restaurantos:{env}:catalog:v1:org:{org_uuid}:restaurant:{restaurant_id}:menus`
and `GET /menus/{menu_id}/items` under
`restaurantos:{env}:catalog:v1:org:{org_uuid}:menu:{menu_id}:items`.

That endpoint resolves current membership, branch assignment, restaurant scope
and `menu.read` before any Redis access. It stores typed menu fields only, with
source-read start time in the payload. The TTL is the remaining portion of the
10-second absolute age after the PostgreSQL read and serialization; hits never
renew it. The menu-list response contains no stock or recipe availability fields.
Corrupt/schema-invalid/expired entries are misses. A Redis timeout or connection
failure falls back to the scoped PostgreSQL query and opens the catalog-only
circuit; reads bypass Redis during a five-second cooldown, then one real cache
operation probes recovery while concurrent requests continue through PostgreSQL.

The item-list endpoint checks current membership, assignment, menu existence/scope
and `menu.read` before Redis. Its payload contains only menu-item IDs, parent IDs,
name, description, fixed-precision price and `is_available`. Inventory tracking,
out-of-stock state and available portions are read from PostgreSQL on every
request, including cache hits. If a cached item is absent from that live read,
the endpoint reloads the scoped list. Both list caches validate the same absolute
age and use the catalog-only outage circuit. Menu create/update invalidates only
the restaurant menu-list key; menu deletion also invalidates that menu's item-list
key. Item create/update/hard-delete/deactivation invalidates only its parent menu's
item-list key. These targeted `DEL` commands run after the service-owned database
transaction commits, never inside it. Classified Redis failures emit a structured
warning without exposing keys and cannot change the committed business result or
open the catalog read circuit. Recipe/tracking and inventory stock changes do not
invalidate catalog keys because their availability fields are read live.

A fill already reading PostgreSQL when a write commits may repopulate a deleted
key afterward. Its `SET PX` still uses only the remaining portion of the original
10-second source-read age, for both list types; invalidation does not change the
bounded-staleness policy.

The validation runner discovers random loopback Redis ports from its unique
Compose project and passes explicit runtime settings into tests and browser API
processes. External CI services require explicit `TEST_REDIS_HOST/PORT`.
`test_support/redis_environment.py` overrides ambient developer settings and
generates an opaque run namespace. Service tests additionally use unique key
suffixes, delete only their exact owned keys in `finally`, and retain short TTLs
as an outage safety net. They test cleanup after success and injected failure
without deleting a sentinel key. Compose removes only its owned project in
`finally`, including an injected gate failure. PostgreSQL disposal guards remain
unchanged. No `FLUSHDB`, `FLUSHALL` or global wildcard deletion is used.

Unit tests use injected async clients and the existing socket-blocking fixture.
Real Redis tests run under `backend-integration`; image smoke deliberately points
at unavailable Redis to prove boot/liveness without automatic migrations.
Normal developer `docker compose down` retains `postgres_data`; local Redis has
no persistent volume. `docker-compose.test.yml` remains disposable and unchanged.
