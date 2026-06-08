from __future__ import annotations

import argparse
import fnmatch
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from eumdac import AccessToken, DataStore


COVERAGE_PATTERNS = {
    "FD": ["*_????_00[0-3][0-9].nc", "*_????_0040.nc", "*_????_0041.nc"],
    "H1": ["*_????_000[1-9].nc", "*_????_001[0-9].nc", "*_????_002[0-1].nc", "*_????_0041.nc"],
    "H2": ["*_????_002[0-9].nc", "*_????_003[0-9].nc", "*_????_0040.nc", "*_????_0041.nc"],
    "T1": ["*_????_000[1-9].nc", "*_????_001[0-6].nc", "*_????_0041.nc"],
    "T2": ["*_????_001[3-9].nc", "*_????_002[0-7].nc", "*_????_0041.nc"],
    "T3": ["*_????_002[6-9].nc", "*_????_003[0-9].nc", "*_????_0040.nc", "*_????_0041.nc"],
    "Q1": ["*_????_000[0-9].nc", "*_????_001[0-3].nc", "*_????_0041.nc"],
    "Q2": ["*_????_001[0-9].nc", "*_????_002[0-1].nc", "*_????_0041.nc"],
    "Q3": ["*_????_002[0-9].nc", "*_????_0030.nc", "*_????_0041.nc"],
    "Q4": ["*_????_0029.nc", "*_????_003[0-9].nc", "*_????_0040.nc", "*_????_0041.nc"],
}


def parse_utc(value: str) -> datetime:
    normalized = value.strip().replace("Z", "")
    return datetime.fromisoformat(normalized)


def resolve_credentials(args: argparse.Namespace) -> tuple[str, str]:
    key = (
        args.consumer_key
        or os.getenv("EUMETSAT_CONSUMER_KEY")
        or os.getenv("EUMETSAT_DATASTORE_KEY")
    )
    secret = (
        args.consumer_secret
        or os.getenv("EUMETSAT_CONSUMER_SECRET")
        or os.getenv("EUMETSAT_DATASTORE_SECRET")
    )
    if not key or not secret:
        raise SystemExit(
            "Missing credentials. Set --consumer-key/--consumer-secret or the "
            "EUMETSAT_CONSUMER_KEY/EUMETSAT_CONSUMER_SECRET environment variables."
        )
    return key, secret


def build_entry_filter(args: argparse.Namespace) -> list[str]:
    if args.entry and args.coverage:
        raise SystemExit("Use either --entry or --coverage, not both.")
    if args.coverage:
        return COVERAGE_PATTERNS[args.coverage]
    return args.entry or []


def matching_entries(entries: Iterable[str], patterns: list[str]) -> list[str]:
    if not patterns:
        return []
    matches: list[str] = []
    for entry in entries:
        if any(fnmatch.fnmatch(entry, pattern) for pattern in patterns):
            matches.append(entry)
    return sorted(set(matches))


def download_stream(target: Path, stream) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as fh:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download MTG products from the EUMETSAT Data Store using EUMDAC."
    )
    parser.add_argument("--consumer-key")
    parser.add_argument("--consumer-secret")
    parser.add_argument(
        "--collection",
        default="EO:EUM:DAT:0662",
        help="EUMETSAT collection id. Default: EO:EUM:DAT:0662 (MTG FCI L1c normal resolution).",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="UTC sensing start, e.g. 2026-06-03T05:00:00",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="UTC sensing end, e.g. 2026-06-03T06:30:00",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("downloads"),
        help="Output directory. Default: ./downloads",
    )
    parser.add_argument(
        "--coverage",
        choices=sorted(COVERAGE_PATTERNS),
        help="Download only MTG chunk coverage. Q4 is the usual Europe quarter for FCI L1c.",
    )
    parser.add_argument(
        "--entry",
        nargs="+",
        help="Shell-style wildcard(s) for SIP entries, e.g. data/*VIS06*.nc",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List matching products and exit without downloading.",
    )
    args = parser.parse_args()

    start = parse_utc(args.start)
    end = parse_utc(args.end)
    if end <= start:
        raise SystemExit("--end must be later than --start.")

    consumer_key, consumer_secret = resolve_credentials(args)
    entry_patterns = build_entry_filter(args)

    token = AccessToken((consumer_key, consumer_secret))
    datastore = DataStore(token)
    collection = datastore.get_collection(args.collection)

    results = collection.search(dtstart=start, dtend=end, set="brief")
    products = list(results)

    print(f"Collection: {collection}")
    print(f"Products found: {len(products)}")
    for product in products:
        print(
            f"- {product} | {product.sensing_start.isoformat()}Z -> "
            f"{product.sensing_end.isoformat()}Z"
        )

    if args.list_only:
        return

    args.out.mkdir(parents=True, exist_ok=True)

    for product in products:
        product_dir = args.out / str(product)
        if not entry_patterns:
            with product.open() as stream:
                filename = Path(stream.name).name
                target = product_dir / filename
                print(f"Downloading full product to {target}")
                download_stream(target, stream)
            continue

        entries = matching_entries(product.entries, entry_patterns)
        if not entries:
            print(f"No matching entries for {product}")
            continue

        print(f"Downloading {len(entries)} entries for {product}")
        for entry in entries:
            target = product_dir / entry
            with product.open(entry=entry) as stream:
                download_stream(target, stream)


if __name__ == "__main__":
    main()
