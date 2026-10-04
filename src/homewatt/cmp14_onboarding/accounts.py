"""v0.12 CMP-14 sign-up and log-in, kept simple on purpose (OI-07: every account opens the one
demo household). Passwords are scrypt-hashed with a per-account salt; a session is a signed
cookie (HMAC-SHA256) carrying the email and an expiry. No email verification, no reset."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass

from homewatt.config import REPO_ROOT

SESSION_COOKIE = "hw_session"
SESSION_DAYS = 7
MIN_PASSWORD = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SECRET_FILE = REPO_ROOT / "data" / ".session_secret"
_N, _R, _P = 2**14, 8, 1


class SignupError(ValueError):
    pass


@dataclass(frozen=True)
class Signup:
    name: str
    email: str
    password: str
    zip: str

    def validated(self) -> Signup:
        name, email, zip_ = self.name.strip(), self.email.strip().lower(), self.zip.strip()
        if not name:
            raise SignupError("Enter your name.")
        if not EMAIL_RE.match(email):
            raise SignupError("That email doesn't look right.")
        if len(self.password) < MIN_PASSWORD:
            raise SignupError(f"Use a password of at least {MIN_PASSWORD} characters.")
        if not re.fullmatch(r"\d{5}", zip_):
            raise SignupError("ZIP must be 5 digits.")
        return Signup(name, email, self.password, zip_)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def session_secret() -> bytes:
    """HOMEWATT_SESSION_SECRET if set, else a random secret kept in data/.session_secret (gitignored)."""
    from homewatt.config import get_settings

    s = get_settings().session_secret
    if s:
        return s.encode()
    if not SECRET_FILE.exists():
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        SECRET_FILE.write_text(secrets.token_hex(32))
        SECRET_FILE.chmod(0o600)
    return SECRET_FILE.read_text().strip().encode()


def make_session(email: str, secret: bytes, now: float | None = None, days: int = SESSION_DAYS) -> str:
    exp = int((now or time.time()) + days * 86400)
    body = base64.urlsafe_b64encode(f"{email}|{exp}".encode()).decode()
    sig = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_session(token: str | None, secret: bytes, now: float | None = None) -> str | None:
    """The email in a valid, unexpired session, else None."""
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        email, exp = base64.urlsafe_b64decode(body.encode()).decode().rsplit("|", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    return email if int(exp) > (now or time.time()) else None


def find_account(client, email: str) -> dict | None:
    email = email.strip().lower().replace("'", "")
    df = client.sql(f"SELECT * FROM user_account WHERE email = '{email}'")
    return df.iloc[0].to_dict() if len(df) else None


def create_account(client, s: Signup, household_id: str) -> dict:
    from homewatt.spacetime import SpacetimeError

    v = s.validated()
    if find_account(client, v.email):
        raise SignupError("An account with this email already exists. Log in instead.")
    try:
        client.call("create_user_account", v.email, v.name, v.zip, hash_password(v.password), household_id)
    except SpacetimeError as e:
        raise SignupError(str(e)) from e
    return {"email": v.email, "name": v.name}


def check_login(client, email: str, password: str) -> dict | None:
    acc = find_account(client, email)
    if acc is None or not verify_password(password, str(acc["password_hash"])):
        return None
    return {"email": acc["email"], "name": acc["name"]}
