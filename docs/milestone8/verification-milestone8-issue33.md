# Milestone 8 Issue #33 / T3 verification

Date: 2026-10-12 (Asia/Bangkok).
Authority: [approved revision 1 design](milestone-8-design.md).
Issue: [#33](https://github.com/ShinningF1eld/RestaurantOS/issues/33).
Inspected starting HEAD: `6e8062b04a3a75dc21436c5af84ed6d39850c0b4`;
implementation and tests are working-tree changes, not a published revision.

## Scope and decisions

Orders, catalog and inventory append through the public event service inside
existing service-owned transactions. Existing post-commit cache invalidation
remains in place. There are no schema migrations, dependency changes, frontend
changes, new HTTP endpoints or response fields. The application database was
not migrated. Events still require the existing T1/T2 repository schema.

Order revisions advance once for genuine order-state changes, even preparation,
ready and non-status edits without lifecycle events. Same-state retries leave
the revision unchanged. Completion uses persisted totals/creation timestamps;
deletions append the next revision and immutable identity/status/total/time
before removal. Naive creation timestamps retain their explicit UTC convention.

Catalog revisions count emitted changes and are allocated from scoped retained
outbox facts under the restaurant lock. Menu writers now refresh the locked menu
before comparing changes. Item writers preserve their restaurant/item lock order.
Repeated historical-item deactivation returns the existing outcome without a
second event. Retained catalog watermarks survive entity removal; their query
cost grows with retained history, with no pruning or performance guarantee added.

The shared inventory transition writer emits resulting-state events and emits
low-stock events only on opening boundaries. It accepts one command correlation
from order acceptance, shared across every ingredient and order event; direct
service calls generate one fallback correlation per command. No-op counts retain
physical-count version/ledger behavior without state events.

Compatibility disagreement found during inspection: T2 truthfully permits a
legacy low ingredient with no episode before maintenance initialization, while
T1 rejected such an emitted resulting-state payload. T3 permits an episode-less
low snapshot with no boundary, preserving ordinary stock writes without inventing
history or notifications. Opened/resolved boundaries still require episode
identity and valid resulting state. Baseline initialization still emits no event.
See [event contracts](../api/events.md). Approved episode semantics are unchanged.

## Acceptance review

| Issue criterion | Evidence |
|---|---|
| Genuine order transitions; completion and deletion facts | `integration/test_event_producers.py`: lifecycle snapshot test changes the catalog price after acceptance and still observes the original authoritative total; completion revision/time and higher deletion tombstone revision survive row removal. Preparation/ready emit no lifecycle event. |
| Catalog/inventory triggers, episode-only low events, correlation | Catalog create/edit/delete/deactivate/no-op cases verify operation and affected identities. Episode tests cover creation, further waste while low, threshold recovery/reentry, archive/restore and stock recovery. Creation retries/mismatches, legacy state and direct-command correlation have explicit regressions. |
| Complete atomic transaction and no visible partial fan-out | Twelve combinations of acceptance/catalog/stock commands with audit/event/delivery/flush failure. Real PostgreSQL rejecting triggers inject insertion errors; delivery injection allows alerts fan-out before rejecting notification fan-out. Flush injection fails after subscribed delivery rows were flushed. Independent connections see only pre-command state during the transaction and after rollback across eleven business/history/event tables. |
| No duplicate events; existing business invariants | Read/no-op/status retry/idempotency tests inspect retained event identities. Catalog overlap tests hold the restaurant lock until another assigned user's request reaches it, then verify locked-state no-op comparison and distinct monotonic revisions. Existing tenant/role/revocation, monetary snapshot, stock/recipe locking, shortage rollback, replay/mismatch and cancellation regression suites run in the full backend integration gate. |
| API death leaves durable recoverable work; Redis/worker independence | `integration/test_event_producer_process.py` starts a real Uvicorn API with Redis unavailable, logs in through existing auth fallback, and pauses immediately after accepted order transaction commit. Parent kills the process while the HTTP response is pending. A fresh connection observes accepted order/consumption, three correlated events and all four fixed subscriptions pending with zero attempts and null publication timestamps. No worker or publisher runs. |

This crash test demonstrates the T3 durable recovery source, not execution of
later worker effects. Relay/recovery and consumers are T4–T7; full Milestone 8
crash-to-effect acceptance remains open.

## Commands and outcomes

Supported interpreter used: Python 3.12.13 in `backend/.venv-m6-dev`.
Each command runs from the repository root, uses committed installed dependencies,
and is explicitly a partial repository validation:

```powershell
./scripts/validate.ps1 -PythonExecutable backend/.venv-m6-dev/Scripts/python.exe -Gate backend-unit -NoInstall
./scripts/validate.ps1 -PythonExecutable backend/.venv-m6-dev/Scripts/python.exe -Gate backend-integration -NoInstall
./scripts/validate.ps1 -PythonExecutable backend/.venv-m6-dev/Scripts/python.exe -Gate backend-static -NoInstall
```

- `backend-unit`: passed, 262 tests, outside sandbox.
- `backend-static`: passed, Ruff lint/format and mypy (133 source files).
- `backend-integration`: passed, 257 tests; clean disposable upgrades and
  `alembic check` passed with no new upgrade operations detected. Owned test
  databases and Compose services were cleaned up.

Earlier attempts: sandbox Docker access was denied; the disposable integration
runner succeeded in starting after escalation. The initial sandbox unit run
stalled at the first asynchronous auth test, consistent with the previously
recorded Windows socketpair limitation, and was interrupted;
the same supported interpreter passed outside the sandbox. Initial integration
finished with 253 passed / one failed due to the new raw legacy test fixture
omitting required timestamps, fixed before rerunning. A later static check found
formatting after the validation-message edit; formatted that file and reran to
pass. A second integration run passed 255 tests and failed only the two new catalog
concurrency fixtures, which shared a lifespan Redis pool across separate
TestClient loops. They now share one API portal and use an asynchronous barrier,
keeping real post-commit Redis invalidation enabled. No production Redis policy
changed. These failed attempts are not acceptance evidence.

Omitted: baseline, frontend-static/tests/build, browser, migrations and image,
locked reinstall, final PR CI and full ten-gate/M8 acceptance. No frontend,
schema or image changes require those slice-specific gates. Integration performs
clean disposable upgrades and `alembic check`; no application database or
developer volume is modified. Existing deprecation warnings are retained;
no dependency upgrades were introduced to silence them.


## PR #43 baseline CI follow-up — 2026-10-12

The [initial baseline job](https://github.com/ShinningF1eld/RestaurantOS/actions/runs/38211391721/job/114686133940)
at PR head `8b6ee748de0558ea67e2f46ca8e0fde71ebf00e7` failed secret scanning:
the public Alembic revision `b8f34c2a91de` in the T2 migration and public downgrade
target `e68d9a24b537` in `scripts/verify-migrations.py` were flagged as hex
high-entropy strings. These are migration identities, not credentials. Added
only line-scoped `pragma: allowlist secret` annotations documenting that fact,
following the repository's existing migration convention. Secret scanning,
its reviewed baseline, the CI workflow and required aggregate are unchanged.

`./scripts/validate.ps1 -PythonExecutable backend/.venv-m6-dev/Scripts/python.exe
-Gate baseline -NoInstall` passed after the fix: Compose configuration,
`pip check` and the full tracked/unignored-file secret scan. The sandbox attempt
could not create its disposable temporary baseline; the same gate passed
outside the sandbox. No behavioral tests were rerun for comment-only changes.
Final CI for the follow-up commit remains to be observed; this local partial
gate does not establish complete PR or Milestone 8 acceptance.
