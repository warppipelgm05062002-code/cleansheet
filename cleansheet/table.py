"""Read and write CSV/TSV/XLSX tables without converting values silently.

Every cell is held as text. Numbers and dates are only rewritten by explicit
cleaning rules, so what the file said is what the file keeps unless a rule
changes it on purpose.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import CleanSheetError


@dataclass
class Table:
    """A rectangular table: one header row plus text rows of equal width."""

    headers: list[str]
    rows: list[list[str]] = field(default_factory=list)
    sheet: str | None = None
    source: str | None = None


CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
EXCEL_SUFFIXES = {".xlsx", ".xlsm"}


def cell_to_text(value: Any) -> str:
    """Render an Excel/CSV cell as plain text without losing meaningful digits."""
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        if value.time() == dt.time(0, 0):
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dt.time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _pad(row: list[str], width: int) -> list[str]:
    if len(row) >= width:
        return row[:width]
    return row + [""] * (width - len(row))


def _read_csv(path: Path, delimiter: str | None, encoding: str) -> Table:
    if delimiter is None:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    try:
        with path.open("r", encoding=encoding, newline="") as handle:
            raw = [row for row in csv.reader(handle, delimiter=delimiter) if row]
    except UnicodeDecodeError as exc:
        raise CleanSheetError(
            f"Could not decode {path.name} as {encoding}. "
            "Try --encoding utf-8 or --encoding latin-1."
        ) from exc
    if not raw:
        raise CleanSheetError(f"{path.name} has no rows.")
    width = max(len(row) for row in raw)
    headers = _pad(raw[0], width)
    rows = [_pad(row, width) for row in raw[1:]]
    return Table(headers=headers, rows=rows, source=str(path))


def _read_excel(path: Path, sheet: str | None) -> Table:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise CleanSheetError(
            "Reading .xlsx files needs openpyxl. Run: pip install -r requirements.txt"
        ) from exc

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises several unrelated types
        raise CleanSheetError(f"Could not open {path.name}: {exc}") from exc

    try:
        if sheet is not None:
            if sheet not in workbook.sheetnames:
                names = ", ".join(workbook.sheetnames)
                raise CleanSheetError(f"Sheet {sheet!r} not found. Sheets: {names}")
            names = [sheet]
        else:
            names = workbook.sheetnames
        if not names:
            raise CleanSheetError(f"{path.name} has no worksheets.")

        selected = names[0]
        worksheet = workbook[selected]
        raw = [
            [cell_to_text(value) for value in row] for row in worksheet.iter_rows(values_only=True)
        ]
    finally:
        workbook.close()

    while raw and not any(cell != "" for cell in raw[0]):
        raw.pop(0)
    if not raw:
        raise CleanSheetError(f"Worksheet {selected!r} in {path.name} is empty.")

    width = max(len(row) for row in raw)
    headers = _pad(raw[0], width)
    rows = [_pad(row, width) for row in raw[1:]]
    return Table(headers=headers, rows=rows, sheet=selected, source=str(path))


def read_table(
    path: str | Path,
    *,
    sheet: str | None = None,
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
) -> Table:
    """Load a CSV/TSV/TXT or XLSX/XLSM file into a :class:`Table`."""
    source = Path(path)
    if not source.exists():
        raise CleanSheetError(f"Input file not found: {source}")
    suffix = source.suffix.lower()
    if suffix in CSV_SUFFIXES:
        return _read_csv(source, delimiter, encoding)
    if suffix in EXCEL_SUFFIXES:
        return _read_excel(source, sheet)
    if suffix == ".xls":
        raise CleanSheetError(
            f"{source.name} is the old .xls format. Save it as .xlsx or .csv first."
        )
    raise CleanSheetError(
        f"Unsupported input type {suffix or '(none)'}. Use .csv, .tsv, .txt, .xlsx, or .xlsm."
    )


def _write_csv(table: Table, path: Path, delimiter: str, encoding: str) -> None:
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(table.headers)
        writer.writerows(table.rows)


def _write_excel(table: Table, path: Path) -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise CleanSheetError(
            "Writing .xlsx files needs openpyxl. Run: pip install -r requirements.txt"
        ) from exc

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "cleaned"
    worksheet.append(table.headers)
    for row in table.rows:
        worksheet.append(row)

    if table.headers:
        for cell in worksheet[1]:
            cell.font = Font(bold=True)
        worksheet.freeze_panes = "A2"
        last_column = get_column_letter(len(table.headers))
        worksheet.auto_filter.ref = f"A1:{last_column}{len(table.rows) + 1}"
        for index, header in enumerate(table.headers, start=1):
            width = max(
                [len(str(header))]
                + [len(row[index - 1]) for row in table.rows if index - 1 < len(row)]
            )
            worksheet.column_dimensions[get_column_letter(index)].width = min(
                max(10, width + 2), 60
            )

    workbook.save(path)


def write_table(
    table: Table,
    path: str | Path,
    *,
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
) -> Path:
    """Write a cleaned table to CSV/TSV or XLSX, creating the parent folder."""
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix in CSV_SUFFIXES:
        if delimiter is None:
            delimiter = "\t" if suffix == ".tsv" else ","
    elif suffix in EXCEL_SUFFIXES:
        pass
    elif suffix == ".xls":
        raise CleanSheetError("Cannot write .xls. Use .xlsx or .csv.")
    else:
        raise CleanSheetError(
            f"Unsupported output type {suffix or '(none)'}. Use .csv, .tsv, .txt, .xlsx, or .xlsm."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    if suffix in CSV_SUFFIXES:
        _write_csv(table, target, delimiter or ",", encoding)
    else:
        _write_excel(table, target)
    return target
