"""Build-time and incremental runtime cache for NASA PSI files.

The 12 GB quota is scoped exclusively to this PSI archive. Other Orbital Ember
resources are stored elsewhere and are not included in this accounting.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .models import Investigation
from .psi import PSIProvider

PSI_QUOTA_BYTES = 12_000_000_000  # exactly 12 GB decimal, PSI only
MAX_AUTOMATIC_FILE_BYTES = 1_000_000_000  # Keep automatic downloads to manageable, resumable file sizes.
BUNDLE_DIR = Path(__file__).resolve().parent / "bundled_data" / "psi"
RUNTIME_DIR = Path(os.getenv("ORBITAL_EMBER_PSI_DIR", Path.home() / ".orbital_ember" / "psi")).expanduser().resolve()
MANIFEST_NAME = "manifest.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_manifest() -> dict[str, Any]:
    return {"schema": 1, "provider": "NASA Physical Sciences Informatics", "source_url": "https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation", "updated_at": None, "investigations": {}, "files": {}}


def _read_manifest(directory: Path) -> dict[str, Any]:
    try:
        data = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("investigations"), dict) and isinstance(data.get("files"), dict):
            return data
    except (OSError, ValueError):
        pass
    return _empty_manifest()


def _write_manifest(directory: Path, manifest: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = _now()
    temp = directory / (MANIFEST_NAME + ".tmp")
    temp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(directory / MANIFEST_NAME)


def _active_dir() -> Path:
    runtime_manifest = RUNTIME_DIR / MANIFEST_NAME
    bundle_manifest = BUNDLE_DIR / MANIFEST_NAME
    if runtime_manifest.exists():
        return RUNTIME_DIR
    if bundle_manifest.exists():
        return BUNDLE_DIR
    return RUNTIME_DIR


def resolve_archive_file(directory: Path, relative: str | None) -> Path | None:
    if not relative:
        return None
    if relative.startswith("@bundle/"):
        base, rel = BUNDLE_DIR, relative[len("@bundle/"):]
    else:
        base, rel = directory, relative
    path = (base / rel).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError:
        return None
    return path


def seed_runtime_from_bundle() -> Path:
    """Seed/upgrade the user cache from a newer packaged build-time snapshot."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    runtime_manifest_path = RUNTIME_DIR / MANIFEST_NAME
    if not (BUNDLE_DIR / MANIFEST_NAME).exists():
        if not runtime_manifest_path.exists():
            _write_manifest(RUNTIME_DIR, _empty_manifest())
        return RUNTIME_DIR

    bundled = _read_manifest(BUNDLE_DIR)
    runtime = _read_manifest(RUNTIME_DIR) if runtime_manifest_path.exists() else _empty_manifest()
    bundle_stamp = str(bundled.get("catalog_checked_at") or bundled.get("updated_at") or "")
    runtime_stamp = str(runtime.get("catalog_checked_at") or runtime.get("updated_at") or "")
    bundle_is_newer = bool(bundle_stamp and bundle_stamp > runtime_stamp)
    if not runtime_manifest_path.exists() or bundle_is_newer:
        # Keep newer runtime file contents, but import newer build metadata and
        # any bundled files that are missing locally.
        for investigation_id, record in bundled.get("investigations", {}).items():
            runtime.setdefault("investigations", {})[investigation_id] = record
        for file_id, record in bundled.get("files", {}).items():
            existing = runtime.setdefault("files", {}).get(file_id, {})
            merged = {**record, **existing}
            relative = existing.get("path") or record.get("path")
            if relative:
                destination = (RUNTIME_DIR / relative).resolve()
                try:
                    destination.relative_to(RUNTIME_DIR.resolve())
                except ValueError:
                    continue
                if not destination.is_file() and record.get("path"):
                    source = (BUNDLE_DIR / record["path"]).resolve()
                    try:
                        source.relative_to(BUNDLE_DIR.resolve())
                    except ValueError:
                        source = None
                    if source and source.is_file():
                        relative = record["path"]
                        destination = (RUNTIME_DIR / relative).resolve()
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        # Move rather than copy so the bundled PSI archive and
                        # writable cache do not double the 12 GB storage use.
                        try:
                            shutil.move(str(source), str(destination))
                        except OSError:
                            # A read-only install directory stays the file's
                            # source; runtime manifest references it in place.
                            relative = "@bundle/" + record["path"]
                merged["path"] = relative
            runtime["files"][file_id] = merged
        runtime["catalog_count"] = bundled.get("catalog_count", len(runtime.get("investigations", {})))
        runtime["catalog_checked_at"] = bundled.get("catalog_checked_at") or runtime.get("catalog_checked_at")
        runtime["source_url"] = bundled.get("source_url") or runtime.get("source_url")
        _write_manifest(RUNTIME_DIR, runtime)
    elif not runtime_manifest_path.exists():
        _write_manifest(RUNTIME_DIR, runtime)
    return RUNTIME_DIR


