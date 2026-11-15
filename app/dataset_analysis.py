"""Bounded, provenance-preserving analysis for downloaded CSV/TSV/JSON datasets."""
from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

MAX_ANALYSIS_BYTES = 10 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_FILES = 25
MAX_ROWS = 100_000
MAX_COLUMNS = 200
MAX_SAMPLE_ROWS = 8
TABULAR_EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl"}


def analyze_dataset(path: Path) -> dict[str, Any]:
    """Analyze tabular data or tabular files inside a ZIP without extracting to disk."""
    if not path.is_file():
        raise FileNotFoundError("Downloaded file is missing")
    size = path.stat().st_size
    if size > MAX_ANALYSIS_BYTES:
        raise ValueError("Dataset exceeds the 10 MB analysis limit")
    raw = path.read_bytes()
    if not raw:
        raise ValueError("Downloaded file is empty")
    if path.suffix.lower() == ".zip":
        return _analyze_zip(raw)
    return _analyze_bytes(raw, path.suffix.lower())


def _analyze_zip(raw: bytes) -> dict[str, Any]:
    datasets = []
    total_uncompressed = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir() and Path(item.filename).suffix.lower() in TABULAR_EXTENSIONS]
            if len(members) > MAX_ARCHIVE_FILES:
                raise ValueError(f"ZIP contains more than {MAX_ARCHIVE_FILES} tabular files")
            for member in members:
                if member.file_size > MAX_ANALYSIS_BYTES:
                    raise ValueError(f"ZIP member {Path(member.filename).name} exceeds the 10 MB analysis limit")
                total_uncompressed += member.file_size
                if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise ValueError("ZIP tabular content exceeds the 50 MB expanded analysis limit")
                # Read members in memory only; no archive paths are ever extracted.
                data = archive.read(member)
                datasets.append({
                    "file_name": Path(member.filename).name,
                    "analysis": _analyze_bytes(data, Path(member.filename).suffix.lower()),
                })
    except zipfile.BadZipFile as error:
        raise ValueError("Downloaded ZIP file is invalid") from error
    if not datasets:
        raise ValueError("ZIP contains no supported CSV, TSV, JSON or JSONL files")
    return {
        "format": "ZIP",
        "file_count": len(datasets),
        "datasets": datasets,
        "notice": "Only tabular files inside this archive were analyzed. Other archive contents were skipped. Units, experimental context, and scientific validity require source documentation.",
    }


def _analyze_bytes(raw: bytes, suffix: str) -> dict[str, Any]:
    if len(raw) > MAX_ANALYSIS_BYTES:
        raise ValueError("Dataset exceeds the 10 MB analysis limit")
    if not raw:
        raise ValueError("Dataset file is empty")
    text = raw.decode("utf-8-sig", errors="strict")
    if suffix in {".json", ".jsonl"} or text.lstrip().startswith(("{", "[")):
        rows = _json_rows(text)
        format_name = "JSON"
    else:
        rows = _delimited_rows(text, suffix)
        format_name = "TSV" if suffix == ".tsv" else "CSV"
    if not rows:
        raise ValueError("No tabular records were found")
    headers = list(dict.fromkeys(key for row in rows for key in row.keys()))[:MAX_COLUMNS]
    if not headers:
        raise ValueError("No data columns were found")
    rows = [{key: row.get(key) for key in headers} for row in rows[:MAX_ROWS]]
    columns = [_summarize_column(name, [row.get(name) for row in rows]) for name in headers]
    for column in columns:
        if column["type"] == "numeric":
            series = []
            for row in rows:
                try:
                    value = float(str(row.get(column["name"])).replace(",", ""))
                    if math.isfinite(value):
                        series.append(value)
                except (TypeError, ValueError):
                    continue
            column["series"] = [_round(value) for value in series[:60]]
    return {
        "format": format_name,
        "row_count": len(rows),
        "column_count": len(headers),
        "truncated": len(rows) >= MAX_ROWS,
        "columns": columns,
        "sample_rows": [_json_safe(row) for row in rows[:MAX_SAMPLE_ROWS]],
        "notice": "Descriptive statistics only. Column names and values are reported as stored; units, experimental context, and scientific validity require source documentation.",
    }


def _json_rows(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, dict):
        for key in ("data", "results", "records", "measurements", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise ValueError("JSON must contain an object or a list of records")
    rows = []
    for item in data[:MAX_ROWS]:
        if isinstance(item, dict):
            rows.append({str(k): v for k, v in item.items() if not isinstance(v, (dict, list))})
        elif isinstance(item, (str, int, float, bool)) or item is None:
            rows.append({"value": item})
    return rows


def _delimited_rows(text: str, suffix: str) -> list[dict[str, Any]]:
    delimiter = "\t" if suffix == ".tsv" else None
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("Delimited file must include a header row")
    return [dict(row) for _, row in zip(range(MAX_ROWS), reader)]


def _summarize_column(name: str, values: list[Any]) -> dict[str, Any]:
    present = [value for value in values if value not in (None, "")]
    numeric: list[float] = []
    for value in present:
        if isinstance(value, bool):
            continue
        try:
            number = float(str(value).replace(",", ""))
            if math.isfinite(number):
                numeric.append(number)
        except (TypeError, ValueError):
            pass
    result: dict[str, Any] = {
        "name": name, "non_empty": len(present), "missing": len(values) - len(present),
        "type": "numeric" if present and len(numeric) == len(present) else "categorical",
    }
    if result["type"] == "numeric":
        ordered = sorted(numeric)
        result.update({"min": _round(ordered[0]), "max": _round(ordered[-1]),
                       "mean": _round(sum(ordered) / len(ordered)), "median": _round(_median(ordered))})
    else:
        counts = Counter(str(value)[:160] for value in present)
        result["top_values"] = [{"value": value, "count": count} for value, count in counts.most_common(5)]
    return result


def _median(values: list[float]) -> float:
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def _round(value: float) -> float:
    return round(value, 8)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
