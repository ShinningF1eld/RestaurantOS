# Issue #58 — local monitoring foundation verification

Recorded 2026-11-01 (Asia/Bangkok). Local implementation; no push, issue closure,
remote CI or deployment. GitHub issue #58 was fetched again on this date; its six
acceptance criteria match task-plan revision 1. Current M9 is observability;
historical `docs/milestone9/` deployment is current M15.

Status: local T1 implementation and six-criterion evidence complete, with a
retained strict-pacing failure alongside four passing resource trials. This is
synthetic foundation evidence, not full M9 or consistently uninterrupted pacing
acceptance. Source/config hashes, failures and limitations remain visible.

## Evidence against the six issue criteria

| Criterion | Implementation and evidence |
|---|---|
| Five immutable images and three signals through Grafana | `monitoring/images.lock.json`, five-service Compose and native parsers; `step4-grafana.json`, final `step9-fixed-host-smoke.json` and `step9-fixed-container-smoke.json`. Authenticated Grafana proxy queries reconcile the counter/histogram, all generated logs and windowed trace IDs, plus a parent-child trace/log correlation. Anonymous source access returns 401. |
| Bounded prototype, resources, counts and failure reporting | [Protocol/results](performance-milestone9-issue58.md), `benchmark-monitoring.py` and four retained Step 9 reports. Fixed 2,000,000,000-byte total, actual engine limits, sampled per-service/concurrent aggregate memory and CPU, volume allocation/growth and exact workload counts. Initial Grafana OOM attempts are retained; the allocation was revised within the same total. |
| Both workflows, loopback access and private authentication | [Operator runbook](../runbooks/monitoring.md), base/host Compose and `local-monitoring.py`. Only UI and host ingestion publish loopback ports; stores remain internal. Container acceptance uses a private network and only ephemeral Grafana access. `step6-lifecycle.json` and both corrected-profile smoke reports. |
| Retention, persistence and initial disk budget | Seven-day Prometheus and 72-hour Loki/Tempo cleanup. `step7-host-restart.json` preserves known metrics/logs/traces across down/up. `step8-retention.json` proves old stored data physically removed and recent controls preserved. [Disk budget](performance-milestone9-issue58.md) is an initial planning allowance, not a byte quota. |
| Bounded queues/retries, destination failure and freshness | Collector 4 MiB queues per log/trace exporter with finite waits/retry sequences. `step7-host-outage.json` stops Loki/Tempo for 180 seconds each; exporter failures rise without Collector OOM and fresh data recovers. `step7-saturation.json` deliberately uses smaller test queues and observes enqueue rejection. `step3-smoke.json` checks stale-series expiry; scraper evidence records real missing raw samples. |
| Owned lifecycle, developer persistence, sampling and compatibility | Exact-label test teardown, private state and test/development identity guards; intentional nonzero `step7-host-cleanup.json` still verifies cleanup. Developer deletion is rejected; normal down retains volumes. [Configuration guide](../../monitoring/README.md) records applied limits, 100% synthetic trace emission and versioned receiver compatibility. PostgreSQL/Redis receivers remain disabled pending #61. |

Evidence files are in [the issue58 directory](evidence/issue58/). Acknowledged
OTLP requests are not equated with downstream storage or Prometheus scrape counts.
Two-span totals follow the deterministic producer's fixture; backend trace-ID
counts are exhaustive within bounded search windows and parentage is spot-checked.
No claim is made that every stored span was independently enumerated.

## Failure evidence and boundaries

The first internal-only host bridge failed published connectivity; a second
host-ingress bridge for Collector/Grafana fixed it. Grafana's original 350 MB
allocation failed startup, including a confirmed OOM; a Go target alone failed.
The final split is Collector 250 MB, Prometheus 300 MB, Grafana 650 MB and
Loki/Tempo 400 MB each, preserving the 2 GB total. Both failures remain retained.

Retention fixtures initially failed because Tempo's normal WAL window made the
backdated block current, and because Loki WAL replay kept an old record visible.
The corrected test-only profile widens the timestamp window and waits for zero
hot chunks plus a completed new checkpoint. Retention durations stay unchanged.
The passing run requires physical old-file deletion, absent old queries and
surviving recent controls; no clocks or application data were changed.

Two initial resource candidates passed, but Grafana's default preinstallation
had downloaded unpinned plugins. They are retained as uncontrolled candidates,
not final fixed-profile resource acceptance. The second container candidate was
intentionally interrupted and verified cleanup. Automatic preinstallation and
startup updates were then disabled; final trials require an empty plugin directory.
The corrected protocol and candidate report identities are retained separately.

