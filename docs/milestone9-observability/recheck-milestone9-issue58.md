# Issue #58 pre-merge recheck

Dated 2026-11-01 (Asia/Bangkok), reviewed base `c9dc231`. The user authorized
rechecking all issue criteria, publishing a new branch and merging after success.
The issue body was fetched again and its six criteria match the implementation
review. Current GitHub main rules require a PR, an up-to-date branch and the
unchanged `Milestone 6 acceptance` check. No protection bypass is authorized.

## Review findings and fixes

The low-level development Compose guard rejected `--volumes` but missed equivalent
short/boolean/combined flag spellings. It now rejects all such volume-deletion
requests before invoking Docker. The normal CLI shutdown still retains volumes.
Four pure regressions cover `-v`, `--volumes=true`, `-v=true` and `-vt 3`.

The local-engine guard now resolves an explicit `DOCKER_CONTEXT` before
`DOCKER_HOST`, matching Docker's context precedence. A pure regression ensures a
remote context cannot hide behind a local socket environment variable. Native
Docker help was inspected; no remote daemon was contacted for the regression.

Destination/queue fault checks now require zero Collector restarts in addition
to running/no-OOM state, and retain actual failed-export/enqueue metric samples.
Counters describe failed attempts, not an exact ledger of permanently lost data.
The intended cleanup scenario must still return nonzero with its specific
intentional interruption and verified owned cleanup.

## Criterion review

| Issue criterion | Current-code proof |
|---|---|
| Five immutable images and three signals through Grafana | Locked images/configs are unchanged; four native parsers and both fresh authenticated connection-mode smokes. |
| Bounded prototype/resources/counts/failures | Retained raw report hashes verified; pipeline/workload/observer inputs are unchanged. Four passing trials and the additional strict-pacing failure remain separately visible. |
| Two workflows, loopback access and private credentials | Compose review, pure isolation contracts and fresh host/container runtime tests. No storage port is published. |
| Seven-day/72-hour physical retention and persistence | Fresh restart and accelerated physical-old-file/recent-control fixtures; initial 13 GiB planning allowance remains separate from quotas. |
| Bounded queues/retries, destination failure and honest freshness | Fresh 180-second destination faults, reduced-queue rejection, actual exporter counters and a raw scraper gap; final fault checks also require zero restarts. |
| Owned lifecycle/developer persistence/sampling/compatibility | Corrected deletion aliases/context preflight, pure ownership regressions, intended failure cleanup and retained receiver/sampling documentation. |

## Reuse of the measured resource prototype

`evidence/issue58/recheck/resource-evidence-audit.json` verifies raw hashes and
compares the current pipeline/workload/observer inputs with all four passing
reports. The lifecycle guard changed, and only `outage`/`saturation` functions
changed in the checker; AST comparison verifies every other checker function,
including those used by the resource observer/reconciliation, is unchanged.
No runtime limit, image pin, workload, pipeline or observer loop changed.
Those boundary/fault-check changes do not justify re-running the hour-long fixed
resource protocol. This is not a false claim that every historical source hash
matches the new guard code. The failed pacing attempt remains retained and no
claim of uninterrupted scheduling or application capacity is made.

## Reproduction and outcomes

Fresh runtime reports are retained in `evidence/issue58/recheck/`. The commands
run from the root with the locked Python 3.12 environment:

```sh
backend/.venv/bin/python scripts/check-monitoring-config.py
backend/.venv/bin/python scripts/check-monitoring.py --mode host --report docs/milestone9-observability/evidence/issue58/recheck/host-smoke.json
backend/.venv/bin/python scripts/check-monitoring.py --mode container --report docs/milestone9-observability/evidence/issue58/recheck/container-smoke.json
backend/.venv/bin/python scripts/check-monitoring.py --scenario restart --report docs/milestone9-observability/evidence/issue58/recheck/host-restart.json
backend/.venv/bin/python scripts/check-monitoring.py --scenario outage --report docs/milestone9-observability/evidence/issue58/recheck/host-outage-reviewed.json
backend/.venv/bin/python scripts/check-monitoring.py --scenario saturation --report docs/milestone9-observability/evidence/issue58/recheck/host-saturation.json
backend/.venv/bin/python scripts/check-monitoring.py --scenario scraper --report docs/milestone9-observability/evidence/issue58/recheck/host-scraper.json
backend/.venv/bin/python scripts/check-monitoring.py --scenario cleanup --report docs/milestone9-observability/evidence/issue58/recheck/host-cleanup.json
backend/.venv/bin/python scripts/check-monitoring-retention.py --report docs/milestone9-observability/evidence/issue58/recheck/retention.json
backend/.venv/bin/python scripts/validate.py --gate backend-unit --no-install
backend/.venv/bin/python scripts/validate.py --gate backend-static --no-install
backend/.venv/bin/python scripts/validate.py --gate baseline --no-install
```

Pure tests: 451 passed. Backend-static and baseline passed. All four native parsers and all fresh runtime scenarios passed, including
physical retention and the specific expected nonzero cleanup outcome. Each
verified owned cleanup. The full scraper stop was 189.943 seconds with a
199.998-second raw sample gap. Both final destination faults reported zero
Collector restarts and the actual 250,000,000-byte memory limit. Final baseline
validation, including secret scanning of the completed evidence, passed. The first fresh outage command began before the additional restart
assertion was written and is retained as `host-outage.json`; the final reviewed
outage command above rechecks with the stronger assertions.

No application/schema/API/dependency changes or developer database migration.
The complete ten-gate PR check is required before merge; local partial checks
alone are not represented as remote CI success or full M9 acceptance.
