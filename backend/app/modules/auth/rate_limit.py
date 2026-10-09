"""Atomic fixed-window admission with no PostgreSQL limiter backend."""

import hashlib
import hmac
import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol
from uuid import uuid4

from app.core.config import Settings
from app.modules.auth.domain.errors import AuthStorageError, RateLimitError
from app.redis.adapter import RedisFailure

LEASE_SECONDS = 10

# Check ALL buckets before inserting ANY reservation. Failure entries expire at
# fixed-window boundaries; reservations survive a window boundary. Use server time.
ADMIT = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
local retry = 0
for i, key in ipairs(KEYS) do
  redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
  if redis.call('ZCARD', key) >= tonumber(ARGV[2*i]) then
    local first = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    retry = math.max(retry, tonumber(first[2]) - now)
  end
end
if retry > 0 then return math.max(1, math.ceil(retry / 1000)) end
for i, key in ipairs(KEYS) do
  redis.call('ZADD', key, now + 10000, 'r:' .. ARGV[1])
  local last = redis.call('ZRANGE', key, -1, -1, 'WITHSCORES')
  redis.call('PEXPIRE', key, math.ceil(tonumber(last[2]) - now))
  if ARGV[2 * #KEYS + 2] == 'probe' then
    redis.call('ZREM', key, 'r:' .. ARGV[1])
  end
end
return 0
"""

FINALIZE = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
for i, key in ipairs(KEYS) do
  redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
  local removed = redis.call('ZREM', key, 'r:' .. ARGV[1])
  if ARGV[2] == '2' then redis.call('ZREM', key, 'f:' .. ARGV[1]) end
  if removed == 1 and ARGV[2] == '1' then
    local window = tonumber(ARGV[i+2]) * 1000
    local expiry = (math.floor(now / window) + 1) * window
    redis.call('ZADD', key, expiry, 'f:' .. ARGV[1])
  end
  local last = redis.call('ZRANGE', key, -1, -1, 'WITHSCORES')
  if #last > 0 then redis.call('PEXPIRE', key, math.ceil(tonumber(last[2]) - now)) end
end
return 0
"""


class RedisCommands(Protocol):
    async def execute(self, *arguments: object) -> object: ...
    def namespace(self, use_case: str, version: int) -> str: ...


@dataclass(frozen=True)
class Bucket:
    key: str
    maximum: int
    local_maximum: int
    window: int


@dataclass
class LocalBucket:
    failures: dict[str, float] = field(default_factory=dict)
    reservations: dict[str, float] = field(default_factory=dict)


@dataclass
class Admission:
    id: str
    buckets: tuple[Bucket, ...]
    redis: RedisCommands | None
    local: bool


class AuthLimiter:
    def __init__(
        self,
        settings: Settings,
        redis: Callable[[], RedisCommands],
        *,
        monotonic: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._redis = redis
        self._monotonic = monotonic
        self._wall = wall
        self._lock = Lock()
        self._entries: dict[str, LocalBucket] = {}
        self._degraded_at: float | None = None
        self._next_probe = 0.0
        self._probing = False
        self._successes = 0

    def _key(self, kind: str, *identifiers: str) -> str:
        # Length framing prevents email/IP separator ambiguity.
        payload = "".join(f"{len(value)}:{value}" for value in identifiers)
        digest = hmac.new(
            self.settings.auth_rate_limit_secret.get_secret_value().encode(),
            (kind + ":" + payload).encode(),
            hashlib.sha256,
        ).hexdigest()
        return kind + ":" + digest

    def login_buckets(self, email: str, ip: str) -> tuple[Bucket, ...]:
        return (
            Bucket(
                self._key("login-pair", email, ip),
                self.settings.auth_login_email_limit,
                3,
                self.settings.auth_login_window_seconds,
            ),
            Bucket(
                self._key("login-ip", ip),
                self.settings.auth_login_ip_limit,
                10,
                self.settings.auth_login_ip_window_seconds,
            ),
        )

    def refresh_ip(self, ip: str) -> tuple[Bucket, ...]:
        return (
            Bucket(
                self._key("refresh-ip", ip),
                self.settings.auth_refresh_ip_limit,
                50,
                self.settings.auth_refresh_window_seconds,
            ),
        )

    def refresh_family(self, family: str) -> tuple[Bucket, ...]:
        return (
            Bucket(
                self._key("refresh-family", family),
                self.settings.auth_refresh_family_limit,
                5,
                self.settings.auth_refresh_window_seconds,
            ),
        )

    def _clean(self, now: float) -> None:
        for key, entry in tuple(self._entries.items()):
            entry.failures = {k: v for k, v in entry.failures.items() if v > now}
            entry.reservations = {
                k: v for k, v in entry.reservations.items() if v > now
            }
            if not entry.failures and not entry.reservations:
                del self._entries[key]

    def _local_admit(
        self, buckets: tuple[Bucket, ...], identifier: str, *, guard: bool
    ) -> bool:
        with self._lock:
            now = self._monotonic()
            self._clean(now)
            # During recovery only surviving local buckets need dual admission.
            tracked = tuple(b for b in buckets if not guard or b.key in self._entries)
            retry = 0.0
            for bucket in tracked:
                entry = self._entries.get(bucket.key)
                if (
                    entry
                    and len(entry.failures) + len(entry.reservations)
                    >= bucket.local_maximum
                ):
                    retry = max(
                        retry,
                        min((*entry.failures.values(), *entry.reservations.values()))
                        - now,
                    )
            if retry > 0:
                raise RateLimitError(max(1, math.ceil(retry)))
            missing = sum(b.key not in self._entries for b in tracked)
            if len(self._entries) + missing > self.settings.auth_local_max_entries:
                raise RateLimitError(LEASE_SECONDS)
            for bucket in tracked:
                entry = self._entries.setdefault(bucket.key, LocalBucket())
                entry.reservations[identifier] = now + LEASE_SECONDS
            return bool(tracked)

    def _local_finalize(
        self, admission: Admission, count: bool, *, discard: bool = False
    ) -> None:
        with self._lock:
            now = self._monotonic()
            self._clean(now)
            for bucket in admission.buckets:
                entry = self._entries.get(bucket.key)
                if entry and discard:
                    entry.failures.pop(admission.id, None)
                if not entry or entry.reservations.pop(admission.id, None) is None:
                    continue
                if count:
                    remaining = bucket.window - self._wall() % bucket.window
                    entry.failures[admission.id] = now + remaining
            self._clean(now)

    def _event(self, event: str, reason: str) -> None:
        logging.getLogger(__name__).warning(
            "Authentication limiter transition",
            extra={
                "event": event,
                "reason": reason,
                "process_id": os.getpid(),
                "duration_seconds": max(0.0, self._monotonic() - self._degraded_at)
                if self._degraded_at is not None
                else 0.0,
            },
        )

    def _degrade(self, reason: str) -> None:
        with self._lock:
            if self._degraded_at is None:
                self._degraded_at = self._monotonic()
                self._event("auth_limiter_degraded", reason)
            self._successes = 0
            self._next_probe = self._monotonic() + 5

    async def _mode(self, redis: RedisCommands) -> bool:
        with self._lock:
            degraded = self._degraded_at is not None
            probe = (
                degraded and not self._probing and self._monotonic() >= self._next_probe
            )
            if probe:
                self._probing = True
                self._next_probe = self._monotonic() + 5
        if not probe:
            return degraded
        try:
            # Exercise reads, strict admission and lease writes on an owned
            # probe bucket, then release it within the SAME operation budget.
            # Concurrent requests remain local without waiting for this probe.
            await redis.execute(
                "EVAL",
                ADMIT,
                1,
                redis.namespace("auth", 1) + "probe:" + str(os.getpid()),
                uuid4().hex,
                1,
                60,
                "probe",
            )
        except RedisFailure as error:
            self._degrade(error.kind.value)
            self._event("auth_limiter_probe_failed", error.kind.value)
        except BaseException:
            self._degrade("cancelled")
            raise
        else:
            with self._lock:
                self._successes += 1
                self._event("auth_limiter_recovering", "probe_success")
                if self._successes == 3:
                    self._event("auth_limiter_healthy", "stable_recovery")
                    self._degraded_at = None
        finally:
            with self._lock:
                self._probing = False
        with self._lock:
            return self._degraded_at is not None

    async def admit(self, buckets: tuple[Bucket, ...]) -> Admission:
        identifier = uuid4().hex
        redis = self._redis()
        if await self._mode(redis):
            self._local_admit(buckets, identifier, guard=False)
            return Admission(identifier, buckets, None, True)
        local = self._local_admit(buckets, identifier, guard=True)
        admission = Admission(identifier, buckets, redis, local)
        args: list[object] = [identifier]
        for bucket in buckets:
            args.extend((bucket.maximum, bucket.window))
        try:
            retry = await redis.execute(
                "EVAL",
                ADMIT,
                len(buckets),
                *(redis.namespace("auth", 1) + b.key for b in buckets),
                *args,
            )
            if not isinstance(retry, int):
                raise ValueError("Invalid limiter result")
            if retry:
                raise RateLimitError(retry)
            return admission
        except RedisFailure as error:
            self._degrade(error.kind.value)
            self._local_finalize(admission, False)
            self._local_admit(buckets, identifier, guard=False)
            return Admission(identifier, buckets, None, True)
        except BaseException:
            self._local_finalize(admission, False)
            # Ambiguous cancellation leaves at most a 10-second Redis lease.
            raise

    async def finalize(
        self, admission: Admission, *, count: bool, discard: bool = False
    ) -> None:
        self._local_finalize(admission, count, discard=discard)
        redis = admission.redis
        if redis is None:
            return
        try:
            await redis.execute(
                "EVAL",
                FINALIZE,
                len(admission.buckets),
                *(redis.namespace("auth", 1) + b.key for b in admission.buckets),
                admission.id,
                2 if discard else int(count),
                *(b.window for b in admission.buckets),
            )
        except RedisFailure as error:
            self._degrade(error.kind.value)
            if count and not admission.local:
                # Never replay an ambiguous Redis finalization. Track a local
                # failure conservatively, subject to the bounded capacity guard.
                try:
                    self._local_admit(admission.buckets, admission.id, guard=False)
                except RateLimitError:
                    return
                self._local_finalize(admission, True)


_process_limiter: AuthLimiter | None = None


def install_limiter(limiter: AuthLimiter) -> None:
    """Application wiring installs one process policy with its transport provider."""
    global _process_limiter
    _process_limiter = limiter


def get_limiter() -> AuthLimiter:
    if _process_limiter is None:
        raise AuthStorageError()
    return _process_limiter
