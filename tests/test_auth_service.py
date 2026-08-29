import pytest

from app.core.security import verify_password
from app.services.auth import (
    EmailAlreadyRegistered,
    authenticate_user,
    get_user_by_email,
    normalize_email,
    signup_user,
)


def test_normalize_email_lowercases_and_strips():
    assert normalize_email("  Alice@Example.COM ") == "alice@example.com"


async def test_signup_creates_a_user(session):
    user = await signup_user(session, "alice@example.com", "a-good-password")
    assert user.id is not None
    assert user.email == "alice@example.com"
    assert user.created_at is not None


async def test_signup_stores_a_hash_not_the_password(session):
    user = await signup_user(session, "alice@example.com", "a-good-password")
    assert user.password_hash != "a-good-password"
    assert verify_password("a-good-password", user.password_hash)


async def test_signup_normalizes_the_email(session):
    user = await signup_user(session, "  Alice@Example.COM ", "a-good-password")
    assert user.email == "alice@example.com"


async def test_signup_rejects_a_duplicate_email(session):
    await signup_user(session, "alice@example.com", "a-good-password")
    with pytest.raises(EmailAlreadyRegistered):
        await signup_user(session, "alice@example.com", "another-password")


async def test_signup_rejects_a_duplicate_in_a_different_case(session):
    """Case-only variants are the same mailbox and must collide."""
    await signup_user(session, "alice@example.com", "a-good-password")
    with pytest.raises(EmailAlreadyRegistered):
        await signup_user(session, "ALICE@EXAMPLE.COM", "another-password")


async def test_authenticate_accepts_correct_credentials(session):
    created = await signup_user(session, "alice@example.com", "a-good-password")
    found = await authenticate_user(session, "alice@example.com", "a-good-password")
    assert found is not None
    assert found.id == created.id


async def test_authenticate_is_case_insensitive_on_email(session):
    created = await signup_user(session, "alice@example.com", "a-good-password")
    found = await authenticate_user(session, "ALICE@example.com", "a-good-password")
    assert found is not None
    assert found.id == created.id


async def test_authenticate_rejects_a_wrong_password(session):
    await signup_user(session, "alice@example.com", "a-good-password")
    assert await authenticate_user(session, "alice@example.com", "wrong-one") is None


async def test_authenticate_rejects_an_unknown_email(session):
    assert await authenticate_user(session, "nobody@example.com", "whatever") is None


async def test_get_user_by_email_returns_none_when_absent(session):
    assert await get_user_by_email(session, "nobody@example.com") is None
