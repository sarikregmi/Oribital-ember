# Orbital Ember

Orbital Ember is an AI-assisted spacecraft fire-safety screening and visualization prototype.

## Boundaries

This project is not a rocket flight simulator, CFD solver, certification tool, or engineering safety guarantee. It does not invent ignition temperatures, predict ignition, or claim that a component will definitely catch fire.

- Python performs transparent screening calculations.
- NASA research can provide evidence references after qualified review.
- AI explains supplied results in plain language.
- User-described, estimated, unknown, and screening-only values are labeled.

## Run

From the project root:

```powershell
python Backend/emu.py
python Backend/emu.py --visualize
python Backend/emu.py --description "It is about 3 meters long and weighs about 500 kg with plastic insulation."
python Backend/emu.py --qwen-explain
python -m unittest discover -s tests -v
```

The default analysis reads `data/vehicle.json` and writes `output/analysis_result.json`.

## Complete desktop workflow

The Pygame console provides:

- Editable vehicle name, environment, and oxygen fraction fields.
- Scenario presets for ground, ascent, space internal fire, external fire, entry, and engine-region fire.
- Run, clear, and exit controls plus Escape-to-exit navigation.
- A findings inspector showing location, severity, certainty, evidence, and affected components.
- Persistent output when Run is pressed.

The screening checks for an active user-described fire scenario, oxygen fraction above a terrestrial reference value, unspecified materials, and a bounded entry-speed screening index. These are review prompts, not physical predictions.

The editor does not save changes back into `data/vehicle.json`; it keeps edits in the current session and writes the analysis result to `output/analysis_result.json`.

## Plain-language input

The `--description` option is a deterministic fallback adapter. It extracts only explicit dimensions, mass, nose angle, and broad material categories. It does not identify an exact polymer, infer missing physics, or replace a Qwen model. Any extracted broad category remains labeled `user-described`, and unspecified exact material remains `unknown`.

## Real integrations

- Press `Tab` in the visualizer to open the 3D spacecraft projection. Use arrow keys to rotate it. This is a software 3D projection rendered from the configured geometry, not a flight simulator.
- `--qwen-explain` calls the local Ollama-compatible endpoint `http://localhost:11434/api/generate` with model `qwen3:0.6b`. Qwen receives the Python result and may explain it; it is not allowed to calculate or add claims. Without a running endpoint, the result records `unavailable`.
- Planned entry cases use a Sutton-Graves-style heat-flux screening equation with explicit reference-atmosphere assumptions in `entry_thermal_screening`. It is an estimate, not CFD, certification, ablation modeling, or a damage threshold.
- NASA evidence records now carry source type, URL, and verification status. The BASS and SAFFIRE entries use NASA discovery records where a stable direct page could not be verified; users must select and verify the primary report before engineering use.
