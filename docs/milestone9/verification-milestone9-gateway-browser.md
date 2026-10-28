# Milestone 9 S1 step #4: HTTPS Chromium matrix

Date: 2026-10-28 (Asia/Bangkok). Source starts at `47535d1`; changes were verified
locally and the user authorized committing them. No push, cloud provisioning, public deployment or machine trust
installation. This is local browser verification inside S1, not M9's S4 backup slice.

## Implementation

`scripts/run-gateway-browser-tests.py` owns a fresh marked browser state/project,
builds the real backend/frontend images, migrates only its synthetic PostgreSQL
database, starts the production container stack and invokes
`scripts/gateway-browser.mjs`. `local-gateway.py` now permits strictly named private
browser subdirectories and confines test instrumentation to those disposable
states. Path checks occur before initialization and destructive cleanup; private
state/profiles, containers, networks and volumes are verified removed on exit.
Built images/cache may remain. The persistent rehearsal and developer DB are not used.

The matrix covers actual JWT expiry/SSR renewal, shared-tab serialized rotation,
lost response after committed refresh, A/B tenant markers in API/HTML/RSC/client
navigation, warm assignment/membership revocation, account switching/history and
reopened browser profile, restart persistence and exact worker receipt, credential
privacy and controlled local client identity/admission before/after restart.
The [matrix guide](../testing/gateway-browser.md) describes assertions and fixtures.

Fixtures use existing CLI/services through trusted Docker exec and authenticated
HTTP. No production routes, auth bypass, weakened quota/session policy, business
behavior, frontend product code, dependencies or schema changed. Temporary IP
observation wraps and returns the unchanged real resolver. Reports retain only
client labels/comparison booleans, safe case status and limitations.

Strict Node TLS chain/hostname verification supplies a generated leaf-key pin.
Chromium uses that scoped key exception, with blanket HTTPS ignoring disabled;
an unconfigured browser must reject the CA. This is explicitly not proof of native
browser trust-store setup. Credentials/cookies stay out of traces, HAR, reports,
DOM and JS storage; known observed values are checked against runtime logs before
and after restart. Private ordinary browser cookie profiles are deleted afterward.

The shared browser gate now requires both existing host workflows/cleanup and
the new gateway matrix/cleanup probe. Ten gate names, workflow and `Milestone 6
acceptance` aggregate are unchanged. Unit policy tests reject unsafe paths,
instrumentation in persistent state, early failure, false pass and leaked resources.
No remote new-head CI or repository-rule proof was performed.

## Commands and evidence

Windows host Python 3.13.15/Node 24; application images use supported Python 3.12
and Node 24. Existing installed locks were used; installation was omitted.

| Command | Result |
|---|---|
| `backend/.venv/Scripts/python.exe scripts/run-gateway-browser-tests.py` | First run passed certificate/cookie/expiry cases, then hit the intentional 15-second renewal guard because the test reused one tab for two artificial expiries; owned cleanup passed |
| Same command after separating concurrency sessions | Passed the initial 11-case matrix, including controlled peer/quota assertions; owned cleanup passed; BFCache persisted count was zero |
| `./scripts/validate.ps1 -Gate baseline,backend-static,backend-unit,frontend-static,frontend-tests,frontend-build,browser -NoInstall` | Passed baseline/static, 366 units, frontend suites/build, 29 existing Chromium workflows, 13 gateway cases and both verified failure-cleanup probes |
| `./scripts/validate.ps1 -Gate backend-static,backend-unit -NoInstall` | Final path-guard follow-up passed: static and 367 unit tests |
| `backend/.venv/Scripts/python.exe scripts/run-gateway-browser-tests.py` final targeted follow-up | Passed all 13 cases with alternating single/chained forwarding headers and receipt joined to durable diagnostic effect, before/after restart; runtime resources/profiles removed |
| `./scripts/validate.ps1 -Gate baseline -NoInstall` final evidence follow-up | Passed dependency integrity, Compose configuration and candidate-file secret scan after the sanitized evidence was saved |
| JavaScript syntax/Prettier and changed Python Ruff checks; `git diff --check` | Passed |

Safe reports live under ignored `test-results/gateway-browser/browser-<id>/`.
The sanitized final matrix, negative probe, cleanup markers and initial fixture
failure are retained in [dated JSON evidence](evidence/gateway-browser-2026-10-28.json).
An intentional-failure run must return 1, report `intentional failure`, and retain
a positive `cleanup.json` marker after verified teardown; an earlier unrelated
failure cannot satisfy the cleanup gate.

## Remaining limits

The final matrix recorded zero `pageshow.persisted` events after the explicit
full-document attempt with Playwright's disabling argument removed. Actual BFCache
restoration therefore remains unverified; Back/Forward, account switching and
restored-profile access passed. No inference from private/no-store headers
substitutes for that observation.

Controlled local peers are not two public egress addresses. Native ARM, host reboot,
native browser trust-store configuration, other browser engines and actual OCI
capacity/recovery remain unverified. Backend-integration, migrations and image
gates were omitted in this task because backend product/schema/image sources did
not change; the new matrix itself builds/runs images and migrates a fresh isolated
database. This is partial validation, not full S1 or M9 acceptance. Historical
performance or CI passes do not establish this head's acceptance.
