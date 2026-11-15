"""Automatic discovery of public NASA PSI and OSDR datasets.

PSI's public AWS bucket is queried with the S3 ListObjectsV2 REST API.
OSDR is queried through NASA's documented JSON search and study-file APIs.
Only small, openly downloadable tabular files and ZIPs are handed to the
existing bounded downloader. These repositories are kept distinct in metadata.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from urllib.parse import quote, urljoin

import httpx

from .models import ResearchSource

PSI_S3_LIST_URL = "https://nasa-psi.s3.us-west-2.amazonaws.com/"
PSI_S3_OBJECT_BASE = "https://nasa-psi.s3.us-west-2.amazonaws.com/"
OSDR_BASE = "https://osdr.nasa.gov"
OSDR_SEARCH_URL = f"{OSDR_BASE}/osdr/data/search"
TABULAR_SUFFIXES = {".csv", ".tsv", ".json", ".jsonl", ".zip"}
MAX_FILE_BYTES = 25_000_000
MAX_PSI_OBJECTS = 8
MAX_OSDR_STUDIES = 5
MAX_OSDR_FILES = 8
SEARCH_TERMS = ("combustion", "fire", "flame", "smoke", "microgravity")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_s3_listing(xml_text: str) -> list[ResearchSource]:
    """Parse public S3 ListObjectsV2 XML; ignore folders and oversized objects."""
    root = ET.fromstring(xml_text)
    found: list[ResearchSource] = []
    for item in root.iter():
        if _local_name(item.tag) != "Contents":
            continue
        fields = {_local_name(child.tag): (child.text or "") for child in item}
        key, size_text = fields.get("Key", ""), fields.get("Size", "0")
        try:
            size = int(size_text)
        except ValueError:
            continue
        suffix = PurePosixPath(key).suffix.lower()
        if not key or suffix not in TABULAR_SUFFIXES or not 0 < size <= MAX_FILE_BYTES:
            continue
        url = PSI_S3_OBJECT_BASE + quote(key, safe="/")
        found.append(ResearchSource(
            title=PurePosixPath(key).name,
            url=url,
            snippet=f"Public NASA PSI S3 object; listed size {size} bytes. Original bucket key: {key}",
            source_type="nasa",
            provider="NASA PSI public S3 bucket",
        ))
        if len(found) >= MAX_PSI_OBJECTS:
            break
    return found


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def extract_osd_study_ids(payload: object) -> list[str]:
    """Find OSD accession identifiers in documented search JSON variants."""
    ids: list[str] = []
    pattern = re.compile(r"\bOSD-?(\d+(?:\.\d+)?)\b", re.IGNORECASE)

    def visit(value: object):
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(key, str):
                    yield key
                yield from visit(child)
        elif isinstance(value, list):
            for child in value:
                yield from visit(child)
        elif isinstance(value, (str, int)):
            yield str(value)

    for candidate in visit(payload):
        match = pattern.search(candidate)
        if match:
            accession = match.group(1)
            if accession not in ids:
                ids.append(accession)
    return ids[:MAX_OSDR_STUDIES]


def parse_osdr_files(payload: object) -> list[ResearchSource]:
    """Extract public downloadable tabular file URLs from OSDR file metadata."""
    found: list[ResearchSource] = []
    seen: set[str] = set()
    for record in _walk_dicts(payload):
        remote = record.get("remote_url") or record.get("remoteUrl")
        filename = record.get("file_name") or record.get("fileName") or record.get("name")
        if not isinstance(remote, str) or not isinstance(filename, str):
            continue
        suffix = PurePosixPath(filename).suffix.lower()
        try:
            size = int(record.get("file_size") or record.get("fileSize") or 0)
        except (TypeError, ValueError):
            continue
        if suffix not in TABULAR_SUFFIXES or not 0 < size <= MAX_FILE_BYTES:
            continue
        url = urljoin(OSDR_BASE, remote)
        if not url.startswith(OSDR_BASE + "/") or url in seen:
            continue
        seen.add(url)
        found.append(ResearchSource(
            title=filename,
            url=url,
            snippet=f"Public NASA OSDR file; listed size {size} bytes. Dataset file metadata retrieved from NASA OSDR API.",
            source_type="nasa",
            provider="NASA OSDR API",
        ))
        if len(found) >= MAX_OSDR_FILES:
            break
    return found


async def discover_psi_sources(client: httpx.AsyncClient | None = None) -> list[ResearchSource]:
    """List actual public PSI bucket objects through S3's unauthenticated REST API."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20.0, follow_redirects=False, headers={"User-Agent": "OrbitalEmber/1.0"})
    try:
        response = await client.get(PSI_S3_LIST_URL, params={"list-type": "2", "max-keys": "1000"})
        response.raise_for_status()
        return parse_s3_listing(response.text)
    finally:
        if own_client:
            await client.aclose()


async def discover_osdr_sources(client: httpx.AsyncClient | None = None) -> list[ResearchSource]:
    """Search NASA OSDR and resolve file lists using NASA's documented APIs."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20.0, follow_redirects=False, headers={"User-Agent": "OrbitalEmber/1.0"})
    try:
        study_ids: list[str] = []
        for term in SEARCH_TERMS:
            response = await client.get(OSDR_SEARCH_URL, params={"term": term, "from": 0, "size": 10, "type": "cgene"})
            response.raise_for_status()
            for accession in extract_osd_study_ids(response.json()):
                if accession not in study_ids:
                    study_ids.append(accession)
            if len(study_ids) >= MAX_OSDR_STUDIES:
                break
        sources: list[ResearchSource] = []
        for accession in study_ids[:MAX_OSDR_STUDIES]:
            response = await client.get(f"{OSDR_BASE}/osdr/data/osd/files/{accession}", params={"page": 0, "size": 25, "all_files": "false"})
            response.raise_for_status()
            sources.extend(parse_osdr_files(response.json()))
            if len(sources) >= MAX_OSDR_FILES:
                break
        # Keep only a small, deterministic batch per sync.
        unique = {source.url: source for source in sources}
        return list(unique.values())[:MAX_OSDR_FILES]
    finally:
        if own_client:
            await client.aclose()


async def discover_nasa_sources() -> dict[str, list[ResearchSource]]:
    """Query official NASA sources independently so one outage does not block the other."""
    results: dict[str, list[ResearchSource]] = {"psi": [], "osdr": []}
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False, headers={"User-Agent": "OrbitalEmber/1.0"}) as client:
        try:
            results["psi"] = await discover_psi_sources(client)
        except (httpx.HTTPError, ET.ParseError, ValueError):
            pass
        try:
            results["osdr"] = await discover_osdr_sources(client)
        except (httpx.HTTPError, ValueError, TypeError):
            pass
    return results
