# Milestone 7 issue #26 verification

Date: 2026-10-10 (Asia/Bangkok). Branch: `milestone7`. Starting revision:
`aed399c6b4906f32f587a23131c2bab551f718ec`; working tree initially clean.
Source: live [issue #26](https://github.com/ShinningF1eld/RestaurantOS/issues/26),
[Milestone 7 design](milestone-7-design.md) revision **13**, T8, the roadmap,
API contracts, Redis architecture, runbooks and testing documentation.
Issue #26's revision 5 and old document path are superseded by the user's
instruction to use revision 13. Dependencies #23 and #25 are closed.

The user authorized adding missing tests and harness support and requested this
report before committing. No commit, push, PR, issue mutation, application
migration, schema change, dependency update or production-code change is part of
this pre-commit result. Performance/completion evidence under issue #27 remains
separate from T8.

## Changes and reused evidence

- Reused all existing backend unit/integration regressions and the 24 Chromium
  journeys, including tenant/assignment revocation on warm hits, live stock,
  authoritative order prices, rollback, invalidation failures, admission overlap,
  ambiguous acknowledgements, deadline/cancellation, physical outage/restart,
  memory capacity, recovery flapping and safe events.
- Added two real PostgreSQL/Redis races, one per cached list. Event barriers hold
  an old source read across a successful update and invalidation. At 9.5 seconds
  the late fill retains its original timestamp and at most 500 ms Redis TTL;
  after ten seconds a fresh read returns the committed update. Only catalog
  clocks are controlled; no sleeps establish concurrency.
- Extended the existing catalog recovery unit regression: an event holds its
  single probe while twenty overlapping menu/item cache lookups immediately
  return bypass results without issuing another Redis command or waiting for
  the probe. Services interpret these results as scoped PostgreSQL reads.
- Added a Chromium journey proving actual warm payload reuse, current stock
  after waste, disabled ordering when out of stock and committed menu/item edits.
  It uses the existing account/catalog/inventory fixtures, actual credentialed
  browser fetches and scoped test-only Redis inspection.
- Added a login UI journey for five normal failures followed by generic 429,
  physical Redis loss, three local failures followed by the same generic 429,
  existing access/refresh sessions, PostgreSQL catalog fallback, physical restart,
  three real recovery probes, healthy transition evidence, restored cache fills
  and continued enforcement of surviving local failures. Fixed windows start
  away from a minute boundary; the real five-second probes/quotas stay unchanged.
- Extracted the existing physical-outage Redis helper for reuse by backend and
  browser tests. Browser execution allocates its own nonpersistent Redis with a
  random pinned loopback port and removes only that container in `finally`.
  The browser helper reads its guarded generated `_test` database, exact cache
  keys and temporary API log event names. No production control endpoint exists.
- Updated the backend/browser regression maps. CI policy and all ten shared gate
  selections, including `Milestone 6 acceptance`, are unchanged. Auth traces stay
  disabled; existing uncertain-refresh tests are retained.

## Acceptance mapping

| Issue criterion | Status and evidence |
|---|---|
| Real PostgreSQL/Redis correctness and concurrency cases | Passed: final full run executed 223 integration and 210 unit tests; existing scenarios plus both real cache races. The extended single-flight unit regression also passed its final rerun. |
| Chromium warm edits, current stock, throttling, outage/recovery and cookie safety | Passed: final full run executed all 26 Chromium journeys, zero failures/skips/retries. Warm-cache and physical outage/recovery cases passed after correcting the login-form selector. Second fresh run also passed all 26 tests with zero failures/skips/retries. |
| Guarded resources, random ports, cleanup on failures and disabled auth traces | Passed: existing infrastructure tests, injected service/browser failure cleanup, two fresh browser successes and final owned-resource inspection; auth traces remain off. |
| Full ten-gate local validation and remote PR CI | Partially passed: all ten local gates and locked installation passed. Remote PR CI on the resulting commit is untested; prior push CI is baseline evidence only. |
| Schema/migration safeguards and no application migration | Passed: no schema change; unchanged unique head `e68d9a24b537`, no model drift, clean/seeded-legacy upgrades and prohibited-downgrade preservation passed. All validation targets are generated disposable databases. |

## Commands and results

Development backend verification, exit 0:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-static --gate backend-unit --gate backend-integration --no-install
```

Ruff lint/format (170 files), mypy (123 sources), 210 unit tests (one warning),
223 PostgreSQL/Redis integration tests (640 existing deprecation warnings), and
Alembic drift passed. This selected-gate run is explicitly partial.

Expected service-failure verification, exit 1 with owned Compose cleanup:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-integration --no-install --inject-failure backend-integration
```

The existing injected Chromium diagnostic scenario was run inside the same
`services(False)` disposable Compose context, with its yielded environment:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/run-browser-tests.py --inject-failure
```

The browser command returned the expected exit 1 (one deliberately failing
test). The wrapper checked that result, unwound the service context and returned
exit 0. JUnit/screenshot/error context were retained and diagnostic redaction ran;
the owned database, dedicated Redis, API, source copy and Compose project were
removed. Log: `test-results/issue26-injected-browser-failure.log`.

After extending the existing catalog single-flight unit regression:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-unit --gate backend-static --no-install
```

Passed, exit 0: 210 unit tests, Ruff lint/format and mypy. This final test-only
extension was made after the full run's unit stage; the separate rerun verifies
its final contents without claiming that the earlier unit stage included it.

Final full validation command, **passed, exit 0** (Windows, Python 3.12.13,
Node 24.14.1, disposable PostgreSQL 16/Redis 7):

```powershell
./scripts/validate.ps1 -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
```

| Full gate | Result |
|---|---|
| baseline | Passed: Compose config, locked dependency integrity, candidate secret scan |
| backend-static | Passed: Ruff lint/format (170 files), mypy (123 sources) |
| frontend-static | Passed: ESLint, Prettier, Next route types and strict TypeScript |
| backend-unit | Passed: 210 tests, one existing deprecation warning |
| backend-integration | Passed: 223 tests, 640 existing deprecation warnings, migrated disposable PostgreSQL/Redis, no model drift |
| frontend-tests | Passed: 10 client and 12 component tests |
| frontend-build | Passed: isolated production Next build |
| migrations | Passed: unique head, clean/seeded-legacy upgrades, preservation and prohibited downgrade guards |
| browser | Passed: 26 Chromium journeys, zero failures/skips/retries, isolated production build and resource cleanup |
| image | Passed: locked nonroot production build, content/configuration checks, startup/liveness, connection to disposable PostgreSQL and no startup migration |

Compose project `restaurantos-m6-65f67b787e4e` was removed after the full run.
The second complete fresh browser run required by `docs/testing/browser.md`
**passed, exit 0**, with 26 tests and zero failures/skips/retries (4.5 minutes;
first full-run browser execution 3.2 minutes). Its command was:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate browser --no-install
```

Compose project `restaurantos-m6-9282ede2dbad` and the dedicated Redis were
removed after the repeat. This browser-only invocation is labelled partial by the
runner and supplements the already successful full command.

Log: `test-results/issue26-browser-repeat.log`. The first successful browser JUnit
was preserved in `test-results/issue26-browser-full-run.xml` before the repeat.

Helper lint and format checks passed, as did `git diff --check`. Frontend
typecheck passed outside the filesystem sandbox; the sandbox attempt failed
because Next.js could not canonicalize the workspace path. The first full run
overlapped helper extraction and stopped at its temporary import/format findings;
these were corrected before the final full command. The initial Chromium
development run returned exit 1 with 25 passed and one selector failure; it
removed owned processes, database, source copy and Redis container.

Ignored logs: `test-results/issue28-full-validation.log` (original issue-number
typo), `issue26-backend-development.log`, `issue26-browser-development.log`,
`issue26-typecheck.log`, `issue26-injected-service-failure.log`, and
`issue26-full-validation.log`, `issue26-final-unit-static.log`, and
`issue26-injected-browser-failure.log`, `issue26-browser-repeat.log`, and
`issue26-baseline-final.log` under `test-results/`.

## Remote evidence and limits

GitHub [push run 38028742200](https://github.com/ShinningF1eld/RestaurantOS/actions/runs/38028742200)
passed all ten jobs and `Milestone 6 acceptance` at starting revision `aed399c`.
Its event is `push`, its PR list is empty, and it does not contain these local
test/harness changes. No PR-triggered run was returned for that exact revision.
It therefore does not satisfy issue #26's requirement for a complete remote PR
CI run of the final change. That criterion remains unverified until the user
reviews this result, authorizes publication and the resulting PR CI passes.
Issue #26 and full Milestone 7 acceptance must not be marked complete beforehand.

The application database was not queried or migrated for validation; its actual
revision is not inferred from the repository's migration head. Production local
memory sizing, measured caching performance and the optional dashboard decision
remain separate issue #27/deployment evidence.

The task plan's original direct-PostgreSQL/cache-free description, the root
instructions' PostgreSQL-only limiter note and ADR 0003's original fail-closed
limiter paragraph describe earlier behavior. Current code, auth/API/runbook
contracts and design revision 13 specify Redis plus stricter process-local
fallback. These historical descriptions are not treated as current behavior or
permission to change the accepted policy.

Locked `npm ci` reported six high-severity dependency advisories. No versions or
locks were changed; resolving those advisories is separate from these passing
repository gates. Existing deprecation warnings also remain. This verification
is not a new dependency-security assessment.

Final documentation/candidate secret scan command:

```powershell
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --no-install
git diff --check
```

Passed, exit 0: the final baseline command checked current candidate files and
dependency integrity; `git diff --check` passed. Independent Docker/directory/
process inspection found no remaining test Compose/outage Redis containers,
`.m6-browser-*` copies or test API/Next processes. The secret scanner itself was
excluded from process matching. Git HEAD is still `aed399c` and all changes are
unstaged/uncommitted. Final outcome: four criteria passed, one partially passed
because remote PR CI for this final change is pending. No acceptance claim is
based on a skipped gate.
