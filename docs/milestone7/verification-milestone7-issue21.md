# Issue 21 Redis infrastructure verification

Date: 2026-10-07 (Asia/Bangkok). Branch: `milestone7`.
Scope: T3 of approved Milestone 7 design/task revision 12. GitHub issue 21's
revision 5 reference is superseded by the approved local revision 12.
This is issue evidence, not full Milestone 7 acceptance or deployment evidence.

## Implementation and changed files

| Files | Purpose |
|---|---|
| `backend/app/redis/__init__.py`, `adapter.py` | Shared async transport, bounded lifecycle/commands, safe failure kinds and namespace prefixes; injectable client factory |
| `backend/app/core/config.py`, `backend/.env.example` | Secret Redis URL; positive budget capped at 100 ms; bounded pool size; safe test namespace |
| `backend/app/main.py` | Reusable lifecycle-owned pool without startup network checks; safe shutdown handling and nested test ownership |
| `backend/requirements.in`, `requirements.txt`, `requirements-dev.txt` | Pinned redis-py 8.1.0 with generated artifact hashes; dev input already includes runtime input |
| `docker-compose.yml` | Loopback local Redis with healthcheck, no persistence; existing PostgreSQL volume retained |
| `scripts/test_support/redis_environment.py`, `scripts/validate.py` | Explicit isolated runtime Redis settings from random test ports; unique owned namespaces; replace raw synchronous Redis probe with real adapter tests |
| `scripts/run-browser-tests.py`, `scripts/check-backend-image.py` | Browser/API environment wiring and URL diagnostic redaction; unavailable Redis in image smoke |
| `backend/tests/conftest.py`, `tests/unit/test_redis.py`, `tests/test_redis_infrastructure.py` | Network-free fakes and real disposable Redis regressions; preserve PostgreSQL guards |
| `AGENTS.md`, `README.md`, `docs/current-state.md`, `docs/testing/README.md`, `docs/testing/backend.md`, `docs/architecture/redis.md`, this file | Current setup, architecture, testing boundaries and dated evidence |

No schema migration, endpoint/response change, catalog cache/invalidation,
catalog circuit, Redis/local auth limiter, quota change or business health state
was added. Application PostgreSQL was not migrated or mutated. No commit, push,
issue closure or PR publication was performed.

## Exact reproducible commands

Compiler: uv 0.11.31; validation interpreter: Python 3.12.13. From `backend/`:

```powershell
uv --cache-dir .uv-cache pip compile --python .venv-m6-dev/Scripts/python.exe --universal --python-version 3.12 --generate-hashes --no-header --output-file requirements.txt requirements.in
uv --cache-dir .uv-cache pip compile --python .venv-m6-dev/Scripts/python.exe --universal --python-version 3.12 --generate-hashes --no-header --constraint requirements.txt --output-file requirements-dev.txt requirements-dev.in
```

From the repository root:

```powershell
backend/.venv-m6-dev/Scripts/python.exe -m pip install --require-hashes -r backend/requirements-dev.txt
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --gate backend-static --gate backend-unit --no-install
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --gate backend-static --gate backend-integration --gate image --no-install
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate image --gate browser --no-install
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-integration --no-install --inject-failure backend-integration
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate baseline --no-install
git diff --check
```

Focused unit command, from `backend/`:

```powershell
.venv-m6-dev/Scripts/python.exe -m pytest tests/unit/test_redis.py -q
```

Focused real Redis suite ran with `validate.services(False)` and
`disposable_database(prefix='restaurantos_redis_focus', ...)`, applying Alembic
only to that allocated database, then calling:

```text
python -m pytest tests/test_redis_infrastructure.py -q
```

## Results

| Check | Result |
|---|---|
| Hash-checked install / dependency integrity | Passed; only Redis added, previous pins retained |
| baseline | Passed Compose config, pip check and secret scan |
| backend-static | Passed Ruff lint, format (157 files) and mypy (121 source files) |
| backend-unit | 169 passed; 25 new Redis cases; existing socket block remains active |
| Focused real Redis suite | 6 passed; success/failure owned cleanup, outage liveness, nested/overlapping lifespans, stalled real transport |
| backend-integration / final image rebuild | 189 passed; Alembic check found no model drift; rebuilt image passed contents, unavailable-Redis liveness, PostgreSQL connectivity and no startup migrations |
| image / browser run | Passed image contents/nonroot/boot/no migrations with Redis unavailable; 24 Chromium tests passed after production build |
| Injected validation failure | Expected exit 1; owned containers/network removed; follow-up Docker inspection found none |
| Diff review | No synchronous application Redis, retry loop, global health flag, business policy, fixed test port or destructive Redis cleanup |

Initial development runs failed on nested lifecycle ownership and test assumptions
that PING/SET return wire bytes (redis-py returns booleans), plus a Windows
non-listening port returning timeout instead of immediate connection refusal.
Ownership and assertions were corrected, then focused/final gates were rerun.
The full suite also exposed out-of-order overlapping lifespans restoring a closed
predecessor; active-owner tracking and an explicit out-of-order regression fix it.
The early service run also cleaned its disposable project after failure.

Known existing warnings: Starlette's httpx TestClient deprecation and SQLAlchemy
`datetime.utcnow()` deprecation. No dependency upgrade was made to suppress them.
Asynchronous deadlines have normal event-loop scheduling tolerance; tests allow
small timing tolerance while proving the deadline is not connect plus read.

Frontend static/component gates and dedicated migration gate were omitted:
there is no frontend source or schema change. Browser ran its production build;
integration still checks Alembic drift and image smoke proves no startup migration.
These are deliberately partial repository runs, not full milestone acceptance.

## Acceptance mapping

- Lifecycle/deadline/classification: adapter fakes, stalled real transport,
  lifecycle reuse and outage startup/health tests.
- Namespaces/secrets: typed URL/settings/error tests; environment/use-case/version
  prefix tests; unique run IDs and exact owned cleanup. Auth identifiers are not
  stored by this issue; future callers must reuse HMAC protection.
- Local and isolated configuration: loopback local Compose Redis; unchanged
  disposable random-port Compose; explicit browser/API subprocess environment.
- PostgreSQL authority/liveness/no migrations: unchanged business modules and
  health handler; outage TestClient and production image smoke.
- Reproducibility/unit isolation: documented uv compiler, unchanged old pins,
  hashed install and socket-blocked pure unit gate.

All five issue 21 / T3 acceptance criteria are satisfied within this infrastructure
scope. Catalog/auth HMAC identifiers and degradation policies remain caller-owned
future work; this issue writes no auth identifiers. The full Milestone 7 gates and
exit criteria are not claimed complete. Successful final/browser project inspection
also found no surviving owned containers or networks.
