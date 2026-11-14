"""Orbital Ember: transparent spacecraft fire-safety screening emulator."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

try:
    from Backend.consequence_engine import map_consequences
    from Backend.evidence import evidence_for
    from Backend.entry_engine import estimate_entry_heating
    from Backend.interpreter import interpret_description
    from Backend.model import SCENARIO_DEFINITIONS, normalize_vehicle
    from Backend.qwen import explain_result
    from Backend.renderer3d import SpacecraftRenderer
except ModuleNotFoundError:
    from consequence_engine import map_consequences
    from evidence import evidence_for
    from entry_engine import estimate_entry_heating
    from interpreter import interpret_description
    from model import SCENARIO_DEFINITIONS, normalize_vehicle
    from qwen import explain_result
    from renderer3d import SpacecraftRenderer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "vehicle.json"
DEFAULT_OUTPUT = ROOT / "output" / "analysis_result.json"
SCENARIOS = [
    (definition["label"], scenario_type, definition["fire_present"])
    for scenario_type, definition in SCENARIO_DEFINITIONS.items()
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def analyze_vehicle(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Apply conservative screening rules; this is not a fire prediction model."""
    vehicle = normalize_vehicle(vehicle)
    scenario = vehicle.get("scenario", {})
    environment = vehicle.get("environment", {})
    components = vehicle.get("components", [])
    findings: list[dict[str, Any]] = []

    fire_present = scenario.get("fire_present") is True
    if fire_present:
        affected = [component.get("name", "Unnamed component") for component in components]
        findings.append({
            "id": "scenario-fire-present",
            "title": "User-described fire scenario is active",
            "location": scenario.get("location", "Unknown location"),
            "severity": "screening attention",
            "certainty": "user-described",
            "evidence": "User input; no ignition prediction performed",
            "affected_components": affected,
            "screening_only": True,
        })

    oxygen = environment.get("oxygen_fraction")
    if isinstance(oxygen, str):
        try:
            oxygen = float(oxygen)
        except ValueError:
            oxygen = None
    if isinstance(oxygen, (int, float)) and oxygen > 0.21:
        findings.append({
            "id": "oxygen-enrichment",
            "title": "Oxygen fraction is above the terrestrial reference value",
            "location": "Environment",
            "severity": "screening attention",
            "certainty": "estimated from user input",
            "evidence": "Reference comparison only; no flammability limit inferred",
            "affected_components": [component.get("name", "Unnamed component") for component in components],
            "screening_only": True,
        })

    materials = {component.get("material", "unknown").lower() for component in components}
    if "unknown" in materials:
        findings.append({
            "id": "unknown-material",
            "title": "One or more component materials are unspecified",
            "location": "Component inventory",
            "severity": "information gap",
            "certainty": "known data gap",
            "evidence": "No material property was supplied; no ignition temperature assumed",
            "affected_components": [
                component.get("name", "Unnamed component")
                for component in components
                if component.get("material", "unknown").lower() == "unknown"
            ],
            "screening_only": True,
        })

    entry = vehicle.get("entry", {})
    entry_index = None
    entry_thermal = {"status": "not requested", "estimate_w_m2": None, "screening_index": None, "certainty": "not applicable"}
    if entry.get("planned") is True:
        speed = entry.get("speed_km_s")
        if isinstance(speed, (int, float)):
            entry_index = round(min(speed / 7.8, 1.0), 2)
            entry_thermal = estimate_entry_heating(entry, vehicle.get("geometry", {}))
            if entry_thermal.get("screening_index") is not None:
                entry_index = entry_thermal["screening_index"]
            findings.append({
                "id": "entry-screening-index",
                "title": "Atmospheric-entry speed requires thermal review",
                "location": "External vehicle surfaces",
                "severity": "screening attention" if entry_index >= 0.75 else "monitor",
                "certainty": "estimated from user input",
                "evidence": "Sutton-Graves-style screening estimate with declared reference-atmosphere assumptions; no CFD or trajectory model",
                "affected_components": ["External thermal protection"],
                "screening_only": True,
            })

    return {
        "vehicle_name": vehicle.get("name", "Unnamed vehicle"),
        "scenario": scenario.get("type", "unknown"),
        "analysis_type": "transparent fire, thermal, and consequence screening",
        "model": {
            "geometry": vehicle.get("geometry", {}),
            "mass": vehicle.get("mass", {"value": None, "certainty": "unknown"}),
            "center_of_mass": vehicle.get("center_of_mass", {"certainty": "unknown"}),
            "environment": environment,
        },
        "limitations": [
            "Does not predict ignition or fire spread.",
            "Does not replace CFD, certification, testing, or engineering review.",
            "NASA evidence references must be added by a qualified reviewer.",
        ],
        "entry_screening_index": entry_index,
        "entry_thermal_screening": entry_thermal,
        "evidence": evidence_for(vehicle),
        "consequences": map_consequences(vehicle),
        "findings": findings,
    }


