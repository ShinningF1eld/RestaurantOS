"""Real Redis atomicity and PostgreSQL auth effects, coordinated without sleeps."""

import asyncio
import json
import threading

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from app.core.logging import JsonFormatter
from app.main import app
from app.modules.auth import deadline, service, security
from app.modules.auth.domain.errors import AuthenticationError, RateLimitError
from app.modules.auth.rate_limit import Bucket
from conftest import engine

HEADERS = {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}


def scalar(query, **params):
    with engine.begin() as connection:
        return connection.execute(text(query), params).scalar_one()


async def state(subject, buckets):
    redis = subject._redis()
    return [
        await redis.execute("ZRANGE", redis.namespace("auth", 1) + b.key, 0, -1)
        for b in buckets
    ]


def capture_timer(monkeypatch):
    timers = []
    original = deadline.create_timeout

    def factory(seconds):
        assert seconds == 8
        timer = original(seconds)
        timers.append(timer)
        return timer

    monkeypatch.setattr(deadline, "create_timeout", factory)
    return timers


def test_real_redis_ip_admission_across_distinct_pairs():
    async def scenario():
        async with app.router.lifespan_context(app):
            subject = app.state.auth_limiter
            from tests.support.redis_ready import warm_redis

            await warm_redis(subject._redis())
            pairs = [
                (Bucket("pair-" + str(i), 5, 3, 60), Bucket("shared-ip", 3, 2, 900))
                for i in range(8)
            ]
            results = await asyncio.gather(
                *(subject.admit(b) for b in pairs), return_exceptions=True
            )
            accepted = [a for a in results if not isinstance(a, BaseException)]
            assert len(accepted) == 3
            assert sum(isinstance(a, RateLimitError) for a in results) == 5
            redis = subject._redis()
            for pair, result in zip(pairs, results):
                pair_count = await redis.execute(
                    "ZCARD", redis.namespace("auth", 1) + pair[0].key
                )
                assert pair_count == (0 if isinstance(result, RateLimitError) else 1)
            for admission in accepted:
                await subject.finalize(admission, count=True)
                await subject.finalize(
                    admission, count=True
                )  # Finalization is idempotent.
            values = await state(subject, (pairs[0][1],))
            assert len(values[0]) == 3 and all(v.startswith(b"f:") for v in values[0])

    asyncio.run(scenario())


def test_real_redis_expired_leases_and_fixed_windows():
    async def scenario():
        async with app.router.lifespan_context(app):
            subject = app.state.auth_limiter
            buckets = (Bucket("lease-pair", 1, 1, 60), Bucket("lease-ip", 1, 1, 900))
            first = await subject.admit(buckets)
            redis = subject._redis()
            keys = [redis.namespace("auth", 1) + b.key for b in buckets]
            # Advance stored expiry deterministically; server TIME remains real.
            for key in keys:
                assert 0 < await redis.execute("PTTL", key) <= 10000
                await redis.execute("ZADD", key, 0, "r:" + first.id)
            second = await subject.admit(buckets)
            await subject.finalize(first, count=True)
            await subject.finalize(second, count=True)
            for key, bucket in zip(keys, buckets):
                values = await redis.execute("ZRANGE", key, 0, -1, "WITHSCORES")
                assert len(values) == 1
                member, score = values[0]
                assert int(score) % (bucket.window * 1000) == 0
                # Simulate reaching the fixed boundary without a timed sleep.
                await redis.execute("ZADD", key, 0, member)
            next_admission = await subject.admit(buckets)
            await subject.finalize(next_admission, count=False)
            assert await state(subject, buckets) == [[], []]

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["wrong", "unknown", "disabled"])
def test_equal_failures_service_normalization_and_generic_throttle(
    auth_user, monkeypatch, outcome
):
    if outcome == "disabled":
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET status='disabled' WHERE id=:id"), auth_user
            )

    async def scenario():
        async with app.router.lifespan_context(app):
            subject = app.state.auth_limiter
            email = (
                auth_user["email"] if outcome != "unknown" else "absent@example.test"
            )
            for _ in range(5):
                with pytest.raises(AuthenticationError):
                    await service.login(
                        "  " + email.upper() + "  ",
                        auth_user["password"]
                        if outcome == "disabled"
                        else "wrong password long enough",
                        "192.0.2.1",
                    )
            values = await state(subject, subject.login_buckets(email, "192.0.2.1"))
            assert all(
                len(v) == 5 and all(m.startswith(b"f:") for m in v) for v in values
            )
            with pytest.raises(RateLimitError) as limited:
                await service.login(email, auth_user["password"], "192.0.2.1")
            assert limited.value.retry_after > 0
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("192.0.2.1", 123)),
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    "/auth/login",
                    headers=HEADERS,
                    json={"email": email, "password": auth_user["password"]},
                )
            assert response.status_code == 429
            assert response.json() == {"detail": "Too many attempts"}
            assert int(response.headers["retry-after"]) > 0
            assert email not in response.text and "192.0.2.1" not in response.text

    asyncio.run(scenario())
    assert scalar("SELECT count(*) FROM auth_rate_limit_buckets") == 0


