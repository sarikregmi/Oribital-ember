"""NASA PSI investigation and file-list reader.

PSI's public UI is the authoritative source used here. The site does not publish
one stable, documented PSI-specific REST contract, so this reader tolerates its
HTML links, embedded JSON, sitemap and pagination variants.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

import httpx

from .models import Investigation

PSI_SEARCH_URL = os.getenv(
    "PSI_SEARCH_URL",
    "https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation",
)
PSI_BASE = "https://psi.nasa.gov"
FILE_EXTENSIONS = {
    ".pdf", ".csv", ".tsv", ".txt", ".json", ".jsonl", ".zip", ".gz", ".tar",
    ".xlsx", ".xls", ".doc", ".docx", ".ppt", ".pptx", ".mp4", ".avi", ".h5",
    ".hdf5", ".mat", ".dat", ".bin", ".nc", ".fits",
}


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []
        self.text: list[str] = []
        self.attrs: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self._href = attrs.get("href") or attrs.get("data-href") or attrs.get("data-url")
            self._parts = []
        for key, value in attrs.items():
            if value and key in {"href", "src", "data-href", "data-url", "data-download-url", "data-file-url", "data-original-url", "content"}:
                self.attrs.append(str(value))

    def handle_data(self, data):
        self.text.append(data)
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            label = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
            self.links.append((self._href, label))
            self._href, self._parts = None, []


class _InvestigationLinks(_LinkParser):
    """Compatibility name for the HTML investigation-link parser."""


def _page_url(base: str, page: int) -> str:
    parts = urlsplit(base)
    pairs = dict(parse_qsl(parts.query, keep_blank_values=True))
    pairs["page"] = str(page)
    # The PSI UI defaults to 25; request the largest documented UI page size.
    pairs.setdefault("items_per_page", "100")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def _record_id(url: str, label: str = "") -> str | None:
    match = re.search(r"PSI[-_ ]?\d+", url, re.I) or re.search(r"PSI[-_ ]?\d+", label, re.I)
    if match:
        return re.sub(r"[-_ ]", "-", match.group(0)).upper()
    path = urlparse(url).path.rstrip("/")
    if "/data/investigations/" in path:
        tail = path.rsplit("/", 1)[-1]
        return tail if tail and tail.lower() not in {"investigations", "search"} else None
    return None


def _domain_for(text: str) -> str:
    value = text.lower()
    if any(x in value for x in ("smoke", "aerosol", "particle", "sensor", "detection")):
        return "detection"
    if any(x in value for x in ("extinguish", "suppression", "droplet")):
        return "suppression"
    if any(x in value for x in ("flame", "combustion", "burning", "flammab", "fire")):
        return "flammability"
    return "fundamental"


class _FileTableParser(HTMLParser):
    """Associate PSI's filename cell with its row's View Content link."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, list[str]]] = []
        self.in_row = False
        self.in_cell = False
        self.row_text: list[str] = []
        self.row_links: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.in_row, self.row_text, self.row_links = True, [], []
        elif self.in_row:
            href = (attrs.get("href") or attrs.get("data-href") or attrs.get("data-url")
                    or attrs.get("data-download-url") or attrs.get("data-file-url") or attrs.get("data-original-url"))
            if href:
                self.row_links.append(href)

    def handle_data(self, data):
        if self.in_row:
            self.row_text.append(data)

    def handle_endtag(self, tag):
        if tag == "tr" and self.in_row:
            self.rows.append((re.sub(r"\s+", " ", " ".join(self.row_text)).strip(), self.row_links.copy()))
            self.in_row = False


