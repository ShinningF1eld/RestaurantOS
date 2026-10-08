# Milestone 7 issue #22 verification

Reviewed: 2026-10-08  
Revision: `c1993460bddd3047b0ec62f9c2c4b7248c2e2748`, branch `milestone7`; initially clean working tree.  
Comparison base: `94b488222b83e810494db5c5cf4aeb82c9413373` (parent of the oldest reviewed commit).  
Environment: Windows, Python 3.12.13; disposable PostgreSQL 16 and Redis 7 via the repository validation runner.

## Result

All five issue #22 acceptance criteria pass based on current implementation inspection and the executed backend gates. No blocking implementation defect was found. A physical Redis stop/restart during warm catalog requests was not executed; restart correctness is supported by failure handling inspection, injected connection failures, real transport deadline tests and deterministic recovery tests, rather than direct server-restart evidence. This review does not establish full Milestone 7 acceptance.

## Sources and reviewed commits

Read root engineering instructions, README, current-state, the master roadmap's Milestone 7 section, approved design revision 12, task plan T1–T9, Redis architecture, and testing procedures. GitHub issue [#22](https://github.com/ShinningF1eld/RestaurantOS/issues/22) was retrieved directly, including its five criteria and verification requirements. GitHub's `milestone7` commits endpoint confirmed the following three branch commits match the local checkout:

| Commit | Subject | Review scope |
|---|---|---|
| `c199346` | Complete milestone 7 catalog cache acceptance | Additional authorization, stock, deletion and age regressions; completion documentation |
| `91346c3` | Cache menu item lists in Redis | Item payload/cache, router/service integration and public recipe availability interface |
| `65596a4` | Cache restaurant menu lists in Redis | Menu payload/cache, application state, router/service integration and outage circuit |

Latest means latest on the issue's implementation branch, not the repository's default `main` branch. No frontend source, dependency or migration change is present in this three-commit comparison.

## Criteria and coverage

| Criterion | Status | Evidence |
|---|---|---|
| AC1: Fresh membership, assignment, existence/scope and `menu.read`; foreign/unassigned 404 and forbidden 403 | Passed | `CatalogService.list_menus` and `list_menu_items` perform live tenancy/resource/capability checks before Redis. Access reads refresh membership and assignments. Executed warm-hit tests revoke membership and assignment and warm a separate tenant's item cache; denied requests do not access those keys. Existing tenancy regressions cover policy errors. |
| AC2: Typed serialized catalog data and scoped/versioned keys; no cached ORM, permission decisions or stock | Passed | Frozen Pydantic payload models serialize JSON. Environment/schema prefix comes from the adapter; organization derives from verified context; endpoint-specific restaurant/menu keys match the accepted design matrix. Tests verify fields, keys and decimal price preservation. Transient ORM objects reconstructed for item responses are not stored in Redis. |
| AC3: Live stock/recipe tracking and authoritative order prices/stock | Passed | Every nonempty item hit calls `RecipeAvailabilityService.for_menu_items`, restricted to the expected menu. Executed regression verifies receipt, waste, count, order consumption and disabling tracking while catalog source-read count remains one. After a PostgreSQL price update, order creation snapshots the new price despite the warm cache. Existing stock/order regressions passed. |
| AC4: Source-start age, remaining TTL, slow-fill rejection, payload validation and concurrent old fills | Passed | Services timestamp before source queries; cache subtracts query/construction/serialization elapsed time and skips exhausted fills. Lookups reject expired, future/nonfinite age, wrong schema/parents and duplicate item IDs. Deterministic unit tests cover remaining TTL, expired fills for both lists and barrier-controlled old fills writing last with their original short TTL. Hits do not renew TTL. |
| AC5: Redis failure/corruption fallback and fresh inactive/deleted resource scope | Passed | Lookup/store catch classified Redis failures; scoped PostgreSQL fallback preserves existing response models. Timeout/connection/closed failures open a catalog-only circuit, with cooldown and one recovery lookup. Integration tests cover injected connection failures for both lists, corrupt version payloads, deleted menu checks before lookup and deleted-item reload. Adapter tests cover actual stalled transport deadlines and unavailable Redis liveness. Active organization/membership checks remain live. Physical server restart was not directly exercised. |

The accepted design explicitly caches `is_available` as a static catalog field; `inventory_tracking`, `out_of_stock` and `available_portions` are live. Briefly stale catalog fields, including item deactivation, are permitted within the age bound and are not cached authorization decisions. The accepted item key uses organization/menu scope; restaurant identity is checked in its payload and live parent lookup.

## Executed checks

Commands were run from the repository root with the committed installed environment and no dependency resolution:

| Command | Result |
|---|---|
| `backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-unit --no-install` | Passed: 182 tests, 1 existing deprecation warning |
| `backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-integration --no-install` | Passed: 197 tests, 626 existing deprecation warnings; clean disposable migrations and Alembic check found no new upgrade operations |
| `backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-static --no-install` | Passed: Ruff lint, 160 files already formatted, mypy checked 122 source files |

The initial integration attempt was denied access to Docker by the sandbox; the approved retry passed. The initial sandboxed combined unit/static run stalled at the first async security test and was interrupted. The approved standalone unit retry passed; static was executed separately. These are environment limitations, not failing cache assertions. Integration cleanup removed the owned Compose containers/network. No application database migration was run.

## Findings and limits

- No actionable issue #22 implementation defect found.
- At review time, GitHub #22 remained open with all five boxes unchecked and cited design revision 5; the local task document checked all five and used approved revision 12. The code matches revision 12's accepted cache decisions. After review, the user authorized completion on 2026-10-08: GitHub #22 was closed as completed, its criteria checked, and its design reference updated to revision 12 and the new document path.
- Post-commit invalidation is still absent and belongs to #23/T5. Its absence does not fail #22, but prevents claiming complete roadmap cache/invalidation acceptance. Redis authentication limiting and full integration/performance evidence also remain later tasks.
- Physical Redis restart during warm reads and recovery with overlapping catalog requests were not directly executed. Current recovery unit coverage exercises cooldown/recovery sequentially; inspection supports the single-flight implementation. These are narrower execution evidence limits, not observed failures.
- Omitted gates: baseline, frontend-static, frontend-tests, frontend-build, migrations, browser and image. Remote CI and post-cache benchmarks were not run. No schema or public URL/response-contract change was found; no new cross-feature repository import was introduced. The recipe availability API still accepts menu-item objects, with transient objects constructed from typed cached views.

The review added only this report and did not change implementation, tests, configuration, issue state or branch publication. A subsequent user-authorized documentation organization moved milestone files into `docs/milestoneN/`, updated references and closed GitHub #22; no implementation or branch publication was performed.
