# MTG Download

This workspace contains a minimal script to download `MTG FCI` products from the `EUMETSAT Data Store` using `EUMDAC`.

Main script: [download_mtg_fci.py](C:/Users/Daniele.LOKI/Documents/medicanes/MTG_data/download_mtg_fci.py)

Italian version: [README_it.md](C:/Users/Daniele.LOKI/Documents/medicanes/MTG_data/README_it.md)

## Requirements

- Python 3.9+
- a EUMETSAT account with Data Store access
- EUMETSAT `consumer key` and `consumer secret`
- the Python package `eumdac`

Installation:

```powershell
pip install eumdac
```

## Credentials

The script accepts credentials in two ways:

1. from the command line
2. through environment variables

PowerShell example:

```powershell
$env:EUMETSAT_CONSUMER_KEY="your_consumer_key"
$env:EUMETSAT_CONSUMER_SECRET="your_consumer_secret"
```

Alternatively:

```powershell
python .\download_mtg_fci.py --consumer-key "KEY" --consumer-secret "SECRET" ...
```

Note: in most cases you do not need a new key if the one you already use for MSG is a valid `EUMETSAT Data Store` key. What usually matters is that the MTG dataset license is enabled on the EUMETSAT portal.

## Basic Usage

The script searches for products in the requested time interval and then:

- if you do not specify filters, it downloads the full product
- if you specify `--coverage`, it downloads only the corresponding MTG chunks
- if you specify `--entry`, it downloads only the files matching the provided wildcards

Help:

```powershell
python .\download_mtg_fci.py --help
```

## Main Parameters

- `--start`: UTC interval start, format `YYYY-MM-DDTHH:MM:SS`
- `--end`: UTC interval end, format `YYYY-MM-DDTHH:MM:SS`
- `--collection`: EUMETSAT collection to use
- `--out`: output directory
- `--coverage`: MTG area to download (`FD`, `H1`, `H2`, `T1`, `T2`, `T3`, `Q1`, `Q2`, `Q3`, `Q4`)
- `--entry`: wildcard for single files inside the product
- `--list-only`: list matching products without downloading

Default collection:

```text
EO:EUM:DAT:0662
```

This corresponds to `MTG FCI L1c normal resolution`.

## Examples

### 1. List products without downloading

```powershell
python .\download_mtg_fci.py `
  --start 2026-06-03T05:00:00 `
  --end 2026-06-03T06:30:00 `
  --list-only
```

### 2. Download the full product

```powershell
python .\download_mtg_fci.py `
  --start 2026-06-03T05:00:00 `
  --end 2026-06-03T06:30:00 `
  --out .\downloads_full
```

### 3. Download only the Europe coverage (`Q4`)

```powershell
python .\download_mtg_fci.py `
  --start 2026-06-03T05:00:00 `
  --end 2026-06-03T06:30:00 `
  --coverage Q4 `
  --out .\mtg_20260603_q4
```

### 4. Download only files matching a wildcard

```powershell
python .\download_mtg_fci.py `
  --start 2026-06-03T05:00:00 `
  --end 2026-06-03T06:30:00 `
  --entry "data/*VIS06*.nc" `
  --out .\downloads_vis06
```

### 5. Use a different collection

```powershell
python .\download_mtg_fci.py `
  --collection EO:EUM:DAT:0665 `
  --start 2026-06-03T05:00:00 `
  --end 2026-06-03T06:30:00 `
  --coverage Q4 `
  --out .\mtg_hr_q4
```

## Time Notes

The script works in `UTC`.

If your operational reference is Italian summer time (`CEST`, UTC+2), then:

- `07:00 CEST` = `05:00 UTC`
- `08:30 CEST` = `06:30 UTC`

So for the `June 3, 2026` interval from `07:00` to `08:30` Italian local time, the correct parameters are:

```text
--start 2026-06-03T05:00:00
--end   2026-06-03T06:30:00
```

## Output Structure

For each matching product, the script creates a subdirectory inside `--out`.

Example:

```text
mtg_20260603_q4/
  PRODUCT_ID_1/
    data/...
  PRODUCT_ID_2/
    data/...
```

If you download the full product, the product directory will contain the full archive returned by the Data Store.

## Common Errors

### Missing credentials

Typical message:

```text
Missing credentials. Set --consumer-key/--consumer-secret or the EUMETSAT_CONSUMER_KEY/EUMETSAT_CONSUMER_SECRET environment variables.
```

Solution: export the environment variables or pass credentials through the CLI.

### Reversed time interval

Typical message:

```text
--end must be later than --start.
```

Solution: make sure `--end` is later than `--start`.

### No products found

Common causes:

- the wrong time zone was used
- the wrong collection was selected
- the MTG dataset license is not enabled

## Possible Extensions

This script is intentionally minimal. The most natural next steps are:

- integrate it with the existing MSG script
- batch downloads over multiple time intervals
- automatic retries
- file logging
- guided MTG collection selection
