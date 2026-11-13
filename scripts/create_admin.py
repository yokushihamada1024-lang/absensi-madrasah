"""Buat admin pertama.

Pakai:  python -m scripts.create_admin
        (atau non-interaktif: ADMIN_USERNAME, ADMIN_NAME, ADMIN_PIN di env)
"""

from __future__ import annotations

import getpass
import os
import sys
import uuid

from core.models import AppError, User
from core.repo.base import Repository
from core.security import hash_pin
from core.timeutil import system_clock


def create_admin(repo: Repository, username: str, name: str, pin: str) -> User:
    username = username.strip().lower()
    if not username or not name.strip():
        raise AppError("INVALID_INPUT", "Username dan nama wajib diisi.", 422)
    if repo.users.get_by_username(username):
        raise AppError("USERNAME_TAKEN", f"Username '{username}' sudah dipakai.", 409)
    u = User(
        user_id=str(uuid.uuid4()),
        username=username,
        name=name.strip(),
        role="admin",
        pin_hash=hash_pin(pin),
        created_at=system_clock(),
    )
    repo.users.create(u)
    return u


def main() -> int:
    from core.repo.sheets import SheetsRepository

    sid = os.environ.get("SPREADSHEET_ID", "").strip()
    if not sid:
        print("SPREADSHEET_ID belum di-set.", file=sys.stderr)
        return 2
    username = os.environ.get("ADMIN_USERNAME") or input("Username admin: ")
    name = os.environ.get("ADMIN_NAME") or input("Nama lengkap: ")
    pin = os.environ.get("ADMIN_PIN") or getpass.getpass("PIN (min 6 karakter): ")
    if not os.environ.get("ADMIN_PIN") and getpass.getpass("Ulangi PIN: ") != pin:
        print("PIN tidak sama.", file=sys.stderr)
        return 1
    try:
        u = create_admin(SheetsRepository(sid), username, name, pin)
    except AppError as e:
        print(e.message, file=sys.stderr)
        return 1
    print(f"Admin '{u.username}' dibuat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
