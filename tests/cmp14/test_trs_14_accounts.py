"""v0.12 CMP-14: simple sign-up and log-in."""

import pytest

from homewatt.cmp14_onboarding.accounts import (
    Signup,
    SignupError,
    hash_password,
    make_session,
    read_session,
    verify_password,
)

SECRET = b"test-secret"


def test_password_is_salted_scrypt_and_verifies():
    h1, h2 = hash_password("longenough"), hash_password("longenough")
    assert h1.startswith("scrypt$") and h1 != h2  # salted
    assert verify_password("longenough", h1) and not verify_password("wrong-one", h1)
    assert not verify_password("x", "garbage")


def test_session_is_signed_and_expires():
    tok = make_session("a@b.co", SECRET, now=1000.0, days=1)
    assert read_session(tok, SECRET, now=1001.0) == "a@b.co"
    assert read_session(tok, SECRET, now=1000.0 + 86401) is None  # expired
    assert read_session(tok, b"other-secret", now=1001.0) is None  # wrong key
    body, sig = tok.rsplit(".", 1)
    assert read_session(f"{body}x.{sig}", SECRET, now=1001.0) is None  # tampered
    assert read_session(None, SECRET) is None


@pytest.mark.parametrize(("s", "msg"), [
    (Signup("", "a@b.co", "longenough", "48104"), "name"),
    (Signup("A", "not-an-email", "longenough", "48104"), "email"),
    (Signup("A", "a@b.co", "short", "48104"), "8 characters"),
    (Signup("A", "a@b.co", "longenough", "481"), "ZIP"),
])
def test_signup_asks_for_basic_info_and_checks_it(s, msg):
    with pytest.raises(SignupError, match=msg):
        s.validated()
    assert Signup(" A ", "A@B.CO", "longenough", "48104").validated().email == "a@b.co"


def test_every_api_route_but_auth_needs_a_session():
    from fastapi.testclient import TestClient

    from homewatt.cmp15_api.app import app

    c = TestClient(app)
    for path in ("/api/summary", "/api/appliances", "/api/actions", "/api/day/2025-07-14", "/api/thermostat"):
        assert c.get(path).status_code == 401, path
    assert c.post("/api/actions/x/take").status_code == 401
