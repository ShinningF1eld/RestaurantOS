# Authentication API

The business URLs are unchanged but require an active session. `/health`,
`/api/test`, and OpenAPI documentation contain no private business data.

| Method/path | Behavior |
|---|---|
| POST `/auth/login` | JSON email/password; returns public user and sets cookies |
| GET `/auth/me` | Returns the active user's id, email and status |
| POST `/auth/refresh` | Consumes refresh cookie, rotates both cookies |
| POST `/auth/logout` | Revokes current family and clears cookies; idempotent |

Browser requests use `credentials: "include"`. Every POST/PUT/PATCH/DELETE must
include an allowed `Origin` and `X-CSRF-Protection: 1`. Requests with a body use
`Content-Type: application/json`. This includes login and logout. Native API
clients must supply the same headers and maintain a cookie jar. Tokens are not
returned in response JSON and must never be placed in URLs or logs.

Examples using a local account in browser developer tools (the normal UI handles
this automatically):

```javascript
await fetch("http://localhost:8000/auth/login", {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "application/json", "X-CSRF-Protection": "1" },
  body: JSON.stringify({ email, password }),
});
await fetch("http://localhost:8000/auth/me", { credentials: "include" });
```

Use variables for entered credentials; do not save real passwords in scripts.
The browser supplies Origin. Error bodies retain `{ "detail": "..." }`.
401 indicates invalid credentials/session, 403 failed request-origin checks,
422 invalid input, 429 throttling (with Retry-After), and 503 unavailable auth
storage. Invalid-password, unknown-email and disabled-account login failures
share a generic error. Auth responses are not cacheable.

Authentication uses fixed windows and atomic Redis admission. Login reserves
capacity in both normalized email/source-IP and IP-wide buckets before password
verification: 5 failures per pair per 60 seconds and 30 per IP per 900 seconds.
Wrong passwords, unknown users (with dummy verification) and disabled users count
equally. Success never clears failures; storage errors and cancellation do not
count. Reservations expire after 10 seconds. During Redis outages, process-local
quotas are 3/pair/60 seconds and 10/IP/900 seconds. All throttles, including local
capacity exhaustion, return the same generic 429 and Retry-After.

Refresh counts every client attempt against 100/IP/60 seconds, and every attempt
resolving to a known family against 10/family/60 seconds, including successful
rotation, expiry and replay. Missing/malformed/unknown tokens have no family
charge. Genuine storage errors are excluded. Local outage limits are 50/IP and
5/family per 60 seconds. PostgreSQL limiter history is retained without runtime
counter writes. Existing rotation/replay and CSRF contracts remain in force.

An 8-second operation deadline covers lookup, verification, session creation and
commit. Timeout returns generic 503 without credentials or cookies and releases
admission best effort. Cancellation discards late native verification results;
there is no lease renewal. If commit acknowledgement is delayed, an orphaned
family may persist, but its undisclosed credentials cannot be used. Normal absolute
expiry and the operator's expired-session cleanup also cover those families.
Uncertain commits produce safe structured events without account identifiers or
credentials. Cookie construction and ASGI header delivery both enforce expiry.

Local counters are bounded, independent per process and lost on restart. They do
not inherit pre-outage Redis history. Recovery probes run at most once per five
seconds per process and require three successes; surviving local buckets remain
enforced alongside Redis until natural expiry. These weaker outage guarantees and
weaker distributed guessing protection without an email-global limit are accepted.
Concurrent requests do not wait for the single probe owner. Failed operations
invalidate overlapping probe results and reset recovery stability without clearing
local history. Active entries are never evicted to make room for new identities.

Refresh reuse revokes the family, including its current access token. Independent
logins create independent families. Disabling an account rejects all of its
sessions. Rotation never extends the family's absolute expiry. A refresh whose
response is lost may require signing in again; do not retry it blindly.

Business operations additionally require an active organization membership and
role capability. See [tenancy policies](tenancy.md) for organization/branch scope,
Owner bootstrap and Employee preparation permissions.
