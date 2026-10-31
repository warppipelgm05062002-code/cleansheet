"""Command line interface for CleanSheet."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .cleaner import clean
from .config import CleanOptions, Config, load_config
from .errors import CleanSheetError
from .table import Table, read_table, write_table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cleansheet",
        description=(
            "Clean a messy CSV/Excel export deterministically: trim text, normalize "
            "headers, drop empties and duplicates, normalize dates and numbers, and "
            "validate values. Writes a JSON report of every change."
        ),
        epilog=(
            "Examples:\n"
            "  python -m cleansheet -i orders.csv -o orders_clean.csv --report report.json\n"
            "  python -m cleansheet -i orders.csv --preview\n"
            '  python -m cleansheet -i data.xlsx --sheet "Q3" -o data_clean.xlsx -c config.yml\n\n'
            "Pipeline order: trim -> headers -> empty rows -> empty columns -> dates/numbers "
            "-> split -> fill -> required -> duplicates -> validate. See README.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-i", "--input", metavar="FILE", help="Input .csv/.tsv/.txt/.xlsx/.xlsm.")
    parser.add_argument("-o", "--output", metavar="FILE", help="Destination .csv/.tsv/.txt/.xlsx.")
    parser.add_argument("-c", "--config", metavar="FILE.yml", help="YAML cleanup rules.")
    parser.add_argument("--sheet", metavar="NAME", help="Worksheet name for .xlsx input.")
    parser.add_argument(
        "--delimiter", metavar="CHAR", help="CSV delimiter (default: auto by suffix)."
    )
    parser.add_argument("--encoding", metavar="NAME", help="Text encoding (default: utf-8-sig).")
    parser.add_argument("--report", metavar="FILE.json", help="Write a JSON change report.")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print the first rows after cleaning and write nothing.",
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=5,
        metavar="N",
        help="Rows to show with --preview (default: 5).",
    )
    parser.add_argument(
        "--no-auto",
        action="store_true",
        help="Disable heuristic date/number detection; only configured rules run.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _clip(text: str, limit: int = 28) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _print_preview(table: Table, rows_to_show: int) -> None:
    shown = table.rows[: max(0, rows_to_show)]
    widths = [
        min(28, max(len(header), *(len(row[index]) for row in shown)) if shown else len(header))
        for index, header in enumerate(table.headers)
    ]
    widths = [max(1, width) for width in widths]

    def line(values: list[str]) -> str:
        return " | ".join(
            _clip(value, widths[index]).ljust(widths[index]) for index, value in enumerate(values)
        )

    print(f"Preview: first {len(shown)} of {len(table.rows)} row(s); nothing written.")
    print(line(table.headers))
    print("-+-".join("-" * width for width in widths))
    for row in shown:
        print(line(row))


def _print_summary(report: dict, output_path: Path | None) -> None:
    source = report["input"]
    target = report["output"]
    print(
        f"Rows: {source['rows']} -> {target['rows']}    "
        f"Columns: {source['columns']} -> {target['columns']}"
    )
    if output_path is not None:
        print(f"Wrote: {output_path}")
    cleaning = report["cleaning"]
    if cleaning["cells_trimmed"]:
        print(f"Trimmed cells: {cleaning['cells_trimmed']}")
    drops = []
    if cleaning["empty_rows_dropped"]:
        drops.append(f"{cleaning['empty_rows_dropped']} empty row(s)")
    if cleaning["empty_columns_dropped"] or report["heads"]["dropped"]:
        drops.append(f"{len(report['heads']['dropped'])} empty column(s)")
    if cleaning["duplicate_rows_dropped"]:
        drops.append(f"{cleaning['duplicate_rows_dropped']} duplicate row(s)")
    if cleaning["rows_missing_required"]:
        drops.append(f"{cleaning['rows_missing_required']} row(s) missing required values")
    if drops:
        print("Dropped: " + ", ".join(drops))
    if cleaning["cells_filled"]:
        print(f"Filled cells: {cleaning['cells_filled']}")
    for column, stats in report["dates"].items():
        print(f"Dates: {column} {stats['converted']} converted, {stats['unparsed']} unparsed")
    for column, stats in report["numbers"].items():
        print(f"Numbers: {column} {stats['converted']} converted, {stats['unparsed']} unparsed")
    for kind, columns in report["validation"].items():
        for column, stats in columns.items():
            print(
                f"Validation: {kind} on {column}: {stats['invalid']} invalid of {stats['checked']}"
            )
    for warning in report["warnings"]:
        print(f"Warning: {warning}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        auto_override = False if args.no_auto else None
        config = (
            load_config(args.config, auto_detect=auto_override)
            if args.config
            else Config(options=CleanOptions(auto_detect=not args.no_auto))
        )

        input_path = args.input or config.input
        if not input_path:
            raise CleanSheetError("No input file. Pass --input FILE or set 'input' in the config.")
        output_path = args.output or config.output
        if not output_path and not args.preview:
            raise CleanSheetError(
                "No output file. Pass --output FILE, or use --preview to inspect without writing."
            )
        if args.preview_rows < 0:
            raise CleanSheetError("--preview-rows must be zero or greater.")

        sheet = args.sheet or config.sheet
        delimiter = args.delimiter or config.delimiter
        encoding = args.encoding or config.encoding

        table = read_table(input_path, sheet=sheet, delimiter=delimiter, encoding=encoding)
        cleaned, report = clean(table, config.options)

        if args.preview:
            _print_preview(cleaned, args.preview_rows)
            _print_summary(report, None)
        else:
            written = write_table(cleaned, output_path, delimiter=delimiter, encoding=encoding)
            report["output"]["path"] = str(written)
            _print_summary(report, written)

        if args.report:
            report_path = Path(args.report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"Report: {report_path}")
    except CleanSheetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
