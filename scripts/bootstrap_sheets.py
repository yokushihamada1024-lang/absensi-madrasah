"""Buat tab + header di spreadsheet (idempoten) dan isi default kelas/mapel/jam sesi/pengaturan.

Pakai:  python -m scripts.bootstrap_sheets
Env:    SPREADSHEET_ID + (GOOGLE_SERVICE_ACCOUNT_JSON | GOOGLE_APPLICATION_CREDENTIALS)
"""

from __future__ import annotations

import os
import sys

from core.repo.memory import seed_defaults
from core.repo.sheets import SheetsBackend
from core.repo.tables import build_repository


def main() -> int:
    sid = os.environ.get("SPREADSHEET_ID", "").strip()
    if not sid:
        print("SPREADSHEET_ID belum di-set.", file=sys.stderr)
        return 2
    backend = SheetsBackend(sid)
    actions = backend.ensure_schema()
    for a in actions:
        print("-", a)
    seed_defaults(build_repository(backend))
    print("Selesai. Tab & header siap; default kelas/mapel/jam sesi diisi bila kosong.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
