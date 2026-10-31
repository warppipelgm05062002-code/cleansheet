# CleanSheet — CSV & Excel cleanup that tells you what it changed

CleanSheet is a small command-line tool for the boring part of data work: the
export with padded headers, duplicate rows, dates in three formats, currency
symbols inside numbers, and an empty column nobody noticed.

It runs locally, needs no account or subscription, and writes a JSON report
counting every change. Cells it cannot parse are **left exactly as they were**
and listed in the report — nothing is silently deleted or "fixed".

- Reads `.csv`, `.tsv`, `.txt`, `.xlsx`, `.xlsm`
- Writes `.csv`, `.tsv`, `.txt`, `.xlsx`
- Keeps code-like values (`00123`, VAT ids, phone numbers) as text
- Preview mode shows the result without writing a file
- Tested on Windows, macOS, and Linux

## Requirements

- Python 3.10 or newer
- Two free packages: `openpyxl` (Excel) and `PyYAML` (config)

Excel is not required to run the tool, only to view `.xlsx` output.

## Setup

### Windows (PowerShell)

```powershell
cd cleansheet
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### macOS / Linux

```bash
cd cleansheet
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Quick start

Clean a CSV with sensible defaults:

```bash
python -m cleansheet -i orders.csv -o orders_clean.csv --report report.json
```

Inspect first, write later:

```bash
python -m cleansheet -i orders.csv --preview
```

Run the included example:

```bash
python -m cleansheet -c config.example.yml --report sample_output/report.json
```

Clean a sheet from an Excel workbook:

```bash
python -m cleansheet -i report.xlsx --sheet "Q3" -o q3_clean.xlsx
```

## Command line options

| Option | Meaning |
|---|---|
| `-i, --input FILE` | Input file (or set `input:` in the config) |
| `-o, --output FILE` | Output file; required unless `--preview` |
| `-c, --config FILE.yml` | YAML rules (see `config.example.yml`) |
| `--sheet NAME` | Worksheet to read from `.xlsx` / `.xlsm` |
| `--delimiter CHAR` | CSV delimiter override |
| `--encoding NAME` | Text encoding, default `utf-8-sig` |
| `--report FILE.json` | Write the change report |
| `--preview` | Print the cleaned rows and write nothing |
| `--preview-rows N` | Rows to show in preview (default 5) |
| `--no-auto` | Disable heuristic date/number detection |
| `--version` | Print the version |

## What the defaults do

With no config, CleanSheet:

1. trims surrounding whitespace and collapses runs of internal whitespace
2. normalizes headers to `snake_case` (`Order ID ` becomes `order_id`)
3. drops rows where every cell is blank
4. drops columns where every cell is blank
5. auto-detects date-like and money-like columns **by header name**
   (`order_date`, `created_at`, `amount`, `price`, `total`, `qty`, ...), and
   rewrites the values it can parse; unparsed values stay untouched and are reported
6. drops exact duplicate rows

Auto-detection is a convenience, not a promise. Turn it off with `--no-auto` or
`auto_detect: false`, and list the columns explicitly when the data matters.

## Pipeline order

Rules always run in this order. Later rules see the columns produced by
earlier ones:

```
trim -> headers -> empty rows -> empty columns -> dates/numbers
     -> split -> fill -> required -> duplicates -> validate
```

Why this order:

- **Dates/numbers before split/fill** so values are normalized while their
  source column still exists.
- **Fill before required** so a filled default can satisfy a required column.
- **Duplicates after fill** so rows made identical by the same default are
  caught.
- **Validation last** so the report describes the rows you will actually ship.
  Validation never deletes a value.

## Configuration reference

