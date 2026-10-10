import asyncio
import json

import pytest

from app.core.logging import JsonFormatter
from app.modules.auth.domain.errors import RateLimitError
from app.modules.auth.rate_limit import ADMIT, AuthLimiter
from app.redis.adapter import FailureKind, RedisFailure
from tests.unit.auth.test_admission import Redis, limiter


@pytest.mark.asyncio
async def test_single_flight_probe_does_not_block_other_requests(unit_settings):
    clock = [1.0]
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.CONNECTION)
    subject = limiter(unit_settings, redis, clock)
    first = await subject.admit(subject.login_buckets("first", "first"))
    await subject.finalize(first, count=False)
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(*args):
        redis.calls.append(args)
        entered.set()
        await release.wait()
        return 0

    redis.execute = blocked
    clock[0] = 6
    probe = asyncio.create_task(subject.admit(subject.login_buckets("probe", "probe")))
    await entered.wait()
    try:
        others = await asyncio.wait_for(
            asyncio.gather(
                *(
                    subject.admit(subject.login_buckets(str(i), str(i)))
                    for i in range(20)
                )
            ),
            1,
        )
        assert all(a.local and a.redis is None for a in others)
        assert len(redis.calls) == 2 and redis.calls[-1][1] == ADMIT
    finally:
        release.set()
        await probe


@pytest.mark.asyncio
async def test_inflight_failure_invalidates_successful_probe(unit_settings):
    clock = [1.0]
    redis = Redis()
    subject = limiter(unit_settings, redis, clock)
    old = await subject.admit(subject.login_buckets("old", "old"))
    redis.failure = RedisFailure(FailureKind.TIMEOUT)
    await subject.admit(subject.login_buckets("outage", "outage"))
    entered, release = asyncio.Event(), asyncio.Event()

    async def overlap(*args):
        if args[-1] == "probe":
            entered.set()
            await release.wait()
            return 0
        raise RedisFailure(FailureKind.TIMEOUT)

    redis.execute = overlap
    clock[0] = 6
    probe = asyncio.create_task(subject.admit(subject.login_buckets("new", "new")))
    await entered.wait()
    try:
        await subject.finalize(old, count=True)
    finally:
        release.set()
        await probe
    assert subject._successes == 0 and subject._degraded_at == 1


@pytest.mark.asyncio
async def test_flapping_logs_transitions_preserves_history_and_requires_three_probes(
    unit_settings, caplog
):
    clock = [1.0]
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.TIMEOUT)
    subject = limiter(unit_settings, redis, clock)
    buckets = subject.login_buckets("private@example.test", "192.0.2.1")
    for _ in range(3):
        await subject.finalize(await subject.admit(buckets), count=True)
    assert len(redis.calls) == 1
    for timestamp, failure in (
        (6, None),
        (11, FailureKind.CONNECTION),
        (16, None),
        (21, None),
        (26, None),
    ):
        clock[0] = timestamp
        redis.failure = RedisFailure(failure) if failure else None
        with pytest.raises(RateLimitError):
            await subject.admit(buckets)
    assert subject._degraded_at is None
    assert all(len(e.failures) == 3 for e in subject._entries.values())
    events = [json.loads(JsonFormatter().format(r)) for r in caplog.records]
    assert [e["event"] for e in events] == [
        "auth_limiter_degraded",
        "auth_limiter_recovering",
        "auth_limiter_degraded",
        "auth_limiter_probe_failed",
        "auth_limiter_recovering",
        "auth_limiter_healthy",
    ]
    assert events[-1]["duration_seconds"] == 25
    assert all(e["process_id"] > 0 for e in events)
    assert "private@example.test" not in json.dumps(events)
    assert "192.0.2.1" not in json.dumps(events)
    # Pair expires at 60, IP history survives until 900; neither mode nor wall
    # clock jumps clear monotonic deadlines already attached to local counters.
    clock[0] = 61
    guarded = await subject.admit(buckets)
    assert guarded.local
    await subject.finalize(guarded, count=False)
    clock[0] = 901
    fresh = await subject.admit(buckets)
    assert not fresh.local and not subject._entries


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, True, -1, b"private result", 1])
async def test_invalid_probe_result_never_establishes_recovery(unit_settings, result):
    clock = [1.0]
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.CONNECTION)
    subject = limiter(unit_settings, redis, clock)
    await subject.admit(subject.refresh_ip("ip"))

    async def invalid(*args):
        return result

    redis.execute = invalid
    clock[0] = 6
    assert (await subject.admit(subject.refresh_ip("ip"))).local
    assert subject._successes == 0