def test_success_does_not_clear_either_failure_bucket(auth_user):
    async def scenario():
        async with app.router.lifespan_context(app):
            subject = app.state.auth_limiter
            with pytest.raises(AuthenticationError):
                await service.login(
                    auth_user["email"], "wrong password long enough", "ip"
                )
            await service.login(auth_user["email"], auth_user["password"], "ip")
            assert all(
                len(v) == 1
                for v in await state(
                    subject, subject.login_buckets(auth_user["email"], "ip")
                )
            )

    asyncio.run(scenario())
    assert scalar("SELECT count(*) FROM auth_sessions") == 1
    assert scalar("SELECT count(*) FROM auth_rate_limit_buckets") == 0


@pytest.mark.parametrize("abandon", ["deadline", "cancel"])
def test_late_native_password_completion_cannot_authenticate(
    auth_user, monkeypatch, abandon
):
    timers = capture_timer(monkeypatch)

    async def scenario():
        async with app.router.lifespan_context(app):
            entered, finished = asyncio.Event(), asyncio.Event()
            release = threading.Event()
            loop = asyncio.get_running_loop()
            original = security._hasher.verify_and_update

            def blocked(*args):
                result = original(*args)
                loop.call_soon_threadsafe(entered.set)
                release.wait(6)
                loop.call_soon_threadsafe(finished.set)
                return result

            monkeypatch.setattr(security._hasher, "verify_and_update", blocked)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                task = asyncio.create_task(
                    client.post(
                        "/auth/login",
                        headers=HEADERS,
                        json={
                            "email": auth_user["email"],
                            "password": auth_user["password"],
                        },
                    )
                )
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    if abandon == "deadline":
                        timers[-1].reschedule(loop.time())
                        response = await task
                        assert response.status_code == 503
                        assert response.json() == {
                            "detail": "Authentication service unavailable"
                        }
                        assert "set-cookie" not in response.headers
                    else:
                        task.cancel()
                        response = await task
                        assert response.status_code == 503
                        assert response.json() == {
                            "detail": "Authentication service unavailable"
                        }
                        assert "set-cookie" not in response.headers
                    assert scalar("SELECT count(*) FROM auth_sessions") == 0
                    assert await state(
                        app.state.auth_limiter,
                        app.state.auth_limiter.login_buckets(
                            auth_user["email"], "127.0.0.1"
                        ),
                    ) == [[], []]
                finally:
                    release.set()
                    await asyncio.wait_for(finished.wait(), 5)
                assert scalar("SELECT count(*) FROM auth_sessions") == 0
                assert (
                    "ros_access" not in client.cookies
                    and "ros_refresh" not in client.cookies
                )

    asyncio.run(scenario())


def test_delayed_commit_acknowledgement_no_credentials_and_normal_cleanup(
    auth_user, monkeypatch, caplog
):
    timers = capture_timer(monkeypatch)
    original = AsyncSessionTransaction.__aexit__

    async def delayed_ack(transaction, *args):
        result = await original(transaction, *args)
        if args[0] is None:
            assert scalar("SELECT count(*) FROM auth_sessions") == 1
            timers[-1].reschedule(asyncio.get_running_loop().time())
            await asyncio.Event().wait()
        return result

    monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", delayed_ack)

    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/auth/login",
                    headers=HEADERS,
                    json={
                        "email": auth_user["email"],
                        "password": auth_user["password"],
                    },
                )
                assert (
                    response.status_code == 503 and "set-cookie" not in response.headers
                )
                assert (await client.get("/auth/me")).status_code == 401
                assert all(
                    not v
                    for v in await state(
                        app.state.auth_limiter,
                        app.state.auth_limiter.login_buckets(
                            auth_user["email"], "127.0.0.1"
                        ),
                    )
                )
            monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", original)
            from app.modules.auth.cli import cleanup

            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE auth_sessions SET created_at=now()-interval '8 days', expires_at=now()-interval '1 second'"
                    )
                )
            assert await cleanup() == 1

    asyncio.run(scenario())
    assert scalar("SELECT count(*) FROM auth_sessions") == 0
    assert scalar("SELECT count(*) FROM auth_refresh_tokens") == 0
    events = [json.loads(JsonFormatter().format(r)) for r in caplog.records]
    assert any(
        e.get("event") == "auth_commit_uncertain" and e.get("reason") == "deadline"
        for e in events
    )
    assert auth_user["password"] not in repr(events) and auth_user["email"] not in repr(
        events
    )


