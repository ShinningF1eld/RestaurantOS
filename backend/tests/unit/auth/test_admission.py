import asyncio
import json

import pytest

from app.core.logging import JsonFormatter
from app.modules.auth.domain.errors import RateLimitError
from app.modules.auth.rate_limit import ADMIT, FINALIZE, AuthLimiter, Bucket
from app.redis.adapter import FailureKind, RedisFailure


class Redis:
    def __init__(self):
        self.calls = []
        self.failure = None

    def namespace(self, *_):
        return "restaurantos:test:owned:auth:v1:"

    async def execute(self, *args):
        self.calls.append(args)
        if self.failure:
            raise self.failure
        return 0


def limiter(settings, redis, clock):
    return AuthLimiter(
        settings, lambda: redis, monotonic=lambda: clock[0], wall=lambda: clock[0]
    )


@pytest.mark.asyncio
async def test_redis_identifiers_and_atomic_two_bucket_operation(unit_settings):
    redis = Redis()
    subject = AuthLimiter(unit_settings, lambda: redis)
    buckets = subject.login_buckets("private@example.test", "192.0.2.12")
    admission = await subject.admit(buckets)
    assert redis.calls[0][0:3] == ("EVAL", ADMIT, 2)
    assert [(b.maximum, b.window) for b in buckets] == [(5, 60), (30, 900)]
    await subject.finalize(admission, count=True)
    assert redis.calls[1][1] == FINALIZE
    assert "private@example.test" not in repr(redis.calls)
    assert "192.0.2.12" not in repr(redis.calls)


@pytest.mark.asyncio
async def test_ambiguous_admission_immediate_atomic_local_quota_and_expiry(
    unit_settings,
):
    clock = [1.0]
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.TIMEOUT)
    subject = limiter(unit_settings, redis, clock)
    buckets = subject.login_buckets("a", "ip")
    results = await asyncio.gather(
        *(subject.admit(buckets) for _ in range(12)), return_exceptions=True
    )
    admissions = [r for r in results if not isinstance(r, BaseException)]
    assert len(admissions) == 3
    assert sum(isinstance(r, RateLimitError) for r in results) == 9
    assert len(redis.calls) == 1
    for entry in subject._entries.values():
        assert len(entry.reservations) == 3
    clock[0] = 12
    another = await subject.admit(buckets)
    await subject.finalize(another, count=False)
    # Expired leases cannot finalize into failures.
    for admission in admissions:
        await subject.finalize(admission, count=True)
    assert not subject._entries


@pytest.mark.asyncio
async def test_local_ip_quota_cross_pair_and_success_preserves_failures(unit_settings):
    clock = [1.0]
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.CONNECTION)
    subject = limiter(unit_settings, redis, clock)
    for i in range(9):
        admission = await subject.admit(subject.login_buckets(str(i), "shared"))
        await subject.finalize(admission, count=True)
    success = await subject.admit(subject.login_buckets("good", "shared"))
    await subject.finalize(success, count=False)
    last = await subject.admit(subject.login_buckets("last", "shared"))
    await subject.finalize(last, count=True)
    with pytest.raises(RateLimitError):
        await subject.admit(subject.login_buckets("fresh", "shared"))
    # A different source IP does not share the pair or IP quota.
    other = await subject.admit(subject.login_buckets("last", "other"))
    await subject.finalize(other, count=False)


@pytest.mark.asyncio
async def test_fixed_window_boundary_does_not_remove_active_reservations(unit_settings):
    clock = [59.0]
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.CONNECTION)
    subject = limiter(unit_settings, redis, clock)
    buckets = subject.login_buckets("a", "ip")
    failure = await subject.admit(buckets)
    await subject.finalize(failure, count=True)
    active = await subject.admit(buckets)
    clock[0] = 61
    await subject.admit(buckets)
    await subject.admit(buckets)
    with pytest.raises(RateLimitError):
        await subject.admit(buckets)
    await subject.finalize(active, count=False)


@pytest.mark.asyncio
async def test_memory_guard_and_recovery_preserve_live_local_history(
    unit_settings, caplog
):
    clock = [1.0]
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.CONNECTION)
    unit_settings.auth_local_max_entries = 2
    subject = limiter(unit_settings, redis, clock)
    buckets = subject.login_buckets("a", "ip")
    for _ in range(3):
        admission = await subject.admit(buckets)
        await subject.finalize(admission, count=True)
    with pytest.raises(RateLimitError):
        await subject.admit(subject.login_buckets("other", "other"))
    redis.failure = None
    for timestamp in (6, 11, 16):
        clock[0] = timestamp
        with pytest.raises(RateLimitError):
            await subject.admit(buckets)
    assert subject._degraded_at is None
    assert len(subject._entries) == 2
    fresh = await subject.admit(subject.login_buckets("fresh", "other"))
    assert not fresh.local
    await subject.finalize(fresh, count=False)
    events = [json.loads(JsonFormatter().format(record)) for record in caplog.records]
    assert any(e.get("event") == "auth_limiter_healthy" for e in events)
    assert all("process_id" in e and "reason" in e for e in events)


@pytest.mark.asyncio
async def test_ambiguous_failure_finalization_is_not_retried(unit_settings):
    redis = Redis()
    subject = limiter(unit_settings, redis, [1.0])
    admission = await subject.admit(subject.login_buckets("a", "ip"))
    redis.failure = RedisFailure(FailureKind.TIMEOUT)
    await subject.finalize(admission, count=True)
    assert len(redis.calls) == 2
    assert all(len(e.failures) == 1 for e in subject._entries.values())


def test_refresh_local_and_shared_quotas(unit_settings):
    subject = AuthLimiter(unit_settings, lambda: Redis())
    family = subject.refresh_family("family")[0]
    ip = subject.refresh_ip("ip")[0]
    assert (family.maximum, family.local_maximum, family.window) == (10, 5, 60)
    assert (ip.maximum, ip.local_maximum, ip.window) == (100, 50, 60)


@pytest.mark.asyncio
async def test_local_two_bucket_rejection_reserves_neither_bucket(unit_settings):
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.CONNECTION)
    subject = limiter(unit_settings, redis, [1.0])
    buckets = (Bucket("pair", 1, 1, 60), Bucket("ip", 3, 3, 900))
    await subject.admit(buckets)
    with pytest.raises(RateLimitError):
        await subject.admit(buckets)
    assert len(subject._entries["ip"].reservations) == 1
