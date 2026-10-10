# Milestone 7 issue #23 verification

Reviewed: 2026-10-08 (Asia/Bangkok), independent review of current code.
Branch: `milestone7`.
Reviewed HEAD: `004f95c965a32666bce15b0dc3ed3622be4640aa`
(`docs: record final issue 23 verification`). Working tree was clean before review.
Comparison base: `1d97a18` (before T5 implementation); current behavior was also
inspected directly rather than inferred only from the diff.
Environment: Windows, Python 3.12.13, installed development environment
`backend/.venv-m6-dev`; disposable PostgreSQL 16 and Redis 7 supplied by the
repository validation runner.

## Result

All five **approved T5 acceptance criteria pass**, using code inspection and fresh
execution of the three required backend gates. No business correctness regression
was found in the reviewed catalog invalidation paths. The review found a
diagnostics defect (F1): production JSON omitted the invalidation event name and
failure category. The authorized follow-up now preserves those safe fields and
catalog circuit diagnostics; see the resolution below. A generic warning was
always observable, so F1 did not fail T5's minimum safe-warning requirement.
This review does not certify an absence of every possible unwanted behavior.

The published issue and approved design also differ in their cache scope. These
qualifications must accompany any acceptance claim; full Milestone 7 acceptance
is not established by this review.

## Sources and scope

