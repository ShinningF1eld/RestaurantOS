# Issue #58 implementation checkpoints

These steps refer to the ten-step implementation plan for issue #58, not the
ten separate M9 issues. Work stays local; no push or issue closure is authorized.

## Step 4 — Grafana provisioning, 2026-11-01

Provisioned three stable data sources with internal proxy URLs and trace/log
links. Grafana's own provisioning expansion requires the escaped trace expression
`$${__value.raw}`. A temporary authenticated five-container smoke confirmed all
three source health checks and real metric/log/trace queries through Grafana.
Anonymous data-source access returned 401. All five nonroot processes retained
their declared memory/swap limits and had zero observed OOM/restarts on the final
run; its project-owned volumes/networks/containers were removed.

The original Grafana 350 MB allocation failed (exit 137; OOM confirmed on the
second run). Adding a 280 MB Go target alone also failed. Preserved failures and
the successful result are under `evidence/issue58/step4-*.json`. Before the final
run, the same 2 GB total was reallocated: Collector 250 MB, Prometheus 300 MB,
Grafana 650 MB, Loki/Tempo 400 MB each. Collector's limiter is now 160 MiB with a
200 MB Go target; Grafana's Go target is 420 MB. No image pins changed.

The targeted configuration suite passed six checks. The temporary smoke command
was `backend/.venv/bin/python -u /tmp/restaurantos-step4-smoke.py`; its durable
replacement follows in Step 7. Credentials existed only in a private temporary
directory. Persistent secret initialization follows in Step 6. Grafana Explore
was verified through authenticated source-proxy APIs; no rendered UI evidence or
four operational dashboards are claimed. Sustained capacity remains Step 9.
