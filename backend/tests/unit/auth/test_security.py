import asyncio
import base64
from uuid import uuid4

import pytest

from app.modules.auth.security import (
    decode_access,
    encode_access,
    hash_password,
    new_refresh_token,
    normalize_email,
    token_digest,
    verify_password,
)


def test_argon2id_password_verification_and_dummy_unknown_hash():
    async def check():
        password = "A long password with spaces"  # pragma: allowlist secret
        encoded = await hash_password(password)
        assert encoded.startswith("$argon2id$") and password not in encoded
        assert (await verify_password(password, encoded))[0]
        assert not (await verify_password("wrong long password", encoded))[0]
        assert not (await verify_password(password, None))[0]

    asyncio.run(check())


@pytest.mark.parametrize("password", ["short", "x" * 129])
def test_password_policy_rejects_without_truncation(password):
    with pytest.raises(ValueError):
        asyncio.run(hash_password(password))


@pytest.mark.parametrize("password", ["x" * 15, "x" * 128, "     space password     "])
def test_password_policy_accepts_boundaries_and_spaces(password):
    encoded = asyncio.run(hash_password(password))
    assert asyncio.run(verify_password(password, encoded))[0]


def test_refresh_has_256_bits_and_only_sha256_digest():
    tokens = [new_refresh_token() for _ in range(32)]
    assert len(set(tokens)) == len(tokens)
    assert all(
        len(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))) >= 32
        for token in tokens
    )
    digest = token_digest(tokens[0])
    assert len(digest) == 64 and tokens[0] not in digest
    assert digest == token_digest(tokens[0])


def test_access_round_trip_preserves_only_identity():
    user, family = uuid4(), uuid4()
    assert decode_access(encode_access(user, family)) == (user, family)


def test_email_normalization():
    assert normalize_email("  Operator@EXAMPLE.test ") == "operator@example.test"