class PSIProvider:
    def __init__(self, base_url: str | None = None, timeout: float = 45.0):
        self.base_url = base_url or PSI_SEARCH_URL
        self.timeout = timeout
        self.last_catalog_complete = False
        self.last_catalog_total: int | None = None
        self.headers = {"User-Agent": "OrbitalEmber/1.0 (NASA PSI public research archive; contact: project maintainer)"}

    async def fetch_investigations(self) -> list[Investigation]:
        """Fetch the complete PSI catalogue from NASA's observed search API.

        The public Angular UI calls ``/geode-py/ws/repo/search``. Its response
        is Elasticsearch-shaped (``hits.total`` and ``hits.hits[*]._source``).
        Pagination uses zero-based ``from`` plus ``size``; the UI's observed
        default is 25 records per request.
        """
        self.last_catalog_complete = False
        self.last_catalog_total = None
        records: dict[str, Investigation] = {}
        api_url = f"{PSI_BASE}/geode-py/ws/repo/search"
        page_size = 25
        offset = 0

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=self.headers) as client:
                while True:
                    params = {
                        "source": "psi",
                        "type": "investigation",
                        "sort": "Public Release Date",
                        "order": "desc",
                    }
                    if offset:
                        params.update({"from": str(offset), "size": str(page_size)})
                    try:
                        response = await client.get(api_url, params=params)
                    except TypeError:
                        # Legacy/simple test clients may expose get(url) only.
                        break
                    response.raise_for_status()
                    try:
                        payload = response.json()
                    except (ValueError, AttributeError):
                        break
                    page_records = list(_walk_json_records(payload))
                    total = _json_total(payload)
                    if total is not None:
                        self.last_catalog_total = total

                    for item in page_records:
                        record = normalize_record(item)
                        if record.id != "unknown":
                            records[record.id] = record

                    if not page_records:
                        break
                    offset += len(page_records)
                    if self.last_catalog_total is not None and offset >= self.last_catalog_total:
                        break
                    # A short page without a reported total is the only safe
                    # end marker; never declare a full catalogue from it alone.
                    if len(page_records) < page_size:
                        break

                self.last_catalog_complete = (
                    self.last_catalog_total is not None
                    and len(records) == self.last_catalog_total
                )

                # Keep the older HTML path for deployments/tests where the
                # JSON endpoint is unavailable and the search URL serves HTML.
                if not records:
                    for page_number in range(0, 100):
                        try:
                            html_response = await client.get(_page_url(self.base_url, page_number))
                            html_response.raise_for_status()
                        except TypeError:
                            # Lightweight mocked clients may only accept a URL.
                            break
                        parser = _InvestigationLinks()
                        parser.feed(html_response.text)
                        added = 0
                        for href, title in parser.links:
                            absolute = urljoin(PSI_BASE, href)
                            identifier = _record_id(absolute, title)
                            if identifier and identifier not in records:
                                records[identifier] = _from_catalog_link(identifier, title or identifier, absolute)
                                added += 1
                        if not added:
                            break

                # Sitemap fallback covers records omitted by a client-side result grid.
                if not records:
                    for sitemap_url in (f"{PSI_BASE}/sitemap.xml", f"{PSI_BASE}/physci/sitemap.xml"):
                        try:
                            sitemap = await client.get(sitemap_url)
                            if sitemap.is_success:
                                for raw_url in re.findall(r"<loc>(.*?)</loc>", sitemap.text, re.I | re.S):
                                    absolute = raw_url.strip()
                                    identifier = _record_id(absolute)
                                    if identifier and "/repo/data/investigations/" in absolute:
                                        records.setdefault(identifier, _from_catalog_link(identifier, identifier, absolute))
                        except httpx.HTTPError:
                            pass
        except (httpx.HTTPError, ValueError, TypeError):
            self.last_catalog_complete = False

        # Only use browser discovery if the API returned no records. A browser
        # link scrape cannot enrich the authoritative API metadata safely.
        if not records:
            browser_records = await self._fetch_with_browser()
            for record in browser_records:
                records.setdefault(record.id, record)

        self.last_catalog_complete = bool(
            self.last_catalog_total is not None
            and len(records) == self.last_catalog_total
        )
        return list(records.values())

    async def _fetch_with_browser(self) -> list[Investigation]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return []
        found: dict[str, Investigation] = {}
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(self.base_url, wait_until="domcontentloaded", timeout=int(self.timeout * 1000))
                # Prefer the largest page size supported by the PSI UI.
                try:
                    for option in await page.locator("select").all():
                        values = await option.locator("option").all_text_contents()
                        if any(value.strip() == "100" for value in values):
                            await option.select_option(label="100")
                            await page.wait_for_load_state("networkidle", timeout=15000)
                            break
                except Exception:
                    pass
                reached_last_page = False
                for _ in range(100):
                    body_text = await page.locator("body").inner_text()
                    total_match = re.search(r"\b\d+\s*[–-]\s*\d+\s+of\s+([\d,]+)", body_text, re.I)
                    if total_match:
                        self.last_catalog_total = int(total_match.group(1).replace(",", ""))
                    links = await page.locator("a[href*='/physci/repo/']").evaluate_all(
                        "nodes => nodes.map(a => ({href:a.href, title:(a.innerText||a.textContent||'').trim()}))"
                    )
                    added = 0
                    for item in links:
                        identifier = _record_id(item.get("href", ""), item.get("title", ""))
                        if identifier and identifier not in found:
                            found[identifier] = _from_catalog_link(identifier, item.get("title") or identifier, item["href"])
                            added += 1
                    if not added:
                        break
                    next_button = page.locator("button[aria-label*='Next'], a[aria-label*='Next'], button[title*='Next'], a[title*='Next'], li.next a, .pagination-next, button:has-text('Next'), a:has-text('Next')").first
                    try:
                        if not await next_button.is_visible() or await next_button.is_disabled():
                            reached_last_page = True
                            break
                        await next_button.click()
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        reached_last_page = True
                        break
                await browser.close()
            self.last_catalog_complete = bool(found) and (reached_last_page or (self.last_catalog_total is not None and len(found) >= self.last_catalog_total))
        except Exception:
            return []
        return list(found.values())

    async def fetch_investigation_details(self, investigation: Investigation) -> tuple[Investigation, list[dict[str, Any]]]:
        html = ""
        resolved_url = investigation.source_url
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=self.headers) as client:
                response = await client.get(investigation.source_url)
                response.raise_for_status()
                html = response.text
                resolved_url = str(response.url)
        except httpx.HTTPError:
            html, resolved_url = await self._render_url(investigation.source_url)
        parser = _LinkParser()
        parser.feed(html)
        page_text = re.sub(r"\s+", " ", " ".join(parser.text)).strip()
        files = _extract_file_links(html, parser, investigation.id)
        # Some PSI versions hydrate the objective and file table with JavaScript.
        if len(page_text) < 300 or not files:
            try:
                rendered_html, rendered_url = await self._render_url(investigation.source_url)
                if len(rendered_html) > len(html):
                    html, resolved_url = rendered_html, rendered_url
                    parser = _LinkParser()
                    parser.feed(html)
                    page_text = re.sub(r"\s+", " ", " ".join(parser.text)).strip()
                    files = _extract_file_links(html, parser, investigation.id)
            except Exception:
                pass
        title = _extract_section(page_text, investigation.id) or investigation.name
        description = _extract_objective(page_text) or investigation.description
        enriched = investigation.model_copy(update={
            "name": title[:300], "description": description[:5000],
            "domain": _domain_for(title + " " + description),
            "source_url": resolved_url,
        })
        return enriched, files

    async def _render_url(self, url: str) -> tuple[str, str]:
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout * 1000))
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            html, resolved = await page.content(), page.url
            await browser.close()
            return html, resolved


