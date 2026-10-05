# Milestone 6: test architecture and quality gates

Status: Published; all nine issues created and verified.
Source: `RestaurantOS_Master_Roadmap.md`, Milestone 6, lines 730–778.  
Updated: 2026-10-05 (Asia/Bangkok).  
Source revision: `a0012eeaa58a873a7c075780725d4dfc76e9dabd`; working tree was clean before this plan.  
Target repository: `ShinningF1eld/RestaurantOS`, resolved from origin.  
Publication approval: User approved all nine issues on 2026-10-05: "I approve this 9 issues, publish it to github".

## Repository evidence

- `backend/tests` already contains unit, characterization, PostgreSQL integration, authentication, tenancy, inventory, transaction, and concurrency tests. Extend missing behavior rather than recreate existing suites.
- `backend/tests/conftest.py` requires a test database URL even for unit collection; unit fixtures override database cleanup. Improve isolation without weakening integration safeguards.
- `frontend/tests` already contains Playwright authentication, permissions, inventory, recipe, and order tests. No component/API-client test runner is configured in `frontend/package.json`.
- `.github/workflows/ci.yml` installs pinned Python requirements and uses `npm ci`; it runs Ruff, mypy, ESLint, TypeScript, PostgreSQL tests, clean migration/model checks, a frontend build, and Chromium tests. It lacks explicit format checks, coverage reporting, Redis, and a backend image build.
- `scripts/validate.ps1` is the current single Windows validation command, but upgrades the configured application database. `scripts/verify-milestone5.py` provides reusable disposable-database and migration verification patterns.
- No backend Dockerfile was found. Worker/outbox features are planned for Milestone 8; Redis product behavior belongs to Milestone 7.
- `docs/current-state.md` records 309 backend and 21 Chromium tests passing on 2026-10-05. Those are historical results, not checks rerun by this planning task.
- No issue template was found under `.github`. GitHub search across open and closed issues returned no issues on 2026-10-05. Repeat the duplicate search before publication and inspect any plausible matches.

## Ordered tasks

Requirement references below are local aliases for the roadmap bullets, not new roadmap requirements.

