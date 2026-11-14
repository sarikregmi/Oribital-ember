"""Structured, uncertainty-aware spacecraft model helpers."""
from __future__ import annotations

from typing import Any


SCENARIO_DEFINITIONS = {
    "ground": {"label": "Ground / pre-launch", "fire_present": False, "gravity_m_s2": 9.81},
    "ascent": {"label": "Ascent", "fire_present": False, "gravity_m_s2": 9.81},
    "space_internal_fire": {"label": "Space / internal fire", "fire_present": True, "gravity_m_s2": 0.0},
    "external_fire": {"label": "External fire", "fire_present": True, "gravity_m_s2": 9.81},
    "entry": {"label": "Atmospheric entry", "fire_present": False, "gravity_m_s2": 9.81},
    "engine_region_fire": {"label": "Engine-region fire", "fire_present": True, "gravity_m_s2": 9.81},
}


def normalize_vehicle(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Fill structural defaults without inventing user engineering values."""
    normalized = dict(vehicle)
    normalized.setdefault("name", "Unnamed spacecraft")
    normalized.setdefault("type", "spacecraft")
    normalized.setdefault("geometry", {})
    normalized.setdefault("mass", {"value": None, "unit": "kg", "certainty": "unknown"})
    normalized.setdefault("center_of_mass", {"x_m": None, "y_m": None, "z_m": None, "certainty": "unknown"})
    normalized.setdefault("environment", {})
    normalized.setdefault("components", [])
    normalized.setdefault("scenario", {})
    normalized.setdefault("entry", {})
    scenario_type = normalized["scenario"].get("type", "ground")
    definition = SCENARIO_DEFINITIONS.get(scenario_type, SCENARIO_DEFINITIONS["ground"])
    normalized["scenario"].setdefault("label", definition["label"])
    normalized["scenario"].setdefault("fire_present", definition["fire_present"])
    normalized["environment"].setdefault("gravity_m_s2", definition["gravity_m_s2"])
    return normalized


def component_names(vehicle: dict[str, Any]) -> list[str]:
    return [component.get("name", "Unnamed component") for component in vehicle.get("components", [])]
