"""Password hashing (spec §12.1: Argon2id) and the password policy."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi defaults follow RFC 9106's second recommended option (Argon2id, 64 MiB, t=3, p=4).
_hasher = PasswordHasher()

MIN_LENGTH = 10
MAX_LENGTH = 128


def password_problem(password: str, email: str | None = None) -> str | None:
    """Why a password is not acceptable, or None. Length over composition rules (NIST 800-63B)."""
    if len(password) < MIN_LENGTH:
        return f"must be at least {MIN_LENGTH} characters"
    if len(password) > MAX_LENGTH:
        return f"must be at most {MAX_LENGTH} characters"
    if password.strip() != password:
        return "must not start or end with spaces"
    if email and password.lower() == email.lower():
        return "must not be your e-mail address"
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# Verified against when the e-mail is unknown, so a login takes the same time either way.
DUMMY_HASH = _hasher.hash("tastify-timing-equalizer")