Corrected container repetition 2 generated all 3,600 operations and acknowledged
all 1,809 requests, but one pacing miss exceeded the strict 50 ms threshold. The
attempt correctly failed before final storage/resource reconciliation and
verified cleanup. It is retained; an identical retry uses a distinct path. The
cause is unestablished and the tolerance is unchanged. Passing retries do not
prove uninterrupted timing reliability; the resource report keeps this failure
separate and visible.

The resource observer initially encountered terminal-control frames in Docker's
JSON output. A preflight regression and native observer smoke handle those
frames explicitly; malformed measurements still fail. This was corrected before
the declared timed trials. No failed workload is discarded or silently shortened.

The initial experiment requested one-second samples; actual intervals/gaps are
reported rather than asserted. Docker working-set values are rounded/cache
adjusted and sampled peaks are not continuous maxima. Startup peaks before
readiness and host-observer RSS are unmeasured. Temporary producer/readers are
outside the five-container sum; CPU is shared with the host and not isolated.
No memory or throughput ceiling for application workloads is established.

The original scraper plan requested 180 seconds; Step 7's first passing fixture
used 30 seconds and is retained as shorter evidence. The full `step10-scraper-180.json` then passed with 189.935 seconds stopped,
a 205-second raw scrape gap and verified cleanup. Fault telemetry may be lost;
export failure counters do not establish an exact loss ledger across restarts.

Earlier restart/destination/saturation/retention reports precede the Grafana
plugin-preinstallation correction; the Collector/store configurations and image
pins did not change. Both connection-mode smokes, the full scraper check and the
four final resource trials use the corrected profile. Every report retains its
own input hashes; these distinct runs are not represented as one identical run.

## Validation commands and outcomes

Baseline, backend-static and backend-unit passed (446 pure tests); the native
Collector/Prometheus/Loki/Tempo parsers passed. Static includes all monitoring
helpers; baseline renders both Compose models without runtime credentials.
The final unit/static runs after the resource trials passed again. The final baseline rerun with all completed reports also passed. The application image gate passed
before the resource trials with:

```sh
backend/.venv/bin/python scripts/validate.py --gate image --no-install
```

Its disposable PostgreSQL/Redis and API/worker/frontend image checks completed
and cleaned up; application Dockerfiles and dependencies were unchanged.
The focused commands are:

```sh
backend/.venv/bin/python scripts/check-monitoring-config.py
backend/.venv/bin/python scripts/validate.py --gate baseline --no-install
backend/.venv/bin/python scripts/validate.py --gate backend-static --no-install
backend/.venv/bin/python scripts/validate.py --gate backend-unit --no-install
```

[The testing guide](../testing/monitoring.md) lists exact runtime scenario commands,
retention and resource reproduction. `cleanup` intentionally exits nonzero; its
intended interruption and verified cleanup are required. The other completed
scenarios require exit zero and passed reports. The source/config hashes and
sanitized counts are retained with results; private credentials are not.

These are focused local `--no-install` checks using committed dependencies, not
the full ten-gate milestone run. Backend integration, migrations, frontend tests,
frontend static/build and browser gates were not rerun: no application behavior,
schema, frontend code or dependency lock changed. The image gate separately
exercised runtime packaging. CI's ten gates and required `Milestone 6 acceptance`
name remain unchanged. Remote CI, native AMD64 execution and Windows runtime behavior were not verified.

No developer application database was selected or migrated; developer monitoring state was
not initialized, and no application schema, HTTP API or dependency lock changed.
Named telemetry volumes have no backup commitment or hard byte quota. Images and
build cache may remain after disposable resource cleanup. This establishes only
T1's local synthetic foundation; #59–#67 and M9's application/worker correlation,
operational dashboard, objectives and incident acceptance remain outstanding.

## File walkthrough for the remaining implementation steps

