"""Hash PIN dengan argon2."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from core.models import AppError

_ph = PasswordHasher()
MIN_PIN_LEN = 6
MAX_PIN_LEN = 64

# Hash dummy untuk menyamakan waktu respons saat username tidak ada
_DUMMY_HASH = _ph.hash("dummy-pin-untuk-timing")


def validate_pin(pin: str) -> str:
    if not isinstance(pin, str) or not (MIN_PIN_LEN <= len(pin) <= MAX_PIN_LEN):
        raise AppError("INVALID_PIN", f"PIN minimal {MIN_PIN_LEN} karakter.", 422)
    return pin


def hash_pin(pin: str) -> str:
    return _ph.hash(validate_pin(pin))


def verify_pin(pin_hash: str | None, pin: str) -> bool:
    try:
        return _ph.verify(pin_hash or _DUMMY_HASH, pin) and pin_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
