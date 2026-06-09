# EUMETSAT Download

This workspace contains two minimal scripts to download products from the `EUMETSAT Data Store` using `EUMDAC`.

Main scripts:

- [download_mtg_fci.py](C:/Users/Daniele.LOKI/Documents/medicanes/MTG_data/download_mtg_fci.py): download `MTG FCI` products
- [download_msg_seviri.py](C:/Users/Daniele.LOKI/Documents/medicanes/MTG_data/download_msg_seviri.py): download `MSG SEVIRI` ZIP products

Italian version: [README_it.md](C:/Users/Daniele.LOKI/Documents/medicanes/MTG_data/README_it.md)

## Quick Start

Install the minimal dependencies:

```powershell
pip install eumdac requests
```

Set your credentials:

```powershell
$env:EUMETSAT_CONSUMER_KEY="your_consumer_key"
$env:EUMETSAT_CONSUMER_SECRET="your_consumer_secret"
```

Download `MTG FCI` products:

```powershell
python .\download_mtg_fci.py `
  --start 2026-06-03T05:00:00 `
  --end 2026-06-03T06:30:00 `
  --out .\mtg_downloads
```

Download `MSG SEVIRI` ZIP products:

```powershell
python .\download_msg_seviri.py `
  --start 2026-03-15T00:00:00 `
  --end 2026-03-15T01:00:00 `
  --out .\msg_downloads
```

If you only want to see which products match the interval, add `--list-only`.

## Requirements

- Python 3.9+
- a EUMETSAT account with Data Store access
- EUMETSAT `consumer key` and `consumer secret`
- the Python package `eumdac`
- the Python package `requests` for the MSG downloader

Installation:

```powershell
pip install eumdac requests
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

Alternatively for MTG:

```powershell
python .\download_mtg_fci.py --consumer-key "KEY" --consumer-secret "SECRET" ...
```

Or for MSG SEVIRI:

```powershell
python .\download_msg_seviri.py --consumer-key "KEY" --consumer-secret "SECRET" ...
```

Note: in most cases you do not need a new key if the one you already use for MSG is a valid `EUMETSAT Data Store` key. What usually matters is that the MTG dataset license is enabled on the EUMETSAT portal.

## MTG FCI Usage

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

## MSG SEVIRI Usage

The MSG script downloads full ZIP products as returned by the Data Store. It does not extract files and does not build RGB composites.

Help:

```powershell
python .\download_msg_seviri.py --help
```

Main parameters:

- `--start`: UTC interval start, format `YYYY-MM-DDTHH:MM:SS`
- `--end`: UTC interval end, format `YYYY-MM-DDTHH:MM:SS`
- `--collection`: EUMETSAT collection to use
- `--out`: output directory where ZIP files are stored
- `--download-workers`: concurrent download workers
- `--retries`: maximum retries per product
- `--read-timeout`: HTTP read timeout in seconds
- `--list-only`: list matching products without downloading

Default collection:

```text
EO:EUM:DAT:MSG:MSG15-RSS
```

This corresponds to `MSG-15 Rapid Scan SEVIRI`.

Examples:

### 1. List MSG products without downloading

```powershell
python .\download_msg_seviri.py `
  --start 2026-03-15T00:00:00 `
  --end 2026-03-15T01:00:00 `
  --list-only
```

### 2. Download MSG ZIP products

```powershell
python .\download_msg_seviri.py `
  --start 2026-03-15T00:00:00 `
  --end 2026-03-17T23:55:00 `
  --out .\msg_20260315_20260317
```

### 3. Tune concurrency and retries

```powershell
python .\download_msg_seviri.py `
  --start 2026-03-15T00:00:00 `
  --end 2026-03-15T06:00:00 `
  --download-workers 4 `
  --retries 3 `
  --read-timeout 180 `
  --out .\msg_retry_test
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

For each matching MTG product, the script creates a subdirectory inside `--out`.

Example:

```text
mtg_20260603_q4/
  PRODUCT_ID_1/
    data/...
  PRODUCT_ID_2/
    data/...
```

If you download the full product, the product directory will contain the full archive returned by the Data Store.

For the MSG script, ZIP files are written directly inside `--out` together with a `download_manifest.csv` file.

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
- the dataset license is not enabled for the requested collection

## Possible Extensions

These scripts are intentionally minimal. The most natural next steps are:

- integrate MTG and MSG selection into a single CLI
- batch downloads over multiple time intervals
- automatic retries
- file logging
- guided collection selection
