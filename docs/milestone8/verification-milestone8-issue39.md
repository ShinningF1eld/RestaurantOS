# Milestone 8 issue #39 verification

Reviewed: 2026-10-15 (Asia/Bangkok).
Sources: [issue #39](https://github.com/ShinningF1eld/RestaurantOS/issues/39),
approved revision 1 of [the design](milestone-8-design.md), T9 in
[the task plan](milestone-8-task.md), and the user's 2026-10-15 implementation
instruction and pagination/history/polling/baseline decisions.
Comparison base: `c381323059e70654d09833a3a19c51bda45d4057`, initially clean tree.
Scope: uncommitted T9 implementation and documentation. This is the implementation
agent's review using review-verify, not an independent agent or remote CI review.
Environment: Windows, Python 3.12.13 (`backend/.venv-m6-dev`), Node 24.14.1,
installed locked dependencies, PostgreSQL 16/Redis 7 on disposable Compose services,
production Next.js 16.3.7 and Chromium. Authentication traces remain disabled.

## CI investigation, 2026-10-16 (UTC)

The push [CI run 38755497431](https://github.com/ShinningF1eld/RestaurantOS/actions/runs/38755497431)
for `8817c1a` failed only `backend-integration` (327 passed, one failed), which
also failed the aggregate acceptance check. The failure was
`test_start_real_worker_after_baseline_then_resume_business_writes` asserting
that the baseline alert's `resolved_at` was non-null. It was not the earlier
Redis cleanup timeout recorded below.

The test waited for a notification stub and two alert episodes, but those facts
do not establish that the separate baseline-resolution delivery has committed.
A controlled disposable PostgreSQL/Redis rehearsal held that delivery pending:
both original readiness checks passed with an unresolved projected baseline.
Releasing the delivery resolved that same baseline without maintenance or repair.
Ten ordinary repetitions of the original test passed, consistent with the
timing-dependent failure. The temporary ordering probe was removed afterward.

The test now waits for all retained deliveries to succeed before asserting the
same exact notification count, episode count, baseline resolution and episode
identity. No production, schema, API, dependency-lock or migration change.
On Linux/Python 3.12 with committed hash-checked dependencies, backend static
checks and 282 unit tests passed. The corrected maintenance and alert projection
suites passed all 25 tests against disposable services, followed by ten separate
passing invocations of the corrected worker-start regression. The commands include:

```bash
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-dev.txt
backend/.venv/bin/python scripts/validate.py --gate backend-static --gate backend-unit --no-install
backend/.venv/bin/python scripts/validate.py --gate backend-integration --no-install
# Within the runner's disposable services/database helpers, after upgrade head:
python -m pytest tests/integration/test_event_maintenance.py tests/integration/test_alert_projection.py -q
python -m pytest tests/integration/test_event_maintenance.py::test_start_real_worker_after_baseline_then_resume_business_writes -q
```

The full integration gate also passed: 328 tests and `alembic check` with no
new upgrade operations. That run collected tests before the synchronization edit;
the 25-test focused suite and ten regression repetitions exercised the corrected
source. All disposable database/Compose resources were removed on completion.
`git diff --check` passed.

This is partial validation; remote CI has not been rerun and no commit or push
was performed. No application database was migrated or initialized.

## Result

All six issue criteria passed implementation review and final execution. No
actionable implementation findings remain. Two complete fresh Chromium runs and
the injected-failure cleanup scenario passed. No schema, dependencies, image,
application migration/initialization, commit, push or GitHub issue changes.
Full Milestone 8 acceptance remains open for T10/T11 and complete final CI.

## Implementation and review

- `alerts/router.py` and `schemas.py` expose two GET collections under the existing
  restaurant inventory namespace. Serialization is allowlisted at the HTTP
  boundary, including lossless decimal strings and UTC timestamps. No user-supplied
  organization ID, raw ORM inspection, actor details, worker diagnostics or write
  action is exposed. Existing routes/error/session contracts are preserved.
- `AlertReadService` resolves current membership/organization/assignment using
  tenancy's public interface and requires `inventory.read` before data/count reads.
  Foreign/unassigned branches are 404; forbidden roles/revoked membership are 403.
  Reads do not invoke trusted maintenance hooks or repair derived state.
- Alert repository queries keep cross-feature joins in persistence. Active
  projection rows must match unresolved authoritative producer episodes and live
  active/low inventory. Names/quantities/thresholds are current; stale projection
  values cannot retain a recovered, archived or superseded active alert. History
  preserves immutable opening fields and records ongoing/resolved/baseline facts.
  Both collections use default 20/max 100, nonnegative offset, scoped totals and
  `opened_at DESC, episode_id DESC` ordering before pagination.
- `InventoryAlerts` and `useInventoryAlerts` provide independent active/history
  pages, collapsed history, manual refresh, initial loading/error/successful-empty
  states and marked last-known stale data/retry. Failed refreshes do not display
  empty-success messages. Baselines read “Low when tracking started.” There are
  no acknowledgement/dismissal controls or external notifications.
- Visible polling runs at 15 seconds and refreshes on return to visibility and
  successful local inventory writes. History polls only while expanded. Request
  generations and cancellation prevent obsolete responses from overwriting newer
  pages. The inventory manager also fences ingredient responses and resets scope
  by restaurant key. Access failures clear protected data and unmount polling.
  Background refresh preserves form values, focus and captured physical-count
  versions; uncertain stock writes retain existing idempotency keys.
- The browser harness starts the standalone production worker against the same
  isolated PostgreSQL/Redis resources as the API, after disposable migrations.
  Its finally block terminates/waits/kills the worker alongside the existing API
  cleanup. API/worker startup still performs no migrations.

## Criteria and evidence

| Issue criterion | Status | Evidence |
|---|---|---|
| 1. Current role/branch/tenant authorization on collections and counts | Passed (focused execution/inspection) | `test_alert_reads.py`: Owner/assigned Manager reads, unassigned/foreign 404, Employee 403, live role/assignment/membership revocation, populated scoped pages/counts. No new direct/nested ID endpoint exists. |
| 2. Live active stock and immutable paginated episode history | Passed (focused execution/inspection) | New tests cover worker-delayed opening, live deduction/name reads, recovery/supersession exclusion, opening snapshots, ongoing/baseline provenance, UUID tie-break, page boundaries, default/max/invalid parameters and other-branch exclusion. |
| 3. Inventory-page placement/history/live indicator/no dismiss | Passed | Component inspection and final-source Chromium workflows: active alerts above ingredients, collapsed paginated history with ongoing episodes, live low-stock indicators and no acknowledge/dismiss controls. Desktop/mobile editor screenshots also inspected. |
| 4. Visible 15-second/local/manual refresh; form preservation/request ordering | Passed (focused execution/inspection) | Fake-timer tests assert visible cadence, hidden suppression, visibility return, mutation token refresh, old-response rejection and editor focus/values. Initial browser workflow exercised real local stock write and refresh/error recovery. |
| 5. Loading/error/stale/empty, retry, access loss and scope change | Passed (focused execution/inspection) | Component tests cover initial failure, retained stale rows/retry, access-loss clearing and stopped polling, and previous-restaurant late response rejection. Initial browser revocation screenshot showed cleared data; its locator needed correction. |
| 6. Installed Next docs and existing transport/session behavior | Passed | Read `frontend/AGENTS.md` and installed Next docs `01-app/01-getting-started/05-server-and-client-components.md` and `01-app/03-api-reference/04-functions/use-router.md`. Browser calls reuse `apiFetch`; server access/renewal code is unchanged. Final-source full Chromium auth/SSR/session regression passed. |

## Commands and outcomes

All commands run from the root unless otherwise stated. The interpreter uses
committed installed locks; `--no-install` and selected gates are explicit partial
repository validation, not full M8 acceptance.

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-static --gate backend-unit --gate backend-integration --no-install
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-static --gate backend-integration --no-install
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate frontend-tests --gate frontend-static --gate frontend-build --gate browser --no-install
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --gate frontend-tests --gate frontend-static --no-install
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate browser --no-install
backend/.venv-m6-dev/Scripts/python.exe -m ruff check scripts/run-browser-tests.py
backend/.venv-m6-dev/Scripts/python.exe -m ruff format --check scripts/run-browser-tests.py
git diff --check
```

The browser gate above was run twice from fresh services after correcting the
locator and adding final pagination coverage. Failure-cleanup verification invokes
the production browser runner with its existing `--inject-failure` switch inside
the same disposable Compose helper (never an application database):

```python
import runpy, subprocess, sys
from pathlib import Path
sys.path.insert(0, "scripts")
validation = runpy.run_path("scripts/validate.py")
def containers():
    return set(subprocess.check_output(
        ["docker", "ps", "-a", "--format", "{{.Names}}"], text=True
    ).splitlines())
before_containers = containers()
before_copies = set(Path(".").glob(".m6-browser-*"))
with validation["services"](False) as env:
    result = subprocess.run([
        sys.executable, "scripts/run-browser-tests.py", "--inject-failure"
    ], env=env)
    assert result.returncode == 1
assert not (containers() - before_containers)
assert not (set(Path(".").glob(".m6-browser-*")) - before_copies)
```

| Check | Outcome |
|---|---|
| Backend unit | Passed: 282 tests. |
| Backend static | Passed: Ruff lint/format and mypy, 163 source files. Rechecked with final backend changes. |
| First backend integration | 326 test bodies passed; one teardown error: existing auth-key cleanup exceeded Redis's operation budget. This run failed and did not reach `alembic check`. |
| Final backend integration | Passed: 328 tests, including six focused T9 cases, followed by `alembic check` with no new upgrade operations. Fresh services; no teardown failure. |
| Baseline and final frontend tests/static | Passed: dependency/secret baseline; 10 client and 19 component tests; ESLint, Prettier and Next type generation/TypeScript. |
| Frontend build | Passed in isolated source copies. |
| First full Chromium suite | 27 passed, one new test failed because its broad alert locator matched Next's route announcer and the intended access-denied message. Corrected test scope to `main`; retained screenshot proved protected inventory data had cleared. |
| Final Chromium suites and failure-cleanup scenario | Two fresh final-source suites passed all 29 tests each (5.2m and 4.7m, zero retries). Injected assertion failed with expected exit 1; harness cleanup completed, and the wrapper confirmed no new containers or temporary source copies remained. Worker/API exit is awaited by the runner; the suite-owned database is dropped. |
| Browser harness Ruff / diff whitespace | Passed. |
| Visual inspection | Inspected desktop/mobile inventory screenshots from the existing editor journey; alerts precede ingredients and controls fit the narrow layout. Full-page captures include the existing sticky-header capture artifact. |

Earlier implementation checks also found synchronous effect-state lint errors,
unsupported Testing Library `exact` role-query options, formatting differences,
and an existing generic save-status assertion selecting the new alert-loading
status. These were corrected and the final frontend gates rerun. Initial sandboxed
Docker access and Next route type generation failed on Windows permissions;
authorized checks with required host access used only disposable test targets.
No validation used application `DATABASE_URL` as a fallback.

Local ignored logs are under `test-results/issue39-*.log`; browser outputs are
under `test-results/browser/` and may be replaced by subsequent runs. Dated
outcomes here are retained independently of those local artifacts.

## Limits

No remaining actionable findings. This review covers the final uncommitted T9
change set; it is not an independent review or remote CI result.

No application cutover was performed. The repository migration head remains
`c3d8e1f52a74`; this is not an assertion about the application's actual revision.
Legacy low-stock initialization remains the explicit T8 maintenance operation.
Alert history is asynchronous and can lag authoritative resolution. Successful UI
refresh time does not establish worker freshness. Offset pages can shift between
requests when new episodes arrive; counts/data are scoped but do not promise a
cross-request snapshot. No new cache or automatic retention/pruning is added.

Migrations/image gates are not required by this schema/image-unchanged slice.
Full ten-gate locked-install validation, final remote CI, M8 failure enforcement
and measured processing freshness remain T10/T11. Historical M8 design/task
inspection paragraphs describing no worker remain dated baseline observations;
current code and T7/T8 evidence establish the implemented dependencies.