@pytest.mark.asyncio
async def test_memory_pressure_cleanup_and_refresh_atomic_capacity(unit_settings):
    clock = [1.0]
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.CONNECTION)
    unit_settings.auth_local_max_entries = 4
    subject = limiter(unit_settings, redis, clock)
    for i in range(4):
        await subject.finalize(
            await subject.admit(subject.refresh_family(str(i))), count=True
        )
    snapshot = dict(subject._entries)
    for i in range(1000):
        with pytest.raises(RateLimitError) as caught:
            await subject.admit(subject.refresh_family("new-" + str(i)))
        assert caught.value.retry_after > 0
    assert subject._entries == snapshot and len(redis.calls) == 1
    clock[0] = 61
    fresh = await subject.admit(subject.refresh_family("new"))
    assert len(subject._entries) == 1
    await subject.finalize(fresh, count=False)
    buckets = subject.refresh_family("family") + subject.refresh_ip("ip")
    results = await asyncio.gather(
        *(subject.admit(buckets) for _ in range(20)), return_exceptions=True
    )
    assert sum(not isinstance(r, BaseException) for r in results) == 5
    assert all(len(e.reservations) == 5 for e in subject._entries.values())


@pytest.mark.asyncio
async def test_local_expiry_uses_monotonic_clock_despite_wall_jump(unit_settings):
    clock, wall = [1.0], [1.0]
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.CONNECTION)
    subject = AuthLimiter(
        unit_settings, lambda: redis, monotonic=lambda: clock[0], wall=lambda: wall[0]
    )
    buckets = subject.login_buckets("email", "ip")
    for _ in range(3):
        await subject.finalize(await subject.admit(buckets), count=True)
    wall[0] = 100000
    with pytest.raises(RateLimitError):
        await subject.admit(buckets)
    wall[0] = -100000
    with pytest.raises(RateLimitError):
        await subject.admit(buckets)


@pytest.mark.asyncio
async def test_local_refresh_ip_limit_counts_attempts_and_release_excludes_errors(
    unit_settings,
):
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.CONNECTION)
    subject = limiter(unit_settings, redis, [1.0])
    buckets = subject.refresh_ip("ip")
    for _ in range(50):
        # Successful/server-error cleanup releases only this reservation and
        # never clears earlier client-originated attempt history.
        await subject.finalize(await subject.admit(buckets), count=False)
        await subject.finalize(await subject.admit(buckets), count=True)
    with pytest.raises(RateLimitError):
        await subject.admit(buckets)
    assert len(redis.calls) == 1
    assert len(next(iter(subject._entries.values())).failures) == 50


@pytest.mark.asyncio
async def test_ambiguous_finalize_counts_new_pair_with_surviving_ip_guard(
    unit_settings,
):
    clock = [1.0]
    redis = Redis()
    redis.failure = RedisFailure(FailureKind.CONNECTION)
    subject = limiter(unit_settings, redis, clock)
    old = subject.login_buckets("old", "shared")
    await subject.finalize(await subject.admit(old), count=True)
    redis.failure = None
    for timestamp in (6, 11, 16):
        clock[0] = timestamp
        await subject.finalize(
            await subject.admit(subject.login_buckets("recovery", "other")), count=False
        )
    assert subject._degraded_at is None
    fresh = subject.login_buckets("new", "shared")
    admission = await subject.admit(fresh)
    assert admission.local and fresh[0].key not in subject._entries
    before = len(redis.calls)
    redis.failure = RedisFailure(FailureKind.TIMEOUT)
    await subject.finalize(admission, count=True)
    assert len(subject._entries[fresh[0].key].failures) == 1
    assert len(subject._entries[fresh[1].key].failures) == 2
    assert len(redis.calls) == before + 1