def get_archive_manifest(directory: Path | None = None) -> dict[str, Any]:
    return _read_manifest(directory or _active_dir())


def get_archive_catalog(directory: Path | None = None) -> list[Investigation]:
    manifest = get_archive_manifest(directory)
    records: list[Investigation] = []
    for item in manifest.get("investigations", {}).values():
        try:
            records.append(Investigation.model_validate(item.get("record", item)))
        except Exception:
            continue
    return records


def archive_status(directory: Path | None = None) -> dict[str, Any]:
    root = directory or _active_dir()
    manifest = _read_manifest(root)
    total = 0
    downloaded = 0
    for item in manifest.get("files", {}).values():
        relative = item.get("path")
        if not relative:
            continue
        path = resolve_archive_file(root, relative)
        if path and path.is_file():
            total += path.stat().st_size
            downloaded += 1
    return {
        "investigations": len(manifest.get("investigations", {})),
        "listed_files": len(manifest.get("files", {})),
        "downloaded_files": downloaded,
        "storage_bytes": total,
        "storage_limit_bytes": PSI_QUOTA_BYTES,
        "storage_percent": round(total / PSI_QUOTA_BYTES * 100, 3),
        "updated_at": manifest.get("updated_at"),
        "directory": str(root),
    }


def list_archive_files(directory: Path | None = None) -> list[dict[str, Any]]:
    root = directory or _active_dir()
    manifest = _read_manifest(root)
    output = []
    for key, item in manifest.get("files", {}).items():
        relative = item.get("path")
        path = resolve_archive_file(root, relative)
        exists = bool(path and path.is_file())
        output.append({**item, "id": key, "downloaded": exists,
                       "size_bytes": path.stat().st_size if exists else int(item.get("size_bytes") or 0)})
    return sorted(output, key=lambda x: (x.get("investigation_id", ""), x.get("name", "").lower()))


def _used_bytes(directory: Path, manifest: dict[str, Any]) -> int:
    used = 0
    for record in manifest.get("files", {}).values():
        rel = record.get("path")
        if not rel:
            continue
        path = resolve_archive_file(directory, rel)
        if path and path.is_file():
            used += path.stat().st_size
    return used


def _evict_oldest(directory: Path, manifest: dict[str, Any], needed: int) -> int:
    """Evict oldest PSI file contents only; never delete investigation metadata."""
    candidates = []
    used = 0
    for key, record in manifest.get("files", {}).items():
        rel = record.get("path")
        if not rel:
            continue
        path = resolve_archive_file(directory, rel)
        if path and path.is_file():
            size = path.stat().st_size
            used += size
            candidates.append((record.get("last_accessed") or record.get("downloaded_at") or "", key, path, size))
    for _, key, path, size in sorted(candidates):
        if used + needed <= PSI_QUOTA_BYTES:
            break
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
        used -= size
        manifest["files"][key]["path"] = None
        manifest["files"][key]["evicted_at"] = _now()
    return used


def _safe_psi_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and not parsed.username and not parsed.password and (host == "nasa.gov" or host.endswith(".nasa.gov"))


async def _remote_file_size(client: httpx.AsyncClient, url: str) -> int | None:
    request_url = url
    for redirect in range(5):
        if not _safe_psi_url(request_url):
            raise ValueError("PSI file URL or redirect is not an HTTPS NASA domain")
        try:
            response = await client.head(request_url, follow_redirects=False)
        except httpx.HTTPError:
            return None
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location or redirect == 4:
                raise ValueError("Too many PSI file redirects")
            request_url = urljoin(request_url, location)
            continue
        if response.status_code in {403, 405, 501}:
            return None
        response.raise_for_status()
        value = response.headers.get("content-length")
        return int(value) if value and value.isdigit() else None
    return None


