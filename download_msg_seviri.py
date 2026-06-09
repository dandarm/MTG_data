from __future__ import annotations

import argparse
import concurrent.futures
import csv
import logging
import os
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path
from threading import local
from typing import Iterable

import eumdac
import requests


DEFAULT_COLLECTION_ID = "EO:EUM:DAT:MSG:MSG15-RSS"
TIMESTAMP_FROM_PRODUCT_RE = re.compile(r"-(\d{14})\.\d+Z-NA$")
THREAD_LOCAL = local()
LOG = logging.getLogger("download_msg_seviri")


def parse_datetime(value: str, *, is_end: bool) -> datetime:
    raw = value.strip().replace("Z", "")
    formats = (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y%m%d_%H%M",
        "%Y%m%d%H%M",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y_%H:%M",
        "%Y-%m-%d",
        "%d-%m-%Y",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw, fmt)
            if looks_like_date_only(raw):
                return parsed.replace(hour=23, minute=55) if is_end else parsed.replace(hour=0, minute=0)
            return parsed
        except ValueError:
            continue
    raise SystemExit(
        "Unsupported datetime format. Use for example 2026-03-15T00:00:00, "
        "20260315_0000, or 15-03-2026 00:00."
    )


def looks_like_date_only(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or re.fullmatch(r"\d{2}-\d{2}-\d{4}", value))


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


def setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        force=True,
    )


