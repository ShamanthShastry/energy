"""v0.12 CMP-14 account reducer against the published database (HOMEWATT_TEST_DB=1)."""

import uuid

import pytest

pytestmark = pytest.mark.needs_db


def test_create_account_refuses_duplicates_and_bad_input():
    from homewatt.cmp14_onboarding.accounts import check_login, hash_password
    from homewatt.spacetime import SpacetimeClient, SpacetimeError

    c = SpacetimeClient.from_settings()
    email = f"live-{uuid.uuid4().hex[:8]}@example.com"
    c.call("create_user_account", email.upper(), "Live", "48104", hash_password("longenough"), "hh-demo")
    assert check_login(c, email, "longenough") == {"email": email, "name": "Live"}  # stored lower-cased
    assert check_login(c, email, "wrong-pass") is None
    with pytest.raises(SpacetimeError, match="already exists"):
        c.call("create_user_account", email, "Live", "48104", hash_password("x" * 8), "hh-demo")
    with pytest.raises(SpacetimeError, match="ZIP"):
        c.call("create_user_account", "z" + email, "Live", "481", hash_password("x" * 8), "hh-demo")
    with pytest.raises(SpacetimeError, match="no household"):
        c.call("create_user_account", "h" + email, "Live", "48104", hash_password("x" * 8), "hh-nope")
