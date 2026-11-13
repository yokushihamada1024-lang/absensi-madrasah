from core import tokens
from tests.conftest import MADRASAH, QR_KEY


def qr_now(svc, session):
    return svc.qr(session.session_id).token


def scan(svc, clock, user, session, lat=MADRASAH[0], lng=MADRASAH[1], acc=10.0, token=None):
    tok = token or qr_now(svc, session)
    ms = clock().timestamp() * 1000
    return svc.scan(user, tok, lat, lng, acc, ms, ms)


def scan_submit(svc, clock, user, session, kelas="Umar", mapel="Fikih"):
    r = scan(svc, clock, user, session)
    return svc.submit(user, r.ticket, kelas, mapel)


def stale_token(svc, session, clock, slots_back=2):
    rot = svc.repo.settings.get().qr_rotate_sec
    return tokens.make_qr_token(QR_KEY, session.session_id, tokens.current_slot(clock(), rot) - slots_back)
