# Relay scheduling verification and publication handoff

Reviewed 2026-10-19 (Asia/Bangkok) against the user request and authoritative
`milestone-8-design.md`, especially R3–R5/R11–R14. Comparison base is busy-reference
checkpoint `b9b6931ee0d5d97459974e70d25bd84e593eebda`. The measured relay source
fingerprint and exact raw evidence are in
[the comparison report](performance-milestone8-relay-drain.md). It was measured
before committing the relay continuation; raw repository-head fields correctly
identify that checkpoint, not the later publication commit.

| Criterion | Status | Evidence / limitation |
|---|---|---|
| Preserve current work on a new branch | Passed | Busy-reference source, tests and five raw cells committed as b9b6931 on `codex/m8-worker-throughput`; pushed on user's later request |
| Remove relay wait while work exists | Passed | Six-line production diff; successful full/partial batches yield and continue; real PostgreSQL/Redis 2/2/1 backlog drains before first idle wait |
| Preserve bounded batches and idle waits | Passed | Claim/concurrency/lease settings unchanged; unit and real repository/Redis tests; empty result retains 1,500 ms wait |
| Preserve failure backoff and stop behavior | Passed | New transport/PostgreSQL/internal backoff and stop-between-batches regressions; existing outage, fencing, poison-restart, replay and shutdown suites |
| Preserve business/security/consumer invariants | Passed | Production handlers/producer/auth/API/UI/schema unchanged; full backend and Chromium coverage; 1,980 correct measured effects with zero healthy failures/missing/charged retries |
| Repeat same benchmark | Passed | All five cells exit zero; settings, versions, script hash, dataset, effects and retained DB counts match earlier versions |
| Meet five seconds / overall performance improvement | Failed | Paced analytics P95 3.952s, alerts 6.293s, sink 37.125s; sink worsens markedly; pressure still misses; do not present aggregate misses as universal improvement |
| Full local required gate coverage | Passed across two commands | Initial four gates passed; integration failed one existing auth case with 336 passes. Unchanged six-gate retry passed all 337 integration plus remaining gates. Initial full command itself failed |
| Definitive cause of intermittent auth failure | Untested | Same auth assertion passed unchanged on retry; fixed-window expiry plausible but unproven; no auth code/tests changed |
| Relay without busy-retry control / multiple workers | Untested | Neither variant was measured; ordered cloud follow-up |
| Exact published-head CI | Untested at handoff | Both new branches pushed at user request; cloud task must inspect current heads and all ten gates plus aggregate |
| Final artifact scan / source identity / cleanup | Passed | Baseline recheck, exact 15 non-secret metadata entries, unchanged detector rules, measured source hashes and diff check; seven owned projects have zero containers and no owned worker/benchmark process remains |

Executed commands:

```powershell
# Focused worker unit file: 17 passed.
cd backend
.venv-m6-dev/Scripts/python.exe -m pytest tests/unit/test_event_worker.py -q -o faulthandler_timeout=15
cd ..
# Locked installation and four early gates passed; integration 336 passed / 1 failed.
./scripts/validate.ps1 -PythonExecutable ./backend/.venv-m6-dev/Scripts/python.exe
# Unchanged retry and remaining gates: passed; no installation repeated.
backend/.venv-m6-dev/Scripts/python.exe scripts/validate.py --gate backend-integration --gate frontend-tests --gate frontend-build --gate migrations --gate browser --gate image --no-install
```

Passing coverage totals: 307 unit, 337 integration, 10 client, 19 component,
29 Chromium; static, production build, clean/legacy migrations, backup/restore,
downgrade guards, intentional-failure cleanup and image checks. Exact initial
auth failure and uncertainty are documented in the comparison report. Ignored
console logs are local only; cloud must obtain accessible CI/validation evidence.

No change-induced functional defect was found in inspected/executed paths.
The paced sink regression is an actionable performance blocker for treating this
as finished. Profile transport versus consumer/DB wait, then run the controlled
variants described in [the cloud handoff](cloud-handoff-worker-freshness.md).
This review does not fix implementation, claim new CI success or mark M8 complete.