def test_cancellation_during_session_creation_rolls_back_and_releases(
    auth_user, monkeypatch
):
    async def scenario():
        entered = asyncio.Event()
        original = AsyncSession.flush

        async def blocked(db, *args, **kwargs):
            await original(db, *args, **kwargs)
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(AsyncSession, "flush", blocked)
        async with app.router.lifespan_context(app):
            task = asyncio.create_task(
                service.login(auth_user["email"], auth_user["password"], "ip")
            )
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            from app.modules.auth.domain.errors import AuthStorageError

            with pytest.raises(AuthStorageError):
                await task
            assert await state(
                app.state.auth_limiter,
                app.state.auth_limiter.login_buckets(auth_user["email"], "ip"),
            ) == [[], []]

    asyncio.run(scenario())
    assert scalar("SELECT count(*) FROM auth_sessions") == 0
    assert scalar("SELECT count(*) FROM auth_refresh_tokens") == 0


def test_refresh_known_family_accounting_and_storage_error_release(
    auth_user, monkeypatch
):
    async def scenario():
        async with app.router.lifespan_context(app):
            subject = app.state.auth_limiter
            issued = await service.login(
                auth_user["email"], auth_user["password"], "ip"
            )
            original_token = issued.refresh_token
            for _ in range(10):
                issued = await service.refresh_session(issued.refresh_token, "ip")
            family_bucket = subject.refresh_family(str(issued.principal.session_id))
            assert len((await state(subject, family_bucket))[0]) == 10
            with pytest.raises(RateLimitError):
                await service.refresh_session(issued.refresh_token, "ip")
            assert len((await state(subject, subject.refresh_ip("ip")))[0]) == 11
            # A replay from another source still targets the same family quota.
            with pytest.raises(RateLimitError):
                await service.refresh_session(original_token, "other-ip")
            assert len((await state(subject, subject.refresh_ip("other-ip")))[0]) == 1
            from sqlalchemy.exc import SQLAlchemyError

            original = service.token_identity

            async def broken(*_):
                raise SQLAlchemyError("injected")

            monkeypatch.setattr(service, "token_identity", broken)
            from app.modules.auth.domain.errors import AuthStorageError

            with pytest.raises(AuthStorageError):
                await service.refresh_session("unknown", "storage-ip")
            assert await state(subject, subject.refresh_ip("storage-ip")) == [[]]
            monkeypatch.setattr(service, "token_identity", original)

    asyncio.run(scenario())
    assert scalar("SELECT count(*) FROM auth_rate_limit_buckets") == 0


@pytest.mark.parametrize("token", [None, "", "unknown", "x" * 129])
def test_refresh_unresolvable_tokens_charge_ip_only(token):
    async def scenario():
        async with app.router.lifespan_context(app):
            with pytest.raises(AuthenticationError):
                await service.refresh_session(token, "ip")
            values = await state(
                app.state.auth_limiter, app.state.auth_limiter.refresh_ip("ip")
            )
            assert len(values[0]) == 1 and values[0][0].startswith(b"f:")

    asyncio.run(scenario())


def test_direct_caller_cannot_receive_credentials_after_limiter_cleanup(
    auth_user, monkeypatch
):
    from app.modules.auth.domain.errors import AuthStorageError

    async def scenario():
        async with app.router.lifespan_context(app):
            subject = app.state.auth_limiter
            original = subject.finalize
            start = deadline.monotonic()
            clock = [start]
            monkeypatch.setattr(deadline, "monotonic", lambda: clock[0])

            async def delayed_cleanup(*args, **kwargs):
                await original(*args, **kwargs)
                clock[0] = start + 9

            monkeypatch.setattr(subject, "finalize", delayed_cleanup)
            with pytest.raises(AuthStorageError):
                await service.login(auth_user["email"], auth_user["password"], "ip")
            assert (
                scalar("SELECT count(*) FROM auth_sessions") == 1
            )  # Undisclosed orphan.
            assert await state(
                subject, subject.login_buckets(auth_user["email"], "ip")
            ) == [[], []]

    asyncio.run(scenario())


def test_refresh_cancelled_during_finalization_discards_only_its_charge(
    auth_user, monkeypatch
):
    from app.modules.auth.domain.errors import AuthStorageError

    async def scenario():
        async with app.router.lifespan_context(app):
            subject = app.state.auth_limiter
            issued = await service.login(
                auth_user["email"], auth_user["password"], "ip"
            )
            issued = await service.refresh_session(issued.refresh_token, "ip")
            original = subject.finalize
            entered = asyncio.Event()

            async def blocked(admission, *, count, discard=False):
                await original(admission, count=count, discard=discard)
                if count and not discard:
                    entered.set()
                    await asyncio.Event().wait()

            monkeypatch.setattr(subject, "finalize", blocked)
            task = asyncio.create_task(
                service.refresh_session(issued.refresh_token, "ip")
            )
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with pytest.raises(AuthStorageError):
                await task
            assert len((await state(subject, subject.refresh_ip("ip")))[0]) == 1
            assert (
                len(
                    (
                        await state(
                            subject,
                            subject.refresh_family(str(issued.principal.session_id)),
                        )
                    )[0]
                )
                == 1
            )

    asyncio.run(scenario())
