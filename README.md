
Orbital Ember

AI-assisted fire-safety insights from NASA microgravity combustion research, built for the 2026 NASA Space Apps Challenge: "Flame in Freefall".

NASA's Physical Science Informatics (PSI) database holds decades of combustion experiments, but the volume makes it hard to find, compare and interpret. Orbital Ember is a local, web-based dashboard that searches, ranks and explains those investigations, with source links attached so every answer can be traced back to its provenance.

Status: hackathon prototype. Outputs are screening-level and for education only. Do not use them for real safety decisions without validation against primary NASA sources and review by qualified fire-safety engineers.

Download and run (Windows)

No Python or install needed.

Go to the Releases page of this repository and download the .zip file.
Extract (unzip) the whole zip. Don't run the exe from inside the zip.
Open the extracted folder. You will see the .exe file and a folder next to it.
Double-click the .exe to start Orbital Ember. Keep the exe and its folder together in the same place, because the app needs that folder to run.

The app opens in its own window.

Notes

If Windows SmartScreen says "Windows protected your PC", click More info, then Run anyway. This appears because the app is not code-signed.
The first run may take a few seconds to start.
An internet connection is only needed if you turn on NASA/web search. Local search works offline.
Optional AI summaries need Ollama installed and running. Without it the app still works.
Features
Ask AI: ask a fire-safety question. The app checks the local PSI catalog first, and only adds NASA and web sources if you allow external search.
Custom scenario: describe a scenario and get a grounded explanation.
Search data: ranked search over five seeded investigations, followed by every NASA/web resource that has actually been downloaded (shown separately so they aren't mistaken for investigations).
Evidence: source links for each result.
Investigation explanations: per-investigation summaries, plus upload of a UTF-8 text, CSV, JSON or Markdown file (max 1 MB, not stored) for the AI to explain.
Optional local LLM: if an Ollama server is running, it rewrites grounded summaries. Without it, the app falls back to deterministic grounded answers.
Desktop mode: run the same interface in a native window.
Seeded investigations
ID	Investigation
BASS	Burning and Suppression of Solids
FLEX	Flame Extinguishment Experiment
SAME	Smoke and Aerosol Measurement Experiment
ACME-CFI	Cool Flames Investigation
BRE	Burning Rate Emulator
Tech stack

Python 3.11+, FastAPI, Uvicorn, Pydantic v2, httpx, plain HTML/CSS/JavaScript frontend, optional Ollama, optional pywebview / PySide6 for desktop, pytest.

Project structure
Oribital-ember/
├── app/                    FastAPI application
│   ├── main.py             API routes and static file serving
│   ├── ai.py               Grounded answers and optional Ollama calls
│   ├── catalog.py          Seed investigation catalog
│   ├── ranking.py          Search ranking
│   ├── research.py         NASA and web source search, with caching
│   ├── resource_store.py   Downloads and indexes research resources
│   ├── psi.py              PSI record normalization
│   ├── models.py           Pydantic schemas
│   ├── desktop.py          PySide6 desktop shell
│   └── static/             Web UI (index.html, app.js, styles.css)
├── Backend/                Standalone spacecraft fire-safety screening emulator
├── data/                   Vehicle input and NASA source registry
├── json NASA EXPT/         Curated NASA fire-safety knowledge notes and JSON
├── output/                 Emulator output (analysis_result.json)
├── temp_ui/                Separate synthetic browser-only prototype
├── tests/                  pytest suite
├── desktop.py              Launcher (pywebview window or --web mode)
├── resources.md            Primary NASA PSI source links
└── instruction             Challenge brief and transcript
Build from source (developers)

Requires Python 3.11 or newer.

bash
git clone https://github.com/sarikregmi/Oribital-ember.git
cd Oribital-ember

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e .
Run the web app
bash
uvicorn app.main:app --reload

Open http://127.0.0.1:8000. Interactive API docs are at /docs.

Run the desktop app
bash
pip install -e ".[desktop]"
python desktop.py            # native window (pywebview)
python desktop.py --web      # server only, no window
python -m app.desktop        # PySide6 shell
Optional: local AI summaries
bash
ollama pull llama3.2:1b
Variable	Default	Purpose
OLLAMA_URL	http://127.0.0.1:11434	Ollama server
OLLAMA_MODEL	llama3.2:1b	Model used for summaries
PSI_API_URL	unset	Optional PSI data provider URL
ORBITAL_EMBER_RESOURCE_DIR	~/.orbital_ember/resources	Where downloaded resources are saved
ORBITAL_EMBER_CACHE	~/.orbital_ember/research_cache.json	Research search cache
API
Method	Endpoint	Description
GET	/health	Health check
GET	/api/v1/investigations	Search and rank investigations (q, domain, limit)
GET	/api/v1/investigations/{id}	Get one investigation
POST	/api/v1/investigations/{id}/explain	Grounded explanation
POST	/api/v1/investigations/{id}/explain-file	Explain an uploaded text file
POST	/api/v1/ask	Answer a question using local evidence first
POST	/api/v1/resources/bootstrap	Collect NASA/web fire-research resources once per process
GET	/api/v1/resources	List downloaded resources
Spacecraft screening emulator

Backend/ is a separate, transparent screening tool for spacecraft fire scenarios (ground, ascent, space internal fire, external fire, atmospheric entry, engine-region fire). Python does the calculations; an optional local Qwen model only explains the results.

bash
python Backend/emu.py                          # reads data/vehicle.json, writes output/analysis_result.json
python Backend/emu.py --description "..."      # apply values from a plain-language description
python Backend/emu.py --qwen-explain           # add a local Qwen/Ollama explanation
python Backend/emu.py --visualize              # Pygame 3D viewer (pip install pygame)
Temporary UI

temp_ui/ is a self-contained, browser-only prototype that trains a small neural network on synthetic data. It is served at /temp-ui/ for comparison only. See temp_ui/README.md.

Testing
bash
pip install -e ".[dev]"
pytest
Data and sources

Source links are in resources.md, including the NASA PSI repository and database tutorials. Catalog and knowledge-base records are curated metadata: verify the primary source before engineering use.

Limitations
The catalog is a small seed set, not the full PSI database (24 combustion investigations, about 12 TB).
There is currently no partial-gravity (Moon/Mars) combustion data in PSI.
AI summaries are grounded in the catalog but can still be wrong. Check cited sources.
Independent project. Not affiliated with or endorsed by NASA.
