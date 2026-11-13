import uuid
from datetime import UTC, datetime, timedelta

import pytest

from core import tokens
from core.models import AppError

KEY = "master"
SID = str(uuid.uuid4())
NOW = datetime(2026, 11, 13, 6, 30, 7, tzinfo=UTC)
ROT = 30


def tok(slot_offset=0, sid=SID, key=KEY):
    return tokens.make_qr_token(key, sid, tokens.current_slot(NOW, ROT) + slot_offset)


def test_valid_current_slot():
    assert tokens.verify_qr_token(KEY, tok(), NOW, ROT) == SID


def test_previous_slot_accepted():
    assert tokens.verify_qr_token(KEY, tok(-1), NOW, ROT) == SID


def test_slot_minus_two_rejected():
    with pytest.raises(AppError) as e:
        tokens.verify_qr_token(KEY, tok(-2), NOW, ROT)
    assert e.value.code == "TOKEN_EXPIRED"


def test_future_slot_rejected():
    with pytest.raises(AppError) as e:
        tokens.verify_qr_token(KEY, tok(+1), NOW, ROT)
    assert e.value.code == "TOKEN_EXPIRED"


def test_token_lifetime_30_to_60_seconds():
    t = tok()
    assert tokens.verify_qr_token(KEY, t, NOW + timedelta(seconds=29), ROT)
    with pytest.raises(AppError):
        tokens.verify_qr_token(KEY, t, NOW + timedelta(seconds=61), ROT)


def test_modified_signature_rejected():
    sid, slot, sig = tok().split(".")
    bad = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    with pytest.raises(AppError) as e:
        tokens.verify_qr_token(KEY, f"{sid}.{slot}.{bad}", NOW, ROT)
    assert e.value.code == "TOKEN_INVALID"


def test_modified_slot_rejected():
    sid, slot, sig = tok().split(".")
    with pytest.raises(AppError) as e:
        tokens.verify_qr_token(KEY, f"{sid}.{int(slot) + 1}.{sig}", NOW, ROT)
    assert e.value.code == "TOKEN_INVALID"


def test_other_session_id_rejected():
    other = str(uuid.uuid4())
    sid_b64 = tokens._b64e(other.encode())
    _, slot, sig = tok().split(".")
    with pytest.raises(AppError) as e:
        tokens.verify_qr_token(KEY, f"{sid_b64}.{slot}.{sig}", NOW, ROT)
    assert e.value.code == "TOKEN_INVALID"
    # token sah untuk sesi lain ditolak jika diharapkan sesi tertentu
    with pytest.raises(AppError):
        tokens.verify_qr_token(KEY, tok(sid=other), NOW, ROT, expected_session_id=SID)


def test_wrong_master_key_rejected():
    with pytest.raises(AppError) as e:
        tokens.verify_qr_token("lain", tok(), NOW, ROT)
    assert e.value.code == "TOKEN_INVALID"


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "....", "x" * 500, "Zm9v.12.!!!"])
def test_garbage_rejected(garbage):
    with pytest.raises(AppError) as e:
        tokens.verify_qr_token(KEY, garbage, NOW, ROT)
    assert e.value.code == "TOKEN_INVALID"


def test_expires_at_is_end_of_slot():
    slot = tokens.current_slot(NOW, ROT)
    assert tokens.slot_expires_at(slot, ROT) == datetime(2026, 11, 13, 6, 30, 30, tzinfo=UTC)


def test_ticket_roundtrip_and_expiry():
    t = tokens.Ticket("tid", SID, "uid", NOW, 12.3, 10.0, -6.2, 106.8)
    s, exp = tokens.issue_ticket("secret", t)
    back = tokens.decode_ticket("secret", s, NOW + timedelta(seconds=299))
    assert back.ticket_id == "tid" and back.scanned_at == NOW
    with pytest.raises(AppError) as e:
        tokens.decode_ticket("secret", s, NOW + timedelta(seconds=301))
    assert e.value.code == "TICKET_EXPIRED"
    with pytest.raises(AppError) as e:
        tokens.decode_ticket("other", s, NOW)
    assert e.value.code == "TICKET_INVALID"
