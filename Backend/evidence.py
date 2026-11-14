"""Curated evidence metadata; these records are references, not calculation inputs."""
from __future__ import annotations

NASA_EVIDENCE = [
    {
        "id": "sofie",
        "title": "Solid Fuel Ignition and Extinction",
        "source": "NASA",
        "variables": ["oxygen concentration", "pressure", "flow", "fuel temperature"],
        "relevance": ["spacecraft material flammability", "internal fire screening"],
        "url": "https://www.nasa.gov/glenn/sofie/",
        "source_type": "NASA project page",
        "verification_status": "URL recorded; live fetch may be rate-limited",
    },
    {
        "id": "bass",
        "title": "Burning and Suppression of Solids",
        "source": "NASA",
        "variables": ["microgravity", "oxygen concentration", "material geometry"],
        "relevance": ["spacecraft combustion research"],
        "url": "https://ntrs.nasa.gov/search?q=Burning%20and%20Suppression%20of%20Solids",
        "source_type": "NASA NTRS search",
        "verification_status": "Search record; select and verify the applicable report",
    },
    {
        "id": "saffire",
        "title": "Spacecraft Fire Experiment",
        "source": "NASA",
        "variables": ["material behavior", "airflow", "spacecraft atmosphere"],
        "relevance": ["large-scale spacecraft fire behavior"],
        "url": "https://www.nasa.gov/search/?q=SAFFIRE%20spacecraft%20fire%20experiment",
        "source_type": "NASA search record",
        "verification_status": "Search record; select and verify the applicable mission page",
    },
]


def evidence_for(vehicle: dict) -> list[dict]:
    scenario = vehicle.get("scenario", {}).get("type", "")
    if scenario == "space_internal_fire":
        return [NASA_EVIDENCE[0], NASA_EVIDENCE[1], NASA_EVIDENCE[2]]
    if scenario in {"external_fire", "engine_region_fire", "entry"}:
        return [NASA_EVIDENCE[0], NASA_EVIDENCE[2]]
    return [NASA_EVIDENCE[0]]
