# Frontend tests

The frontend has three fast Vitest suites in addition to the Playwright journeys:

- `tests/component/` renders synchronous client components with React Testing Library and checks user-visible loading, empty, error, validation, and permission states.
- `tests/client/` exercises the real browser API client and safe return-path helpers with controlled `fetch`, Web Locks, and navigation primitives.
- `tests/server/` uses Node for SSR cookie/401 contracts, trace propagation, single SDK registration, configuration validation, actual OTLP privacy serialization and bounded exporter failure/retry behavior. Its HTTP receivers are local synthetic fixtures; real Next/FastAPI/Tempo correlation uses the [monitoring harness](monitoring.md).

Run all suites once with `npm test` from `frontend/`. Component/client suites use `jsdom`, server tests use Node; no API, database, or browser installation is required. Vitest 5 requires Node 22.12 or later, and this project uses Node 24. The frontend Node typings are pinned to the matching 24 line. Playwright remains responsible for full-browser behavior and asynchronous Server Components, which the installed Next.js App Router testing guide says Vitest does not support.

The Vitest configuration includes `tests/component/**/*.test.*`, `tests/client/**/*.test.*` and `tests/server/**/*.test.ts`. This keeps the existing `tests/*.spec.ts` Playwright files out of Vitest discovery. Playwright separately ignores these three directories. Vitest persists transformed modules under `node_modules/.vitest-cache` so its workers can share the cache; reinstalling dependencies clears it. The shared `frontend-tests` gate runs all three suites; server startup wiring also has real-service coverage in the focused monitoring harness.

Tests reset module state and browser mocks between cases. In particular, session renewal state is module-scoped, so client tests reload the real client module per case. Keep test requests credential-free and use synthetic responses; never place real credentials or tokens in fixtures or output.

Component tests cover login failure/loading, order validation and idempotent retry, order action permissions, recipe loading/validation/save behavior, and inventory loading/empty/error and manager capabilities. API-client tests cover cookie credentials, CSRF headers, safe paths, one bounded renewal retry, concurrent renewal coalescing through Web Locks, and renewal-failure lockout. Browser-level authentication and backend persistence remain covered by Playwright.
