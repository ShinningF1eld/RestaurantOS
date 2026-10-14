# Daily completed-sales projection

Issue #36 implements the analytics consumer from the approved Milestone 8 design.
Existing dashboard routes still query live orders; no HTTP contract or frontend
changes. This projection is eventually consistent and operator-facing.

`order.completed.v1` replaces the order contribution only at a newer revision.
`order.deleted.v1` removes a contribution and retains a terminal revision
tombstone, including when deletion arrives first. An equal/older revision is
receipted as `skipped`; receipt-checked redelivery does not run the effect again.
Creation timestamps are interpreted as UTC and grouped by creation date, exactly
as current naive-UTC order SQL, rather than completion date or restaurant timezone.
Individual totals use `Numeric(10,2)`; daily sums use `Numeric(20,2)`.

`analytics_order_contributions` retains organization, restaurant, order identity,
revision, creation date, total and state (`completed`, `inactive`, `deleted`). It
has no order FK, so permitted deletion cannot erase its watermark.
`analytics_daily_sales` stores counts and sales keyed by restaurant/creation date.
Both tables enforce the restaurant/organization pair with restrictive composite
FKs; nonnegative money/counts and valid revisions/states have database checks.
Empty daily rows may remain after deletion; reconciliation treats an absent SQL
date as count/sales zero. No automatic pruning is introduced.

The execution service owns the transaction: contribution, daily deltas, receipt
and successful delivery commit together before Redis ACK. The handler shares
the restaurant write lock, serializing branch projection updates, including
different orders and first daily-row inserts. This conservative strategy trades
branch concurrency for simple correctness; no performance improvement is claimed.

Trusted operator commands from `backend/`:

```text
python -m app.modules.events.cli analytics-inspect --organization-id UUID --restaurant-id ID
python -m app.modules.events.cli analytics-reconcile --organization-id UUID --restaurant-id ID
```

Inspection returns daily rows plus contributions/tombstones. Reconciliation
returns `matches` and date-level discrepancies with authoritative/projected count
and lossless sales strings. It compares the full retained range for one verified
scope pair under the restaurant lock; it does not repair data. Database credentials
provide operator authority; these commands are not exposed to browser users.
Customer names, notes and raw payloads are not returned.

`AnalyticsProjectionService.rebuild(organization_id, restaurant_id)` in analytics'
public `service.py` is the maintenance seeding/rebuild interface for T8. It owns
one transaction and the shared restaurant lock. Stop workers and quiesce business
writes before calling it. It reconstructs daily totals, seeds all current orders'
revision watermarks (including noncompleted orders), and seeds deletion tombstones
from retained producer deletion facts. Existing missing-order tombstones survive;
missing nondeleted contributions without deletion facts abort rather than silently
losing protection. Receipts, events, attempts and deliveries remain unchanged.
Queued old events cannot double count the seeded contribution or undo its revision.
Repeated rebuilds are safe. The combined initialization/provenance/CLI workflow
remains T8; this issue does not expose an unattended rebuild command.

Additive migration `a936d8e4c021` follows `b8f34c2a91de`, creates empty projection
tables without rewriting business data, and rejects downgrade if either table
contains retained data. Apply application migrations only through the explicit
backup/maintenance procedure; validation migrates disposable databases only.
