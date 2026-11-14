"""Download bounded research files for later offline use."""

import hashlib
import ipaddress
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .models import ResearchSource


# A user-writable location works in source runs and future packaged executables.
RESOURCE_DIR = Path(os.getenv("ORBITAL_EMBER_RESOURCE_DIR", Path.home() / ".orbital_ember" / "resources"))
INDEX_PATH = RESOURCE_DIR / "index.json"
# Decimal 1 GB per downloaded resource; this is a storage limit, not gravity.
MAX_RESOURCE_BYTES = 1_000_000_000
MAX_TOTAL_RESOURCE_BYTES = 1_000_000_000


def _is_safe_remote_url(url: str) -> bool:
    """Reject local/private destinations before a downloaded URL is opened."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        if parsed.username or parsed.password:
            return False
        if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
            return False
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        return all(ipaddress.ip_address(address[4][0]).is_global for address in addresses)
    except (OSError, ValueError, socket.gaierror):
        return False


async def download_sources(sources: list[ResearchSource]) -> list[str]:
    """Download unique HTTP sources up to a safe size and return saved filenames."""
    if not sources:
        return []
    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    index = _read_index()
    used_bytes = sum(
        Path(record.get("path", "")).stat().st_size
        for record in index.values()
        if record.get("path") and Path(record["path"]).exists()
    )
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        for source in sources:
            if not _is_safe_remote_url(source.url) or used_bytes >= MAX_TOTAL_RESOURCE_BYTES:
                continue
            filename = hashlib.sha256(source.url.encode("utf-8")).hexdigest()[:20] + ".resource"
            destination = RESOURCE_DIR / filename
            try:
                async with client.stream("GET", source.url, headers={"User-Agent": "OrbitalEmber/0.1"}) as response:
                    response.raise_for_status()
                    content_length = int(response.headers.get("content-length", "0"))
                    remaining = MAX_TOTAL_RESOURCE_BYTES - used_bytes
                    if content_length > min(MAX_RESOURCE_BYTES, remaining):
                        continue
                    temporary_path = destination.with_suffix(".part")
                    written = 0
                    with temporary_path.open("wb") as output:
                        async for chunk in response.aiter_bytes(64 * 1024):
                            written += len(chunk)
                            if written > min(MAX_RESOURCE_BYTES, remaining):
                                break
                            output.write(chunk)
                    if written > min(MAX_RESOURCE_BYTES, remaining):
                        temporary_path.unlink(missing_ok=True)
                        continue
                    temporary_path.replace(destination)
                used_bytes += written
                saved.append(str(destination))
                index[source.url] = {
                    "path": str(destination),
                    "title": source.title,
                    "snippet": source.snippet,
                    "source_type": source.source_type,
                }
            except (httpx.HTTPError, OSError, ValueError):
                continue
    _write_index(index)
    return saved


def load_saved_resource_sources(query: str | None = None) -> list[ResearchSource]:
    """Return downloaded source records as local research evidence."""
    sources = [
        ResearchSource(
            title=str(record.get("title", "Saved research")),
            url=str(url),
            snippet=str(record.get("snippet", "")),
            source_type=record.get("source_type", "nasa"),
        )
        for url, record in _read_index().items()
        if record.get("path")
    ]
    if not query:
        return sources
    terms = {word.lower() for word in query.split() if len(word) > 3}
    return [source for source in sources if any(term in f"{source.title} {source.snippet}".lower() for term in terms)]


def _read_index() -> dict:
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_index(index: dict) -> None:
    try:
        temporary_path = INDEX_PATH.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
        temporary_path.replace(INDEX_PATH)
    except OSError:
        return
