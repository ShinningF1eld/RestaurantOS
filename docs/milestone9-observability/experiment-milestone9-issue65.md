# Issue #65 local baseline experiment declaration

Declared on 2026-11-19 before workload execution. The source starts at
`bb01d8cd8e0d8a869538f69cdec5f09acbc7967e`. This is the T8 local demo baseline.

- Each run starts with an empty disposable PostgreSQL/Redis project, applies the
  committed migrations, and uses one synthetic Owner, one restaurant, one menu,
  four THB items and one tracked ingredient. The measured item costs 12.50 and
  consumes one piece. Opening stock and the reorder threshold are one piece.
- Two independent paced lanes share a start time. The read lane starts one request
  every 500 ms and rotates through menus, menu items, inventory, dashboard analytics
  and authenticated menu SSR. The command lane starts one workflow every five
  seconds. It receives one piece, creates a draft, submits, accepts, prepares,
  marks ready, completes and submits a deliberately mismatched create replay
  (expected 409). Each lane has at most one request in flight. Late starts retain
  their original schedule and are reported. Requests are never retried.
- Warm up for 30 seconds (60 reads, six workflows) and measure for 90 seconds
  (180 reads, 18 workflows). In the measured phase this schedules 324 requests
  (180 reads, 126 successful commands and 18 expected conflicts). Start a fresh
  environment for each of three pairs, ordered off/on, on/off, off/on. Use the same
  application images, data shape, workload and settings except telemetry. A failed
  repetition is retained with its stage and is excluded from healthy comparisons.
- Off uses the API, standalone Next.js frontend, worker, PostgreSQL and Redis.
  On adds the five locked monitoring services, enables API and worker metrics,
  tracing and log export, Next.js tracing, business aggregates at 30 seconds and
  THB opt-in, and worker slot 0. Both arms use normal runtime pools over local
  loopback HTTP. Incoming trace context is not needed for sampling. Enabled
  runtime samplers stay at 100%. Use default application telemetry and worker
  settings for everything else. No concurrent developer or test containers.
- Measure full HTTP response latency (including SSR HTML) in milliseconds. Use
  PostgreSQL transaction commit timestamps for outbox-to-consumer-receipt deltas
  in seconds. `track_commit_timestamp` is enabled only in the disposable database
  server, in both arms. Allow 30 seconds to drain and reconcile all workload
  effects. Compare PostgreSQL activity and queued work in both arms, and inspect
  available Prometheus pool, queue and Collector counters in the on arm.
- Sample Docker container working sets, CPU and VM memory headroom approximately
  every five seconds during the workload. Record monitor volume and PostgreSQL
  data sizes, and Docker disk headroom. Report the load driver's resources
  separately from the Docker VM. Short-lived setup and observation helpers and
  VM overhead are considered separately from the five monitoring limits.
- Preserve sanitized per-request and per-effect records, sample timestamps, source
  and image identities, settings, failures, and reconciliation. No credentials,
  response bodies, application IDs, or raw spans/logs are part of the report.
