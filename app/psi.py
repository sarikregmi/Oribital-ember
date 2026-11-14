import os
from collections.abc import Mapping
from typing import Any

import httpx

from .models import Investigation


class PSIProvider:
    """Small adapter for the PSI export/API contract once its endpoint is confirmed."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv("PSI_API_URL")

    async def fetch_investigations(self) -> list[Investigation]:
        if not self.base_url:
            return []
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(self.base_url)
            response.raise_for_status()
            payload = response.json()
        records = payload.get("investigations", payload) if isinstance(payload, Mapping) else payload
        return [normalize_record(record) for record in records]


def normalize_record(record: Mapping[str, Any]) -> Investigation:
    """Normalize common PSI export fields into the dashboard's stable schema."""
    return Investigation(
        id=str(record.get("id") or record.get("identifier")),
        name=str(record.get("name") or record.get("title")),
        description=str(record.get("description") or record.get("summary") or ""),
        domain=record.get("domain", "fundamental"),
        gravity=list(record.get("gravity", [])),
        fuels=list(record.get("fuels", [])),
        conditions=list(record.get("conditions", [])),
        measurements=list(record.get("measurements", [])),
        hardware=list(record.get("hardware", [])),
        source_url=str(record.get("source_url") or record.get("url") or "https://psi.nasa.gov/"),
        keywords=list(record.get("keywords", [])),
    )
