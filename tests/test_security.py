import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt

from app.core.config import settings
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def _b64url(data: dict) -> str:
    """Encode a dict the way a JWT segment is encoded (no padding)."""
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# --- password hashing -------------------------------------------------


def test_hash_does_not_contain_the_password():
    hashed = hash_password("correct horse battery staple")
    assert "correct horse battery staple" not in hashed
    assert hashed.startswith("$argon2id$")


def test_verify_accepts_the_correct_password():
    hashed = hash_password("s3cret-password")
    assert verify_password("s3cret-password", hashed) is True


def test_verify_rejects_a_wrong_password():
    hashed = hash_password("s3cret-password")
    assert verify_password("wrong-password", hashed) is False


def test_identical_passwords_get_different_hashes():
    """Per-user salt: same input must not produce the same stored hash."""
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second
    assert verify_password("same-password", first)
    assert verify_password("same-password", second)


def test_dummy_hash_never_matches():
    """The login timing-defense hash must not authenticate anyone."""
    assert verify_password("anything at all", DUMMY_HASH) is False


# --- tokens -----------------------------------------------------------


def test_token_round_trip():
    user_id = uuid4()
    assert decode_access_token(create_access_token(user_id)) == user_id


def test_token_payload_is_readable_but_signed():
    """A JWT is signed, not encrypted - the payload is public by design."""
    user_id = uuid4()
    token = create_access_token(user_id)
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["sub"] == str(user_id)
    assert "exp" in claims and "iat" in claims


def test_tampered_payload_is_rejected():
    """Swap in a different user id, keep the original signature."""
    header, _, signature = create_access_token(uuid4()).split(".")
    forged_payload = _b64url({"sub": str(uuid4())})
    assert decode_access_token(f"{header}.{forged_payload}.{signature}") is None


def test_token_signed_with_a_different_key_is_rejected():
    foreign = jwt.encode({"sub": str(uuid4())}, "not-our-secret", algorithm="HS256")
    assert decode_access_token(foreign) is None


def test_alg_none_token_is_rejected():
    """The classic attack: declare alg=none and drop the signature."""
    forged = "{}.{}.".format(
        _b64url({"alg": "none", "typ": "JWT"}),
        _b64url({"sub": str(uuid4())}),
    )
    assert decode_access_token(forged) is None


def test_expired_token_is_rejected():
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    expired = jwt.encode(
        {"sub": str(uuid4()), "iat": past, "exp": past},
        settings.secret_key,
        algorithm="HS256",
    )
    assert decode_access_token(expired) is None


def test_token_without_a_subject_is_rejected():
    no_sub = jwt.encode({"iat": datetime.now(timezone.utc)}, settings.secret_key,
                        algorithm="HS256")
    assert decode_access_token(no_sub) is None


def test_token_with_a_non_uuid_subject_is_rejected():
    bad_sub = jwt.encode({"sub": "not-a-uuid"}, settings.secret_key, algorithm="HS256")
    assert decode_access_token(bad_sub) is None


def test_garbage_input_is_rejected():
    assert decode_access_token("") is None
    assert decode_access_token("not-a-jwt") is None
    assert decode_access_token("a.b.c") is None