| ID | Proposed issue title | Requirements | Depends on | Publication |
|---|---|---|---|---|
| M6-T1 | [M6] Isolate backend test layers and close critical regression gaps | Backend unit/repository/API layers; business rules and isolation | None | [#6](https://github.com/ShinningF1eld/RestaurantOS/issues/6) |
| M6-T2 | [M6] Add frontend component and API-client regression tests | Frontend component/client layers | None | [#7](https://github.com/ShinningF1eld/RestaurantOS/issues/7) |
| M6-T3 | [M6] Complete deterministic browser coverage for critical user journeys | Frontend end-to-end layer | None | [#8](https://github.com/ShinningF1eld/RestaurantOS/issues/8) |
| M6-T4 | [M6] Automate clean and previous-revision migration verification | Backend migration layer; migration smoke gate | None | [#9](https://github.com/ShinningF1eld/RestaurantOS/issues/9) |
| M6-T5 | [M6] Make dependency installs and formatting checks reproducible | Lockfile installs; lint/format/type tooling | None | [#10](https://github.com/ShinningF1eld/RestaurantOS/issues/10) |
| M6-T6 | [M6] Publish useful backend and frontend coverage reports | Coverage as feedback | M6-T1, M6-T2 | [#11](https://github.com/ShinningF1eld/RestaurantOS/issues/11) |
| M6-T7 | [M6] Add a reproducible backend production image build | Backend production build gate | M6-T5 | [#12](https://github.com/ShinningF1eld/RestaurantOS/issues/12) |
| M6-T8 | [M6] Unify safe local validation and complete CI quality gates | PostgreSQL/Redis services; all CI gates; one local command | M6-T1–M6-T7 | [#13](https://github.com/ShinningF1eld/RestaurantOS/issues/13) |
| M6-T9 | [M6] Enforce required PR checks and record milestone acceptance | Merge enforcement; milestone exit evidence | M6-T8 | [#14](https://github.com/ShinningF1eld/RestaurantOS/issues/14) |

## Coverage and sequencing

M6-T1 through M6-T5 can proceed independently. M6-T6 joins the backend and frontend test foundations; M6-T7 follows dependency reproducibility. M6-T8 integrates all gates and M6-T9 verifies merge enforcement using the actual emitted check names.

Worker/event tests are explicitly deferred to Milestone 8 because there is no worker/outbox implementation to test. Record the required future cases (delivery, retry, duplicate handling, failure recovery) in the testing strategy without creating a speculative worker or empty passing suite. Redis in this milestone is service/test infrastructure only; caching and rate-limiting features remain in Milestone 7. Pre-commit hooks are optional and omitted unless a fast, documented subset proves useful. No blanket coverage percentage is prescribed. Deployment, registry publication, feature work, and repository-wide architectural rewrites are outside scope.

## Published issue bodies

### M6-T1 — [M6] Isolate backend test layers and close critical regression gaps

**Purpose and references:** Complete the backend unit, repository, and API layers and the critical-rule/isolation exit criterion in Milestone 6 of `RestaurantOS_Master_Roadmap.md` at source revision `a0012eeaa58a873a7c075780725d4dfc76e9dabd`.

**Scope:** Inspect and extend `backend/tests`, fixtures, and pytest configuration. Write a testing strategy with a requirement-to-test map, layer boundaries, fixture lifecycle, and commands. Reuse current authentication, tenancy, inventory, and concurrency cases. Avoid moving tests solely to rename folders.

**Dependencies:** None.

**Acceptance criteria:**

- [ ] Unit tests for transitions, permission policies, totals, and inventory math run without PostgreSQL, Redis, or application secrets and make no service connections.
- [ ] Repository integration tests use real PostgreSQL; API tests exercise actual authentication and tenant-scoped workflows. Database cleanup still rejects unsafe targets.
- [ ] A test map identifies existing and newly added cases for cross-tenant access, role restrictions, refresh replay/account revocation, immutable totals, idempotency mismatch/replay, rollback, concurrent stock acceptance, and cancellation without restocking.
- [ ] Missing cases are added at the appropriate layer; existing behavior is not duplicated merely to increase test counts. Concurrent tests prove overlap rather than depending only on timing sleeps.
- [ ] The strategy explicitly assigns worker/event coverage to Milestone 8 with its required future cases, without claiming that coverage exists today.

**Verification:** Run unit tests with service variables absent and services unavailable; run repository/API suites against a newly migrated disposable PostgreSQL database. Run the relevant race cases repeatedly with deterministic coordination, demonstrate no cross-test leakage, and record commands/results.

<!-- github-plan: RestaurantOS_Master_Roadmap.md#milestone-6 | M6-T1 -->

### M6-T2 — [M6] Add frontend component and API-client regression tests

**Purpose and references:** Complete Milestone 6 frontend component tests and useful API client tests/mocks; same source revision as the plan.

**Scope:** Add a compatible test runner and component utilities, scripts, and focused tests around important forms and the shared API transport. Follow `frontend/AGENTS.md` and installed Next.js documentation before implementation. Keep server-rendered behavior in integration/browser tests where component mocks would hide it.

**Dependencies:** None.

**Acceptance criteria:**

- [ ] A documented frontend test command runs deterministically without a live API or database and is suitable for CI.
- [ ] Important login, order, and inventory/recipe forms cover invalid inputs, pending/submission behavior, server errors, and successful state updates where relevant.
- [ ] Permission-dependent controls and loading/empty/error states have focused regression coverage.
- [ ] Shared transport tests cover credential handling, successful/error responses, session renewal failure and bounded retry behavior; order retries preserve the same idempotency key where implemented.
- [ ] Mocks are reset between tests, assert observable contracts, and do not replace real browser coverage of authentication and tenancy.

**Verification:** Run the new suite plus ESLint and TypeScript checks. Deliberately break a representative error/retry behavior to confirm its test fails, then restore it. Document runner/setup choices and commands.

<!-- github-plan: RestaurantOS_Master_Roadmap.md#milestone-6 | M6-T2 -->

### M6-T3 — [M6] Complete deterministic browser coverage for critical user journeys

**Purpose and references:** Complete Milestone 6 end-to-end tests for login, restaurant selection, order flow, and permission restrictions.

**Scope:** Audit and extend current Playwright suites and isolated API/seed helpers. Add only missing journeys and reliability fixes; retain real browser/API/PostgreSQL boundaries.

**Dependencies:** None.

**Acceptance criteria:**

- [ ] A journey matrix maps login/session handling, restaurant selection and switching, order creation/lifecycle, and role-restricted screens/actions to executable tests.
- [ ] Representative Owner, assigned Manager, Employee, and unauthorized/cross-tenant cases verify both visible controls and server rejection where appropriate.
- [ ] Order journeys retain shortage, duplicate submission/retry, accepted stock consumption, and cancellation-without-restock coverage.
- [ ] Tests use disposable seeded state, production frontend builds, isolated ports/processes, and deterministic waits; cleanup also runs on failure.
- [ ] CI failures retain useful traces/screenshots/reports without secrets; retries cannot conceal a persistently failing test.

**Verification:** Run the complete Chromium suite twice from fresh test state and exercise failure artifact collection. Confirm the harness leaves existing application data and developer servers untouched.

<!-- github-plan: RestaurantOS_Master_Roadmap.md#milestone-6 | M6-T3 -->

### M6-T4 — [M6] Automate clean and previous-revision migration verification

**Purpose and references:** Complete Milestone 6 clean/representative-previous-revision tests and migration smoke gate.

**Scope:** Generalize useful checks from the existing milestone migration scripts into a reusable harness. Use disposable databases and the actual Alembic head; document the representative starting revision and fixture rationale.

**Dependencies:** None.

**Acceptance criteria:**

- [ ] An empty database upgrades to the unique current head and passes the Alembic model-drift check.
- [ ] A representative previous revision with seeded legacy business data upgrades successfully; assertions prove preservation of tenant relationships, order snapshots, and applicable inventory/history data.
- [ ] Existing migration policies are preserved: legacy menu items stay untracked, legacy orders stay unprocessed, and prohibited downgrades fail without partial data/schema changes where covered by the selected path.
- [ ] The harness rejects non-test targets, uses unique database names, and cleans up on success and failure.
- [ ] CI-ready commands and the method for advancing the representative baseline as migrations evolve are documented.

**Verification:** Run clean and seeded upgrade scenarios locally and on PostgreSQL in CI; assert final revision and representative data invariants. Force a migration/test failure to verify nonzero exit and cleanup. Do not migrate the application database.

<!-- github-plan: RestaurantOS_Master_Roadmap.md#milestone-6 | M6-T4 -->

### M6-T5 — [M6] Make dependency installs and formatting checks reproducible

**Purpose and references:** Complete Milestone 6 lockfile installation and backend/frontend lint, formatting, and type-check tooling.

**Scope:** Build on pinned Python requirements, npm lockfile, Ruff, mypy, ESLint, and TypeScript. Choose and document a reproducible Python locking/update workflow, including transitive development tools. Add explicit format verification and resolve existing formatting drift in a mechanical change.

**Dependencies:** None.

**Acceptance criteria:**

- [ ] Clean Python and Node installs use committed dependency locks; validation does not silently resolve new dependency versions or rewrite locks.
- [ ] Documented lock update commands cover runtime and test/development dependencies and supported Python/Node baselines.
- [ ] Backend and frontend each expose separate non-mutating lint/format checks, with formatter configuration compatible with existing tooling.
- [ ] Backend mypy and frontend TypeScript checks remain enabled; formatting does not weaken lint/type rules or change behavior.
- [ ] Pre-commit hooks remain optional; if introduced, they run only a fast documented subset and are not required to reproduce CI checks.

**Verification:** Install in fresh environments from the committed locks; run integrity, lint, format, and type checks. Confirm intentionally misformatted samples fail verification, restore them, and check that validation leaves tracked files unchanged.

<!-- github-plan: RestaurantOS_Master_Roadmap.md#milestone-6 | M6-T5 -->

### M6-T6 — [M6] Publish useful backend and frontend coverage reports

**Purpose and references:** Fulfill Milestone 6 coverage reports as feedback, without arbitrary vanity thresholds.

**Scope:** Add coverage collection for backend tests and frontend component/client tests. Report meaningful application modules and document intentional exclusions. Browser coverage instrumentation is not required.

**Dependencies:** [M6-T1](https://github.com/ShinningF1eld/RestaurantOS/issues/6), [M6-T2](https://github.com/ShinningF1eld/RestaurantOS/issues/7).

**Acceptance criteria:**

- [ ] Backend and frontend commands emit readable summaries and machine-readable/HTML reports with separate labels for each suite.
- [ ] Reports include applicable business logic and missed branches, and exclude generated output, dependencies, and test code for documented reasons.
- [ ] CI retains coverage artifacts, including available reports on test failure, without masking the failed test exit status.
- [ ] The testing strategy explains how reviewers use uncovered critical behavior to choose regression tests; no blanket percentage or meaningless tests are required.

**Verification:** Generate reports from the real suites, inspect representative covered/uncovered business code, and confirm report generation preserves test failure status. Record local report locations and CI artifact names.

<!-- github-plan: RestaurantOS_Master_Roadmap.md#milestone-6 | M6-T6 -->

### M6-T7 — [M6] Add a reproducible backend production image build

**Purpose and references:** Fulfill the Milestone 6 backend image production-build gate, complementing the existing frontend build.

**Scope:** Add a backend Dockerfile and appropriate build-context exclusions, using the selected runtime lock and supported Python baseline. This is an image build/smoke task, not deployment or registry publishing.

**Dependencies:** [M6-T5](https://github.com/ShinningF1eld/RestaurantOS/issues/10).

**Acceptance criteria:**

- [ ] A documented Docker build produces the runnable API image using locked runtime dependencies.
- [ ] Local `.env` files, credentials, virtual environments, caches, and test artifacts are excluded from the image/context as appropriate.
- [ ] The application starts with runtime-provided configuration and passes a health smoke check against isolated test services when needed.
- [ ] Building/starting the image does not implicitly migrate the application database; migration execution remains an explicit operation.
- [ ] CI can build and smoke-test the image without pushing it to a registry.

**Verification:** Build from a clean checkout, inspect image contents/configuration for unwanted files, and run the health smoke check with disposable configuration. Record the build/start commands and successful shutdown/cleanup.

<!-- github-plan: RestaurantOS_Master_Roadmap.md#milestone-6 | M6-T7 -->

### M6-T8 — [M6] Unify safe local validation and complete CI quality gates

**Purpose and references:** Complete all Milestone 6 CI gates and the single documented local validation command.

**Scope:** Integrate the preceding tasks into `scripts/validate.ps1` (or a shared portable runner behind it), `.github/workflows/ci.yml`, and README/testing documentation. Reuse existing baseline/secret scanning and production frontend/browser checks.

**Dependencies:** [M6-T1](https://github.com/ShinningF1eld/RestaurantOS/issues/6), [M6-T2](https://github.com/ShinningF1eld/RestaurantOS/issues/7), [M6-T3](https://github.com/ShinningF1eld/RestaurantOS/issues/8), [M6-T4](https://github.com/ShinningF1eld/RestaurantOS/issues/9), [M6-T5](https://github.com/ShinningF1eld/RestaurantOS/issues/10), [M6-T6](https://github.com/ShinningF1eld/RestaurantOS/issues/11), [M6-T7](https://github.com/ShinningF1eld/RestaurantOS/issues/12).

**Acceptance criteria:**

- [ ] One documented root command runs the complete validation sequence with clear prerequisites and nonzero failure propagation. Partial/skip modes clearly report omitted gates and cannot be mistaken for full validation.
- [ ] Full validation uses disposable test databases and isolated resources; remove the current implicit `alembic upgrade head` against the configured application database.
- [ ] CI performs locked installs, lint/format verification, type checks, backend tests with healthy PostgreSQL and Redis services, frontend component/client tests, browser tests, both production builds, and migration smoke verification.
- [ ] Redis availability/isolation is verified as infrastructure; no caching, rate-limiting, or worker product behavior is invented to justify its presence.
- [ ] Local and CI commands share the same gate definitions or document unavoidable platform differences. Required jobs cannot silently skip relevant suites.
- [ ] Coverage and diagnostic artifacts are retained appropriately; service/process/temp-data cleanup runs on failure as well as success.

**Verification:** Run the full local command on the supported environment and a complete remote PR CI run. Exercise a representative failed gate and cleanup path. Record gate names, commands, outcomes, and local/CI parity in testing documentation.

<!-- github-plan: RestaurantOS_Master_Roadmap.md#milestone-6 | M6-T8 -->

### M6-T9 — [M6] Enforce required PR checks and record milestone acceptance

**Purpose and references:** Satisfy Milestone 6's requirement that PRs cannot merge in the chosen workflow when required checks fail, and record exit-criteria evidence.

**Scope:** Inspect actual default-branch rules, repository permissions, workflow triggers, and check names after M6-T8. Configure the chosen required-check workflow through an authorized repository administrator and document the policy. Do not infer enforcement merely from a green workflow.

**Dependencies:** [M6-T8](https://github.com/ShinningF1eld/RestaurantOS/issues/13).

**Acceptance criteria:**

- [ ] The chosen target branch/workflow requires the actual emitted quality checks and documents how bypass/admin access is governed.
- [ ] Failed and pending/missing required checks block ordinary PR merges; path filters, check naming, and any merge-queue usage do not create an enforcement gap.
- [ ] A disposable failing PR demonstrates blocking; after checks pass, the PR is eligible under the chosen policy without merging the test change.
- [ ] If account features or permissions prevent enforcement, record the exact limitation and administrator action required; do not claim the milestone is complete.
- [ ] README/current-state/testing documentation records the single local command, CI evidence, critical-rule/isolation test map, and explicit worker/event deferral to Milestone 8.

**Verification:** Inspect effective repository rules and check names, capture failing/pending and passing PR evidence, and review each roadmap exit criterion against executable evidence. Keep historical results clearly dated.

<!-- github-plan: RestaurantOS_Master_Roadmap.md#milestone-6 | M6-T9 -->

## Publication record

Publication authorized on 2026-10-05. Duplicate checks found no existing issues. The connector returned HTTP 403 (Resource not accessible by integration); all nine issues were successfully created through the authenticated GitHub browser session. Labels, assignees, and GitHub milestones remain unset. No publication errors remain unresolved.

| Task | Result | Issue |
|---|---|---|
| M6-T1 | Created 2026-10-05 via authenticated browser | [#6](https://github.com/ShinningF1eld/RestaurantOS/issues/6) |
| M6-T2 | Created 2026-10-05 via authenticated browser | [#7](https://github.com/ShinningF1eld/RestaurantOS/issues/7) |
| M6-T3 | Created 2026-10-05 via authenticated browser | [#8](https://github.com/ShinningF1eld/RestaurantOS/issues/8) |
| M6-T4 | Created 2026-10-05 via authenticated browser | [#9](https://github.com/ShinningF1eld/RestaurantOS/issues/9) |
| M6-T5 | Created 2026-10-05 via authenticated browser | [#10](https://github.com/ShinningF1eld/RestaurantOS/issues/10) |
| M6-T6 | Created 2026-10-05 via authenticated browser | [#11](https://github.com/ShinningF1eld/RestaurantOS/issues/11) |
| M6-T7 | Created 2026-10-05 via authenticated browser | [#12](https://github.com/ShinningF1eld/RestaurantOS/issues/12) |
| M6-T8 | Created 2026-10-05 via authenticated browser | [#13](https://github.com/ShinningF1eld/RestaurantOS/issues/13) |
| M6-T9 | Created 2026-10-05 via authenticated browser | [#14](https://github.com/ShinningF1eld/RestaurantOS/issues/14) |
