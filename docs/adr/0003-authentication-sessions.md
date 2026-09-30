# ADR 0003: Cookie sessions with rotating refresh tokens

- Status: Accepted
- Date: 2026-09-30

Use Argon2id for passwords, a ten-minute HS256 access JWT, and a random opaque
refresh token with a seven-day absolute session expiry. Each login creates a
session family. Persist only refresh digests and retain consumed digests until
expiry so replay revokes the family. Rotation and revocation are transactional;
replay revocation commits before returning an authentication error.

Verify JWT issuer, audience, expiry, required claims and fixed algorithm, plus
active database user/session state on each protected request. This makes logout
and account disable effective on subsequent requests without waiting for JWT
expiry. An already authorized operation can still finish.

Use host-only HttpOnly SameSite=Lax cookies: `ros_access` at `/`, `ros_refresh`
at `/auth`, both Secure in production. No token enters JavaScript storage or
response JSON. All unsafe requests require a trusted Origin and
`X-CSRF-Protection: 1`. Credentialed CORS allowlists exact origins.

Preserve server-rendered reads by forwarding only the access cookie to the
configured API. On 401, navigate through browser renewal; server components do
not rotate cookies. Serialize browser rotation across tabs with Web Locks and
recheck identity after acquiring the lock. Unsupported browsers can log in but
must log in again on expiry. A lost refresh response can require re-login;
there is no replay grace interval or automatic transport-failure retry.

Production requires a same-host HTTPS gateway for the frontend and API. Separate
hosts require a future BFF/transport decision. Development uses localhost on
ports 3000 and 8000. Do not mix localhost and 127.0.0.1.

Principal lookup uses a separate short-lived DB session, avoiding SQLAlchemy's
implicit read transaction colliding with existing command `session.begin()`.
PostgreSQL rate counters are shared across workers; a narrow adapter allows
replacement by Redis later. Issuance fails closed if limiter storage fails.

Accounts are provisioned by CLI. Public registration waits for tenant/RBAC
enforcement: milestone 3 authenticates a shared workspace, not isolated tenants.
