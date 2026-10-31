"""The cleaning pipeline.

Order is fixed and documented in README.md:

1. trim / collapse whitespace
2. normalize header names
3. drop empty rows
4. drop empty columns
5. normalize dates and numbers
6. split columns
7. fill blanks
8. drop rows missing required columns
9. drop duplicate rows
10. validate values (report only, never delete)

Every step records what it changed in the report. Nothing is deleted without a
count you can check.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from typing import Any

from .config import CleanOptions, DateRule, NumberRule
from .errors import CleanSheetError
from .table import Table

_DATE_HINT = re.compile(r"(^|_)(date|day|dob|birthday|created|updated|timestamp|time)(_|$)")
_NUMBER_HINT = re.compile(
    r"(amount|price|total|cost|qty|quantity|fee|balance|subtotal|salary|budget|revenue|tax)"
)
_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
_NUMBER_TEXT = re.compile(r"[+-]?\d+(\.\d+)?")

MAX_EXAMPLES = 3


def normalize_name(name: str) -> str:
    """Turn a header into a stable snake_case name."""
    text = re.sub(r"[^0-9a-z]+", "_", name.strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "column"


def _normalize_headers(headers: list[str]) -> tuple[list[str], dict[str, str]]:
    finals: list[str] = []
    renamed: dict[str, str] = {}
    used: set[str] = set()
    for header in headers:
        base = normalize_name(header)
        candidate = base
        counter = 2
        while candidate in used:
            candidate = f"{base}_{counter}"
            counter += 1
        used.add(candidate)
        finals.append(candidate)
        if candidate != header:
            renamed[header] = candidate
    return finals, renamed


def _resolver(headers: list[str], aliases: dict[str, str]) -> Callable[[str], str]:
    def resolve(name: str) -> str:
        target = aliases.get(name, name)
        if target in headers:
            return target
        normalized = normalize_name(name)
        if normalized in headers:
            return normalized
        if name in aliases:
            raise CleanSheetError(
                f"Column {name!r} is no longer present: an earlier rule dropped or "
                "replaced it. Check the rule order in the config."
            )
        raise CleanSheetError(
            f"Column {name!r} not found. Available columns: {', '.join(headers)}."
        )

    return resolve


def _parse_date(value: str, formats: list[str]) -> dt.datetime | None:
    text = value.strip()
    if not text:
        return None
    for fmt in formats:
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


def _format_date(parsed: dt.datetime, original: str) -> str:
    if ":" in original:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return parsed.strftime("%Y-%m-%d")


def _parse_number(value: str, rule: NumberRule) -> float | None:
    text = value.strip()
    if not text:
        return None
    cleaned = "".join(char for char in text if char not in rule.remove_chars)
    if rule.decimal != ".":
        cleaned = cleaned.replace(rule.decimal, ".")
    if not _NUMBER_TEXT.fullmatch(cleaned):
        return None
    try:
        return float(cleaned)
    except ValueError:  # pragma: no cover - regex already constrained this
        return None


def _format_number(number: float) -> str:
    if number.is_integer():
        return str(int(number))
    text = repr(number)
    if "e" in text or "E" in text:
        text = format(number, ".15f").rstrip("0").rstrip(".")
    return text


def _auto_rules(
    headers: list[str], rows: list[list[str]]
) -> tuple[list[DateRule], list[NumberRule], list[str]]:
    dates: list[DateRule] = []
    numbers: list[NumberRule] = []
    warnings: list[str] = []
    for index, header in enumerate(headers):
        values = [row[index] for row in rows if row[index] != ""]
        if not values:
            continue
        if _DATE_HINT.search(header):
            rule = DateRule(column=header)
            if sum(1 for value in values if _parse_date(value, rule.formats)) >= 1:
                dates.append(rule)
                warnings.append(f"Auto-detected date column {header!r} (day-first formats first).")
        elif _NUMBER_HINT.search(header):
            rule = NumberRule(column=header)
            if sum(1 for value in values if _parse_number(value, rule)) >= 1:
                numbers.append(rule)
                warnings.append(f"Auto-detected number column {header!r}.")
    return dates, numbers, warnings


def _is_email(value: str) -> bool:
    return bool(_EMAIL.fullmatch(value.strip()))


def _is_url(value: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_phone(value: str, min_digits: int) -> bool:
    digits = sum(1 for char in value if char.isdigit())
    return digits >= min_digits


def clean(table: Table, options: CleanOptions) -> tuple[Table, dict[str, Any]]:
    """Apply the pipeline and return a new table plus a JSON-ready report."""
    original_headers = list(table.headers)
    headers = list(table.headers)
    width = len(headers)
    rows = [list(row[:width]) + [""] * (width - len(row)) for row in table.rows]

    report: dict[str, Any] = {
        "version": 1,
        "input": {
            "path": table.source,
            "sheet": table.sheet,
            "rows": len(rows),
            "columns": width,
        },
        "heads": {
            "before": list(original_headers),
            "after": [],
            "renamed": {},
            "dropped": [],
            "added": [],
        },
        "cleaning": {
            "cells_trimmed": 0,
            "empty_rows_dropped": 0,
            "empty_columns_dropped": 0,
            "duplicate_rows_dropped": 0,
            "rows_missing_required": 0,
            "cells_filled": 0,
        },
        "dates": {},
        "numbers": {},
        "splits": {},
        "validation": {},
        "warnings": [],
    }

    # 1. trim / collapse whitespace
    if options.trim:
        trimmed = 0
        for row in rows:
            for index, value in enumerate(row):
                new_value = value.strip()
                if options.collapse_whitespace:
                    new_value = re.sub(r"\s+", " ", new_value)
                if new_value != value:
                    trimmed += 1
                    row[index] = new_value
        report["cleaning"]["cells_trimmed"] = trimmed

    # 2. header names
    aliases: dict[str, str] = {}
    if options.normalize_headers:
        finals, renamed = _normalize_headers(headers)
        for original, final in zip(headers, finals):
            aliases.setdefault(original, final)
        headers = finals
        report["heads"]["renamed"] = renamed
    resolve = _resolver(headers, aliases)

    # 3. empty rows
    if options.drop_empty_rows:
        before = len(rows)
        rows = [row for row in rows if any(value != "" for value in row)]
        report["cleaning"]["empty_rows_dropped"] = before - len(rows)

    # 4. empty columns (a column a later rule names is kept even when blank)
    protected: set[str] = set()
    named_columns = [
        *options.fill,
        *options.required,
        *options.dedupe_keys,
        *(column for columns in options.validate.values() for column in columns),
        *(rule.column for rule in options.dates),
        *(rule.column for rule in options.numbers),
        *(rule.column for rule in options.splits),
    ]
    for name in named_columns:
        target = aliases.get(name, name)
        if target in headers:
            protected.add(target)

    if options.drop_empty_columns and rows:
        keep = [
            index
            for index in range(len(headers))
            if headers[index] in protected or any(row[index] != "" for row in rows)
        ]
        if len(keep) < len(headers):
            report["heads"]["dropped"] = [
                header for index, header in enumerate(headers) if index not in keep
            ]
            headers = [headers[index] for index in keep]
            rows = [[row[index] for index in keep] for row in rows]

    # 5. dates and numbers
    date_rules = list(options.dates)
    number_rules = list(options.numbers)
    if options.auto_detect and (not date_rules or not number_rules):
        auto_dates, auto_numbers, warnings = _auto_rules(headers, rows)
        if not date_rules:
            date_rules = auto_dates
        if not number_rules:
            number_rules = auto_numbers
        report["warnings"].extend(warnings)

    for rule in date_rules:
        column = resolve(rule.column)
        index = headers.index(column)
        converted = 0
        unparsed_count = 0
        unparsed: list[dict[str, Any]] = []
        for row_number, row in enumerate(rows, start=2):
            value = row[index]
            if value == "":
                continue
            parsed = _parse_date(value, rule.formats)
            if parsed is None:
                unparsed_count += 1
                if len(unparsed) < MAX_EXAMPLES:
                    unparsed.append({"row": row_number, "value": value})
                continue
            row[index] = _format_date(parsed, value)
            converted += 1
        if unparsed_count:
            report["warnings"].append(
                f"{column!r}: {unparsed_count} value(s) could not be parsed as dates and were left alone."
            )
        report["dates"][column] = {
            "converted": converted,
            "unparsed": unparsed_count,
            "examples": unparsed,
        }

    for rule in number_rules:
        column = resolve(rule.column)
        index = headers.index(column)
        converted = 0
        unparsed_count = 0
        unparsed: list[dict[str, Any]] = []
        for row_number, row in enumerate(rows, start=2):
            value = row[index]
            if value == "":
                continue
            parsed = _parse_number(value, rule)
            if parsed is None:
                unparsed_count += 1
                if len(unparsed) < MAX_EXAMPLES:
                    unparsed.append({"row": row_number, "value": value})
                continue
            row[index] = _format_number(parsed)
            converted += 1
        if unparsed_count:
            report["warnings"].append(
                f"{column!r}: {unparsed_count} value(s) could not be parsed as numbers and were left alone."
            )
        report["numbers"][column] = {
            "converted": converted,
            "unparsed": unparsed_count,
            "examples": unparsed,
        }

    # 6. split columns
    for rule in options.splits:
        column = resolve(rule.column)
        index = headers.index(column)
        new_names = list(rule.into)
        collisions = [name for name in new_names if name in headers]
        if collisions:
            raise CleanSheetError(
                f"Split target(s) already exist as columns: {', '.join(collisions)}."
            )
        parts_needed = len(new_names)
        rebuilt: list[list[str]] = []
        unmatched = 0
        for row in rows:
            value = row[index]
            if value == "":
                parts = [""] * parts_needed
            else:
                split = value.split(rule.delimiter, parts_needed - 1)
                if len(split) < parts_needed:
                    unmatched += 1
                parts = split + [""] * (parts_needed - len(split))
            if rule.keep_original:
                rebuilt.append(row[: index + 1] + parts + row[index + 1 :])
            else:
                rebuilt.append(row[:index] + parts + row[index + 1 :])
        if rule.keep_original:
            headers = headers[: index + 1] + new_names + headers[index + 1 :]
        else:
            headers = headers[:index] + new_names + headers[index + 1 :]
        rows = rebuilt
        report["heads"]["added"].extend(new_names)
        report["splits"][column] = {
            "created": new_names,
            "rows_without_delimiter": unmatched,
        }

    # 7. fill blanks
    for name, replacement in options.fill.items():
        column = resolve(name)
        index = headers.index(column)
        filled = 0
        for row in rows:
            if row[index] == "":
                row[index] = replacement
                filled += 1
        report["cleaning"]["cells_filled"] += filled

    # 8. required columns
    if options.required:
        required_indexes = [headers.index(resolve(name)) for name in options.required]
        before = len(rows)
        rows = [row for row in rows if all(row[index] != "" for index in required_indexes)]
        report["cleaning"]["rows_missing_required"] = before - len(rows)

    # 9. duplicates
    dedupe_keys = options.dedupe_keys
    if dedupe_keys or options.drop_duplicates:
        if dedupe_keys:
            key_indexes = [headers.index(resolve(name)) for name in dedupe_keys]
        else:
            key_indexes = list(range(len(headers)))
        seen: set[tuple[str, ...]] = set()
        unique: list[list[str]] = []
        duplicates = 0
        for row in rows:
            signature = tuple(row[index] for index in key_indexes)
            if signature in seen:
                duplicates += 1
                continue
            seen.add(signature)
            unique.append(row)
        rows = unique
        report["cleaning"]["duplicate_rows_dropped"] = duplicates

    # 10. validation (report only)
    validators: dict[str, Callable[[str], bool]] = {
        "email": _is_email,
        "url": _is_url,
        "phone": lambda value: _is_phone(value, options.phone_min_digits),
    }
    for kind, columns in options.validate.items():
        kind_report: dict[str, Any] = {}
        for name in columns:
            column = resolve(name)
            index = headers.index(column)
            checked = 0
            invalid_count = 0
            invalid: list[dict[str, Any]] = []
            for row_number, row in enumerate(rows, start=2):
                value = row[index]
                if value == "":
                    continue
                checked += 1
                if not validators[kind](value):
                    invalid_count += 1
                    if len(invalid) < MAX_EXAMPLES:
                        invalid.append({"row": row_number, "value": value})
            kind_report[column] = {
                "checked": checked,
                "invalid": invalid_count,
                "examples": invalid,
            }
            if invalid_count:
                report["warnings"].append(
                    f"{column!r}: {invalid_count} value(s) failed the {kind} check "
                    "(kept, not deleted)."
                )
        report["validation"][kind] = kind_report

    report["heads"]["after"] = list(headers)
    report["output"] = {
        "path": None,
        "rows": len(rows),
        "columns": len(headers),
    }
    cleaned = Table(headers=headers, rows=rows, sheet=table.sheet, source=table.source)
    return cleaned, report