def set_scenario(vehicle: dict[str, Any], scenario_type: str) -> dict[str, Any]:
    """Return a copy with a named screening scenario, without changing the source file."""
    updated = copy.deepcopy(vehicle)
    scenario = next((item for item in SCENARIOS if item[1] == scenario_type), None)
    if scenario is None:
        raise ValueError(f"Unknown scenario: {scenario_type}")
    label, _, fire_present = scenario
    updated.setdefault("scenario", {}).update({
        "type": scenario_type,
        "label": label,
        "fire_present": fire_present,
        "source": "user-selected screening preset",
    })
    if scenario_type == "entry":
        updated.setdefault("entry", {})["planned"] = True
    return updated


def save_result(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")


def run_screening(input_path: Path = DEFAULT_INPUT, output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    result = analyze_vehicle(load_json(input_path))
    save_result(result, output_path)
    return result


def draw_text(window: Any, font: Any, text: str, position: tuple[int, int], color: tuple[int, int, int], pygame: Any) -> None:
    window.blit(font.render(str(text), True, color), position)


def draw_button(window: Any, rect: Any, label: str, active: bool, pygame: Any, font: Any) -> None:
    pygame.draw.rect(window, (39, 55, 70) if active else (25, 36, 48), rect, border_radius=4)
    pygame.draw.rect(window, (244, 157, 67) if active else (65, 83, 98), rect, 1, border_radius=4)
    draw_text(window, font, label, (rect.x + 8, rect.y + 7), (238, 242, 244), pygame)


def draw_screen(window: Any, vehicle: dict[str, Any], result: dict[str, Any] | None, selected: int, active_field: str | None, pygame: Any) -> None:
    title = pygame.font.Font(None, 30)
    heading = pygame.font.Font(None, 22)
    body = pygame.font.Font(None, 18)
    small = pygame.font.Font(None, 16)
    bg, panel, line = (13, 20, 29), (20, 31, 43), (56, 75, 91)
    text, muted, orange, cyan = (224, 231, 235), (145, 162, 176), (244, 157, 67), (118, 190, 201)
    window.fill(bg)
    pygame.draw.rect(window, panel, (0, 0, 860, 70))
    draw_text(window, title, "ORBITAL EMBER", (24, 18), orange, pygame)
    draw_text(window, small, "FIRE-SAFETY SCREENING CONSOLE", (26, 47), muted, pygame)
    draw_text(window, small, "SCREENING ONLY", (744, 27), cyan, pygame)
    pygame.draw.rect(window, panel, (18, 88, 294, 452))
    pygame.draw.rect(window, panel, (328, 88, 514, 452))
    draw_text(window, heading, "SPACECRAFT CONFIGURATION", (34, 106), text, pygame)
    fields = [("name", "Vehicle name", vehicle.get("name", "")), ("location", "Environment", vehicle.get("environment", {}).get("location", "")), ("oxygen", "Oxygen fraction", vehicle.get("environment", {}).get("oxygen_fraction", ""))]
    for index, (key, label, value) in enumerate(fields):
        y = 145 + index * 57
        draw_text(window, small, label, (34, y), muted, pygame)
        rect = pygame.Rect(34, y + 18, 256, 29)
        pygame.draw.rect(window, (15, 24, 34), rect)
        pygame.draw.rect(window, orange if active_field == key else line, rect, 1)
        draw_text(window, body, value, (42, y + 24), text, pygame)
    draw_text(window, heading, "SCENARIO", (34, 326), text, pygame)
    for index, (label, scenario_type, _) in enumerate(SCENARIOS):
        row, column = index // 2, index % 2
        rect = pygame.Rect(34 + column * 130, 357 + row * 35, 122, 27)
        draw_button(window, rect, label, vehicle.get("scenario", {}).get("type") == scenario_type, pygame, small)
    draw_button(window, pygame.Rect(34, 478, 80, 31), "RUN", True, pygame, small)
    draw_button(window, pygame.Rect(122, 478, 80, 31), "CLEAR", False, pygame, small)
    draw_button(window, pygame.Rect(210, 478, 80, 31), "EXIT", False, pygame, small)
    draw_text(window, heading, "FINDINGS INSPECTOR", (346, 106), text, pygame)
    geometry = vehicle.get("geometry", {})
    mass = vehicle.get("mass", {}).get("value", "unknown")
    geometry_summary = f"MODEL  {geometry.get('length_m', 'unknown')} m x {geometry.get('diameter_m', 'unknown')} m  |  MASS {mass} kg"
    draw_text(window, small, geometry_summary, (346, 124), cyan, pygame)
    if result is None:
        draw_text(window, body, "Run screening to populate findings.", (346, 151), muted, pygame)
        draw_text(window, small, "User-described, estimated, and unknown values stay labeled.", (346, 180), muted, pygame)
        return
    draw_text(window, small, f"{len(result['findings'])} findings | scenario: {result['scenario']}", (346, 151), muted, pygame)
    y = 181
    for index, finding in enumerate(result["findings"]):
        rect = pygame.Rect(346, y, 478, 55)
        pygame.draw.rect(window, (29, 43, 55) if index == selected else (17, 27, 38), rect)
        accent = cyan if finding["severity"] == "information gap" else orange
        pygame.draw.rect(window, accent, (346, y, 5, 55))
        draw_text(window, body, finding["title"], (360, y + 8), text, pygame)
        draw_text(window, small, f"{finding['severity']} | {finding['certainty']} | {finding['location']}", (360, y + 31), muted, pygame)
        y += 64
    if result["findings"]:
        selected_finding = result["findings"][min(selected, len(result["findings"]) - 1)]
        pygame.draw.line(window, line, (346, 370), (824, 370))
        draw_text(window, small, "EVIDENCE", (346, 380), cyan, pygame)
        evidence_ids = ", ".join(item["id"] for item in result["evidence"])
        draw_text(window, small, "NASA references: " + evidence_ids, (346, 399), muted, pygame)
        draw_text(window, small, "AFFECTED: " + ", ".join(selected_finding["affected_components"]), (346, 418), muted, pygame)
        draw_text(window, small, "CONSEQUENCE LINKS", (346, 445), cyan, pygame)
        links = result["consequences"][:2]
        if links:
            for index, link in enumerate(links):
                draw_text(window, small, f"{link['source']} -> {link['target']} ({link['certainty']})", (346, 464 + index * 19), muted, pygame)
        else:
            draw_text(window, small, "No configured same-location links.", (346, 464), muted, pygame)
    else:
        draw_text(window, body, "No screening findings. This is not proof of safety.", (346, 186), muted, pygame)


def launch_visualizer(vehicle: dict[str, Any], output_path: Path = DEFAULT_OUTPUT) -> None:
    import pygame

    pygame.init()
    window = pygame.display.set_mode((860, 560))
    pygame.display.set_caption("Orbital Ember")
    clock = pygame.time.Clock()
    result = analyze_vehicle(vehicle)
    renderer = SpacecraftRenderer()
    selected = 0
    active_field: str | None = None
    show_3d = False
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                show_3d = not show_3d
            elif event.type == pygame.KEYDOWN and show_3d:
                if event.key == pygame.K_LEFT:
                    renderer.rotate(-0.12, 0.0)
                elif event.key == pygame.K_RIGHT:
                    renderer.rotate(0.12, 0.0)
                elif event.key == pygame.K_UP:
                    renderer.rotate(0.0, -0.12)
                elif event.key == pygame.K_DOWN:
                    renderer.rotate(0.0, 0.12)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                x, y = event.pos
                if 34 <= x <= 290 and 163 <= y <= 308:
                    active_field = ["name", "location", "oxygen"][(y - 163) // 57]
                elif 34 <= x <= 286 and 357 <= y <= 462:
                    index = ((y - 357) // 35) * 2 + ((x - 34) // 130)
                    if 0 <= index < len(SCENARIOS):
                        vehicle = set_scenario(vehicle, SCENARIOS[index][1])
                        result = analyze_vehicle(vehicle)
                elif 34 <= x <= 114 and 478 <= y <= 509:
                    result = analyze_vehicle(vehicle)
                    save_result(result, output_path)
                elif 122 <= x <= 202 and 478 <= y <= 509:
                    result = None
                elif 210 <= x <= 290 and 478 <= y <= 509:
                    running = False
                elif result and 346 <= x <= 824 and 181 <= y <= 181 + len(result["findings"]) * 64:
                    selected = max(0, min((y - 181) // 64, len(result["findings"]) - 1))
            elif event.type == pygame.KEYDOWN and active_field:
                if event.key == pygame.K_BACKSPACE:
                    if active_field == "name":
                        vehicle["name"] = vehicle.get("name", "")[:-1]
                    else:
                        key = "location" if active_field == "location" else "oxygen_fraction"
                        current = str(vehicle.get("environment", {}).get(key, ""))
                        vehicle.setdefault("environment", {})[key] = current[:-1]
                elif event.key == pygame.K_RETURN:
                    active_field = None
                elif event.unicode.isprintable():
                    if active_field == "name":
                        vehicle["name"] = vehicle.get("name", "") + event.unicode
                    else:
                        key = "location" if active_field == "location" else "oxygen_fraction"
                        current = str(vehicle.get("environment", {}).get(key, ""))
                        vehicle.setdefault("environment", {})[key] = current + event.unicode
        draw_screen(window, vehicle, result, selected, active_field, pygame)
        if show_3d:
            renderer.draw(window, vehicle, result, pygame, (330, 150, 500, 300))
            font = pygame.font.Font(None, 18)
            draw_text(window, font, "3D MODEL  |  arrows rotate  |  TAB returns", (346, 465), (118, 190, 201), pygame)
        pygame.display.flip()
        clock.tick(30)
    pygame.quit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Orbital Ember screening.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--description", help="Apply explicit values from a plain-language spacecraft description")
    parser.add_argument("--qwen-explain", action="store_true", help="Ask a local Qwen/Ollama endpoint to explain the Python result")
    parser.add_argument("--qwen-endpoint", default="http://localhost:11434/api/generate")
    parser.add_argument("--qwen-model", default="qwen3:0.6b")
    parser.add_argument("--visualize", action="store_true")
    args = parser.parse_args()
    vehicle = load_json(args.input)
    if args.description:
        vehicle = interpret_description(args.description, vehicle)
        result = analyze_vehicle(vehicle)
        save_result(result, args.output)
    else:
        result = run_screening(args.input, args.output)
    if args.qwen_explain:
        result["ai_explanation"] = explain_result(result, args.qwen_endpoint, args.qwen_model)
        save_result(result, args.output)
    print(f"Wrote {len(result['findings'])} screening findings to {args.output}")
    if args.visualize:
        launch_visualizer(vehicle, args.output)


if __name__ == "__main__":
    main()