def _from_catalog_link(identifier: str, title: str, url: str) -> Investigation:
    clean = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()
    return Investigation(
        id=identifier, name=clean or identifier,
        description="NASA PSI investigation record. Open the official NASA page for objectives, approach, publications, and available files.",
        domain=_domain_for(clean), gravity=[], fuels=[], conditions=[], measurements=[], hardware=[],
        source_url=url, keywords=["NASA PSI", _domain_for(clean)],
    )


def _json_total(payload: Any) -> int | None:
    """Read Elasticsearch-style ``hits.total`` (object or integer)."""
    if not isinstance(payload, Mapping):
        return None
    hits = payload.get("hits")
    if not isinstance(hits, Mapping):
        return None
    total = hits.get("total")
    if isinstance(total, Mapping):
        total = total.get("value")
    try:
        return int(total) if total is not None else None
    except (TypeError, ValueError):
        return None


def _walk_json_records(payload: Any):
    """Yield records from NASA's Elasticsearch response or legacy JSON lists."""
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, Mapping):
                source = item.get("_source", item)
                if isinstance(source, Mapping) and any(
                    key in source for key in ("Accession", "id", "identifier", "accession", "title", "Title")
                ):
                    record = dict(source)
                    if not any(record.get(k) for k in ("id", "identifier", "accession", "Accession")) and item.get("_id"):
                        record["id"] = item["_id"]
                    yield record
    elif isinstance(payload, Mapping):
        hits = payload.get("hits")
        if isinstance(hits, Mapping) and isinstance(hits.get("hits"), list):
            yield from _walk_json_records(hits["hits"])
            return
        for key in ("investigations", "records", "results", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                yield from _walk_json_records(value)
                return
        if any(k in payload for k in ("Accession", "id", "identifier", "accession", "Title", "title")):
            yield payload


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"\s{2,}|[;|]", str(value)) if part.strip()]


