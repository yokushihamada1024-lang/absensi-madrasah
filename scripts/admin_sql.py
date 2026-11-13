"""Cetak SQL INSERT untuk akun admin pertama (untuk ditempel di Supabase SQL Editor).

PIN diketik di terminal (tidak tampil) dan hanya hash argon2-nya yang dicetak.
Pakai:  python -m scripts.admin_sql
"""

from __future__ import annotations

import getpass
import re
import sys
import uuid

from core.models import AppError
from core.security import hash_pin
from core.timeutil import system_clock, to_iso

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def admin_insert_sql(username: str, name: str, pin: str) -> str:
    username = username.strip().lower()
    name = name.strip()
    if not USERNAME_RE.match(username):
        raise AppError("INVALID_INPUT", "Username 3–32 karakter: huruf kecil, angka, titik, minus, garis bawah.", 422)
    if not name:
        raise AppError("INVALID_INPUT", "Nama wajib diisi.", 422)
    return (
        "insert into absensi.users (user_id, username, name, role, pin_hash, token_version, active, created_at)\n"
        f"values ({_q(str(uuid.uuid4()))}, {_q(username)}, {_q(name)}, 'admin', {_q(hash_pin(pin))}, 0, true, "
        f"{_q(to_iso(system_clock()))});"
    )


def main() -> int:
    username = input("Username admin: ")
    name = input("Nama lengkap: ")
    pin = getpass.getpass("PIN (min 6 karakter, tidak tampil): ")
    if getpass.getpass("Ulangi PIN: ") != pin:
        print("PIN tidak sama.", file=sys.stderr)
        return 1
    try:
        sql = admin_insert_sql(username, name, pin)
    except AppError as e:
        print(e.message, file=sys.stderr)
        return 1
    print("\n-- Tempel di Supabase SQL Editor lalu Run:\n")
    print(sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
