"""Conservative proximity-based consequence screening."""
from __future__ import annotations

from typing import Any


def map_consequences(vehicle: dict[str, Any]) -> list[dict[str, Any]]:
    components = vehicle.get("components", [])
    scenario = vehicle.get("scenario", {})
    sources = [component for component in components if component.get("fire_source") is True]
    if not sources and scenario.get("fire_present") is True:
        sources = [component for component in components if component.get("location") == scenario.get("location")]
    consequences = []
    for source in sources:
        source_name = source.get("name", "Unnamed source")
        for component in components:
            if component is source:
                continue
            if component.get("location") == source.get("location"):
                consequences.append({
                    "source": source_name,
                    "target": component.get("name", "Unnamed component"),
                    "relationship": "potentially affected by shared configured location",
                    "certainty": "screening-only",
                    "basis": "User-provided component location; no spread or ignition claim",
                })
    return consequences
