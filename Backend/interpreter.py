"""Deterministic fallback for turning plain-language descriptions into model fields."""
from __future__ import annotations

import re
from typing import Any


NUMBER = r"(?:\d+(?:\.\d+)?)"


def interpret_description(description: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract explicit values only; this is an AI-adapter seam, not an AI model."""
    vehicle = dict(base or {})
    vehicle["description"] = description
    vehicle["description_source"] = "user-described"
    geometry = dict(vehicle.get("geometry", {}))
    mass = dict(vehicle.get("mass", {}))
    components = list(vehicle.get("components", []))

    length = re.search(rf"({NUMBER})\s*(?:m|meter|meters)\s+long", description, re.I)
    diameter = re.search(rf"(?:diameter|wide)\s*(?:is|of|=)?\s*({NUMBER})\s*m", description, re.I)
    weight = re.search(rf"({NUMBER})\s*(?:kg|kilograms?)", description, re.I)
    nose = re.search(rf"nose\s*(?:angle)?\s*(?:is|of|=)?\s*({NUMBER})\s*(?:deg|degrees?|°)", description, re.I)
    if length:
        geometry.update({"length_m": float(length.group(1)), "length_certainty": "user-described"})
    if diameter:
        geometry.update({"diameter_m": float(diameter.group(1)), "diameter_certainty": "user-described"})
    if nose:
        geometry.update({"nose_angle_deg": float(nose.group(1)), "nose_angle_certainty": "user-described"})
    if weight:
        mass.update({"value": float(weight.group(1)), "unit": "kg", "certainty": "estimated" if "about" in description.lower() else "user-described"})

    if re.search(r"plastic|polymer|insulation", description, re.I):
        components.append({
            "name": "Described insulation",
            "material": "unknown",
            "material_category": "polymer",
            "certainty": "user-described",
            "description": "plastic-like or insulation material mentioned by user",
        })
    vehicle["geometry"] = geometry
    vehicle["mass"] = mass
    vehicle["components"] = components
    return vehicle
