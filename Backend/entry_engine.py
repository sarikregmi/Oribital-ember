"""Transparent atmospheric-entry heating screening, not an aerothermal solver."""
from __future__ import annotations

import math
from typing import Any


RHO0_KG_M3 = 1.225
SCALE_HEIGHT_M = 8500.0
SUTTON_GRAVES_K = 1.83e-4
DISPLAY_REFERENCE_W_M2 = 1.0e7


def estimate_entry_heating(entry: dict[str, Any], geometry: dict[str, Any]) -> dict[str, Any]:
    speed_km_s = entry.get("speed_km_s")
    altitude_km = entry.get("altitude_km")
    nose_radius_m = geometry.get("nose_radius_m")
    if not all(isinstance(value, (int, float)) for value in (speed_km_s, altitude_km, nose_radius_m)):
        return {
            "status": "insufficient input",
            "estimate_w_m2": None,
            "screening_index": None,
            "certainty": "unknown",
            "assumptions": ["speed_km_s, altitude_km, and nose_radius_m are required"],
        }
    speed_m_s = float(speed_km_s) * 1000.0
    density = RHO0_KG_M3 * math.exp(-float(altitude_km) * 1000.0 / SCALE_HEIGHT_M)
    heat_flux = SUTTON_GRAVES_K * math.sqrt(density / float(nose_radius_m)) * speed_m_s ** 3
    return {
        "status": "screening estimate",
        "estimate_w_m2": round(heat_flux, 2),
        "screening_index": round(min(heat_flux / DISPLAY_REFERENCE_W_M2, 1.0), 3),
        "certainty": "estimated from user input and reference atmosphere",
        "formula": "q_dot = K * sqrt(rho / nose_radius) * velocity^3",
        "assumptions": [
            "Exponential reference atmosphere: sea-level density 1.225 kg/m^3 and scale height 8.5 km",
            "Sutton-Graves coefficient K = 1.83e-4 in SI screening form",
            "No trajectory, catalytic-wall, ablation, radiation, or shock-layer model; no CFD",
            "Display index is normalized to 10 MW/m^2 and is not a damage threshold",
        ],
        "inputs": {
            "speed_km_s": speed_km_s,
            "altitude_km": altitude_km,
            "nose_radius_m": nose_radius_m,
        },
    }
