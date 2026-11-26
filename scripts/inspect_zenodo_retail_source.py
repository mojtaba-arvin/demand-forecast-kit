# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Inspect a public Zenodo retail record without committing source data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import polars as pl
import requests

MAX_FILE_BYTES = 300 * 1024 * 1024
USER_AGENT = "demand-forecast-kit/1.0 (public dataset schema inspection)"
SUPPORTED_SUFFIXES = {".csv", ".parquet"}
DATE_COLUMNS = {
    "date",
    "start_date",
    "end_date",
    "last_receipt_date",
    "last_sold_date",
    "week_start",
    "transaction_date",
}
IDENTIFIER_COLUMNS = {
    "store_id",
    "article_id",
    "sku",
    "product_id",
    "item_id",
}
NUMERIC_COLUMNS = {
    "units",
    "on_hand",
    "latest_on_hand",
    "missed_units",
    "in_transit_1w",
    "in_transit_2w",
    "unit_cost",
    "unit_price",
    "cogs",
    "sales_amount",
    "discount_amount",
}
FLAG_COLUMNS = {
    "is_return",
    "is_audit_anomaly",
    "is_phasing_out",
    "in_stock",
    "stock_status",
    "sales_type",
}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _read_frame(path: Path) -> pl.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pl.read_parquet(path)
    sample = path.read_bytes()[:8192].decode("utf-8-sig", errors="replace")
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    return pl.read_csv(
        path,
        separator=delimiter,
        try_parse_dates=True,
        infer_schema_length=10_000,
        low_memory=True,
    )


def inspect_frame(name: str, frame: pl.DataFrame) -> dict[str, Any]:
    columns = set(frame.columns)
    date_ranges: dict[str, dict[str, str | None]] = {}
    for column in sorted(columns & DATE_COLUMNS):
        values = frame[column].cast(pl.String, strict=False)
        date_ranges[column] = {
            "min": _json_value(values.min()),
            "max": _json_value(values.max()),
        }

    distinct_counts = {
        column: int(frame[column].n_unique())
        for column in sorted(columns & IDENTIFIER_COLUMNS)
    }
    null_counts = frame.null_count().row(0, named=True)
    nonzero_nulls = {
        name: int(count) for name, count in null_counts.items() if count
    }

    numeric_diagnostics: dict[str, dict[str, Any]] = {}
    for column in sorted(columns & NUMERIC_COLUMNS):
        values = frame[column].cast(pl.Float64, strict=False)
        numeric_diagnostics[column] = {
            "min": _json_value(values.min()),
            "max": _json_value(values.max()),
            "negative_rows": int((values < 0).sum()),
            "zero_rows": int((values == 0).sum()),
        }

    flag_distributions: dict[str, list[dict[str, Any]]] = {}
    for column in sorted(columns & FLAG_COLUMNS):
        flag_distributions[column] = [
            {key: _json_value(value) for key, value in row.items()}
            for row in frame.group_by(column).len().sort("len", descending=True)
            .head(20)
            .to_dicts()
        ]

    candidate_keys = [
        ["date", "store_id", "article_id"],
        ["date", "store_id", "sku"],
        ["date", "store_id", "product_id"],
        ["date", "store_id", "item_id"],
        ["start_date", "end_date", "store_id", "article_id"],
        ["start_date", "end_date", "store_id", "sku"],
    ]
    key_diagnostics: dict[str, dict[str, int]] = {}
    for key in candidate_keys:
        if set(key).issubset(columns):
            unique_rows = int(frame.select(pl.struct(key).n_unique()).item())
            key_diagnostics["+".join(key)] = {
                "rows": frame.height,
                "unique_keys": unique_rows,
                "duplicate_rows": frame.height - unique_rows,
            }

    return {
        "name": name,
        "rows": frame.height,
        "columns": frame.width,
        "schema": {column: str(dtype) for column, dtype in frame.schema.items()},
        "date_ranges": date_ranges,
        "distinct_identifier_counts": distinct_counts,
        "nonzero_null_counts": nonzero_nulls,
        "candidate_key_diagnostics": key_diagnostics,
        "numeric_diagnostics": numeric_diagnostics,
        "flag_distributions": flag_distributions,
    }


