"""Tests for CleanSheet's cleaning pipeline, file I/O, and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cleansheet.cleaner import clean
from cleansheet.cli import main
from cleansheet.config import (
    CleanOptions,
    DateRule,
    NumberRule,
    SplitRule,
    load_config,
)
from cleansheet.errors import CleanSheetError
from cleansheet.table import Table, read_table, write_table


def make_table(headers: list[str], rows: list[list[str]], **kwargs) -> Table:
    return Table(headers=headers, rows=rows, **kwargs)


def options(**kwargs) -> CleanOptions:
    kwargs.setdefault("auto_detect", False)
    return CleanOptions(**kwargs)


def test_trim_and_collapse_whitespace() -> None:
    table = make_table(["a", "b"], [["  hello   world ", "x"]])
    cleaned, report = clean(table, options())
    assert cleaned.rows == [["hello world", "x"]]
    assert report["cleaning"]["cells_trimmed"] == 1


def test_normalize_headers_and_duplicates() -> None:
    table = make_table(
        ["First Name", "E-Mail ", "first name", ""],
        [["Le", "a@b.co", "x", "z"]],
    )
    cleaned, report = clean(table, options(drop_duplicates=False))
    assert cleaned.headers == ["first_name", "e_mail", "first_name_2", "column"]
    assert report["heads"]["renamed"]["First Name"] == "first_name"


def test_drop_empty_rows_and_columns() -> None:
    table = make_table(
        ["a", "b", "c"],
        [["1", "", ""], ["", "", ""], ["2", "", "x"]],
    )
    cleaned, report = clean(table, options())
    assert cleaned.headers == ["a", "c"]
    assert cleaned.rows == [["1", ""], ["2", "x"]]
    assert report["cleaning"]["empty_rows_dropped"] == 1
    assert report["heads"]["dropped"] == ["b"]


def test_drop_duplicates_all_columns() -> None:
    table = make_table(["a", "b"], [["1", "x"], ["1", "x"], ["2", "y"]])
    cleaned, report = clean(table, options())
    assert cleaned.rows == [["1", "x"], ["2", "y"]]
    assert report["cleaning"]["duplicate_rows_dropped"] == 1


def test_drop_duplicates_by_key() -> None:
    table = make_table(["a", "b"], [["1", "x"], ["1", "y"], ["2", "z"]])
    cleaned, report = clean(table, options(dedupe_keys=["a"]))
    assert cleaned.rows == [["1", "x"], ["2", "z"]]
    assert report["cleaning"]["duplicate_rows_dropped"] == 1


def test_dates_are_normalized_and_unparsed_values_kept() -> None:
    table = make_table(
        ["order_date"],
        [["05/06/2026"], ["not a date"], ["2026-12-31"]],
    )
    opts = options(dates=[DateRule("order_date", ["%d/%m/%Y"])])
    cleaned, report = clean(table, opts)
    assert cleaned.rows == [["2026-06-05"], ["not a date"], ["2026-12-31"]]
    assert report["dates"]["order_date"] == {
        "converted": 2,
        "unparsed": 1,
        "examples": [{"row": 3, "value": "not a date"}],
    }


def test_numbers_strip_currency_and_thousands() -> None:
    table = make_table(["amount"], [["$1,234.50"], ["n/a"], ["-12"]])
    cleaned, report = clean(table, options(numbers=[NumberRule("amount")]))
    assert cleaned.rows == [["1234.5"], ["n/a"], ["-12"]]
    assert report["numbers"]["amount"]["converted"] == 2
    assert report["numbers"]["amount"]["unparsed"] == 1


def test_validation_reports_but_keeps_values() -> None:
    table = make_table(
        ["email"],
        [["good@example.com"], ["bad@@example.com"]],
    )
    cleaned, report = clean(
        table,
        options(drop_duplicates=False, validate={"email": ["email"]}),
    )
    assert cleaned.rows == [["good@example.com"], ["bad@@example.com"]]
    assert report["validation"]["email"]["email"]["checked"] == 2
    assert report["validation"]["email"]["email"]["invalid"] == 1
    assert report["validation"]["email"]["email"]["examples"] == [
        {"row": 3, "value": "bad@@example.com"}
    ]


def test_required_columns_drop_rows() -> None:
    table = make_table(["name", "email"], [["a", ""], ["b", "b@example.com"]])
    cleaned, report = clean(table, options(required=["email"]))
    assert cleaned.rows == [["b", "b@example.com"]]
    assert report["cleaning"]["rows_missing_required"] == 1


def test_fill_keeps_a_fully_blank_column() -> None:
    table = make_table(["name", "country"], [["a", ""], ["b", ""]])
    cleaned, report = clean(
        table,
        options(fill={"country": "Unknown"}, drop_duplicates=False),
    )
    assert cleaned.headers == ["name", "country"]
    assert cleaned.rows == [["a", "Unknown"], ["b", "Unknown"]]
    assert report["cleaning"]["cells_filled"] == 2


def test_split_column() -> None:
    table = make_table(
        ["full_name", "email"],
        [["Le James", "le@example.com"], ["Anna", "anna@example.com"]],
    )
    cleaned, report = clean(
        table,
        options(splits=[SplitRule("full_name", " ", ["first_name", "last_name"])]),
    )
    assert cleaned.headers == ["first_name", "last_name", "email"]
    assert cleaned.rows == [
        ["Le", "James", "le@example.com"],
        ["Anna", "", "anna@example.com"],
    ]
    assert report["splits"]["full_name"]["rows_without_delimiter"] == 1


def test_auto_detect_dates_and_numbers() -> None:
    table = make_table(
        ["order_date", "amount"],
        [["2026-01-02", "$5.00"]],
    )
    cleaned, report = clean(table, CleanOptions())
    assert cleaned.rows == [["2026-01-02", "5"]]
    assert report["numbers"]["amount"]["converted"] == 1
    assert any("Auto-detected" in warning for warning in report["warnings"])


def test_cli_csv_to_csv_with_report(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    source.write_text(
        'Name , Amount ,Country\n Le  James ,"$1,200.50", Vietnam\n',
        encoding="utf-8-sig",
    )
    output = tmp_path / "clean.csv"
    report_path = tmp_path / "report.json"

    code = main(["-i", str(source), "-o", str(output), "--report", str(report_path)])

    assert code == 0
    assert output.exists()
    assert output.read_text(encoding="utf-8-sig").splitlines()[0] == "name,amount,country"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["output"]["rows"] == 1
    assert report["numbers"]["amount"]["converted"] == 1
    assert report["output"]["path"] == str(output)


def test_cli_preview_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "in.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8-sig")
    output = tmp_path / "never.csv"

    code = main(["-i", str(source), "-o", str(output), "--preview", "--preview-rows", "2"])

    assert code == 0
    assert not output.exists()
    assert "Preview" in capsys.readouterr().out


def test_xlsx_round_trip_preserves_leading_zeros(tmp_path: Path) -> None:
    path = tmp_path / "codes.xlsx"
    table = make_table(["code", "value"], [["00123", "x"], ["00456", "y"]])
    write_table(table, path)
    loaded = read_table(path)
    assert loaded.headers == ["code", "value"]
    assert loaded.rows == [["00123", "x"], ["00456", "y"]]
    assert loaded.sheet == "cleaned"


def test_xlsx_input_sheet_selection(tmp_path: Path) -> None:
    from openpyxl import Workbook

    path = tmp_path / "book.xlsx"
    workbook = Workbook()
    first = workbook.active
    first.title = "First"
    first.append(["skip"])
    second = workbook.create_sheet("Second")
    second.append(["keep"])
    second.append(["yes"])
    workbook.save(path)

    loaded = read_table(path, sheet="Second")
    assert loaded.sheet == "Second"
    assert loaded.headers == ["keep"]
    assert loaded.rows == [["yes"]]


def test_config_loads_example() -> None:
    example = Path(__file__).resolve().parent.parent / "config.example.yml"
    config = load_config(example)
    assert config.input == "sample_input/orders.csv"
    assert config.options.dates[0].column == "order_date"
    assert config.options.numbers[0].column == "amount"
    assert config.options.fill == {"country": "Unknown"}
    assert config.options.validate == {"email": ["email"]}
    assert config.options.splits[0].into == ["first_name", "last_name"]


def test_config_rejects_unknown_key(tmp_path: Path) -> None:
    path = tmp_path / "bad.yml"
    path.write_text("bogus: true\n", encoding="utf-8")
    with pytest.raises(CleanSheetError, match="unknown top-level key"):
        load_config(path)


def test_config_rejects_unknown_rule_key(tmp_path: Path) -> None:
    path = tmp_path / "bad.yml"
    path.write_text("dates:\n  - column: d\n    dayfirst: true\n", encoding="utf-8")
    with pytest.raises(CleanSheetError, match="unknown key"):
        load_config(path)


def test_missing_column_raises_clear_error() -> None:
    table = make_table(["a"], [["1"]])
    with pytest.raises(CleanSheetError, match="not found"):
        clean(table, options(required=["nope"]))


def test_unsupported_extension_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(CleanSheetError, match="Unsupported input type"):
        read_table(path)
