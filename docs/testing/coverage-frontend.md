# Frontend coverage

Run the frontend suites independently from `frontend/`:

```sh
npm run test:client:coverage
npm run test:component:coverage
```

The client command runs `tests/client/` and writes its report to
`coverage/client/`. The component command runs `tests/component/` and writes
its report to `coverage/component/`. Each directory contains a text summary in
the command output, `coverage-final.json` for tooling, and `index.html` for
line-by-line review, including branch coverage. Reports are generated even if
a test fails, while the command still exits nonzero for a failed test.

Both reports include eligible TypeScript and TSX files under `app/`,
`components/`, `features/`, and `lib/`, not only files imported by that suite.
This makes untested modules visible with zero coverage and lets the two
reports show which responsibilities each suite exercises. There are no
coverage thresholds; use the per-file and branch details to select focused
regression tests rather than treating one aggregate percentage as a quality
gate.

The current async App Router Server Component routes are excluded from these
Vitest reports because the installed Next.js guide documents that Vitest does
not support async Server Components. Those routes remain exercised through
Playwright. The excluded route files are `app/page.tsx`,
`app/login/page.tsx`, `app/session/renew/page.tsx`, and the page and layout
files under `app/restaurants/`. The synchronous restaurant dashboard client
page and its form component remain in the report.

`lib/api/server.ts` is also excluded: it is a `server-only` request facade that
imports Next.js cookies, headers, and redirect APIs. The V8 provider cannot
parse this unimported TypeScript module while adding uncovered files to the
report. Route-level behavior stays in the Playwright suite; the browser-side
API client remains included in Vitest coverage.

Coverage also excludes TypeScript declarations, test files and test folders,
generated code, dependencies, Next.js build output, prior coverage output, and
browser-test artifacts. Those files are not application logic under test and
would distort the report or recursively include its own output. Keep business
modules in one of the four included source trees so missed modules remain
visible.