def normalize_record(record: Mapping[str, Any]) -> Investigation:
    """Map NASA PSI's capitalized API fields into Orbital Ember's model."""
    identifier = str(
        record.get("Accession") or record.get("id") or record.get("identifier")
        or record.get("accession") or "unknown"
    ).strip()
    name = str(record.get("Title") or record.get("name") or record.get("title") or identifier).strip()

    objectives = str(record.get("Objectives") or record.get("description") or record.get("summary") or "").strip()
    sections = [
        ("Objectives", objectives),
        ("Approach", str(record.get("Approach") or "").strip()),
        ("Hypothesis", str(record.get("Hypothesis") or "").strip()),
        ("Research impacts / Earth benefits", str(record.get("Research Impacts/Earth Benefits") or "").strip()),
    ]
    description = "\n\n".join(f"{label}:\n{text}" for label, text in sections if text)

    research_area = str(record.get("Research Area") or record.get("research_area") or "").strip()
    sub_area = str(record.get("SubResearch Area") or "").strip()
    supplied_domain = str(record.get("domain") or "").strip().lower()
    domain = supplied_domain if supplied_domain in {"flammability", "detection", "suppression", "fundamental"} else _domain_for(" ".join((name, research_area, sub_area, objectives)))

    hardware_value = record.get("Experiment Hardware") or record.get("hardware") or []
    if isinstance(hardware_value, Mapping):
        hardware = _as_list(hardware_value.get("Name"))
        hardware_link = hardware_value.get("Link")
        if hardware_link:
            hardware.append(str(hardware_link))
    else:
        hardware = _as_list(hardware_value)

    keywords = _as_list(record.get("Keywords") or record.get("keywords"))
    for extra in (research_area, sub_area, str(record.get("Acronym") or "").strip()):
        if extra and extra not in keywords:
            keywords.append(extra)
    if not keywords:
        keywords = ["NASA PSI"]

    conditions = []
    for field in ("Project Type", "Flight Platform", "Investigation Start Date", "Investigation End Date"):
        value = record.get(field)
        if value:
            conditions.append(f"{field}: {value}")

    gravity_text = " ".join((name, objectives, str(record.get("Approach") or ""))).lower()
    gravity = ["microgravity"] if "microgravity" in gravity_text or "space station" in gravity_text or "iss " in gravity_text else []
    source_url = str(record.get("source_url") or record.get("url") or f"{PSI_BASE}/physci/repo/data/investigations/{identifier}")

    return Investigation(
        id=identifier, name=name, description=description,
        domain=domain, gravity=gravity, fuels=[], conditions=conditions,
        measurements=[], hardware=hardware, source_url=source_url,
        keywords=keywords,
    )


