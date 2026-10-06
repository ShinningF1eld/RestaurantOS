# Frontend tests

The frontend has two fast Vitest suites in addition to the Playwright journeys:

- `tests/component/` renders synchronous client components with React Testing Library and checks user-visible loading, empty, error, validation, and permission states.
- `tests/client/` exercises the real browser API client and safe return-path helpers with controlled `fetch`, Web Locks, and navigation primitives.

Run both suites once with `npm test` from `frontend/`. They use `jsdom`; no API, database, or browser installation is required. Vitest 5 requires Node 22.12 or later, and this project uses Node 24. The frontend Node typings are pinned to the matching 24 line. Playwright remains responsible for full-browser behavior and asynchronous Server Components, which the installed Next.js App Router testing guide says Vitest does not support.

The Vitest configuration includes only `tests/component/**/*.test.*` and `tests/client/**/*.test.*`. This keeps the existing `tests/*.spec.ts` Playwright files out of Vitest discovery. Playwright separately ignores the two Vitest directories. Vitest persists transformed modules under `node_modules/.vitest-cache` so its workers can share the cache; reinstalling dependencies clears it.

Tests reset module state and browser mocks between cases. In particular, session renewal state is module-scoped, so client tests reload the real client module per case. Keep test requests credential-free and use synthetic responses; never place real credentials or tokens in fixtures or output.

Component tests cover login failure/loading, order validation and idempotent retry, order action permissions, recipe loading/validation/save behavior, and inventory loading/empty/error and manager capabilities. API-client tests cover cookie credentials, CSRF headers, safe paths, one bounded renewal retry, concurrent renewal coalescing through Web Locks, and renewal-failure lockout. Browser-level authentication and backend persistence remain covered by Playwright.
