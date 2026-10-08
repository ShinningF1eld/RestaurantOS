# Milestone 7 task plan

Status: Published
Source: docs/milestone-7-design.md, approved revision 12 (2026-10-07); RestaurantOS_Master_Roadmap.md, Milestone 7.
Inspected revision: 6a528f4826796991d8c5cfe2ad9f6cffb480981e; working tree initially clean.
Updated: 2026-10-07
Target: ShinningF1eld/RestaurantOS
GitHub milestone: [Milestone 7 Redis caching and rate limiting](https://github.com/ShinningF1eld/RestaurantOS/milestone/2)
Assignee: `ShinningF1eld` on all nine issues (#19–#27), verified 2026-10-07.
Publication authorization: user requested “Separate into concrete task and create github issues.”

## Ordered tasks

| ID | Outcome | Requirements | Depends on | Publication |
|---|---|---|---|---|
| T1 | ✅ Resolve cache and limiter tuning before implementation | R1, R5–R9 | None | [#19 — completed](https://github.com/ShinningF1eld/RestaurantOS/issues/19) |
| T2 | Capture reproducible uncached menu-read baseline | R7 | None | [20](https://github.com/ShinningF1eld/RestaurantOS/issues/20) |
| T3 | Provide bounded Redis adapter and isolated runtime configuration | R4–R7, R10 | T1 | [21](https://github.com/ShinningF1eld/RestaurantOS/issues/21) |
| T4 | Cache authorized menu reads with live stock and absolute age bounds | R1–R4 | T1, T2, T3 | [22](https://github.com/ShinningF1eld/RestaurantOS/issues/22) |
| T5 | Invalidate committed catalog changes without risking business writes | R1, R3, R4 | T4 | [23](https://github.com/ShinningF1eld/RestaurantOS/issues/23) |
| T6 | Use atomic Redis admission and failed-login accounting | R5, R8, R9 | T1, T3 | [24](https://github.com/ShinningF1eld/RestaurantOS/issues/24) |
| T7 | Enforce stricter local limits through Redis outages and recovery | R5, R6, R10 | T6 | [25](https://github.com/ShinningF1eld/RestaurantOS/issues/25) |
| T8 | Verify cache and limiter workflows in full repository gates | R1–R10 | T5, T7 | [26](https://github.com/ShinningF1eld/RestaurantOS/issues/26) |
| T9 | Publish measured performance and Milestone 7 operational evidence | R4–R7, R10; roadmap exit criteria | T2, T8 | [27](https://github.com/ShinningF1eld/RestaurantOS/issues/27) |

## Coverage and sequencing

T1 resolves disclosed tuning, not a new product design. T2 can proceed independently; T3 follows T1. Catalog T4–T5 and auth T6–T7 can proceed independently once prerequisites pass. T8 integrates verification; T9 records measurements and completion evidence.

All R1–R10 are mapped above. The approved design narrows the roadmap: AI endpoints are deferred, dashboard caching is evaluation only, and workers/events remain Milestone 8. No application implementation, database migration, commit or push is part of this planning task.

Current code reads catalog directly and counts all login attempts in PostgreSQL using an email-global key. The accepted failure-only/pair-key policy is a deliberate change, not current behavior. Recipe availability currently accepts ORM menu items; T4 may need a public service interface for typed cached views. Developer Compose currently supplies only PostgreSQL; T3 explicitly adds Redis while preserving its volume. Existing PostgreSQL rate-limit history is retained. No schema change is assumed; any justified change requires the migration safeguards in T8.

## Complete issue bodies

### T1: Resolve cache and limiter tuning before implementation — ✅ Completed

## Purpose and references

Resolve cache and limiter tuning before implementation. Source: `docs/milestone-7-design.md`, approved revision 12, 2026-10-07; `RestaurantOS_Master_Roadmap.md`, Milestone 7, inspected at `6a528f4826796991d8c5cfe2ad9f6cffb480981e`. Requirements: R1, R5–R9.

## Scope

Document the remaining choices in docs/milestone-7-design.md and the auth/cache contracts; this task specifies policy rather than implementing it.

## Dependencies

None.

## Acceptance criteria

- [x] Record the menu endpoint/cache-key and invalidation matrix and accept the 10-second absolute TTL; the stale window remains strictly under 15 seconds.
- [x] Finalize normal Redis login thresholds/windows and local email/IP policy; finalize refresh accounting/quotas separately. Accepted refresh quotas are 10/family and 100/IP per 60 seconds in Redis mode, 5/family and 50/IP per 60 seconds locally.
- [x] Specify atomic two-key admission capacity, bounded leases, failure finalization, success/storage-error/cancellation release, ambiguous-operation handling, and generic overload/Retry-After behavior before coding.
- [x] Require bounded local entry capacity, expiry/cleanup and recovery guard; dual enforcement until existing local buckets expire is accepted. The exact finite entry-count value is mandatory deployment sizing rather than an unresolved design decision.
- [x] Preserve the accepted 100 ms total Redis operation budget, 5-second probes, three successful limiter probes, pair-scoped HMAC keys and failed-login accounting. Document distributed guessing and per-process outage limitations; seek review for material changes to accepted behavior.

## Verification

Completed in `docs/milestone-7-design.md` revision 12. The design records concrete overlap, outage, ambiguous-operation and recovery examples, and explicitly assigns the numeric local entry cap to mandatory deployment sizing. GitHub issue #19 is closed as completed.

<!-- github-plan: docs/milestone-7-design.md | T1 -->

### T2: Capture reproducible uncached menu-read baseline

## Purpose and references

Capture reproducible uncached menu-read baseline. Source: `docs/milestone-7-design.md`, approved revision 12, 2026-10-07; `RestaurantOS_Master_Roadmap.md`, Milestone 7, inspected at `6a528f4826796991d8c5cfe2ad9f6cffb480981e`. Requirements: R7.

## Scope

Add benchmark scripts and a disposable seeded workload using current catalog endpoints; do not implement caching yet.

## Dependencies

None.

## Acceptance criteria

- [x] Define dataset sizes, organization/branch memberships, recipe/stock mix, endpoint mix, concurrency and cold/warm/mixed-write scenarios; record hardware, runtime versions and source revision. Cold/warm cache states are N/A for the uncached run and specified for the post-cache comparison. See [benchmark procedure](testing/menu-read-benchmark.md).
- [x] Record P50/P95/P99 latency, PostgreSQL query counts, error rate and baseline cache hit ratio as not applicable; state measurement method and repetitions. The full run contains 1,000 measured requests per cell and three repetitions.
- [x] Seed and clean only owned disposable PostgreSQL resources; never mutate/migrate the application database or retain credentials in artifacts. Success and injected post-measurement failure both cleaned the allocated database.
- [x] Make the same workload reusable for post-cache comparison and define the evidence needed to evaluate optional dashboard caching.

## Verification

Corrected capture completed 2026-10-07 using script version 1.1.0 at clean implementation commit `aa01cde845ba5b780f6875abdca274fc452ad70c`, Python 3.12.13 and PostgreSQL 16.15. It used temporary `docker-compose.test.yml` services and an independently allocated `restaurantos_benchmark_*_test` database. Command: set `TEST_DATABASE_URL` to the test service's loopback `restaurantos_test` template, then run `backend/.venv-m6-dev/Scripts/python.exe scripts/benchmark-menu-reads.py` (default: 1,000 requests, 50 warm-ups, three repetitions, concurrency 1/10/25/50). The corrected run completed 48 cells / 48,000 measured requests with zero errors. JSON: `artifacts/benchmarks/corrected/menu-read-baseline-20261007T130416Z-c6ac7674.json` (git-ignored). Query totals averaged six per menu-list, seven per item-list, 6.8 per mixed-read request, and 7.500916666666667 per mixed-write request. Mixed writes are now exactly 10% item updates, 10% menu updates and 80% reads over complete ten-request cycles. All settings are explicitly isolated and effective nonsecret values are recorded. Injected seed, measurement and real HTTP request failures returned nonzero, left zero allocated benchmark databases and wrote no result artifact. The initial version 1.0.0 artifact is superseded because its mixed-write ratio was mislabeled and settings were not fully isolated. See [reproduction and metric details](testing/menu-read-benchmark.md) and [verification](verification-milestone7-issue20.md).

<!-- github-plan: docs/milestone-7-design.md | T2 -->

### T3: Provide bounded Redis adapter and isolated runtime configuration

## Purpose and references

Provide bounded Redis adapter and isolated runtime configuration. Source: `docs/milestone-7-design.md`, approved revision 12, 2026-10-07; `RestaurantOS_Master_Roadmap.md`, Milestone 7, inspected at `6a528f4826796991d8c5cfe2ad9f6cffb480981e`. Requirements: R4–R7, R10.

## Scope

Add shared external adapter/lifecycle support, typed configuration, env examples, dependency source/hashed locks, local Compose Redis and test-runner wiring. Keep catalog/auth policy inside their modules.

## Dependencies

[T1](https://github.com/ShinningF1eld/RestaurantOS/issues/19).

## Acceptance criteria

- [x] Open and close the asynchronous Redis client through API lifecycle; enforce the accepted 100 ms total operation budget including connection/retry behavior, with safe error classification.
- [x] Namespace cache/limiter/test keys by environment and schema/use case; protect auth identifiers and redact Redis credentials.
- [x] Provide local Redis configuration while retaining postgres_data and normal docker compose down; extend isolated random-port validation to pass Redis settings into API and browser processes.
- [x] Keep Redis loss compatible with API startup and PostgreSQL-backed sessions; preserve /health as liveness and runtime startup without migrations.
- [x] Install Redis dependency using docs/testing/dependencies.md and update .in and hashed locks together; keep pure unit tests free of network/services/secrets.

## Verification

Run baseline, backend-static, backend-unit, backend-integration and image gates as affected; prove owned Redis namespace/resource cleanup on success and failure.

Completed and verified on 2026-10-07; implementation commit `68a79bf` is pushed
to `milestone7` and [issue #21](https://github.com/ShinningF1eld/RestaurantOS/issues/21)
is closed as completed. Baseline, backend-static, backend-unit (169 passed),
backend-integration (189 passed, no Alembic drift), image and browser (24 passed)
verification passed, including owned Redis cleanup on success and injected failure.
See [dated T3 evidence](verification-milestone7-issue21.md) for exact commands,
results, omissions and acceptance mapping. Auth identifier HMAC usage remains
a future caller responsibility; T3 stores no auth identifiers. Full Milestone 7
acceptance is not claimed.

<!-- github-plan: docs/milestone-7-design.md | T3 -->

### T4: Cache authorized menu reads with live stock and absolute age bounds

## Purpose and references

Cache authorized menu reads with live stock and absolute age bounds. Source: `docs/milestone-7-design.md`, approved revision 12, 2026-10-07; `RestaurantOS_Master_Roadmap.md`, Milestone 7, inspected at `6a528f4826796991d8c5cfe2ad9f6cffb480981e`. Requirements: R1–R4.

## Scope

Implement measured catalog read caching in backend/app/modules/catalog and necessary public recipe availability interfaces; preserve existing URLs, shapes, prices and authorization. Avoid new cross-feature repository imports.

## Dependencies

[T1](https://github.com/ShinningF1eld/RestaurantOS/issues/19), [T2](https://github.com/ShinningF1eld/RestaurantOS/issues/20), [T3](https://github.com/ShinningF1eld/RestaurantOS/issues/21).

## Acceptance criteria

- [ ] Fresh membership, assignments, resource existence/scope and menu.read capability checks run before every cache hit; foreign/unassigned IDs remain 404 and forbidden capabilities 403.
- [ ] Cache typed serialized catalog data using environment/organization/restaurant/menu/schema keys; never store ORM instances, permission decisions or stock availability.
- [ ] Read stock and recipe tracking/availability live on hits, including stock consumption, receipt/waste/count and recipe changes; order validation still reads authoritative PostgreSQL prices and stock.
- [ ] Measure age from source-read start and set only remaining TTL; reject expired/slow fills, validate payload schema/age and prevent concurrent old fills receiving a fresh full TTL.
- [ ] Redis timeout/restart or corrupt payload falls back to scoped PostgreSQL reads with the same response contract; inactive/deleted resources do not bypass fresh scope checks.

## Verification

Run backend-unit, backend-integration and backend-static; test actual warm hits, two tenants, revoked assignment/membership, deleted resources, live stock, corruption and deterministic slow/concurrent fills.

Progress (2026-10-08): the first vertical slice caches
`GET /restaurants/{restaurant_id}/menus`; the second caches
`GET /menus/{menu_id}/items`. Both run fresh authorization and tenant scope checks
before cache access and use the accepted tenant-scoped keys and absolute-age
policy. Item payloads leave inventory tracking and availability live in PostgreSQL.
The remaining T4 acceptance coverage is not complete; issue #22 remains open.

<!-- github-plan: docs/milestone-7-design.md | T4 -->

### T5: Invalidate committed catalog changes without risking business writes

## Purpose and references

Invalidate committed catalog changes without risking business writes. Source: `docs/milestone-7-design.md`, approved revision 12, 2026-10-07; `RestaurantOS_Master_Roadmap.md`, Milestone 7, inspected at `6a528f4826796991d8c5cfe2ad9f6cffb480981e`. Requirements: R1, R3, R4.

## Scope

Apply the T1 invalidation matrix to menu/menu-item create/update/delete/deactivate and any other mutations affecting cached catalog fields. Keep business/audit transaction and lock rules unchanged.

## Dependencies

[T4](https://github.com/ShinningF1eld/RestaurantOS/issues/22).

## Acceptance criteria

- [ ] Invalidate affected restaurant/menu/item keys only after successful commit, covering list and detail payloads and all catalog mutations.
- [ ] Audit/flush/constraint failure rolls back business changes and produces no committed-change invalidation; successful writes remain successful when Redis invalidation fails.
- [ ] Handle the existing delete_menu_item early-return paths so deactivation and deletion both invalidate after commit.
- [ ] Prove a fill racing invalidation cannot extend stale data beyond the accepted absolute age; failed invalidation is safely observable.
- [ ] Maintain fixed-precision prices, immutable order snapshots and inventory/order locks; no event worker/outbox is introduced.

## Verification

Run backend-unit, backend-integration and backend-static; deterministically coordinate source read/write/invalidation/fill races and inject audit rollback and Redis invalidation failure.

<!-- github-plan: docs/milestone-7-design.md | T5 -->

### T6: Use atomic Redis admission and failed-login accounting

## Purpose and references

Use atomic Redis admission and failed-login accounting. Source: `docs/milestone-7-design.md`, approved revision 12, 2026-10-07; `RestaurantOS_Master_Roadmap.md`, Milestone 7, inspected at `6a528f4826796991d8c5cfe2ad9f6cffb480981e`. Requirements: R5, R8, R9.

## Scope

Replace PostgreSQL limiter use in backend/app/modules/auth/rate_limit.py and integrate admission/finalization with auth/service.py; implement Redis login and separately agreed refresh policy.

## Dependencies

[T1](https://github.com/ShinningF1eld/RestaurantOS/issues/19), [T3](https://github.com/ShinningF1eld/RestaurantOS/issues/21).

## Acceptance criteria

- [ ] Normalize email with strip().casefold() at the service boundary, including direct callers; use existing validated source IP and HMAC email/IP pair plus IP-wide keys for all account outcomes.
- [ ] Atomically check both buckets and acquire bounded in-flight leases before password verification; finalize wrong-password/unknown/disabled outcomes identically and keep unknown-account dummy verification.
- [ ] Successful logins do not increment failure counts; storage/transport errors and cancellation release capacity per T1. Success never clears IP failures; implement the recorded pair-clear decision.
- [ ] All triggered buckets use existing generic 429 detail and Retry-After independent of account existence; no raw keys or identifiers leak.
- [ ] Implement separate refresh accounting without changing cookie/session/replay/CSRF/renewal contracts; no runtime PostgreSQL limiter writes or shadow accounting remain.
- [ ] Keep existing limiter schema/history in place unless a separately justified migration is required; do not delete data as cleanup.

## Verification

Run backend-unit, backend-integration and backend-static; use real Redis atomic operations and deterministic overlap of password checks to prove bounded admission, lease expiry and account-independent failure handling.

<!-- github-plan: docs/milestone-7-design.md | T6 -->

### T7: Enforce stricter local limits through Redis outages and recovery

## Purpose and references

Enforce stricter local limits through Redis outages and recovery. Source: `docs/milestone-7-design.md`, approved revision 12, 2026-10-07; `RestaurantOS_Master_Roadmap.md`, Milestone 7, inspected at `6a528f4826796991d8c5cfe2ad9f6cffb480981e`. Requirements: R5, R6, R10.

## Scope

Add per-process degraded limiter state and controlled recovery, integrating both login and agreed refresh limits without PostgreSQL limiter fallback.

## Dependencies

[T6](https://github.com/ShinningF1eld/RestaurantOS/issues/24).

## Acceptance criteria

- [ ] First Redis failure immediately enforces local limits on the same request; degraded requests skip Redis without a rejection waiting period or PostgreSQL counter writes.
- [ ] Use atomic local admission/finalization, monotonic expiry, stricter approved quotas and bounded memory/cleanup; reject untrackable new keys with a retryable service error rather than evict active counters.
- [ ] An ambiguous Redis increment/admission/finalization follows T1's conservative accounting; bounded leases prevent unlimited in-flight capacity or permanent leaks.
- [ ] Use one nonblocking limiter-operation recovery probe per process every 5 seconds and require three consecutive successes; failures reset stability, with existing local history retained across flapping.
- [ ] Apply the approved recovery guard to surviving local buckets; explicitly demonstrate independent process quotas and loss on process restart as accepted limitations.
- [ ] Emit healthy/degraded/recovering transition events with process identity, safe reasons and duration; report probe failures/flapping without raw email/IP/password/cookie/token or per-request skipped-Redis logs.

## Verification

Run backend-unit, backend-integration and backend-static; use deterministic clocks/barriers plus real Redis outage/restart, two API processes, memory pressure and process restart; assert Redis is untouched during open-circuit requests.

<!-- github-plan: docs/milestone-7-design.md | T7 -->

### T8: Verify cache and limiter workflows in full repository gates

## Purpose and references

Verify cache and limiter workflows in full repository gates. Source: `docs/milestone-7-design.md`, approved revision 12, 2026-10-07; `RestaurantOS_Master_Roadmap.md`, Milestone 7, inspected at `6a528f4826796991d8c5cfe2ad9f6cffb480981e`. Requirements: R1–R10.

## Scope

Integrate cross-feature service and browser regressions into scripts/validate.py, tests and existing CI gates; reuse regressions from preceding implementation tasks.

## Dependencies

[T5](https://github.com/ShinningF1eld/RestaurantOS/issues/23), [T7](https://github.com/ShinningF1eld/RestaurantOS/issues/25).

## Acceptance criteria

- [ ] Real PostgreSQL/Redis tests cover hit authorization, stock freshness, rollback, invalidation failure, absolute-age races, admission overlap, ambiguity, outage/restart, memory capacity and recovery flapping.
- [ ] Chromium exercises catalog updates with warm cache, current stock, login throttling and Redis outage/recovery against a real API and production frontend; cookies and bounded uncertain-refresh behavior remain intact.
- [ ] Isolated validation provisions Redis for application behavior, retains guarded _test databases, random ports and cleanup on injected failures; auth traces stay disabled.
- [ ] Full ten-gate local validation and remote CI succeed on Python 3.12/Node 24; preserve the required Milestone 6 acceptance aggregate and complete gate enforcement.
- [ ] Any necessary schema change uses a new single-head Alembic revision and clean/seeded-legacy migrations gate; validation never migrates the application database.

## Verification

Run ./scripts/validate.ps1 and a complete remote PR CI run; record exact commands/outcomes/omissions and deterministic race evidence. Follow docs/testing/enforcement.md if gate policy changes.

<!-- github-plan: docs/milestone-7-design.md | T8 -->

### T9: Publish measured performance and Milestone 7 operational evidence

## Purpose and references

Publish measured performance and Milestone 7 operational evidence. Source: `docs/milestone-7-design.md`, approved revision 12, 2026-10-07; `RestaurantOS_Master_Roadmap.md`, Milestone 7, inspected at `6a528f4826796991d8c5cfe2ad9f6cffb480981e`. Requirements: R4–R7, R10; roadmap exit criteria.

## Scope

Run before/after workloads and update README, docs/current-state.md, auth/cache API documentation, runbooks and dated milestone verification evidence.

## Dependencies

[T2](https://github.com/ShinningF1eld/RestaurantOS/issues/20), [T8](https://github.com/ShinningF1eld/RestaurantOS/issues/26).

## Acceptance criteria

- [ ] Compare the identical baseline workload with cold/warm caches and mixed writes; record P50/P95/P99, query counts, hit ratio, error rate, dataset, hardware/environment, versions and revision.
- [ ] Include Redis outage/restart scenarios and separate authorization/live-stock costs; report regressions and actual improvements without invented targets or unsupported claims.
- [ ] Document stale-window guarantee, tuning, cache failure fallback, limiter failure accounting/admission, recovery events, memory overload and multi-process/restart/distributed-guessing limitations.
- [ ] Evaluate optional dashboard caching using measurements and record implement/defer recommendation; implementation requires a reviewed follow-up scope. AI endpoints and workers remain deferred.
- [ ] Map roadmap exit criteria to reproducible scripts and passing correctness/invalidation/full-gate evidence; mark milestone complete only after all evidence exists. Keep application database revision distinct from repository head.

## Verification

Re-run documented benchmark commands, review evidence against all R1–R10 and roadmap exit criteria, and verify README claims directly against saved measurements.

<!-- github-plan: docs/milestone-7-design.md | T9 -->

## Publication record

- T1: created [#19](https://github.com/ShinningF1eld/RestaurantOS/issues/19) on 2026-10-07; completed and closed on 2026-10-07.
- T2: created [#20](https://github.com/ShinningF1eld/RestaurantOS/issues/20) on 2026-10-07.
- T3: created [#21](https://github.com/ShinningF1eld/RestaurantOS/issues/21) on 2026-10-07.
- T4: created [#22](https://github.com/ShinningF1eld/RestaurantOS/issues/22) on 2026-10-07.
- T5: created [#23](https://github.com/ShinningF1eld/RestaurantOS/issues/23) on 2026-10-07.
- T6: created [#24](https://github.com/ShinningF1eld/RestaurantOS/issues/24) on 2026-10-07.
- T7: created [#25](https://github.com/ShinningF1eld/RestaurantOS/issues/25) on 2026-10-07.
- T8: created [#26](https://github.com/ShinningF1eld/RestaurantOS/issues/26) on 2026-10-07.
- T9: created [#27](https://github.com/ShinningF1eld/RestaurantOS/issues/27) on 2026-10-07.
