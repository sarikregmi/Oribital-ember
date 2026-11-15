"""Download and index bounded research resources with safe local file access."""
import hashlib
import ipaddress
import json
import os
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from .models import DownloadedResource, ResearchSource

RESOURCE_DIR = Path(os.getenv("ORBITAL_EMBER_RESOURCE_DIR", Path.home() / ".orbital_ember" / "resources")).resolve()
INDEX_PATH = RESOURCE_DIR / "index.json"
MAX_RESOURCE_BYTES = 25_000_000
MAX_TOTAL_RESOURCE_BYTES = 100_000_000
SUPPORTED_DATA_EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl", ".zip"}


def _is_safe_remote_url(url: str) -> bool:
    """Reject non-web schemes, credentials, unusual ports and non-public DNS targets."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 80, 443):
            return False
        if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (OSError, ValueError, socket.gaierror):
        return False


async def download_sources(sources: list[ResearchSource]) -> list[str]:
    """Download unique resources within per-file and total storage budgets."""
    if not sources:
        return []
    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    index = _read_index()
    used_bytes = 0
    for record in index.values():
        existing_path = _safe_path(record.get("path"))
        if existing_path and existing_path.is_file() and existing_path.suffix.lower() in SUPPORTED_DATA_EXTENSIONS:
            used_bytes += existing_path.stat().st_size
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        for source in sources:
            if not _is_safe_remote_url(source.url) or used_bytes >= MAX_TOTAL_RESOURCE_BYTES:
                continue
            resource_id = hashlib.sha256(source.url.encode("utf-8")).hexdigest()[:20]
            existing_path = _safe_path(index.get(source.url, {}).get("path")) if source.url in index else None
            if existing_path and existing_path.is_file() and existing_path.suffix.lower() in SUPPORTED_DATA_EXTENSIONS:
                continue
            parsed_suffix = Path(urlparse(source.url).path).suffix.lower() or Path(source.title).suffix.lower()
            # This panel is a dataset store, not a link scrapbook: only actual
            # tabular files and archives are accepted for automatic downloads.
            if parsed_suffix not in SUPPORTED_DATA_EXTENSIONS:
                continue
            suffix = parsed_suffix
            destination = RESOURCE_DIR / f"{resource_id}{suffix}"
            temporary_path = destination.with_suffix(destination.suffix + ".part")
            try:
                request_url = source.url
                written = 0
                downloaded = False
                remaining = MAX_TOTAL_RESOURCE_BYTES - used_bytes
                limit = min(MAX_RESOURCE_BYTES, remaining)
                for redirect_count in range(4):
                    # Validate every redirect destination independently; never let
                    # the HTTP client follow a redirect to a private/local address.
                    if not _is_safe_remote_url(request_url):
                        raise ValueError("Unsafe redirect destination")
                    async with client.stream("GET", request_url, headers={"User-Agent": "OrbitalEmber/0.2"}) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location or redirect_count == 3:
                                raise ValueError("Too many or invalid download redirects")
                            request_url = urljoin(request_url, location)
                            continue
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                        if content_type in {"text/html", "application/xhtml+xml"}:
                            raise ValueError("Source returned an HTML page, not a dataset file")
                        content_length = int(response.headers.get("content-length", "0"))
                        if content_length > limit:
                            break
                        with temporary_path.open("wb") as output:
                            async for chunk in response.aiter_bytes(64 * 1024):
                                written += len(chunk)
                                if written > limit:
                                    break
                                output.write(chunk)
                        downloaded = True
                        break
                if not downloaded or written == 0 or written > limit:
                    temporary_path.unlink(missing_ok=True)
                    continue
                temporary_path.replace(destination)
                used_bytes += written
                saved.append(str(destination))
                index[source.url] = {
                    "id": resource_id, "path": str(destination), "title": source.title,
                    "snippet": source.snippet, "source_type": source.source_type, "provider": source.provider,
                    "size_bytes": written, "filename": destination.name,
                }
            except (httpx.HTTPError, OSError, ValueError):
                temporary_path.unlink(missing_ok=True)
                continue
    _write_index(index)
    return saved


def list_downloaded_resources() -> list[DownloadedResource]:
    records: list[DownloadedResource] = []
    for url, record in _read_index().items():
        path = _safe_path(record.get("path"))
        if not path or not path.is_file():
            continue
        # This panel contains datasets, not downloaded web pages or publications.
        if path.suffix.lower() not in SUPPORTED_DATA_EXTENSIONS:
            continue
        resource_id = str(record.get("id") or hashlib.sha256(url.encode()).hexdigest()[:20])
        source_type = record.get("source_type", "nasa")
        if source_type not in {"local", "nasa", "web"}:
            source_type = "nasa"
        records.append(DownloadedResource(
            id=resource_id, title=str(record.get("title", "Saved research")), url=str(url),
            snippet=str(record.get("snippet", "")), source_type=source_type,
            filename=str(record.get("filename") or path.name), size_bytes=path.stat().st_size,
            analysis_supported=path.suffix.lower() in SUPPORTED_DATA_EXTENSIONS,
            provider=record.get("provider"),
        ))
    return records


def get_downloaded_resource(resource_id: str) -> tuple[DownloadedResource, Path] | None:
    for url, record in _read_index().items():
        expected = str(record.get("id") or hashlib.sha256(url.encode()).hexdigest()[:20])
        if expected != resource_id:
            continue
        path = _safe_path(record.get("path"))
        if not path or not path.is_file():
            return None
        source_type = record.get("source_type", "nasa")
        if source_type not in {"local", "nasa", "web"}:
            source_type = "nasa"
        item = DownloadedResource(
            id=expected, title=str(record.get("title", "Saved research")), url=url,
            snippet=str(record.get("snippet", "")), source_type=source_type,
            filename=str(record.get("filename") or path.name), size_bytes=path.stat().st_size,
            analysis_supported=path.suffix.lower() in SUPPORTED_DATA_EXTENSIONS,
            provider=record.get("provider"),
        )
        return item, path
    return None


def load_saved_resource_sources(query: str | None = None) -> list[ResearchSource]:
    sources = [ResearchSource(title=item.title, url=item.url, snippet=item.snippet,
                              source_type=item.source_type, provider=item.provider)
               for item in list_downloaded_resources()]
    if not query:
        return sources
    terms = {word.lower() for word in query.split() if len(word) > 3}
    return [source for source in sources if any(term in f"{source.title} {source.snippet}".lower() for term in terms)]


def _safe_path(value: str | None) -> Path | None:
    if not value:
        return None
    try:
        path = Path(value).resolve()
        path.relative_to(RESOURCE_DIR)
        return path
    except (OSError, ValueError):
        return None


def _read_index() -> dict:
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        return {str(key): value for key, value in data.items() if isinstance(value, dict)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_index(index: dict) -> None:
    try:
        RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
        temporary_path = INDEX_PATH.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
        temporary_path.replace(INDEX_PATH)
    except OSError:
        return


def store_uploaded_resource(filename: str, content: bytes, title: str, source_url: str) -> DownloadedResource:
    """Store a user-downloaded NASA file with its declared source provenance."""
    if not content or len(content) > MAX_RESOURCE_BYTES:
        raise ValueError("Upload must be between 1 byte and 25 MB")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_DATA_EXTENSIONS:
        raise ValueError("Supported dataset uploads: CSV, TSV, JSON, JSONL and ZIP")
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or not (host == "nasa.gov" or host.endswith(".nasa.gov")):
        raise ValueError("Source URL must be an HTTPS NASA domain")
    index = _read_index()
    used_bytes = 0
    for record in index.values():
        path = _safe_path(record.get("path"))
        if path and path.is_file():
            used_bytes += path.stat().st_size
    if used_bytes + len(content) > MAX_TOTAL_RESOURCE_BYTES:
        raise ValueError("Managed resource storage is full (100 MB limit)")
    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(source_url.encode() + b"\0" + content).hexdigest()[:20]
    destination = RESOURCE_DIR / f"{digest}{suffix}"
    destination.write_bytes(content)
    safe_filename = Path(filename.replace("\\", "/")).name[:180]
    index[source_url] = {
        "id": digest, "path": str(destination), "title": title[:200] or safe_filename,
        "snippet": "User-imported file downloaded from the cited NASA source.",
        "source_type": "nasa", "provider": "User-imported NASA file", "filename": safe_filename, "size_bytes": len(content),
    }
    _write_index(index)
    return DownloadedResource(
        id=digest, title=title[:200] or safe_filename, url=source_url,
        snippet="User-imported file downloaded from the cited NASA source.",
        source_type="nasa", filename=safe_filename, size_bytes=len(content),
        analysis_supported=suffix in SUPPORTED_DATA_EXTENSIONS, provider="User-imported NASA file",
    )
