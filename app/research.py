"""Small, optional research connectors used to enrich local AI context."""

import json
import os
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus

import httpx

from .models import ResearchSource


# Use a writable user-data file so a packaged app can keep research between runs.
CACHE_PATH = Path(os.getenv("ORBITAL_EMBER_CACHE", Path.home() / ".orbital_ember" / "research_cache.json"))


def save_cached_sources(query: str, sources: list[ResearchSource]) -> None:
    """Persist returned research without making up records when a search is empty."""
    if not sources:
        return
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        if CACHE_PATH.exists():
            entries = json.loads(CACHE_PATH.read_text(encoding="utf-8")).get("entries", [])
        entries.append({"query": query, "sources": [source.model_dump() for source in sources]})
        temporary_path = CACHE_PATH.with_suffix(".tmp")
        temporary_path.write_text(json.dumps({"entries": entries[-100:]}, indent=2), encoding="utf-8")
        temporary_path.replace(CACHE_PATH)
    except (OSError, ValueError):
        # Caching is helpful but must never stop an answer from being returned.
        return


def load_cached_sources(query: str) -> list[ResearchSource]:
    """Find previously saved sources with overlapping meaningful query words."""
    try:
        entries = json.loads(CACHE_PATH.read_text(encoding="utf-8")).get("entries", [])
    except (OSError, ValueError):
        return []
    query_words = {word.lower() for word in query.split() if len(word) > 3}
    matches = []
    for entry in reversed(entries):
        entry_words = set(str(entry.get("query", "")).lower().split())
        if query_words & entry_words:
            matches.extend(ResearchSource.model_validate(source) for source in entry.get("sources", []))
        if len(matches) >= 6:
            break
    return matches[:6]


class _DuckDuckGoParser(HTMLParser):
    """Extract a few public search results without adding a scraping dependency."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[ResearchSource] = []
        self._link: str | None = None
        self._title: list[str] = []
        self._snippet: list[str] = []
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = attributes.get("class", "") or ""
        if tag == "a" and "result__a" in classes:
            self._link = attributes.get("href")
            self._title = []
            self._in_title = True
        if "result__snippet" in classes:
            self._snippet = []
            self._in_snippet = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)
        if self._in_snippet:
            self._snippet.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
            if self._link and self._title and len(self.results) < 3:
                self.results.append(ResearchSource(
                    title="".join(self._title).strip(),
                    url=self._link,
                    snippet="",
                    source_type="web",
                ))
                self._link = None
        if self._in_snippet and tag in {"a", "div"}:
            self._in_snippet = False
            if self.results and self._snippet:
                self.results[-1].snippet = " ".join("".join(self._snippet).split())[:500]


def _instant_answer_sources(payload: dict) -> list[ResearchSource]:
    """Convert DuckDuckGo's JSON abstract and related topics into cited sources."""
    sources: list[ResearchSource] = []
    abstract_url = payload.get("AbstractURL")
    abstract = payload.get("AbstractText")
    if abstract_url and abstract:
        sources.append(ResearchSource(
            title=str(payload.get("Heading") or "Web research result"),
            url=str(abstract_url),
            snippet=str(abstract)[:500],
            source_type="web",
        ))
    for topic in payload.get("RelatedTopics", []):
        if "Topics" in topic:
            nested = topic.get("Topics", [])
        else:
            nested = [topic]
        for item in nested:
            if item.get("FirstURL") and item.get("Text") and len(sources) < 3:
                sources.append(ResearchSource(
                    title=str(item["Text"]).split(" - ")[0][:120],
                    url=str(item["FirstURL"]),
                    snippet=str(item["Text"])[:500],
                    source_type="web",
                ))
    return sources[:3]


async def search_web(query: str) -> list[ResearchSource]:
    """Fetch at most three general web results using several public paths."""
    if not query.strip():
        return []
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "OrbitalEmber/0.1"})
            response.raise_for_status()
        parser = _DuckDuckGoParser()
        parser.feed(response.text)
        results = parser.results[:3]
        if not results:
            async with httpx.AsyncClient(timeout=8.0) as client:
                api_response = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                )
                api_response.raise_for_status()
                results = _instant_answer_sources(api_response.json())
        if not results:
            async with httpx.AsyncClient(timeout=8.0) as client:
                wiki_response = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={"action": "opensearch", "search": query, "limit": 3, "namespace": 0, "format": "json"},
                )
                wiki_response.raise_for_status()
                wiki_payload = wiki_response.json()
            results = [ResearchSource(
                title=str(title),
                url=str(url),
                snippet=str(snippet),
                source_type="web",
            ) for title, snippet, url in zip(wiki_payload[1], wiki_payload[2], wiki_payload[3])]
        save_cached_sources(query, results)
        return results
    except (httpx.HTTPError, ValueError):
        return []


async def search_nasa(query: str) -> list[ResearchSource]:
    """Search NASA's public image/video API, which needs no API key."""
    if not query.strip():
        return []
    url = f"https://images-api.nasa.gov/search?q={quote_plus(query)}&media_type=image,video"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            items = response.json().get("collection", {}).get("items", [])
        sources = []
        for item in items[:3]:
            data = (item.get("data") or [{}])[0]
            links = item.get("links") or [{}]
            sources.append(ResearchSource(
                title=str(data.get("title", "NASA result")),
                url=str(links[0].get("href", "https://images.nasa.gov/")),
                snippet=str(data.get("description", ""))[:500],
                source_type="nasa",
            ))
        save_cached_sources(query, sources)
        return sources
    except (httpx.HTTPError, ValueError, AttributeError):
        return []