| File or related files | What changed, why it exists, and expected behavior |
|---|---|
| `monitoring/grafana/provisioning/datasources/datasources.yaml` | Declares the three internal proxy sources with stable UIDs and read-only provisioning. Grafana can query each store and link trace IDs to logs. The double dollar in the trace expression survives Grafana's environment expansion. |
| `monitoring/compose.yaml` | Supplies actual memory/swap limits and private Grafana credential mounts. Startup OOM evidence led to reallocation within the same total. Later inspection disabled unpinned automatic plugin downloads; repeatable startup uses only the image's bundled data sources. |
| `scripts/generate-monitoring-telemetry.py` | Builds deterministic OTLP JSON using only the standard library. Each operation creates one correlated log, a root/child trace, and cumulative metric observations. Byte-based payload splitting respects the receiver limit; uncertain transport is counted without replay. An explicit warmup event separates measurement phases. |
| `monitoring/synthetic/Dockerfile` and `Dockerfile.dockerignore` | Package that same producer as nonroot on the pinned Python base. The narrow build context excludes application files, environments and secrets. Container acceptance exercises the private OTLP path without a permanent sixth service. |
| `backend/tests/unit/test_monitoring_generator.py` | Checks fixture identities, counter/histogram values, payload/argument limits and uncertain failures without services. A complete acknowledgement summary still needs independent storage reconciliation. |
| `scripts/test_support/monitoring_environment.py` | Owns state, credentials, project identity, readiness, queries and teardown. Development shutdown retains volumes; disposable cleanup checks exact project labels. Local-engine rejection now occurs before callers can build/create test resources. |
| `scripts/local-monitoring.py` and `.gitignore` | Expose init/config/up/status/down and keep private local state untracked. Initialization refuses replacement; shutdown never asks to delete developer volumes. |
| `backend/tests/unit/test_monitoring_lifecycle.py` | Protects initialization, identity tampering, developer deletion refusal, finally cleanup and remote-context rejection before state creation. These critical safety checks do not call Docker. |
| `scripts/check-monitoring.py` | Exercises actual host/container delivery, restart, destination outage, missing scrape history, reduced queues and intentional failure cleanup. It queries stores through authenticated Grafana rather than treating HTTP admission as delivery. The full scraper fixture records actual stopped time and raw sample gaps. |
| `scripts/check-monitoring-config.py` and `backend/tests/unit/test_monitoring_config.py` | Run exact locked service parsers without network, with named cleanup on timeout/error. Pure regressions protect required pipeline/provisioning behavior and cleanup failures; local-engine rejection applies before parser containers start. |
| `scripts/check-monitoring-retention.py` | Creates genuinely old stored records, proves they exist, then observes physical cleanup and surviving recent controls. This distinguishes retention from ingestion rejection or a hidden query result. It is restricted to disposable test ownership. |
| `monitoring/testing/retention.yaml` and `backend/tests/unit/test_monitoring_retention.py` | Accelerate only isolated cleanup/checkpoint timing and backdated Tempo admission. Production durations remain seven days/72 hours. Regressions protect duration preservation and refusal of developer-owned fixtures. |
| `scripts/benchmark-monitoring.py` and `backend/tests/unit/test_monitoring_benchmark.py` | Implement the fixed timed trials, native stats decoding, disk snapshots, source fingerprints and post-load reconciliation. Unknown/ambiguous data fails. Raw samples make summary calculations inspectable; memory/CPU peaks remain sampled estimates. |
| `backend/tests/unit/test_monitoring_compose.py` | Protects image/budget consistency, loopback-only publication, internal/project-owned resources and strict mounts. The added startup-plugin regression prevents reintroducing the uncontrolled download input. |
| `scripts/validate.py` and `backend/tests/unit/test_validation_policy.py` | Include all monitoring helpers in static checks and render both Compose models in baseline with a temporary placeholder directory. The regression requires both models and excludes ambient credential paths, while preserving all ten gates and the acceptance aggregate. |
| `monitoring/README.md`, `docs/runbooks/monitoring.md`, `docs/testing/monitoring.md` | Separate current configuration concepts, operator workflow and exact repeatable verification commands. They explain disposable queues, freshness, credentials, ownership and retention limits without implying application instrumentation already exists. |
| `experiment-milestone9-issue58.md`, `performance-milestone9-issue58.md`, `implementation-issue58.md`, this review and `evidence/issue58/` | Preserve the initial declaration, measured results, implementation reasoning, criterion mapping and raw successes/failures. Historical expectations are not silently rewritten as measured facts. |
| Root `README.md`, `docs/current-state.md`, `docs/testing/README.md` and `RestaurantOS_Master_Roadmap.md` | Point readers to the optional foundation and dated evidence. Current T1 status is separated from historical deployment work and the unfinished application/incident M9 criteria. |


## Local implementation commits

| Plan step | Local commit | Result |
|---|---|---|
| 1 | `394ac80` | Experiment and image inventory |
| 2 | `1875fef` | Isolated Compose topology |
| 3 | `f004bfb` | Bounded signal pipelines |
| 4 | `a75211b` | Authenticated provisioned Grafana sources |
| 5 | `4947fbd` | Deterministic host/container producer |
| 6 | `7375cb7` | Owned lifecycle and private state |
| 7 | `156ee7e` | Delivery/restart/failure checks |
| 8 | `468128c` | Physical aged-fixture retention |
| 9 | `ff1d3a4` | Fixed resource profile, retained failures and disk allowance |
| 10 | This verification/documentation commit | Shared validation integration and handoff |

The resource reports record base `468128c` plus measured working-tree input
hashes. Step 9 committed those inputs; the evidence does not falsely identify
that later commit as the base used when the experiment started. Source hashes
were checked against the measured working tree before commit. No push occurred.
