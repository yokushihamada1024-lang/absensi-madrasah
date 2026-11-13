"""SheetsRepository — backend Google Sheets via gspread (service account).

- Semua panggilan API diserialkan dengan satu lock (gspread/requests tidak dijamin thread-safe,
  dan ini sekaligus meredam lonjakan kuota).
- Mirror per tab dengan TTL; tulisan proses ini langsung memperbarui mirror.
- Retry exponential backoff untuk 429/5xx dan error jaringan.
- Nilai ditulis RAW sebagai string, dibaca UNFORMATTED_VALUE (DECISIONS D14).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from core.repo.base import SCHEMA, Repository
from core.repo.tables import Row, TableBackend, build_repository

log = logging.getLogger(__name__)
T = TypeVar("T")

STATIC_TTL_S = 30.0
BIG_TTL_S = 300.0
BIG_TABS = {"attendance", "attempts", "audit_log", "session_instances", "payslips"}
RETRY_STATUS = {429, 500, 502, 503, 504}


def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def load_credentials_info() -> dict[str, Any]:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        return json.loads(raw)
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    raise RuntimeError("Set GOOGLE_SERVICE_ACCOUNT_JSON atau GOOGLE_APPLICATION_CREDENTIALS")


@dataclass
class _Cache:
    rows: list[Row] = field(default_factory=list)
    loaded_at: float = 0.0
    last_row: int = 1  # nomor baris data terakhir yang diketahui (1 = hanya header)


class SheetsBackend(TableBackend):
    def __init__(self, spreadsheet_id: str, credentials_info: dict[str, Any] | None = None,
                 sleep: Callable[[float], None] = time.sleep, client: Any = None) -> None:
        import gspread  # impor lokal: core lain tidak bergantung pada gspread

        self._gspread = gspread
        if client is not None:  # test: klien palsu tanpa internet
            self._gc = client
        else:
            self._gc = gspread.service_account_from_dict(credentials_info or load_credentials_info())
        self._spreadsheet_id = spreadsheet_id
        self._sh = None
        self._ws: dict[str, Any] = {}
        self._cache: dict[str, _Cache] = {}
        self._lock = threading.RLock()
        self._sleep = sleep

    # -- infrastruktur -----------------------------------------------------

    def _call(self, fn: Callable[[], T], what: str) -> T:
        delay = 1.0
        for attempt in range(6):
            try:
                return fn()
            except self._gspread.exceptions.APIError as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status not in RETRY_STATUS or attempt == 5:
                    raise
                log.warning("Sheets %s → HTTP %s, retry dalam %.0fs", what, status, delay)
            except (ConnectionError, TimeoutError, OSError) as e:
                if attempt == 5:
                    raise
                log.warning("Sheets %s → %s, retry dalam %.0fs", what, type(e).__name__, delay)
            self._sleep(delay)
            delay = min(delay * 2, 30)
        raise RuntimeError("unreachable")

    def spreadsheet(self):
        if self._sh is None:
            self._sh = self._call(lambda: self._gc.open_by_key(self._spreadsheet_id), "open")
        return self._sh

    def worksheet(self, tab: str):
        if tab not in self._ws:
            sh = self.spreadsheet()
            self._ws[tab] = self._call(lambda: sh.worksheet(tab), f"worksheet {tab}")
        return self._ws[tab]

    def _last_col(self, tab: str) -> str:
        return _col_letter(len(SCHEMA[tab]))

    def _to_dict(self, tab: str, values: list[Any]) -> dict[str, str]:
        cols = SCHEMA[tab]
        vals = ["" if v is None else str(v) for v in values] + [""] * len(cols)
        out = {c: vals[i] for i, c in enumerate(cols)}
        # Sheets UNFORMATTED mengembalikan boolean asli bila sel diketik manual
        for k, v in out.items():
            if v in ("True", "False"):
                out[k] = v.upper()
        return out

    def _ttl(self, tab: str) -> float:
        return BIG_TTL_S if tab in BIG_TABS else STATIC_TTL_S

    # -- operasi backend ---------------------------------------------------

    def rows(self, tab: str, fresh: bool = False) -> list[Row]:
        with self._lock:
            c = self._cache.get(tab)
            if not fresh and c is not None and time.monotonic() - c.loaded_at < self._ttl(tab):
                return list(c.rows)
            ws = self.worksheet(tab)
            unformatted = self._gspread.utils.ValueRenderOption.unformatted
            values = self._call(lambda: ws.get_all_values(value_render_option=unformatted), f"read {tab}")
            header = [str(h).strip() for h in (values[0] if values else [])]
            if header[: len(SCHEMA[tab])] != SCHEMA[tab]:
                raise RuntimeError(
                    f"Header tab '{tab}' tidak sesuai skema. Jalankan: python -m scripts.bootstrap_sheets"
                )
            rows = [(i + 2, self._to_dict(tab, r)) for i, r in enumerate(values[1:])]
            self._cache[tab] = _Cache(rows=rows, loaded_at=time.monotonic(), last_row=len(values))
            return list(rows)

    def tail(self, tab: str, n: int) -> list[Row]:
        with self._lock:
            c = self._cache.get(tab)
            if c is None:
                self.rows(tab, fresh=True)
                c = self._cache[tab]
            start = max(2, c.last_row - n + 1)
            end = c.last_row + 200  # tangkap baris yang mungkin ditambah di luar proses ini
            ws = self.worksheet(tab)
            unformatted = self._gspread.utils.ValueRenderOption.unformatted
            rng = f"A{start}:{self._last_col(tab)}{end}"
            values = self._call(lambda: ws.get(rng, value_render_option=unformatted), f"tail {tab}")
            out: list[Row] = []
            for i, r in enumerate(values):
                if any(str(v).strip() for v in r):
                    out.append((start + i, self._to_dict(tab, r)))
            return out

    def append(self, tab: str, values: dict[str, str]) -> int:
        with self._lock:
            ws = self.worksheet(tab)
            row = [values.get(col, "") for col in SCHEMA[tab]]
            raw = self._gspread.utils.ValueInputOption.raw
            ins = self._gspread.utils.InsertDataOption.insert_rows
            resp = self._call(
                lambda: ws.append_row(row, value_input_option=raw, insert_data_option=ins, table_range="A1"),
                f"append {tab}",
            )
            rng = (resp or {}).get("updates", {}).get("updatedRange", "")
            m = re.search(r"!A(\d+)", rng)
            if not m:
                # tidak tahu nomor baris → paksa muat ulang berikutnya
                self._cache.pop(tab, None)
                fresh = self.rows(tab, fresh=True)
                return fresh[-1][0] if fresh else 2
            rownum = int(m.group(1))
            c = self._cache.get(tab)
            if c is not None:
                c.rows.append((rownum, {col: values.get(col, "") for col in SCHEMA[tab]}))
                c.last_row = max(c.last_row, rownum)
            return rownum

    def update(self, tab: str, rownum: int, values: dict[str, str], key_col: str) -> None:
        with self._lock:
            ws = self.worksheet(tab)
            last = self._last_col(tab)
            unformatted = self._gspread.utils.ValueRenderOption.unformatted
            cur = self._call(
                lambda: ws.get(f"A{rownum}:{last}{rownum}", value_render_option=unformatted),
                f"verify {tab}",
            )
            cur_d = self._to_dict(tab, cur[0] if cur else [])
            if cur_d.get(key_col) != values.get(key_col):
                self._cache.pop(tab, None)
                raise RuntimeError(f"{tab} baris {rownum}: kunci berubah, update dibatalkan")
            row = [values.get(col, "") for col in SCHEMA[tab]]
            raw = self._gspread.utils.ValueInputOption.raw
            self._call(
                lambda: ws.update([row], range_name=f"A{rownum}:{last}{rownum}", value_input_option=raw),
                f"update {tab}",
            )
            c = self._cache.get(tab)
            if c is not None:
                c.rows = [(n, ({col: values.get(col, "") for col in SCHEMA[tab]} if n == rownum else r))
                          for n, r in c.rows]

    # -- bootstrap -----------------------------------------------------------

    def ensure_schema(self) -> list[str]:
        """Buat tab + header jika belum ada. Idempoten. Kembalikan daftar aksi."""
        actions: list[str] = []
        with self._lock:
            sh = self.spreadsheet()
            existing = {ws.title: ws for ws in self._call(sh.worksheets, "list worksheets")}
            for tab, cols in SCHEMA.items():
                ws = existing.get(tab)
                if ws is None:
                    ws = self._call(
                        lambda t=tab, c=cols: sh.add_worksheet(title=t, rows=1000, cols=len(c)),
                        f"add {tab}",
                    )
                    actions.append(f"buat tab {tab}")
                header = self._call(lambda w=ws: w.row_values(1), f"header {tab}")
                if not header:
                    raw = self._gspread.utils.ValueInputOption.raw
                    self._call(
                        lambda w=ws, t=tab, c=cols, r=raw: w.update([c], range_name=f"A1:{self._last_col(t)}1",
                                                             value_input_option=r),
                        f"write header {tab}",
                    )
                    actions.append(f"tulis header {tab}")
                elif header[: len(cols)] != cols:
                    raise RuntimeError(f"Header tab '{tab}' berbeda dari skema: {header}")
                self._ws[tab] = ws
            self._cache.clear()
        return actions


def SheetsRepository(spreadsheet_id: str, credentials_info: dict[str, Any] | None = None) -> Repository:  # noqa: N802
    return build_repository(SheetsBackend(spreadsheet_id, credentials_info))