- [GitHub issue #23](https://github.com/ShinningF1eld/RestaurantOS/issues/23),
  fetched during this review: open, all five boxes unchecked, no comments.
- [Milestone 7 design](milestone-7-design.md), approved revision 12: R1/R3/R4,
  accepted cache endpoints, post-commit invalidation matrix and absolute age.
- [Milestone 7 task plan](milestone-7-task.md), T5 and dependency T4 (#22).
- This existing report, README, `docs/current-state.md`, master roadmap,
  root engineering instructions, ADR 0002, Redis architecture, tenancy/recipe
  contracts and repository testing procedures.
- Current catalog service, routers, cache, repository and response contracts;
  Redis adapter/lifespan, transaction teardown, JSON logging; affected unit,
  catalog/tenancy/transaction integration and order/inventory concurrency tests.

The issue's first criterion says “covering list and detail payloads.” Revision 12
explicitly caches only `GET /restaurants/{restaurant_id}/menus` and
`GET /menus/{menu_id}/items`. `GET /menus/{menu_id}` and
`GET /menu-items/{menu_item_id}` use scoped PostgreSQL reads, with no cache keys.
The local T5 task text reflects this narrower approved scope; GitHub still has
the older wording and old document paths. AC1 below passes against the approved
scope, not an invented detail-cache implementation. Aligning the remote issue
wording is a follow-up documentation action; this review made no GitHub changes.

## Acceptance mapping

| ID | Approved criterion | Result | Current evidence |
|---|---|---|---|
| AC1 | Invalidate only affected keys after successful commit for all mutations of the two cached lists | Passed | Inspection: every catalog mutation calls its invalidation helper after leaving `async with session.begin()`. Executed `test_committed_catalog_mutations_invalidate_only_their_list_keys` covers menu create/update/delete and item create/update/hard-delete/deactivation with real Redis, then verifies current list responses and a retained unrelated key. Unit coverage verifies targeted `DEL`; menu deletion sends its two keys in one command. Detail endpoints remain uncached. |
| AC2 | Audit/flush/constraint/commit failure rolls back without invalidation; Redis failure cannot fail a committed business write | Passed | Executed audit-failure and commit/flush-failure menu-update regressions confirm unchanged PostgreSQL detail data, retained cache and zero `DEL` commands. The Redis command-failure create regression confirms HTTP success and persistence through an uncached detail read. Unit invalidation cases cover timeout, connection and command failure; the adapter also classifies closed-client failure. All share the same post-commit helper. |
| AC3 | Both `delete_menu_item` outcomes invalidate after commit | Passed | Inspection: both branches assign an outcome and join the same post-transaction invalidation call before returning. Executed HTTP/Redis regression exercises hard deletion and historical-item deactivation, verifies key removal and `is_available=false`, and preserves the historical order's name and `7.40` price. |
| AC4 | An old fill racing invalidation cannot extend the accepted source age; failed invalidation is safely observable | Passed; F1 resolved in follow-up | Executed event-controlled unit cases cover both list types: a delayed `SET` follows `DEL` and retains only 500 ms of its original source-age budget. Separate out-of-order fills write 9,900 ms then 500 ms; slow fills are discarded and expired payloads are misses. Inspection confirms both hit validators reject age >=10 seconds. The original review reproduced omitted JSON event/category fields; the authorized fix and formatted-output regressions now preserve those diagnostics. |
| AC5 | Preserve fixed-precision prices, immutable snapshots and inventory/order locks; add no worker/outbox | Passed | Executed catalog price, snapshot, authoritative order-price and inventory/order suites pass. PostgreSQL concurrency cases coordinate actual overlap at the restaurant lock for competing acceptances, receipt/waste/count and recipe replacement. Order/ingredient lock implementation is unchanged by T5; catalog item update/delete retain their restaurant/item locks. The compared changes contain no migration, worker, event or outbox. |

Coverage: **5 Passed, 0 Failed, 0 Untested for the approved T5 criteria**.
This is criterion-level evidence, not exhaustive execution of every failure type
against every mutation. AC2's `IntegrityError` is injected at repository flush and
its commit exception at SQLAlchemy `before_commit`; those tests do not simulate
a real network failure during PostgreSQL commit. Separate existing integration
tests exercise actual database price constraints.

The race proof is at the cache boundary using fake Redis and controlled clocks,
with explicit source timestamps and event-controlled command ordering. It is not
an end-to-end concurrent PostgreSQL-read/commit/Redis-fill experiment. Real
PostgreSQL/Redis mutation tests and the service's transaction placement supply
the complementary evidence. Cache hits validate the embedded source age as well
as relying on Redis TTL; physical key expiration alone is not the entire bound.

Recipe/tracking and stock writes need no catalog invalidation: tracking,
out-of-stock and available portions are read live. Executed warm-cache regressions
cover receipt, waste, count, acceptance consumption and recipe changes, alongside
fresh membership/assignment checks, cross-tenant isolation and deleted resources.

## Findings

### F1 — P3: production JSON logs drop the invalidation event and failure category (resolved)

Locations: `backend/app/modules/catalog/menu_cache.py:104-119` and
`backend/app/core/logging.py:11-28`; production wiring at `backend/app/main.py:44`.

Original trigger: a classified Redis failure during post-commit `DEL`. `invalidate()` adds
`event=catalog_cache_invalidation_failed` and `failure_kind` to the log record.
`JsonFormatter` allowlists only HTTP metadata in addition to its standard fields,
so neither diagnostic field reaches stderr. The existing cache tests inspect
`caplog.records`, which proves the fields exist before formatting and misses this
production-output gap.

A read-only probe executed `CatalogMenuCache.invalidate()` with an injected
`RedisFailure(FailureKind.CONNECTION)`, captured the resulting record and passed
it through the actual `JsonFormatter`. Assertions confirmed the record contained
both fields, the formatted JSON contained neither, and the test key was absent.
The emitted message was `Catalog cache invalidation failed`, with WARNING level,
logger, timestamp and request ID. Thus failure remains safely visible, but
structured filtering and distinguishing timeout/connection/command failures are
unavailable. Circuit transition extras such as reason/process/duration encounter
the same formatter limitation; that behavior predates T5.

Suggested correction: allowlist these specific safe operational fields and add
a regression against formatted JSON while continuing to exclude arbitrary extras,
keys, credentials and payloads. Do not enable indiscriminate extra-field logging.
The formatter is unchanged from the comparison base; T5 introduces the affected
invalidation event. No implementation or tests were modified during the original
review; the subsequent authorized fix is recorded below.

For a minimal reproduction, pipe the following Python into
`.venv-m6-dev/Scripts/python.exe -` from `backend/`:

```python
import json
import logging
from app.core.logging import JsonFormatter
record = logging.LogRecord('app.modules.catalog.menu_cache', logging.WARNING,
    'verification', 1, 'Catalog cache invalidation failed', (), None)
record.event = 'catalog_cache_invalidation_failed'
record.failure_kind = 'connection'
payload = json.loads(JsonFormatter().format(record))
assert payload['event'] == 'catalog_cache_invalidation_failed'
assert payload['failure_kind'] == 'connection'
print(payload)
```

The original probe asserted absence of these fields. This updated reproduction
asserts their presence after the fix.

## Original review verification

Commands ran from the repository root with the existing installed environment.
No dependencies were resolved or lockfiles changed.

| Command/procedure | Result |
|---|---|
| `backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-unit --gate backend-static --no-install` | Passed, exit 0: 188 unit tests, 1 Starlette deprecation warning; Ruff lint, Ruff format check (160 files), mypy (122 sources). |
| `backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-integration --no-install` | Passed, exit 0: 201 tests, 636 Starlette/datetime deprecation warnings; disposable upgrade through `e68d9a24b537`; `alembic check`: “No new upgrade operations detected.” |
| Read-only invalidation-to-`JsonFormatter` probe, Python stdin from `backend/` | Confirmed F1 with the real formatter and injected Redis connection failure; no network/database call. |
| `git diff --check` | Passed before and after rewriting this report. |

Docker access required execution outside the restricted sandbox. The initial
sandboxed unit run and asynchronous logging probe stalled and were interrupted;
their successful reruns outside the sandbox supplied the results above. The
sandbox stalls are environment limitations, not asserted application defects.

The integration runner allocated Compose project
`restaurantos-m6-a753467f7630` with random ports and a guarded disposable test
database. Its final output confirms removal of both containers and its network.
Only the owned test database was migrated; the application database was not read,
migrated or used by validation. Generated coverage remains in ignored locations.

## Limits and review changes

Frontend tests/static/build, Chromium, clean/seeded-legacy migration rehearsal,
image, baseline/secret gate, remote CI, benchmarks, physical Redis restart and
full ten-gate validation were **Untested in this review**. They are not required
by T5's three-gate verification instruction and must not be inferred from these
passes. Full Milestone 7 limiter, recovery and performance acceptance remains
separate work.

Invalidation failure or an old fill can still expose stale catalog fields within
the accepted 10-second source-age window; this is approved behavior, not an
immediate read-after-write guarantee. Orders retain authoritative PostgreSQL
prices/stock and immutable historical snapshots.

The original review rewrote only `docs/milestone7/verification-milestone7-issue23.md`.
No new verification report, source fix, schema/API change, commit, push or remote
issue update was performed during that review. The published-issue/design wording
discrepancy remains for the user to edit on GitHub.

## Authorized logging fix — 2026-10-08

The user requested fixing F1, committing the changes and pushing to `milestone7`.
The fix extends `JsonFormatter`'s explicit allowlist with `event`, `failure_kind`,
`process_id`, `reason` and `duration_seconds`. Arbitrary extra fields, cache keys,
Redis URLs and secret fields remain excluded. There is no schema/API, transaction,
cache policy or dependency change.

Existing regressions now inspect the actual formatted JSON for all three
invalidation failure categories, and actual catalog circuit open/recovery records
verify process identity, safe reason and deterministic duration. The formatter
regression also verifies that private key/URL/secret extras remain excluded.

Follow-up command, from the repository root:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-unit --gate backend-static --gate backend-integration --no-install
```

Passed, exit 0: 188 unit tests (1 existing deprecation warning), Ruff lint/format
(160 files), mypy (122 sources), and 201 PostgreSQL/Redis integration tests
(636 existing deprecation warnings). The runner upgraded only its disposable
database and `alembic check` reported no new upgrade operations. Both containers
and network for `restaurantos-m6-316c3cee707c` were removed successfully. F1 is
resolved with formatted-output evidence. The omitted gates listed above remain
omitted; this is partial validation, not full milestone acceptance.

This follow-up changes only the formatter, two existing unit test files and this
report. The user authorized commit/push to `milestone7`; GitHub issue edits remain
with the user. No application database migration or change was performed.
