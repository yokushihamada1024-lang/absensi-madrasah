"""Terapkan db/schema.sql (idempoten) lalu isi default kelas/mapel/jam sesi/pengaturan.

Pakai:  python -m scripts.migrate
Env:    DATABASE_URL  (Supabase → Connect → Session pooler)
"""

from __future__ import annotations

import os
import sys

from core.repo.postgres import Database, PostgresRepository
from core.repo.seed import seed_defaults


def main() -> int:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("DATABASE_URL belum di-set.", file=sys.stderr)
        return 2
    db = Database(dsn, max_size=1)
    try:
        db.migrate()
        seed_defaults(PostgresRepository(db=db))
    finally:
        db.close()
    print("Selesai: skema 'absensi' siap; default kelas/mapel/jam sesi diisi bila kosong.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