async def _download_file(client: httpx.AsyncClient, url: str, destination: Path, max_bytes: int) -> int:
    request_url = url
    for redirect in range(5):
        if not _safe_psi_url(request_url):
            raise ValueError("PSI file URL or redirect is not an HTTPS NASA domain")
        async with client.stream("GET", request_url, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location or redirect == 4:
                    raise ValueError("Too many PSI download redirects")
                request_url = urljoin(request_url, location)
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type in {"text/html", "application/xhtml+xml"}:
                raise ValueError("NASA returned an HTML page, not a file")
            length = int(response.headers.get("content-length", "0") or 0)
            if length > max_bytes or length > MAX_AUTOMATIC_FILE_BYTES:
                raise ValueError("File exceeds automatic download limit")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_suffix(destination.suffix + ".part")
            written = 0
            with temp.open("wb") as stream:
                async for chunk in response.aiter_bytes(1024 * 256):
                    written += len(chunk)
                    if written > max_bytes or written > MAX_AUTOMATIC_FILE_BYTES:
                        raise ValueError("File exceeded download limit while streaming")
                    stream.write(chunk)
            if not written:
                temp.unlink(missing_ok=True)
                raise ValueError("NASA returned an empty file")
            temp.replace(destination)
            return written
    raise ValueError("Could not resolve PSI download URL")


async def sync_psi_archive(
    provider: PSIProvider | None = None,
    *,
    directory: Path | None = None,
    full: bool = False,
    investigation_limit: int = 3,
    file_limit: int = 12,
) -> dict[str, Any]:
    """Refresh PSI metadata and download a bounded batch of new/changed files.

    `full=True` is intended only for build-time snapshot creation. Runtime sync
    uses small batches so launching the app never pulls the whole repository.
    """
    provider = provider or PSIProvider()
    root = directory or seed_runtime_from_bundle()
    root.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest(root)
    records = await provider.fetch_investigations()
    catalog_complete = bool(getattr(provider, "last_catalog_complete", False))
    if not catalog_complete:
        # Never replace a complete bundled catalogue with a first-page scrape
        # or a transient zero-result/error response.
        return {"status": "incomplete", "catalog_count": len(manifest.get("investigations", {})),
                "catalog_found_count": len(records), "catalog_total": getattr(provider, "last_catalog_total", None),
                "catalog_complete": False, "investigations_checked": 0, "files_listed": 0,
                "files_downloaded": 0, "storage": archive_status(root),
                "errors": ["NASA PSI pagination could not be verified; the existing snapshot was preserved."],
                "source": manifest.get("source_url")}
    old_ids = set(manifest.get("investigations", {}))
    file_count = 0
    downloaded = 0
    errors: list[str] = []
    if full or not records:
        pending_records = records
        cursor = 0
    else:
        cursor = int(manifest.get("sync_cursor", 0)) % len(records)
        count = min(len(records), max(1, investigation_limit))
        pending_records = [records[(cursor + offset) % len(records)] for offset in range(count)]
    async with httpx.AsyncClient(timeout=90.0, follow_redirects=False, headers=provider.headers) as client:
        for record in pending_records:
            try:
                detailed, file_entries = await provider.fetch_investigation_details(record)
            except Exception as exc:
                errors.append(f"{record.id}: metadata: {str(exc)[:180]}")
                detailed, file_entries = record, []
            manifest["investigations"][record.id] = {
                "record": detailed.model_dump(), "last_checked": _now(),
                "file_count": len(file_entries),
            }
            if file_entries:
                current_urls = {entry["url"] for entry in file_entries}
                for old_key, old_file in list(manifest["files"].items()):
                    if old_file.get("investigation_id") == record.id and old_file.get("url") not in current_urls:
                        old_path = old_file.get("path")
                        if old_path:
                            stale_path = resolve_archive_file(root, old_path)
                            if stale_path:
                                try:
                                    stale_path.unlink(missing_ok=True)
                                except OSError:
                                    pass
                        del manifest["files"][old_key]
            for entry in file_entries:
                url = entry["url"]
                key = hashlib.sha256(url.encode("utf-8")).hexdigest()
                previous = manifest["files"].get(key, {})
                manifest["files"][key] = {**previous, **entry, "id": key,
                    "listed_at": previous.get("listed_at") or _now(),
                    "path": previous.get("path")}
                file_count += 1
                previous_path = resolve_archive_file(root, previous.get("path"))
                if previous_path and previous_path.is_file():
                    continue
                if not full and downloaded >= max(0, file_limit):
                    continue
                if not _safe_psi_url(url):
                    errors.append(f"{record.id}: skipped non-PSI file URL")
                    continue
                suffix = entry.get("extension") or Path(urlparse(url).path).suffix.lower() or ".bin"
                relative = Path("files") / record.id / f"{key[:24]}{suffix}"
                destination = root / relative
                # Reserve quota before streaming; if the server omits Content-Length,
                # allow only the remaining quota and enforce it chunk by chunk.
                current = _used_bytes(root, manifest)
                remaining = PSI_QUOTA_BYTES - current
                try:
                    size_hint = await _remote_file_size(client, url)
                    if size_hint and size_hint > MAX_AUTOMATIC_FILE_BYTES:
                        errors.append(f"{record.id}/{entry.get('name')}: over the 1 GB automatic per-file ceiling")
                        continue
                    if size_hint and size_hint > remaining:
                        _evict_oldest(root, manifest, size_hint)
                        current = _used_bytes(root, manifest)
                        remaining = PSI_QUOTA_BYTES - current
                    elif remaining < 1024 * 1024:
                        _evict_oldest(root, manifest, MAX_AUTOMATIC_FILE_BYTES)
                        current = _used_bytes(root, manifest)
                        remaining = PSI_QUOTA_BYTES - current
                    if remaining <= 0:
                        errors.append("PSI storage quota is full; remaining files stay listed but not downloaded")
                        continue
                    size = await _download_file(client, url, destination, min(remaining, MAX_AUTOMATIC_FILE_BYTES))
                    manifest["files"][key].update({"path": str(relative), "size_bytes": size,
                        "downloaded_at": _now(), "sha256": _sha256(destination)})
                    downloaded += 1
                except Exception as exc:
                    destination.with_suffix(destination.suffix + ".part").unlink(missing_ok=True)
                    errors.append(f"{record.id}/{entry.get('name')}: {str(exc)[:180]}")
            if not full and file_limit > 0 and downloaded >= file_limit:
                break
    # A completed, non-empty catalogue scan is authoritative: remove records
    # NASA no longer lists, along with their cached file bytes and file metadata.
    if records and getattr(provider, "last_catalog_complete", False):
        current_ids = {record.id for record in records}
        for removed_id in old_ids - current_ids:
            manifest["investigations"].pop(removed_id, None)
            for old_key, old_file in list(manifest["files"].items()):
                if old_file.get("investigation_id") == removed_id:
                    old_path = old_file.get("path")
                    if old_path:
                        stale_path = (root / old_path).resolve()
                        try:
                            stale_path.relative_to(root.resolve())
                            stale_path.unlink(missing_ok=True)
                        except ValueError:
                            pass
                    del manifest["files"][old_key]
    # Store the complete current catalogue even if only a subset was hydrated.
    for record in records:
        if record.id not in manifest["investigations"]:
            manifest["investigations"][record.id] = {"record": record.model_dump(), "last_checked": None, "file_count": 0}
    manifest["catalog_count"] = len(records)
    manifest["catalog_total"] = getattr(provider, "last_catalog_total", None)
    manifest["catalog_checked_at"] = _now()
    if records and not full:
        manifest["sync_cursor"] = (cursor + len(pending_records)) % len(records)
    elif full:
        manifest["sync_cursor"] = 0
    manifest["catalog_missing_ids"] = sorted(old_ids - {r.id for r in records})
    _write_manifest(root, manifest)
    return {"status": "updated" if records else "empty", "catalog_count": len(records),
            "catalog_total": getattr(provider, "last_catalog_total", None),
            "catalog_complete": catalog_complete,
            "investigations_checked": len(pending_records), "files_listed": file_count,
            "files_downloaded": downloaded, "storage": archive_status(root),
            "errors": errors[:30], "source": manifest["source_url"]}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
