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

Refresh reuse revokes the family, including its current access token. Independent
logins create independent families. Disabling an account rejects all of its
sessions. Rotation never extends the family's absolute expiry. A refresh whose
response is lost may require signing in again; do not retry it blindly.

Business operations additionally require an active organization membership and
role capability. See [tenancy policies](tenancy.md) for organization/branch scope,
Owner bootstrap and Employee preparation permissions.
