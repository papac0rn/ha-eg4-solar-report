"""Make an anonymized test fixture from a real Monitor Center export.

    python tests/make_fixture.py <export.xls> tests/fixtures/<name>.xls

Replaces the serial number in every row. Every other column is kept, since the rules read them.
Needs xlrd and xlwt (dev only; the integration itself never writes .xls).
"""
from __future__ import annotations

import sys

import xlrd
import xlwt

ANON_SERIAL = "0000000000"
ID_COLUMNS = {"Serial number", "serialNum", "Serial Number"}


def anonymize(src: str, dst: str) -> None:
    book = xlrd.open_workbook(src)
    out = xlwt.Workbook()
    for sheet in book.sheets():
        ws = out.add_sheet(sheet.name)
        header = [str(v).strip() for v in sheet.row_values(0)] if sheet.nrows else []
        hide = {i for i, h in enumerate(header) if h in ID_COLUMNS}
        for r in range(sheet.nrows):
            for col, value in enumerate(sheet.row_values(r)):
                ws.write(r, col, ANON_SERIAL if r and col in hide else value)
    out.save(dst)


if __name__ == "__main__":
    anonymize(sys.argv[1], sys.argv[2])