def inspect_path(path: Path, name: str) -> list[dict[str, Any]]:
    if path.suffix.lower() in SUPPORTED_SUFFIXES:
        return [inspect_frame(name, _read_frame(path))]
    if path.suffix.lower() != ".zip":
        return []

    reports: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            member = Path(info.filename)
            if info.is_dir() or member.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if info.file_size > MAX_FILE_BYTES:
                reports.append(
                    {"name": info.filename, "skipped": "member exceeds size limit"}
                )
                continue
            with archive.open(info) as source, tempfile.NamedTemporaryFile(
                suffix=member.suffix, delete=False
            ) as destination:
                shutil.copyfileobj(source, destination)
                temporary_path = Path(destination.name)
            try:
                reports.append(inspect_frame(info.filename, _read_frame(temporary_path)))
            finally:
                temporary_path.unlink(missing_ok=True)
    return reports


def inspect_record(record_id: int, output: Path) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    response = requests.get(
        f"https://zenodo.org/api/records/{record_id}",
        headers=headers,
        timeout=(15, 90),
    )
    response.raise_for_status()
    record = response.json()
    metadata = record.get("metadata", {})
    report: dict[str, Any] = {
        "record_id": record_id,
        "doi": record.get("doi"),
        "title": metadata.get("title"),
        "publication_date": metadata.get("publication_date"),
        "license": metadata.get("license"),
        "source_url": record.get("links", {}).get("html"),
        "files": [],
        "tables": [],
        "limits": {
            "max_file_bytes": MAX_FILE_BYTES,
            "raw_files_committed": False,
        },
    }

    with tempfile.TemporaryDirectory(prefix="retail-source-") as temporary:
        root = Path(temporary)
        for entry in record.get("files", []):
            key = str(entry.get("key", ""))
            size = int(entry.get("size", 0))
            file_report: dict[str, Any] = {
                "key": key,
                "size_bytes": size,
                "checksum": entry.get("checksum"),
            }
            if size > MAX_FILE_BYTES:
                file_report["status"] = "skipped: exceeds size limit"
                report["files"].append(file_report)
                continue

            links = entry.get("links", {})
            download_url = links.get("download") or links.get("self")
            if not download_url:
                file_report["status"] = "skipped: no public download URL"
                report["files"].append(file_report)
                continue

            local_path = root / Path(key).name
            digest = hashlib.sha256()
            source_md5 = hashlib.md5(usedforsecurity=False)
            downloaded = 0
            with requests.get(
                download_url,
                headers={"User-Agent": USER_AGENT},
                stream=True,
                timeout=(15, 180),
            ) as file_response:
                file_response.raise_for_status()
                with local_path.open("wb") as stream:
                    for chunk in file_response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > MAX_FILE_BYTES:
                            raise ValueError(f"{key} exceeded the download size limit")
                        digest.update(chunk)
                        source_md5.update(chunk)
                        stream.write(chunk)

            if size and downloaded != size:
                raise ValueError(f"{key} size mismatch: expected {size}, received {downloaded}")
            expected_checksum = str(entry.get("checksum") or "")
            if expected_checksum.startswith("md5:") and source_md5.hexdigest() != expected_checksum[4:]:
                raise ValueError(f"{key} does not match the source MD5 checksum")
            file_report["downloaded_bytes"] = downloaded
            file_report["sha256"] = digest.hexdigest()
            file_report["source_md5_verified"] = expected_checksum.startswith("md5:")
            file_report["status"] = "downloaded"
            report["files"].append(file_report)
            report["tables"].extend(inspect_path(local_path, key))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    if not report["tables"]:
        raise RuntimeError("No supported CSV/Parquet tables were available to inspect")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-id", type=int, default=19784493)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/zenodo-retail-source-inspection.json"),
    )
    args = parser.parse_args()
    report = inspect_record(args.record_id, args.output)
    print(
        json.dumps(
            {
                "record_id": report["record_id"],
                "doi": report["doi"],
                "files": len(report["files"]),
                "tables": [
                    {"name": table["name"], "rows": table.get("rows")}
                    for table in report["tables"]
                ],
                "report": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
