"""Klien gspread palsu (tanpa internet) untuk menguji SheetsBackend."""

from __future__ import annotations

import re

import gspread


def _parse_a1(rng: str) -> tuple[int, int]:
    m = re.match(r"A(\d+):[A-Z]+(\d+)", rng)
    assert m, rng
    return int(m.group(1)), int(m.group(2))


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status_code = status
        self.text = "{}"

    def json(self):
        return {"error": {"code": self.status_code, "message": "fake", "status": "FAKE"}}


class FakeWorksheet:
    def __init__(self, title: str, cols: int) -> None:
        self.title = title
        self.data: list[list] = []
        self.calls: list[str] = []
        self.fail_next: list[int] = []

    def _maybe_fail(self):
        if self.fail_next:
            raise gspread.exceptions.APIError(FakeResponse(self.fail_next.pop(0)))

    def row_values(self, n):
        self.calls.append("row_values")
        return list(self.data[n - 1]) if len(self.data) >= n else []

    def get_all_values(self, value_render_option=None):
        self.calls.append("get_all_values")
        self._maybe_fail()
        return [list(r) for r in self.data]

    def get(self, rng, value_render_option=None):
        self.calls.append(f"get {rng}")
        self._maybe_fail()
        a, b = _parse_a1(rng)
        out = [list(r) for r in self.data[a - 1:b]]
        while out and not any(str(v) for v in out[-1]):
            out.pop()
        return out

    def append_row(self, row, value_input_option=None, insert_data_option=None, table_range=None):
        self.calls.append("append_row")
        self._maybe_fail()
        self.data.append(list(row))
        n = len(self.data)
        return {"updates": {"updatedRange": f"'{self.title}'!A{n}:Z{n}"}}

    def update(self, values, range_name=None, value_input_option=None):
        self.calls.append(f"update {range_name}")
        self._maybe_fail()
        a, _ = _parse_a1(range_name)
        while len(self.data) < a:
            self.data.append([])
        self.data[a - 1] = list(values[0])


class FakeSpreadsheet:
    def __init__(self) -> None:
        self.sheets: dict[str, FakeWorksheet] = {}

    def worksheets(self):
        return list(self.sheets.values())

    def worksheet(self, title):
        if title not in self.sheets:
            raise gspread.exceptions.WorksheetNotFound(title)
        return self.sheets[title]

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet(title, cols)
        self.sheets[title] = ws
        return ws


class FakeClient:
    def __init__(self) -> None:
        self.sh = FakeSpreadsheet()

    def open_by_key(self, key):
        return self.sh