```yaml
trim: true                    # strip + collapse whitespace
collapse_whitespace: true
normalize_headers: true       # snake_case, de-duplicated names
drop_empty_rows: true
drop_empty_columns: true
drop_duplicates: true
dedupe_keys: []               # e.g. [order_id]; dedupe on these columns only
dates:
  - column: order_date
    formats: ["%d/%m/%Y", "%Y-%m-%d"]
numbers:
  - column: amount
    remove_chars: "$€£₫, "     # characters deleted before parsing
    decimal: "."                # use "," for European decimal commas
required: [email]             # rows with a blank here are dropped
fill:
  country: Unknown            # blank cells replaced
split:
  - column: customer_name
    delimiter: " "
    into: [first_name, last_name]
    keep_original: false
validate:                     # email | url | phone; report only
  email: [email]
phone_min_digits: 7
auto_detect: true
```

The config is strict on purpose: an unknown key or misspelled option is an
error, not a silent no-op. Column names in rules may use either the original
header (`Order Date`) or the normalized name (`order_date`).

### Dates

Formats are tried in order, so put day-first before month-first for ambiguous
values like `05/06/2026`. Parsed values are written as `YYYY-MM-DD` (or
`YYYY-MM-DD HH:MM:SS` when the original had a time). A value that matches no
format stays unchanged and is counted under `dates.<column>.unparsed`.

### Numbers

`remove_chars` is deleted, `decimal` is replaced with `.`, and the result must
look like a number. So `$1,234.50` becomes `1234.5` with the default config.
Text such as `n/a` or `TBD` stays as-is and is reported. Values are written as
plain numbers without currency symbols or thousands separators.

### Validation

- `email` — one `@`, a domain, and a dot-separated suffix
- `url` — `http://` or `https://` with a host
- `phone` — at least `phone_min_digits` digits (separators ignored)

Invalid values are **kept**. Fixing them automatically would be guessing.

## The report

`--report report.json` writes a machine-readable record of the run:

```json
{
  "input":  {"rows": 5, "columns": 6},
  "output": {"rows": 4, "columns": 7},
  "cleaning": {
    "cells_trimmed": 5,
    "duplicate_rows_dropped": 1,
    "cells_filled": 1
  },
  "dates": {"order_date": {"converted": 3, "unparsed": 2, "examples": []}},
  "validation": {"email": {"email": {"checked": 4, "invalid": 1}}}
}
```

Every dropped row, skipped value, and invalid email is counted. If a number
looks wrong, the report tells you which step touched it.

## Limitations (read before buying)

- **One table per file.** The first non-empty row is the header. Multi-table
  sheets and title rows above the header need a pre-step.
- **`.xls` is not supported.** Save as `.xlsx` or `.csv` first.
- **Formulas are read as cached values** (`data_only=True`). If Excel never
  calculated the file, formula cells may come back blank.
- **Excel dates** stored as real date cells are read as `YYYY-MM-DD`; numbers
  stay numbers as text. No serial-date guessing.
- **Auto-detection is header-based.** A date column named `when` is not
  detected automatically; list it in `dates`.
- **Split is literal.** It splits on one delimiter and fills missing parts with
  blank. It is not a CSV parser inside a cell.
- **No fuzzy dedupe.** Duplicates are exact after cleaning; `Jon` and `John`
  are different rows.
- **Not a database tool.** Everything is held in memory; this is for exports up
  to a few hundred thousand rows, not multi-gigabyte dumps.
- **UTF-8 by default.** Legacy encodings need `--encoding`, e.g. `latin-1`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Could not decode ...` | `--encoding latin-1` (or the file's real encoding) |
| `Column 'x' not found` | Check the report's `heads.after` list; rules use original or snake_case names |
| Dates unchanged | Add the exact format to `dates.formats`, or check for stray spaces (they are trimmed first) |
| `00123` became `123` | It was stored as a number in the source file, not as text |
| Excel shows "number stored as text" | Expected: values are written as text to protect ids and leading zeros |
| Output encoding on Windows | `utf-8-sig` is the default so Excel opens accents correctly |

## Development

```bash
pip install -r requirements-dev.txt
ruff format .
ruff check .
python -m pytest
```

The test suite covers each pipeline step, file round-trips, config validation,
and CLI behavior.

## License

See `LICENSE.txt`. Personal and internal business use on unlimited machines;
do not redistribute or resell the source. Provided as-is, without warranty.