def _extract_section(text: str, identifier: str) -> str | None:
    # PSI pages place the title immediately after their version heading.
    match = re.search(re.escape(identifier) + r"\s+Version\s+\d+\s+(.{4,300}?)\s+Investigation", text, re.I)
    if match:
        return match.group(1).strip(" -|:")
    return None


def _extract_objective(text: str) -> str | None:
    for marker in ("Objectives", "Objective"):
        match = re.search(marker + r"\s+(.{40,2500}?)(?:\s+Hypothesis\s+|\s+Approach\s+|\s+Contact\(s\)\s+|\s+Research Impacts|\s+sim_card_download|$)", text, re.I)
        if match:
            return match.group(1).strip()
    return None


def _extract_file_links(html: str, parser: _LinkParser, investigation_id: str) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    candidates = list(parser.links) + [(value, "") for value in parser.attrs]
    # PSI's file browser often puts the filename and View Content link in the
    # same table row, with an opaque URL that has no filename extension.
    table = _FileTableParser()
    table.feed(html)
    for row_text, row_links in table.rows:
        ext_match = re.search(r"(" + "|".join(re.escape(x) for x in sorted(FILE_EXTENSIONS, key=len, reverse=True)) + r")\b", row_text, re.I)
        if not ext_match:
            continue
        filename_match = re.search(r"[^|]+?\.(?:" + "|".join(re.escape(x.lstrip('.')) for x in sorted(FILE_EXTENSIONS, key=len, reverse=True)) + r")", row_text, re.I)
        filename = filename_match.group(0).strip() if filename_match else row_text[:240]
        for href in row_links:
            candidates.append((href, filename))
    # Include URLs embedded in serialized React/JS data.
    for raw in re.findall(r"(?:https?:\\?/\\?/|/)[^\"'<> ]+", html):
        candidates.append((raw.replace("\\/", "/"), ""))
    for href, label in candidates:
        url = urljoin(PSI_BASE, href.strip())
        parsed = urlparse(url)
        path = parsed.path.lower()
        label_path = urlparse(label).path.lower() if label else ""
        suffix = next((ext for ext in FILE_EXTENSIONS if path.endswith(ext) or label_path.endswith(ext)), "")
        if not suffix and label:
            match = re.search(r"(" + "|".join(re.escape(x) for x in sorted(FILE_EXTENSIONS, key=len, reverse=True)) + r")\b", label, re.I)
            suffix = match.group(1).lower() if match else ""
        if not suffix:
            continue
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (host == "nasa.gov" or host.endswith(".nasa.gov")):
            continue
        name = (label or parsed.path.rsplit("/", 1)[-1]).strip()[:240]
        if not name or name.lower() in {"view content", "download"}:
            name = parsed.path.rsplit("/", 1)[-1] or f"{investigation_id}{suffix}"
        found.setdefault(url, {"name": name, "url": url, "extension": suffix, "investigation_id": investigation_id,
                               "category": _guess_category(name)})
    return list(found.values())


def _guess_category(name: str) -> str:
    value = name.lower()
    if "science document" in value or value.endswith(".pdf"):
        return "document"
    if "raw data" in value or value.endswith((".csv", ".tsv", ".dat", ".h5", ".hdf5")):
        return "raw-data"
    if "engineering" in value:
        return "engineering"
    if "report" in value:
        return "report"
    return "file"

# Compatibility name retained for the earlier HTML-parser tests and integrations.
_InvestigationLinks = _LinkParser
