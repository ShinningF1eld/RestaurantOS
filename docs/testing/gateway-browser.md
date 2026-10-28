# Chromium through the HTTPS container gateway

Run from the repository root after installing committed dependencies:

```powershell
backend/.venv/Scripts/python.exe scripts/run-gateway-browser-tests.py
```

Linux uses `backend/.venv/bin/python`; local Docker's Linux engine, Node 24,
installed Playwright Chromium and `ip` are required. Each run creates a unique
`.local-gateway/browser-<id>` directory and Compose project, builds both images,
explicitly migrates only its new synthetic DB and starts six containers. It does
not use the persistent rehearsal or developer DB. No product endpoint, schema,
session policy or authentication bypass is added.

## Matrix

| Case | Assertion |
|---|---|
| Certificate negative control | Fresh Chromium rejects the CA without the scoped key exception |
| Cookies and request boundary | HTTPS secure context; host-only HttpOnly/Secure/Lax cookies at `/` and `/backend/auth`; missing-CSRF logout rejected |
| Actual JWT expiry | Trusted fixture re-signs existing synthetic access claims with past expiry; SSR passes through browser renewal exactly once; SSR sets no cookies |
| Concurrent tabs | Two prepared tabs reload expired access concurrently; Web Locks produce one refresh |
| Tenant isolation | Warm A/B API, initial HTML, explicit RSC and client navigation; foreign IDs remain scoped and markers do not leak |
| Revocation | Warm Manager assignment removal and membership revocation affect subsequent API/SSR reads |
| Lost refresh response | Refresh actually commits; returned cookies are discarded, old browser cookies restored, transport aborted; recovery UI does not automatically replay |
| Identity/history/profile | Logout A, login B, Back/Forward, full-document BFCache attempt and reopening a persistent profile do not restore A's protected marker |
| Log privacy | Observed generated credentials/cookies remain absent from DOM/JS storage and application logs before and after restart |
| Controlled peers | Distinct edge peers A/B plus untrusted internal peer C preserve real peer/resolved identity under forged forwarding/host/protocol headers |
| Quotas and restart | Five failed-login pair attempts bind A while B retains allowance; 100 refreshes across ten families bind A's IP while B retains allowance; repeated after down/up in unchanged fixed windows |
| Durable worker effect | A precise menu event retains one receipt joined to its durable diagnostic effect across restart, alongside session/data/certificate identity |

User creation calls the existing CLI function through trusted Docker exec.
Organizations, catalog and staff operations use real authenticated HTTP. Signing
secrets never leave the container; synthetic JWT output goes only to test memory.
Lost-response interception models
discarded delivery after a real commit; cookie restoration accounts for
Playwright's internal request jar accepting headers the simulated browser lost.
No mocked authorization, SQLite, lowered quotas or shortened session settings.

## TLS and sensitive artifacts

Node strictly validates the generated certificate chain and localhost hostname
using the exported CA, then derives the leaf key's SHA-256 SPKI. Chromium uses an
exception for that exact key with `ignoreHTTPSErrors: false`. There is no global
certificate-error switch or host trust-store installation. The negative control
is required, and strict TLS is checked again after restart. This scoped test
exception does not prove native browser trust-store setup. See Chromium's
[certificate verifier](https://chromium.googlesource.com/chromium/src/+/bff9ec6/services/network/ignore_errors_cert_verifier.h).

Temporary `sitecustomize.py` and a Compose override observe the unchanged real
`client_ip` function. They are mounted only into the disposable API, never copied
into images or activated by normal rehearsal startup. The observer returns the
original result and changes no authorization/admission decision. Peer addresses
remain ephemeral; reports retain only A/B/C labels and comparison booleans.

No traces, HAR, storage-state exports, raw browser call logs or screenshots are
retained. Private browser profiles hold ordinary cookies during the run and are
removed afterward. Reports in `test-results/gateway-browser/browser-<id>/` contain
safe case status, observations and explicit limitations. Fixed failure labels
prevent Playwright error text from echoing credential input.

## Cleanup and enforcement

The runner removes its own containers, networks, database/certificate volumes
and profiles on success/failure; verifies absence; then writes `cleanup.json`.
Built images/cache may remain. Cleanup rejects the persistent rehearsal,
redirects and paths outside the checked run root. A timeout stops the owned
Node/Chromium process tree.

```powershell
backend/.venv/Scripts/python.exe scripts/run-gateway-browser-tests.py --inject-failure
```

This deliberately returns 1 after the real cookie case. The report must name
`intentional failure` and cleanup must succeed. The shared `browser` gate requires
the existing host workflows and cleanup probe, the container matrix and its
verified failure probe. All ten gate names and `Milestone 6 acceptance` remain
unchanged. New-head remote CI remains separate evidence. Static gates check the
runner and JavaScript syntax/formatting; unit regressions cover unsafe targets,
resource leaks, early failure and false-pass paths.

## Limits

Reports record actual `pageshow.persisted` events. Zero means history/profile
checks passed without proving restoration from BFCache; that limitation is kept.
Full-document navigation is attempted with Playwright's default BFCache-disabling
argument removed. Local A/B peers are not two public egress addresses. Native ARM,
host reboot, actual public egress separation, alternate browsers and cloud
capacity/recovery remain untested. These checks do not establish full S1/M9 acceptance.
