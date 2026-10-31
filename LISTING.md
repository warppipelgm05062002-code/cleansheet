# Gumroad Listing Copy

## Product title

CleanSheet - CSV & Excel Cleanup Tool with Change Report

## Price suggestion

$9.99

## Short description

Stop fixing messy exports by hand. CleanSheet trims padded text, normalizes headers, drops blank rows and duplicates, fixes dates and currency-formatted numbers, splits names, and flags bad emails - then writes a JSON report counting every change. Runs locally with Python 3.10+. CSV, TSV, and Excel in and out. Unparseable values are left alone and reported, never silently deleted.

## Long description

**Clean a spreadsheet export without wondering what the tool quietly changed.**

CleanSheet is a small command-line tool for a specific job: take a messy CSV or Excel export and produce a tidy copy, with a report that counts every row dropped and every cell rewritten.

It runs on your computer. No upload, no account, no subscription.

**What it does**

- Trims spaces and collapses runs of internal whitespace.
- Normalizes headers to `snake_case` and de-duplicates repeated names.
- Drops rows that are entirely blank and columns that are entirely empty.
- Drops exact duplicate rows, or duplicates on the key columns you choose.
- Normalizes dates to `YYYY-MM-DD` with formats you list and a day-first order you control.
- Normalizes money values such as `$1,234.50` to `1234.5`, with configurable remove-characters and decimal separator.
- Splits one column into several (`Le James` to first/last) when you ask it to.
- Fills blanks with a value you choose.
- Drops rows missing a required column, after filling.
- Validates email, URL, and phone values and reports the bad ones without deleting them.
- Reads `.csv`, `.tsv`, `.txt`, `.xlsx`, `.xlsm`; writes `.csv`, `.tsv`, `.txt`, `.xlsx`.
- Keeps ids and leading zeros as text: `00123` stays `00123`.
- `--preview` shows the cleaned rows and writes nothing.
- `--report report.json` records every conversion, drop, and invalid value.

**Why the report matters**

Most cleanup scripts either work or silently mangle the file. CleanSheet shows its work. The report says things like: 5 cells trimmed, 1 duplicate row dropped, 3 dates converted, 2 values left unparsed with their row numbers. If a number looks wrong later, you can see which rule touched it.

**Honest fit**

This is a command-line tool. If you need a point-and-click app, this is not it.

It handles one table per file, with the first non-empty row as the header. Multi-table worksheets and title rows above the header need a manual pre-step. `.xls` files must be saved as `.xlsx` or `.csv` first.

Auto-detection is based on header names (`order_date`, `amount`, `price`, and similar). A date column called `when` will not be detected; list it explicitly in the config.

Dates are matched only against the formats you list (plus ISO). Ambiguous values such as `05/06/2026` follow the format order you provide. Values that do not match any format stay untouched.

Validation flags format problems; it does not fix them. Duplicate detection is exact after cleaning, not fuzzy.

Excel formulas are read as cached values. If a workbook was never calculated by Excel, formula cells may come back blank. Very large files are loaded into memory; this is for ordinary exports, not multi-gigabyte dumps.

**Requirements**

- Windows, macOS, or Linux
- Python 3.10 or newer
- Two free packages: openpyxl and PyYAML
- Excel is not required to run the tool

**What's included**

- The complete `cleansheet` Python package and command-line entry point
- `requirements.txt`
- `README.md` with Windows, macOS, and Linux setup, full option and config reference, pipeline order, limitations, and troubleshooting
- `config.example.yml` with commented rules
- A messy sample CSV so you can run it immediately
- The pytest test suite (21 tests)
- `LICENSE.txt` covering personal/internal business use on unlimited machines

**How to run it**

1. Install Python 3.10+ and create a virtual environment.
2. Install `requirements.txt`.
3. Run `python -m cleansheet -i YOUR_FILE.csv -o clean.csv --report report.json`.

The README walks through each step.

**Before you buy**

Try the included sample CSV first. If your workflow needs a graphical interface, fuzzy matching, multi-table parsing, or OCR, this tool will not do that. If the tool does not work for your files, request a refund through Gumroad within its refund window.

**Tags**

csv cleaner, excel cleanup, data cleaning, deduplicate rows, csv to excel, data normalization, spreadsheet automation, python cli