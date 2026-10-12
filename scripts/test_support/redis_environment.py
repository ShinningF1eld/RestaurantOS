"""Explicit disposable Redis configuration, never ambient application targets."""

from uuid import uuid4


def redis_environment(base):
    result = dict(base)
    host = result.get("TEST_REDIS_HOST")
    port = result.get("TEST_REDIS_PORT")
    if host not in {"127.0.0.1", "localhost", "::1", "redis"} or not port:
        raise ValueError("Explicit isolated TEST_REDIS_HOST/PORT required")
    try:
        valid = 0 < int(port) <= 65535
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Invalid test Redis port")
    authority = f"[{host}]" if host == "::1" else host
    result.update(
        REDIS_URL=f"redis://{authority}:{port}/0",
        REDIS_OPERATION_BUDGET_MS="100",
        REDIS_MAX_CONNECTIONS="20",
        REDIS_TEST_NAMESPACE="run-" + uuid4().hex,
        EVENT_WORKER_REDIS_OPERATION_BUDGET_MS="2000",
        EVENT_WORKER_REDIS_BLOCK_MS="1000",
        EVENT_WORKER_REDIS_MAX_CONNECTIONS="8",
        EVENT_WORKER_CLAIM_BATCH_SIZE="10",
        EVENT_WORKER_RELAY_CONCURRENCY="2",
        EVENT_WORKER_CLAIM_LEASE_SECONDS="30",
        EVENT_WORKER_RECOVERY_SCAN_INTERVAL_MS="1500",
        EVENT_WORKER_RECOVERY_BATCH_SIZE="10",
        EVENT_WORKER_REPUBLISH_STALL_SECONDS="60",
        EVENT_WORKER_PENDING_IDLE_MS="60000",
        EVENT_WORKER_INFRA_BACKOFF_INITIAL_MS="1000",
        EVENT_WORKER_INFRA_BACKOFF_MAX_MS="30000",
        EVENT_WORKER_SHUTDOWN_GRACE_SECONDS="10",
        ENVIRONMENT="test",
    )
    return result
