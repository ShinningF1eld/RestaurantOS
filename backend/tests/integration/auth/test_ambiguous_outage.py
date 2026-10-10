"""Drop a real Redis write acknowledgement after the operation has committed."""

import asyncio

import pytest

from app.main import app, settings
from app.modules.auth.rate_limit import ADMIT, FINALIZE, AuthLimiter
from app.redis.adapter import FailureKind, RedisFailure


@pytest.mark.parametrize("operation", [ADMIT, FINALIZE])
def test_applied_redis_write_lost_acknowledgement_is_not_replayed(operation):
    async def scenario():
        async with app.router.lifespan_context(app):
            adapter = app.state.redis
            from tests.support.redis_ready import warm_redis

            await warm_redis(adapter, connections=1)

            class LostReply:
                calls = 0

                def namespace(self, *args):
                    return adapter.namespace(*args)

                async def execute(self, *args):
                    self.calls += 1
                    result = await adapter.execute(*args)
                    if args[1] == operation:
                        raise RedisFailure(FailureKind.TIMEOUT)
                    return result

            transport = LostReply()
            subject = AuthLimiter(
                settings, lambda: transport, monotonic=lambda: 1, wall=lambda: 1
            )
            buckets = subject.login_buckets("ambiguous@example.test", "192.0.2.7")
            admission = await subject.admit(buckets)
            await subject.finalize(admission, count=True)
            assert transport.calls == (1 if operation == ADMIT else 2)
            assert subject._degraded_at == 1
            assert all(len(e.failures) == 1 for e in subject._entries.values())
            keys = [adapter.namespace("auth", 1) + b.key for b in buckets]
            try:
                for key in keys:
                    members = await adapter.execute("ZRANGE", key, 0, -1)
                    assert len(members) == 1
                    assert members[0].startswith(b"r:" if operation == ADMIT else b"f:")
                    assert (
                        0
                        < await adapter.execute("PTTL", key)
                        <= (10000 if operation == ADMIT else 900000)
                    )
                # The applied reservation/failure is not replayed; following
                # admissions/finalizations remain entirely process-local.
                another = await subject.admit(buckets)
                await subject.finalize(another, count=False)
                assert transport.calls == (1 if operation == ADMIT else 2)
            finally:
                await adapter.execute("DEL", *keys)

    asyncio.run(scenario())
