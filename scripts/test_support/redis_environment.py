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
        ENVIRONMENT="test",
    )
    return result