def is_valid_msg_zip(zip_path: Path) -> bool:
    if not zip_path.exists() or zip_path.stat().st_size <= 0:
        return False
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return any(name.lower().endswith(".nat") for name in zf.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def parse_product_start(product_id: str) -> datetime | None:
    match = TIMESTAMP_FROM_PRODUCT_RE.search(product_id)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def sort_product_ids(product_ids: Iterable[str]) -> list[str]:
    return sorted(
        product_ids,
        key=lambda product_id: (parse_product_start(product_id) or datetime.min, product_id),
    )


def get_thread_datastore(consumer_key: str, consumer_secret: str) -> eumdac.DataStore:
    datastore = getattr(THREAD_LOCAL, "datastore", None)
    credentials = getattr(THREAD_LOCAL, "credentials", None)
    current_credentials = (consumer_key, consumer_secret)
    if datastore is not None and credentials == current_credentials:
        return datastore

    token = eumdac.AccessToken(current_credentials)
    datastore = eumdac.DataStore(token)
    THREAD_LOCAL.datastore = datastore
    THREAD_LOCAL.credentials = current_credentials
    return datastore


def search_products(
    consumer_key: str,
    consumer_secret: str,
    collection_id: str,
    start_dt: datetime,
    end_dt: datetime,
) -> list:
    token = eumdac.AccessToken((consumer_key, consumer_secret))
    datastore = eumdac.DataStore(token)
    collection = datastore.get_collection(collection_id)
    products = list(collection.search(dtstart=start_dt, dtend=end_dt))
    products.sort(key=lambda product: (parse_product_start(str(product)) or datetime.min, str(product)))
    LOG.info("Collection: %s", collection)
    LOG.info("Products found: %d", len(products))
    return products


def download_products(
    products: Iterable,
    output_dir: Path,
    collection_id: str,
    consumer_key: str,
    consumer_secret: str,
    download_workers: int,
    retries: int,
    connect_timeout: int,
    read_timeout: int,
    overwrite_invalid: bool,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    product_ids = sort_product_ids(str(product) for product in products)
    valid_paths: list[Path] = []
    pending_ids: list[str] = []

    for product_id in product_ids:
        out_path = output_dir / f"{product_id}.zip"
        if is_valid_msg_zip(out_path):
            valid_paths.append(out_path)
            LOG.debug("Cache hit %s", out_path.name)
            continue
        if out_path.exists():
            if not overwrite_invalid:
                raise SystemExit(f"Found invalid local ZIP and overwrite is disabled: {out_path}")
            LOG.warning("Invalid local ZIP, removing and re-downloading %s", out_path.name)
            out_path.unlink()
        pending_ids.append(product_id)

    LOG.info(
        "Valid ZIPs already present: %d | to download: %d",
        len(valid_paths),
        len(pending_ids),
    )
    if not pending_ids:
        return sorted(valid_paths)

    def download_one(product_id: str) -> Path:
        out_path = output_dir / f"{product_id}.zip"
        tmp_path = out_path.with_suffix(".zip.part")
        last_error: Exception | None = None

        for attempt in range(1, retries + 2):
            try:
                datastore = get_thread_datastore(consumer_key, consumer_secret)
                product = datastore.get_product(
                    product_id=product_id,
                    collection_id=collection_id,
                )
                url = product.datastore.urls.get(
                    "datastore",
                    "download product",
                    vars={
                        "collection_id": collection_id,
                        "product_id": product_id,
                    },
                )
                headers = eumdac.common.headers.copy()
                LOG.info(
                    "Downloading %s [attempt %d/%d]",
                    out_path.name,
                    attempt,
                    retries + 1,
                )
                with requests.get(
                    url,
                    auth=product.datastore.token.auth,
                    stream=True,
                    headers=headers,
                    timeout=(connect_timeout, read_timeout),
                ) as response:
                    response.raise_for_status()
                    expected_bytes = response.headers.get("Content-Length")
                    with tmp_path.open("wb") as file_out:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                file_out.write(chunk)

                if expected_bytes is not None and tmp_path.stat().st_size != int(expected_bytes):
                    raise RuntimeError(
                        f"Incomplete download for {out_path.name}: "
                        f"{tmp_path.stat().st_size} != {expected_bytes} bytes"
                    )

                tmp_path.replace(out_path)
                if not is_valid_msg_zip(out_path):
                    raise RuntimeError(f"Corrupt ZIP or missing .nat file: {out_path.name}")

                LOG.info("Done %s (%.1f MB)", out_path.name, out_path.stat().st_size / 1e6)
                return out_path
            except Exception as exc:
                last_error = exc
                if tmp_path.exists():
                    tmp_path.unlink()
                if attempt > retries:
                    break
                sleep_seconds = min(30, 2 ** (attempt - 1))
                LOG.warning("Retry %d for %s after error: %s", attempt, out_path.name, exc)
                time.sleep(sleep_seconds)

        raise RuntimeError(f"Download failed for {product_id}: {last_error}")

    all_paths = list(valid_paths)
    workers = max(1, int(download_workers))
    LOG.info(
        "Starting concurrent download with %d workers, %d retries max, connect/read timeout %ss/%ss",
        workers,
        retries,
        connect_timeout,
        read_timeout,
    )
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="eumdac",
    ) as executor:
        future_map = {
            executor.submit(download_one, product_id): (index, product_id)
            for index, product_id in enumerate(pending_ids, start=1)
        }
        for future in concurrent.futures.as_completed(future_map):
            index, product_id = future_map[future]
            out_path = future.result()
            LOG.info("[%d/%d] Completed %s", index, len(pending_ids), product_id)
            all_paths.append(out_path)

    return sorted(all_paths)


def write_manifest(manifest_path: Path, zip_paths: Iterable[Path]) -> None:
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["product_id", "product_start_utc", "zip_path", "size_bytes"])
        for zip_path in sorted(zip_paths):
            product_id = zip_path.stem
            product_start = parse_product_start(product_id)
            writer.writerow(
                [
                    product_id,
                    product_start.isoformat() if product_start else "",
                    str(zip_path.resolve()),
                    zip_path.stat().st_size,
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download MSG SEVIRI products from the EUMETSAT Data Store using EUMDAC."
    )
    parser.add_argument("--consumer-key")
    parser.add_argument("--consumer-secret")
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION_ID,
        help="EUMETSAT collection id. Default: EO:EUM:DAT:MSG:MSG15-RSS.",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="UTC start time, e.g. 2026-03-15T00:00:00",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="UTC end time, e.g. 2026-03-17T23:55:00",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("downloads_msg_seviri"),
        help="Output directory. Default: ./downloads_msg_seviri",
    )
    parser.add_argument(
        "--download-workers",
        type=int,
        default=8,
        help="Number of concurrent downloads.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=5,
        help="Maximum retries per product.",
    )
    parser.add_argument(
        "--read-timeout",
        type=int,
        default=180,
        help="Read timeout in seconds for each HTTP stream.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=30,
        help="Connect timeout in seconds for each HTTP request.",
    )
    parser.add_argument(
        "--overwrite-invalid",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Replace corrupt local ZIP files if found.",
    )
    parser.add_argument(
        "--manifest-name",
        default="download_manifest.csv",
        help="Manifest CSV name written into the output directory.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List matching products and exit without downloading.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    start_dt = parse_datetime(args.start, is_end=False)
    end_dt = parse_datetime(args.end, is_end=True)
    if end_dt < start_dt:
        raise SystemExit("--end must be later than or equal to --start.")

    consumer_key, consumer_secret = resolve_credentials(args)
    products = search_products(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        collection_id=args.collection,
        start_dt=start_dt,
        end_dt=end_dt,
    )

    for product in products:
        sensing_start = getattr(product, "sensing_start", None)
        sensing_end = getattr(product, "sensing_end", None)
        if sensing_start and sensing_end:
            print(f"- {product} | {sensing_start.isoformat()}Z -> {sensing_end.isoformat()}Z")
        else:
            print(f"- {product}")

    if args.list_only or not products:
        return

    zip_paths = download_products(
        products=products,
        output_dir=args.out,
        collection_id=args.collection,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        download_workers=args.download_workers,
        retries=args.retries,
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        overwrite_invalid=args.overwrite_invalid,
    )

    manifest_path = args.out / args.manifest_name
    write_manifest(manifest_path, zip_paths)
    LOG.info("Download complete: %d ZIP files available", len(zip_paths))
    LOG.info("Manifest written to %s", manifest_path)


if __name__ == "__main__":
    main()
