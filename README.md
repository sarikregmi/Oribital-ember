# Orbital Ember

Orbital Ember is a local research dashboard for NASA Physical Sciences Informatics (PSI) investigations relevant to spacecraft fire safety. Its investigation catalogue and document archive are sourced from the official NASA PSI repository; the app does not invent substitute investigation records.

## Build the NASA PSI archive first

The release build is intentionally a two-stage process. Run it on an internet-connected build machine:

```bash
python -m venv .venv
source .venv/bin/activate                 # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev,desktop,build]'
python -m playwright install chromium
python scripts/build_psi_archive.py
```

`build_psi_archive.py` reads the investigation search page you specified:

`https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation`

It follows investigation result pages, opens each investigation record, discovers linked PDFs and other files, and downloads them sequentially into `app/bundled_data/psi/`. The PSI archive has its own hard ceiling of **12,000,000,000 bytes (12 GB)**. The quota includes PSI files only; it does not include the executable, application assets, or other research sources.

The builder requires at least 100 records by default and compares the fetched count with the total shown by NASA when available. This prevents a first-page-only scrape from being packaged as the complete index. If the real catalogue has fewer than 100 records in the future, lower the threshold with `--minimum-records N` after verifying the NASA page count. It stops on an incomplete result; `--allow-incomplete` is a development-only override. Zero-record snapshots are refused unless `--allow-empty` is explicitly supplied for testing.

Then package the executable:

```bash
python scripts/build_executable.py
```

Or run both stages in order:

```bash
python scripts/build_release.py
```

PyInstaller creates an `onedir` build in `dist/OrbitalEmber/`. The PSI snapshot is bundled alongside the application. Build on the operating system you intend to distribute (Windows on Windows, Linux on Linux); the executable is not cross-compiled.

## Run from source

```bash
python -m pip install -e '.[dev,desktop]'
python desktop.py
```

For browser mode:

```bash
python desktop.py --web
```

Open `http://127.0.0.1:8000`.

## PSI archive and incremental updates

- At launch, the app loads the packaged PSI snapshot first, so the investigation index is available offline.
- It then checks the live PSI catalogue and hydrates a small rotating batch of new/changed investigation files. It does not attempt to download the entire repository at every launch.
- Use **Refresh NASA index** to refresh catalogue metadata, or **Download next PSI update batch** to fetch the next set of files.
- The file index includes PDFs, datasets, reports, engineering documents and other PSI-linked files. A file is marked downloaded only after its bytes are saved and verified as non-empty.
- File contents are cached under `~/.orbital_ember/psi/` (override with `ORBITAL_EMBER_PSI_DIR`). The packaged snapshot remains unchanged.
- If the 12 GB PSI-only quota is reached, the oldest cached PSI file contents are evicted first. Their metadata and NASA source links remain in the index. The application never deletes non-PSI resources to satisfy this quota.
- The automatic per-file download ceiling is 1 GB. Larger files remain listed for manual retrieval; the app does not pretend to have downloaded them.

The PSI site does not currently expose a stable, documented public REST API for the entire investigation/file catalogue. The integration therefore reads the official public search and investigation pages, including their visible file links and embedded page data. If the search grid is client-rendered, the build tool can use Playwright's Chromium browser to read the rendered results (install it with `python -m playwright install chromium`). If NASA changes its page markup or blocks automated requests, the app keeps the bundled snapshot and reports the update failure rather than displaying fake records.

## Other research resources

Other manually imported or separately sourced datasets are stored under `~/.orbital_ember/resources/` and are independent of the PSI quota. PSI files are managed only by the PSI archive component.

## API

- `GET /health`
- `GET /api/v1/investigations?q=smoke`
- `GET /api/v1/investigations/{id}`
- `POST /api/v1/investigations/sync`
- `GET /api/v1/psi/archive`
- `GET /api/v1/psi/files/{sha256}/download`
- `POST /api/v1/ask`
- `POST /api/v1/investigations/{id}/explain`
- `GET /api/v1/resources` (separate non-PSI resource store)

## Tests

```bash
pytest -q
python -m compileall -q app scripts
node --check app/static/app.js
```

Tests use mocked NASA responses; a live PSI fetch must be verified on a network-connected build machine.
