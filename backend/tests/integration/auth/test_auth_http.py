"""Real PostgreSQL/session security contracts, with no auth dependency overrides."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier, Lock

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.main import app
from conftest import engine

HEADERS = {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}


def synchronize_calls(function, barrier: Barrier, call_count: int):
    """Coordinate only the requested overlapping calls, then pass through."""
    count = 0
    count_lock = Lock()

    async def synchronized(*args, **kwargs):
        nonlocal count
        with count_lock:
            wait = count < call_count
            count += 1
        if wait:
            barrier.wait(timeout=15)
        return await function(*args, **kwargs)

    return synchronized


def login(client, user):
    return client.post(
        "/auth/login",
        json={"email": user["email"], "password": user["password"]},
        headers=HEADERS,
    )


def refresh(token):
    with TestClient(app) as client:
        client.cookies.set("ros_refresh", token, path="/auth")
        return client.post("/auth/refresh", headers=HEADERS)


def scalar(query, **params):
    with engine.begin() as connection:
        return connection.execute(text(query), params).scalar_one()


def test_login_cookie_security_and_public_summary(auth_user):
    with TestClient(app) as client:
        response = login(client, auth_user)
        assert response.status_code == 200
        assert set(response.json()) == {"id", "email", "status"}
        assert response.json()["email"] == auth_user["email"]
        assert "no-store" in response.headers["cache-control"]
        cookies = response.headers.get_list("set-cookie")
        for name, path in [("ros_access", "/"), ("ros_refresh", "/auth")]:
            cookie = next(value for value in cookies if value.startswith(name + "="))
            assert "HttpOnly" in cookie and "SameSite=lax" in cookie
            assert "Path=" + path in cookie and "Domain=" not in cookie
        assert client.get("/auth/me").status_code == 200
        assert (
            scalar(
                "SELECT count(*) FROM auth_refresh_tokens WHERE digest = :digest",
                digest=sha256(client.cookies.get("ros_refresh").encode()).hexdigest(),
            )
            == 1
        )
        assert client.cookies.get("ros_refresh") not in response.text


def test_unknown_wrong_disabled_login_are_indistinguishable(auth_user):
    with TestClient(app) as client:
        bad = {
            **auth_user,
            "password": "Wrong password long enough",  # pragma: allowlist secret
        }
        wrong = login(client, bad)
        unknown = login(client, {**bad, "email": "unknown@example.test"})
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET status='disabled' WHERE id=:id"), auth_user
            )
        disabled = login(client, auth_user)
        assert wrong.status_code == unknown.status_code == disabled.status_code == 401
        assert wrong.json() == unknown.json() == disabled.json()
        assert set(wrong.json()) == {"detail"}
        assert scalar("SELECT count(*) FROM auth_sessions") == 0


def test_login_normalizes_email(auth_user):
    with TestClient(app) as client:
        response = login(client, {**auth_user, "email": "  OPERATOR@EXAMPLE.TEST  "})
        assert response.status_code == 200
        assert response.json()["email"] == auth_user["email"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "null", "X-CSRF-Protection": "1"},
        {"Origin": "https://evil.example", "X-CSRF-Protection": "1"},
        {"Origin": "http://localhost:3000"},
        {**HEADERS, "X-CSRF-Protection": "0"},
    ],
)
@pytest.mark.parametrize(
    "path", ["/auth/login", "/auth/refresh", "/auth/logout", "/api/restaurants"]
)
def test_unsafe_requests_reject_invalid_csrf(path, headers):
    with TestClient(app) as client:
        response = client.post(path, json={}, headers=headers)
        assert response.status_code == 403
        assert scalar("SELECT count(*) FROM auth_sessions") == 0


def test_json_validation_never_echoes_password(auth_user):
    secret = "private-validation-password-marker"  # pragma: allowlist secret
    with TestClient(app) as client:
        response = client.post(
            "/auth/login", json={"email": {}, "password": secret}, headers=HEADERS
        )
        assert response.status_code == 422
        assert secret not in response.text
        assert "input" not in response.text
        non_json = client.post(
            "/auth/login",
            data={"email": auth_user["email"], "password": secret},
            headers=HEADERS,
        )
        assert non_json.status_code in (403, 415, 422)


def test_cors_preflight_public_and_exact_origin():
    with TestClient(app) as client:
        response = client.options(
            "/api/restaurants",
            headers={
                "Origin": HEADERS["Origin"],
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-csrf-protection",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == HEADERS["Origin"]
        assert response.headers["access-control-allow-credentials"] == "true"
        denied = client.options(
            "/api/restaurants",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in denied.headers


def test_all_business_operations_require_authentication():
    document = app.openapi()
    with TestClient(app) as client:
        protected = 0
        for template, methods in document["paths"].items():
            if template.startswith(("/auth", "/health", "/api/test")):
                continue
            path = template
            for parameter in (
                "restaurant_id",
                "menu_id",
                "menu_item_id",
                "order_id",
                "ingredient_id",
            ):
                path = path.replace("{" + parameter + "}", "999999")
            for method in methods:
                if method.upper() not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                    continue
                response = client.request(
                    method.upper(), path, headers=HEADERS, json={}
                )
                assert response.status_code == 401, (method, path, response.text)
                protected += 1
        assert protected >= 20
        assert client.get("/health").status_code == 200
        assert client.get("/api/test").status_code == 200


def test_rotation_retains_digest_and_does_not_extend_expiry(authenticated_client):
    client = authenticated_client
    old = client.cookies.get("ros_refresh")
    before = scalar("SELECT expires_at FROM auth_sessions")
    response = client.post("/auth/refresh")
    assert response.status_code == 200
    assert client.cookies.get("ros_refresh") != old
    assert scalar("SELECT expires_at FROM auth_sessions") == before
    assert scalar("SELECT count(*) FROM auth_refresh_tokens") == 2
    assert (
        scalar("SELECT count(*) FROM auth_refresh_tokens WHERE consumed_at IS NOT NULL")
        == 1
    )
    assert (
        scalar(
            "SELECT count(*) FROM auth_refresh_tokens WHERE digest=:digest",
            digest=sha256(old.encode()).hexdigest(),
        )
        == 1
    )


def test_replay_commits_revocation_and_rejects_successor(authenticated_client):
    client = authenticated_client
    old = client.cookies.get("ros_refresh")
    assert client.post("/auth/refresh").status_code == 200
    successor = client.cookies.get("ros_refresh")
    assert refresh(old).status_code == 401
    assert scalar("SELECT revoked_at IS NOT NULL FROM auth_sessions")
    assert client.get("/auth/me").status_code == 401
    assert refresh(successor).status_code == 401


def test_same_token_concurrent_rotation_revokes_family(
    authenticated_client, monkeypatch
):
    from app.modules.auth import service

    token = authenticated_client.cookies.get("ros_refresh")
    barrier = Barrier(2)
    monkeypatch.setattr(
        service, "lock_family", synchronize_calls(service.lock_family, barrier, 2)
    )

    def rotate():
        return refresh(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: rotate(), range(2)))
    assert sorted(result.status_code for result in results) == [200, 401]
    assert scalar("SELECT revoked_at IS NOT NULL FROM auth_sessions")
    assert scalar("SELECT count(*) FROM auth_refresh_tokens") == 2
    assert authenticated_client.get("/auth/me").status_code == 401


def test_logout_only_current_family_and_is_idempotent(authenticated_client, auth_user):
    with TestClient(app) as other:
        assert login(other, auth_user).status_code == 200
        response = authenticated_client.post("/auth/logout")
        assert response.status_code == 204 and response.content == b""
        assert authenticated_client.cookies.get("ros_access") is None
        assert authenticated_client.cookies.get("ros_refresh") is None
        assert authenticated_client.get("/auth/me").status_code == 401
        assert other.get("/auth/me").status_code == 200
        assert authenticated_client.post("/auth/logout").status_code == 204


def test_disabled_account_blocks_existing_access_and_refresh(
    authenticated_client, auth_user
):
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET status='disabled' WHERE id=:id"), auth_user
        )
    assert authenticated_client.get("/auth/me").status_code == 401
    assert authenticated_client.post("/auth/refresh").status_code == 401


def test_absolute_session_expiry_blocks_both_credentials(authenticated_client):
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE auth_sessions SET created_at = now() - interval '8 days', expires_at = now() - interval '1 second'"
            )
        )
    assert authenticated_client.get("/auth/me").status_code == 401
    assert authenticated_client.post("/auth/refresh").status_code == 401


@pytest.mark.parametrize(
    "mutation",
    [
        "expired",
        "issuer",
        "audience",
        "token_use",
        "sub",
        "sid",
        "iat",
        "missing_exp",
        "missing_sub",
        "missing_sid",
        "missing_iss",
        "missing_aud",
        "missing_iat",
        "missing_token_use",
        "wrong_key",
        "wrong_algorithm",
        "tampered",
    ],
)
def test_access_claim_and_signature_validation(authenticated_client, mutation):
    token = authenticated_client.cookies.get("ros_access")
    payload = jwt.decode(token, options={"verify_signature": False})
    key = get_settings().auth_jwt_secret.get_secret_value()
    algorithm = "HS256"
    if mutation == "expired":
        payload["exp"] = 1
    elif mutation.startswith("missing_"):
        payload.pop(mutation[8:], None)
    elif mutation in {"issuer", "audience"}:
        payload[{"issuer": "iss", "audience": "aud"}[mutation]] = "wrong"
    elif mutation in {"sub", "sid"}:
        payload[mutation] = "not-a-uuid"
    elif mutation == "iat":
        payload["iat"] = "invalid"
    elif mutation == "token_use":
        payload["token_use"] = "refresh"
    elif mutation == "wrong_key":
        key = "wrong-signing-key-at-least-thirty-two-bytes"
    elif mutation == "wrong_algorithm":
        algorithm = "HS384"
    forged = jwt.encode(payload, key, algorithm=algorithm)
    if mutation == "tampered":
        forged = forged[:-8] + "AAAAAAAA"
    with TestClient(app) as client:
        client.cookies.set("ros_access", forged, path="/")
        assert client.get("/auth/me").status_code == 401


def test_expired_access_can_logout_with_refresh(authenticated_client):
    authenticated_client.cookies.delete("ros_access")
    assert authenticated_client.post("/auth/logout").status_code == 204
    assert scalar("SELECT revoked_at IS NOT NULL FROM auth_sessions")


def test_login_limits_include_unknown_accounts_and_spoofed_forwarded_ip():
    with TestClient(app) as client:
        payload = {
            "email": "unknown@example.test",
            "password": "Wrong password long enough",  # pragma: allowlist secret
        }
        limit = get_settings().auth_login_email_limit
        for attempt in range(limit):
            response = client.post(
                "/auth/login",
                json=payload,
                headers={**HEADERS, "X-Forwarded-For": f"198.51.100.{attempt}"},
            )
            assert response.status_code == 401
        limited = client.post("/auth/login", json=payload, headers=HEADERS)
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) > 0


def test_concurrent_login_account_counter_never_exceeds_limit(auth_user, monkeypatch):
    import asyncio
    import httpx
    from app.modules.auth import service

    limit = get_settings().auth_login_email_limit

    async def scenario():
        entered, rejected = 0, 0
        all_entered, all_rejected, release = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        original = service.verify_password

        async def blocked(*args):
            nonlocal entered
            entered += 1
            if entered == limit:
                all_entered.set()
            await release.wait()
            return await original(*args)

        monkeypatch.setattr(service, "verify_password", blocked)
        async with app.router.lifespan_context(app):
            from tests.support.redis_ready import warm_redis

            await warm_redis(app.state.auth_limiter._redis())
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:

                async def attempt():
                    nonlocal rejected
                    result = await client.post(
                        "/auth/login",
                        headers=HEADERS,
                        json={
                            "email": "unknown@example.test",
                            "password": auth_user["password"],
                        },
                    )
                    if result.status_code == 429:
                        rejected += 1
                        if rejected == 3:
                            all_rejected.set()
                    return result.status_code

                tasks = [asyncio.create_task(attempt()) for _ in range(limit + 3)]
                try:
                    async with asyncio.timeout(6):
                        await all_entered.wait()
                        await all_rejected.wait()
                    assert entered == limit
                finally:
                    release.set()
                statuses = await asyncio.gather(*tasks)
        assert statuses.count(401) == limit
        assert statuses.count(429) == 3

    asyncio.run(scenario())
    assert scalar("SELECT count(*) FROM auth_sessions") == 0
    assert scalar("SELECT count(*) FROM auth_rate_limit_buckets") == 0


def test_expired_access_rejection_preserves_refresh_for_renewal(authenticated_client):
    token = authenticated_client.cookies.get("ros_access")
    payload = jwt.decode(token, options={"verify_signature": False})
    payload["iat"], payload["exp"] = 1, 2
    expired = jwt.encode(
        payload, get_settings().auth_jwt_secret.get_secret_value(), algorithm="HS256"
    )
    refresh_token = authenticated_client.cookies.get("ros_refresh")
    with TestClient(app) as client:
        client.headers.update(HEADERS)
        client.cookies.set("ros_access", expired, path="/")
        client.cookies.set("ros_refresh", refresh_token, path="/auth")
        assert client.get("/auth/me").status_code == 401
        assert client.cookies.get("ros_refresh") == refresh_token
        assert client.post("/auth/refresh").status_code == 200
        assert client.get("/auth/me").status_code == 200


def test_rotation_database_failure_rolls_back_consumption(authenticated_client):
    from sqlalchemy import event
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session
    from app.modules.auth.repo.models import RefreshToken

    original = authenticated_client.cookies.get("ros_refresh")

    def fail_rotation_commit(db):
        if any(isinstance(row, RefreshToken) for row in db.new | db.dirty):
            raise SQLAlchemyError("Injected auth commit failure")

    event.listen(Session, "before_commit", fail_rotation_commit)
    try:
        response = authenticated_client.post("/auth/refresh")
    finally:
        event.remove(Session, "before_commit", fail_rotation_commit)
    assert response.status_code == 503
    assert authenticated_client.cookies.get("ros_refresh") == original
    assert scalar("SELECT count(*) FROM auth_refresh_tokens") == 1
    assert (
        scalar("SELECT count(*) FROM auth_refresh_tokens WHERE consumed_at IS NOT NULL")
        == 0
    )
    assert authenticated_client.post("/auth/refresh").status_code == 200


@pytest.mark.parametrize("operation", ["/auth/login", "/auth/refresh"])
def test_rate_storage_outage_fails_closed(monkeypatch, auth_user, operation):
    from sqlalchemy.exc import SQLAlchemyError
    from app.modules.auth import service

    def unavailable():
        raise SQLAlchemyError("Injected rate storage outage")

    monkeypatch.setattr(service, "AsyncSessionLocal", unavailable)
    with TestClient(app) as client:
        if operation == "/auth/refresh":
            client.cookies.set("ros_refresh", "unknown-token", path="/auth")
        response = client.post(
            operation,
            headers=HEADERS,
            json={"email": auth_user["email"], "password": auth_user["password"]},
        )
        assert response.status_code == 503
        assert "ros_access" not in response.headers.get("set-cookie", "")
    assert scalar("SELECT count(*) FROM auth_sessions") == 0


def test_logout_storage_failure_never_claims_revocation(
    monkeypatch, authenticated_client
):
    from sqlalchemy.exc import SQLAlchemyError
    from app.modules.auth import service

    def unavailable():
        raise SQLAlchemyError("Injected logout storage outage")

    monkeypatch.setattr(service, "AsyncSessionLocal", unavailable)
    assert authenticated_client.post("/auth/logout").status_code == 503
    assert not scalar("SELECT revoked_at IS NOT NULL FROM auth_sessions")
    assert authenticated_client.get("/auth/me").status_code == 200


def test_rotation_and_logout_serialize(authenticated_client, monkeypatch):
    from app.modules.auth import service

    old = authenticated_client.cookies.get("ros_refresh")
    barrier = Barrier(2)
    monkeypatch.setattr(
        service, "lock_family", synchronize_calls(service.lock_family, barrier, 2)
    )

    def rotate():
        return refresh(old)

    def logout_family():
        with TestClient(app) as client:
            client.cookies.set("ros_refresh", old, path="/auth")
            return client.post("/auth/logout", headers=HEADERS)

    with ThreadPoolExecutor(max_workers=2) as pool:
        rotation = pool.submit(rotate)
        logout = pool.submit(logout_family)
        rotated, logged_out = rotation.result(timeout=20), logout.result(timeout=20)
    assert logged_out.status_code == 204
    assert rotated.status_code in (200, 401)
    assert scalar("SELECT revoked_at IS NOT NULL FROM auth_sessions")
    assert authenticated_client.get("/auth/me").status_code == 401
    if rotated.status_code == 200:
        successor = rotated.cookies.get("ros_refresh")
        assert refresh(successor).status_code == 401


@pytest.mark.parametrize("operation", ["login", "refresh"])
def test_concurrent_disable_prevents_usable_credentials(
    authenticated_client, auth_user, operation, monkeypatch
):
    import asyncio
    from app.modules.auth import cli, service
    from app.modules.auth.cli import disable_user

    token = authenticated_client.cookies.get("ros_refresh")
    barrier = Barrier(2)

    if operation == "refresh":
        monkeypatch.setattr(
            service, "lock_family", synchronize_calls(service.lock_family, barrier, 1)
        )
        monkeypatch.setattr(
            cli,
            "find_by_email",
            synchronize_calls(cli.find_by_email, barrier, 1),
        )
    else:
        monkeypatch.setattr(
            service,
            "find_by_email",
            synchronize_calls(service.find_by_email, barrier, 1),
        )
        monkeypatch.setattr(
            cli,
            "find_by_email",
            synchronize_calls(cli.find_by_email, barrier, 1),
        )

    def issue():
        if operation == "refresh":
            return refresh(token)
        with TestClient(app) as client:
            return login(client, auth_user)

    def disable():
        return asyncio.run(disable_user(auth_user["email"]))

    with ThreadPoolExecutor(max_workers=2) as pool:
        issuance = pool.submit(issue)
        disabled = pool.submit(disable)
        response = issuance.result(timeout=20)
        disabled.result(timeout=20)
    assert response.status_code in (200, 401)
    assert authenticated_client.get("/auth/me").status_code == 401
    if response.status_code == 200:
        with TestClient(app) as client:
            client.cookies.update(response.cookies)
            assert client.get("/auth/me").status_code == 401
            assert client.post("/auth/refresh", headers=HEADERS).status_code == 401


def test_database_enforces_normalized_email_uniqueness(auth_user):
    from uuid import uuid4
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id,email,password_hash,status) SELECT :id,email,password_hash,status FROM users LIMIT 1"
                ),
                {"id": str(uuid4())},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("UPDATE users SET email=upper(email)"))


def test_database_prevents_two_current_refresh_tokens(authenticated_client):
    from uuid import uuid4
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO auth_refresh_tokens (id,session_id,digest,issued_at,expires_at) SELECT :id,session_id,:digest,issued_at,expires_at FROM auth_refresh_tokens LIMIT 1"
                ),
                {"id": str(uuid4()), "digest": "f" * 64},
            )
    assert scalar("SELECT count(*) FROM auth_refresh_tokens") == 1


def test_refresh_ip_limit_applies_to_unknown_tokens(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_refresh_ip_limit", 3)
    with TestClient(app) as client:
        for attempt in range(3):
            client.cookies.set("ros_refresh", f"unknown-token-{attempt}", path="/auth")
            assert client.post("/auth/refresh", headers=HEADERS).status_code == 401
        limited = client.post("/auth/refresh", headers=HEADERS)
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) > 0


def test_successful_logins_do_not_consume_failure_quota(auth_user):
    with TestClient(app) as client:
        for _ in range(get_settings().auth_login_email_limit + 2):
            assert login(client, auth_user).status_code == 200
    assert scalar("SELECT count(*) FROM auth_rate_limit_buckets") == 0


def test_secure_cookie_flags_and_matching_logout_deletion(monkeypatch, auth_user):
    monkeypatch.setattr(get_settings(), "auth_cookie_secure", True)
    with TestClient(app, base_url="https://testserver") as client:
        response = login(client, auth_user)
        assert response.status_code == 200
        for value in response.headers.get_list("set-cookie"):
            assert "Secure" in value and "HttpOnly" in value and "SameSite=lax" in value
        logout = client.post("/auth/logout", headers=HEADERS)
        assert logout.status_code == 204
        for name, path in [("ros_access", "/"), ("ros_refresh", "/auth")]:
            cookie = next(
                value
                for value in logout.headers.get_list("set-cookie")
                if value.startswith(name + "=")
            )
            assert "Max-Age=0" in cookie and "Path=" + path in cookie
            assert "Secure" in cookie and "HttpOnly" in cookie


def test_auth_password_and_tokens_are_absent_from_logs(auth_user, caplog):
    with TestClient(app) as client:
        logged_in = login(client, auth_user)
        assert logged_in.status_code == 200
        secrets = [
            auth_user["password"],
            client.cookies.get("ros_access"),
            client.cookies.get("ros_refresh"),
        ]
        assert client.post("/auth/refresh", headers=HEADERS).status_code == 200
        assert client.post("/auth/logout", headers=HEADERS).status_code == 204
        for secret in secrets:
            assert secret not in caplog.text
        assert auth_user["password"] not in logged_in.text
