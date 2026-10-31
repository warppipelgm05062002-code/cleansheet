"""YAML configuration for CleanSheet.

The config is deliberately strict: unknown keys and misspelled rules are an
error, not a silent no-op. A cleanup run you cannot explain is worse than a
failed run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import CleanSheetError

DEFAULT_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%m/%d/%Y",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
]

TOP_LEVEL_KEYS = {
    "input",
    "output",
    "sheet",
    "delimiter",
    "encoding",
    "trim",
    "collapse_whitespace",
    "normalize_headers",
    "drop_empty_rows",
    "drop_empty_columns",
    "drop_duplicates",
    "dedupe_keys",
    "dates",
    "numbers",
    "required",
    "fill",
    "split",
    "validate",
    "auto_detect",
    "phone_min_digits",
}

VALIDATORS = {"email", "url", "phone"}


@dataclass
class DateRule:
    column: str
    formats: list[str] = field(default_factory=lambda: list(DEFAULT_DATE_FORMATS))


@dataclass
class NumberRule:
    column: str
    remove_chars: str = "$€£₫, "
    decimal: str = "."


@dataclass
class SplitRule:
    column: str
    delimiter: str
    into: list[str]
    keep_original: bool = False


@dataclass
class CleanOptions:
    trim: bool = True
    collapse_whitespace: bool = True
    normalize_headers: bool = True
    drop_empty_rows: bool = True
    drop_empty_columns: bool = True
    drop_duplicates: bool = True
    dedupe_keys: list[str] = field(default_factory=list)
    dates: list[DateRule] = field(default_factory=list)
    numbers: list[NumberRule] = field(default_factory=list)
    required: list[str] = field(default_factory=list)
    fill: dict[str, str] = field(default_factory=dict)
    splits: list[SplitRule] = field(default_factory=list)
    validate: dict[str, list[str]] = field(default_factory=dict)
    auto_detect: bool = True
    phone_min_digits: int = 7


@dataclass
class Config:
    options: CleanOptions = field(default_factory=CleanOptions)
    input: str | None = None
    output: str | None = None
    sheet: str | None = None
    delimiter: str | None = None
    encoding: str = "utf-8-sig"


def _fail(message: str) -> None:
    raise CleanSheetError(f"Config error: {message}")


def _as_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{where} must be a non-empty string.")
    return value


def _as_str_list(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        _fail(f"{where} must be a list of non-empty strings.")
    return list(value)


def _as_bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{where} must be true or false.")
    return value


def _rule_dict(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{where} must be a mapping with a 'column' key.")
    return value


def _date_rule(value: Any, index: int) -> DateRule:
    where = f"dates[{index}]"
    rule = _rule_dict(value, where)
    allowed = {"column", "formats"}
    unknown = set(rule) - allowed
    if unknown:
        _fail(f"{where} has unknown key(s): {', '.join(sorted(unknown))}.")
    column = _as_str(rule.get("column"), f"{where}.column")
    formats = rule.get("formats", DEFAULT_DATE_FORMATS)
    if not isinstance(formats, list) or not all(isinstance(fmt, str) and fmt for fmt in formats):
        _fail(f"{where}.formats must be a list of strftime strings.")
    return DateRule(column=column, formats=list(formats))


def _number_rule(value: Any, index: int) -> NumberRule:
    where = f"numbers[{index}]"
    rule = _rule_dict(value, where)
    allowed = {"column", "remove_chars", "decimal"}
    unknown = set(rule) - allowed
    if unknown:
        _fail(f"{where} has unknown key(s): {', '.join(sorted(unknown))}.")
    column = _as_str(rule.get("column"), f"{where}.column")
    remove_chars = rule.get("remove_chars", "$€£₫, ")
    if not isinstance(remove_chars, str):
        _fail(f"{where}.remove_chars must be a string of characters to delete.")
    decimal = rule.get("decimal", ".")
    if not isinstance(decimal, str) or len(decimal) != 1:
        _fail(f"{where}.decimal must be a single character.")
    return NumberRule(column=column, remove_chars=remove_chars, decimal=decimal)


def _split_rule(value: Any, index: int) -> SplitRule:
    where = f"split[{index}]"
    rule = _rule_dict(value, where)
    allowed = {"column", "delimiter", "into", "keep_original"}
    unknown = set(rule) - allowed
    if unknown:
        _fail(f"{where} has unknown key(s): {', '.join(sorted(unknown))}.")
    column = _as_str(rule.get("column"), f"{where}.column")
    delimiter = _as_str(rule.get("delimiter"), f"{where}.delimiter")
    into = _as_str_list(rule.get("into"), f"{where}.into")
    if len(into) < 2:
        _fail(f"{where}.into needs at least two target column names.")
    if len(set(into)) != len(into):
        _fail(f"{where}.into contains duplicate column names.")
    keep_original = rule.get("keep_original", False)
    return SplitRule(
        column=column,
        delimiter=delimiter,
        into=into,
        keep_original=_as_bool(keep_original, f"{where}.keep_original"),
    )


def load_config(path: str | Path, *, auto_detect: bool | None = None) -> Config:
    """Parse and validate a YAML config file."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise CleanSheetError(
            "Reading a config file needs PyYAML. Run: pip install -r requirements.txt"
        ) from exc

    source = Path(path)
    if not source.exists():
        raise CleanSheetError(f"Config file not found: {source}")
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CleanSheetError(f"Could not parse {source.name}: {exc}") from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        _fail("the file must contain a mapping at the top level.")
    unknown = set(data) - TOP_LEVEL_KEYS
    if unknown:
        _fail(
            "unknown top-level key(s): "
            + ", ".join(sorted(unknown))
            + f". Allowed: {', '.join(sorted(TOP_LEVEL_KEYS))}."
        )

    options = CleanOptions()
    for key in (
        "trim",
        "collapse_whitespace",
        "normalize_headers",
        "drop_empty_rows",
        "drop_empty_columns",
        "drop_duplicates",
        "auto_detect",
    ):
        if key in data:
            setattr(options, key, _as_bool(data[key], key))

    if "phone_min_digits" in data:
        value = data["phone_min_digits"]
        if not isinstance(value, int) or value < 3:
            _fail("phone_min_digits must be an integer of at least 3.")
        options.phone_min_digits = value
    if "dedupe_keys" in data:
        options.dedupe_keys = _as_str_list(data["dedupe_keys"], "dedupe_keys")
    if "required" in data:
        options.required = _as_str_list(data["required"], "required")

    if "dates" in data:
        if not isinstance(data["dates"], list):
            _fail("dates must be a list.")
        options.dates = [_date_rule(item, index) for index, item in enumerate(data["dates"])]
    if "numbers" in data:
        if not isinstance(data["numbers"], list):
            _fail("numbers must be a list.")
        options.numbers = [_number_rule(item, index) for index, item in enumerate(data["numbers"])]
    if "split" in data:
        if not isinstance(data["split"], list):
            _fail("split must be a list.")
        options.splits = [_split_rule(item, index) for index, item in enumerate(data["split"])]

    if "fill" in data:
        fill = data["fill"]
        if not isinstance(fill, dict):
            _fail("fill must be a mapping of column to replacement text.")
        options.fill = {
            _as_str(column, "fill column"): str(value) for column, value in fill.items()
        }

    if "validate" in data:
        validate = data["validate"]
        if not isinstance(validate, dict):
            _fail("validate must be a mapping such as {email: [email]}.")
        unknown_kinds = set(validate) - VALIDATORS
        if unknown_kinds:
            _fail(
                "unknown validator(s): "
                + ", ".join(sorted(unknown_kinds))
                + f". Use: {', '.join(sorted(VALIDATORS))}."
            )
        options.validate = {
            kind: _as_str_list(columns, f"validate.{kind}") for kind, columns in validate.items()
        }

    if auto_detect is not None:
        options.auto_detect = auto_detect

    config = Config(options=options)
    if "input" in data:
        config.input = _as_str(data["input"], "input")
    if "output" in data:
        config.output = _as_str(data["output"], "output")
    if "sheet" in data:
        config.sheet = _as_str(data["sheet"], "sheet")
    if "delimiter" in data:
        config.delimiter = _as_str(data["delimiter"], "delimiter")
    if "encoding" in data:
        config.encoding = _as_str(data["encoding"], "encoding")
    return config
