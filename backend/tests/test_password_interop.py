"""Guards the shared `users.password` contract with LWCAM / LWCamAdmin.

Both Flutter apps hash with the Dart `bcrypt` package via PasswordHasher; this
backend must read those hashes and write ones they can read back. A regression
here silently locks operators out of one app or the other, so the fixture below
is a real $2a$ hash produced by the Dart side — do not regenerate it in Python.
"""

from app.core.security import hash_password, verify_password

# BCrypt.hashpw("Lifewood01", BCrypt.gensalt()) — Dart bcrypt 1.2.0 defaults.
DART_HASH = "$2a$10$IGv26hHnJPaxrJmMwVKJZeGogYJ1bTGCkp0zX3IlfFXdGPSf/MX.K"
DART_PLAINTEXT = "Lifewood01"


def test_reads_hash_written_by_flutter_apps() -> None:
    assert verify_password(DART_PLAINTEXT, DART_HASH)
    assert not verify_password("wrong", DART_HASH)


def test_writes_hash_the_flutter_apps_can_read() -> None:
    hashed = hash_password(DART_PLAINTEXT)
    # Dart's BCrypt.checkpw round-trips the minor version, so the prefix and
    # cost must match what its gensalt() emits or the string compare fails.
    assert hashed.startswith("$2a$10$")
    assert len(hashed) == 60
    assert verify_password(DART_PLAINTEXT, hashed)


def test_salts_are_random() -> None:
    assert hash_password(DART_PLAINTEXT) != hash_password(DART_PLAINTEXT)


def test_legacy_md5_row_fails_instead_of_raising() -> None:
    # Any account still holding the pre-bcrypt MD5 hash must fail the check,
    # not blow up login with a ValueError.
    assert not verify_password(DART_PLAINTEXT, "8B1A9953C4611296A827ABF8C47804D7")
    assert not verify_password(DART_PLAINTEXT, "")
    assert not verify_password(DART_PLAINTEXT, None)


def test_truncates_at_bcrypt_limit() -> None:
    # 72-byte ceiling is bcrypt's, not ours; pin it so a library change shows up
    # here rather than as "long passwords stopped matching".
    hashed = hash_password("a" * 72)
    assert verify_password("a" * 80, hashed)
