# Browser journey matrix

Playwright runs Chromium against real API authentication and tenant-scoped
PostgreSQL data using a production Next.js build. The component/client suite is
excluded from Playwright discovery. Retries are disabled so failures remain visible.

| Journey | Executable coverage |
|---|---|
| Sign in, deep link, reload, invalid return destinations | `auth.spec.ts` anonymous deep-link, reload and external-return tests |
| Expired SSR access, concurrent requests/tabs, bounded renewal, logout/revocation and outage distinctions | `auth.spec.ts` renewal/session/logout cases |
| Owner restaurant selection and switching with separate order data | `journeys.spec.ts` owner-switching case |
| Assigned manager order creation, restricted owner controls and unassigned branch rejection | `journeys.spec.ts` assigned-manager case |
| Employee kitchen transitions, hidden forbidden controls and actual API denial | `auth.spec.ts` employee kitchen and inventory cases |
| Another tenant's restaurant absent from lists, rejected by API and SSR route | `journeys.spec.ts` other-tenant case |
| Orders, stock shortage, accepted consumption once and cancellation without restocking | `order-inventory.spec.ts` lifecycle/stock case |
| Lost order response, duplicate submission and original idempotent result | `order-inventory.spec.ts` committed-write retry case |
| Recipe validation, saving and stock calculations | `recipes.spec.ts` recipe case |
| Inventory edits/history, waste/count/refresh/archive/restore and idempotent lost-response retries | `auth.spec.ts` inventory cases |

## Isolated execution

Set an explicit `TEST_DATABASE_URL` ending in `_test` on the documented local or
CI host, then run `python scripts/run-browser-tests.py` using the backend test
environment. The supplied database is only a template. The runner allocates and
migrates a random database, copies frontend source without `.env` files, uses
random API/web ports, and sets the same API address at build time and runtime.
The API starts from the temporary workspace with the backend on `PYTHONPATH`,
so application settings cannot fall back to the developer's backend `.env`.
The original `.next` output and developer servers are untouched.

The source copy shares installed dependency files through a junction on Windows
and a symlink on Linux. Its cleanup removes the link itself before removing the
verified temporary workspace. The runner owns only its API child process;
Playwright owns its isolated frontend process. Both unwind on test failure,
and the database context verifies that its generated name was dropped.

## Diagnostics and failure verification

Root `test-results/browser/results.xml` retains a JUnit summary. Failure
screenshots are retained under `test-results/browser/screenshots/`. CI uploads
these available artifacts even on failure. Auth traces remain disabled because
they capture cookies/passwords. Seed credentials are random disposable values,
passed via stdin rather than command-line arguments, and SQL parameters are hidden.
The runner redacts generated test passwords, JWTs, opaque refresh tokens and its
runtime configuration from console diagnostics and retained text reports.

`python scripts/run-browser-tests.py --inject-failure` adds a failing test only in
the temporary source copy. It must return nonzero, produce summary/screenshot
evidence and remove its processes, source copy and database. `--grep` is an explicit
partial suite and does not count as complete browser acceptance.

Verification requires two complete runs from fresh state plus the injected
failure scenario. Dated execution evidence is recorded in the milestone review.

On 2026-10-06, two fresh Chromium runs each passed all 24 tests with zero retries,
failures or skips. The injected diagnostic failure returned exit code 1 and
retained JUnit, a screenshot and error context. Independent checks found no
remaining browser databases, temporary source directories, or owned API/Next
processes after these runs. A generated-value probe also verified diagnostic
redaction without printing the values.
