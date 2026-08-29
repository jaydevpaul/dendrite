"""Route-level tests - tier 3 of docs/auth_design.md section 7.

These assert HTTP behaviour: status codes, cookie flags, and the
indistinguishability requirement from section 4.2. They deliberately do NOT
assert on `detail` message wording, which is free to change; what matters is
that the two login failure modes stay identical to each other.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from sqlalchemy import text

from app.core.config import settings
from app.core.security import create_access_token

EMAIL = "alice@example.com"
PASSWORD = "a-good-password"


async def signup(client, email=EMAIL, password=PASSWORD):
    return await client.post("/auth/signup", json={"email": email, "password": password})


# --- signup -----------------------------------------------------------


async def test_signup_returns_201_and_the_new_user(client):
    response = await signup(client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == EMAIL
    assert body["id"]


async def test_signup_response_never_exposes_credentials(client):
    """UserOut is an allowlist - the hash must not reach the client."""
    response = await signup(client)
    assert "password" not in response.text
    assert "hash" not in response.text


async def test_signup_sets_a_hardened_session_cookie(client):
    response = await signup(client)
    raw = response.headers["set-cookie"]

    assert f"{settings.cookie_name}=" in raw
    assert "HttpOnly" in raw
    assert "SameSite=lax" in raw.replace("samesite=", "SameSite=")
    assert "Path=/" in raw
    assert f"Max-Age={int(settings.access_token_ttl.total_seconds())}" in raw
    # Secure must be absent in dev (cookie_secure=False) or the browser would
    # refuse to send it over plain http and login would silently never work.
    assert ("Secure" in raw) is settings.cookie_secure


async def test_signup_rejects_a_duplicate_email(client):
    await signup(client)
    assert (await signup(client)).status_code == 409


async def test_signup_rejects_a_duplicate_ignoring_case_and_space(client):
    await signup(client)
    assert (await signup(client, email="  ALICE@Example.COM  ")).status_code == 409


async def test_signup_rejects_a_short_password(client):
    assert (await signup(client, password="short")).status_code == 422


async def test_signup_rejects_a_malformed_email(client):
    assert (await signup(client, email="not-an-email")).status_code == 422


# --- login ------------------------------------------------------------


async def test_login_succeeds_with_correct_credentials(client):
    created = (await signup(client)).json()
    response = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_login_normalizes_the_email(client):
    created = (await signup(client)).json()
    response = await client.post(
        "/auth/login", json={"email": "  ALICE@Example.COM  ", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_login_failures_are_indistinguishable(client):
    """Section 4.2: a wrong password and an unknown email must look identical.

    Any difference here - status, body, even wording - lets an attacker
    enumerate which emails have accounts.
    """
    await signup(client)

    wrong_password = await client.post(
        "/auth/login", json={"email": EMAIL, "password": "wrong-one"}
    )
    unknown_email = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.text == unknown_email.text


async def test_login_failure_does_not_set_a_cookie(client):
    await signup(client)
    await client.post("/auth/logout")

    response = await client.post(
        "/auth/login", json={"email": EMAIL, "password": "wrong-one"}
    )
    assert response.status_code == 401
    assert settings.cookie_name not in response.cookies


# --- the authenticated route ------------------------------------------


async def test_me_requires_a_cookie(client):
    assert (await client.get("/auth/me")).status_code == 401


async def test_me_returns_the_signed_up_user(client):
    created = (await signup(client)).json()
    response = await client.get("/auth/me")
    assert response.status_code == 200
    assert response.json() == created


async def test_me_rejects_a_garbage_cookie(client):
    client.cookies.set(settings.cookie_name, "not-even-a-jwt")
    assert (await client.get("/auth/me")).status_code == 401


async def test_me_rejects_a_token_signed_with_another_key(client):
    forged = jwt.encode({"sub": str(uuid4())}, "not-our-secret", algorithm="HS256")
    client.cookies.set(settings.cookie_name, forged)
    assert (await client.get("/auth/me")).status_code == 401


async def test_me_rejects_an_expired_token(client):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    expired = jwt.encode(
        {"sub": str(uuid4()), "iat": past, "exp": past},
        settings.secret_key,
        algorithm="HS256",
    )
    client.cookies.set(settings.cookie_name, expired)
    assert (await client.get("/auth/me")).status_code == 401


async def test_me_rejects_a_valid_token_for_a_deleted_user(client, session):
    """Signature and expiry are fine, but the account no longer exists.

    This is the step-5 database lookup in get_current_user earning its place.
    """
    await signup(client)
    await session.execute(text('delete from "user"'))
    await session.commit()

    assert (await client.get("/auth/me")).status_code == 401


async def test_me_rejects_a_well_formed_token_for_a_random_uuid(client):
    client.cookies.set(settings.cookie_name, create_access_token(uuid4()))
    assert (await client.get("/auth/me")).status_code == 401


# --- logout -----------------------------------------------------------


async def test_logout_returns_204_and_clears_the_session(client):
    await signup(client)
    assert (await client.get("/auth/me")).status_code == 200

    response = await client.post("/auth/logout")
    assert response.status_code == 204

    assert (await client.get("/auth/me")).status_code == 401


async def test_logout_is_harmless_when_not_logged_in(client):
    assert (await client.post("/auth/logout")).status_code == 204
