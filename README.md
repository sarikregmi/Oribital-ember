# Orbital Ember

Orbital Ember is a local research dashboard for NASA Physical Sciences Informatics (PSI) investigations relevant to spacecraft fire safety. It keeps an offline copy of the PSI investigation index and a bounded set of PSI files, and it can write short AI summaries using a small language model that runs entirely on your own computer.

It does not invent investigation records. Everything in the index comes from NASA's public PSI repository.

## Download and run (Windows, no installation)

Go to the **Releases** page and download all of these:

| File | What it contains |
|---|---|
| `OrbitalEmber-<version>-app.zip` | The program (`OrbitalEmber.exe`) and the bundled PSI snapshot |
| `OrbitalEmber-<version>-ollama-runtime.zip` | The Ollama runtime used for offline AI |
| `OrbitalEmber-<version>-model.zip` | The `llama3.2:1b` model |
| `SHA256SUMS.txt` | Checksums to verify your downloads |

1. Create a new empty folder, for example `C:\OrbitalEmber`.
2. Extract **all three ZIP files into that same folder**. They merge into one layout.
3. Run `OrbitalEmber.exe`.

```
OrbitalEmber\
  OrbitalEmber.exe        the application
  _internal\              application files (replaced on update)
  runtime\ollama\         Ollama runtime
  models\                 AI model
  data\psi\               PSI archive (created on first launch)
  data\resources\         other downloaded resources
```

Nothing is installed and nothing is written outside this folder. Delete the folder to remove the app.

To check that your copy works, run `OrbitalEmber.exe --selftest`. It starts the local server, starts the bundled Ollama, asks the model for a short reply, and prints the results. This works with the network disconnected.

### Updating

Replace only `OrbitalEmber.exe` and `_internal\`. Your `data\`, `models\` and `runtime\` folders are separate and are kept.

## Storage

| Area | Location | Limit |
|---|---|---|
| NASA PSI research data | `data\psi\` | **12 GB** (decimal, 12,000,000,000 bytes), PSI files only |
| AI model | `models\` | separate, not counted against the PSI limit |
| Ollama runtime | `runtime\ollama\` | separate |
| Application | `OrbitalEmber.exe`, `_internal\` | separate |
| Other resources | `data\resources\` | separate from the PSI limit |

When the PSI limit is reached, the oldest cached PSI file contents are removed first. Investigation metadata and NASA source links are never removed by this. Files larger than 1 GB are listed but not downloaded automatically.

**Important:** NASA's full PSI repository is far larger than 12 GB. The app always keeps the complete investigation index, but it can hold only part of the underlying data files.

## Offline AI

AI summaries use [Ollama](https://ollama.com) with the `llama3.2:1b` model, both bundled in the release.

- Ollama starts automatically the first time you ask for a summary and stops when you close the app.
- It listens on a private local port (11435) so it does not interfere with an Ollama you may already run.
- The app never downloads a model. If the model is missing it falls back to plain, source-grounded text.
- A 1B model is small and fast but limited. Treat summaries as a reading aid and check them against the NASA source.

The model is licensed separately by its publisher (Meta, under the Llama 3.2 Community License). Read that license before redistributing the model files.

## Automatic research updates

- At launch, the packaged PSI snapshot loads first, so the index works offline.
- The app then checks the live PSI catalogue. It refreshes metadata and downloads a small rotating batch of new or missing files. It does not re-download the whole repository on every launch.
- **Refresh NASA index** updates catalogue metadata. **Download next PSI update batch** fetches the next set of files.
- A refresh is only accepted if the catalogue count matches the total reported by NASA. A partial or failed fetch never replaces your existing snapshot.
- Files from NASA are checked to be real files (not error pages) and are saved only when complete.

## Run from source

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev,desktop,build]"
python launcher.py                 # opens the app on a free local port
```

For source runs, AI uses your own Ollama on `localhost:11434`. Install Ollama and run `ollama pull llama3.2:1b`. Data is kept in `~/.orbital_ember/`.

Run the tests:

```bash
python -m pytest
python -m unittest tests.test_portable_runtime
```

## Build the Windows release

Build on Windows. The executable cannot be built from Linux. You need Python 3.11+ and an internet connection.

```powershell
# 1. Build the PSI snapshot (can take hours; fills up to the 12 GB limit)
python -m playwright install chromium
python scripts/build_psi_archive.py

# 2. Build the app, fetch Ollama and the model, self-test, and create the release ZIPs
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -SkipPsi
```

The release ZIPs and `SHA256SUMS.txt` are written to `dist\release`.

Notes:

- `build_psi_archive.py` refuses to produce a snapshot if the catalogue count is zero, below the minimum, or does not match NASA's reported total.
- GitHub limits each release file to 2 GiB. If the app ZIP (which includes the PSI snapshot) is larger, split it into parts before uploading.
- Large files (PSI data, the model, the Ollama runtime) belong on the Releases page, not in the repository.

## API

- `GET /health`
- `GET /api/v1/investigations?q=smoke`
- `GET /api/v1/investigations/{id}`
- `POST /api/v1/investigations/sync`
- `GET /api/v1/psi/archive`
- `GET /api/v1/psi/files/{sha256}/download`
- `POST /api/v1/ask`
- `POST /api/v1/investigations/{id}/explain`
- `GET /api/v1/resources`

## Known limits

- NASA does not publish a stable, documented API for the full PSI catalogue. The app reads the public search service the PSI website uses. If NASA changes it, updates will report a failure and the app will keep the existing snapshot.
- The PSI archive is capped at 12 GB, so it holds the full index but only part of the data files.
- Interrupted file downloads are retried from the start rather than resumed.
- The app is for research reading and education. It is not a safety system.

## Data source

Investigation data is from NASA's Physical Sciences Informatics repository (https://psi.nasa.gov). This project is not affiliated with or endorsed by NASA.
