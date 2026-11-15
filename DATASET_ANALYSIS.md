# NASA PSI archive and downloaded data

Orbital Ember has two independent stores:

1. **NASA PSI archive** — investigation metadata and PSI-linked files, including PDFs, raw data, reports, engineering documents and supporting files. This store alone has a **12,000,000,000-byte (12 GB)** quota.
2. **Other research resources** — manually imported or separately sourced research, stored outside the PSI archive. These do not count toward the PSI quota.

## Build-time snapshot

Before packaging an executable, run:

```bash
python scripts/build_psi_archive.py
```

The builder reads the official PSI investigation search page, follows result pages, opens investigation detail pages, extracts the available file links and downloads files sequentially into `app/bundled_data/psi/`. It stores a manifest containing the investigation metadata, file metadata, local relative paths, sizes and SHA-256 checksums. The build is stopped if PSI returns no investigation records; it does not substitute demo investigations.

Then create the executable folder:

```bash
python -m pip install -e '.[desktop,build]'
python scripts/build_executable.py
```

Or run both steps with `python scripts/build_release.py`. Build on the target OS. The bundled snapshot is included with the executable so the application can start offline.

## Runtime updates

- At startup, Orbital Ember loads the bundled PSI snapshot first.
- It checks the live PSI search catalogue and downloads only a small rotating batch of investigation files.
- **Refresh NASA index** refreshes investigation metadata. **Download next PSI update batch** advances the file-download queue.
- Old files no longer listed on a refreshed investigation page are removed from the local cache when the current file list is successfully discovered. Records removed from a completed, non-empty PSI catalogue scan are also removed from the active metadata index.
- When the 12 GB PSI-only limit is reached, the oldest PSI file contents are evicted. Investigation metadata and NASA source URLs remain available so files can be downloaded again later.
- Files larger than the 1 GB automatic per-file ceiling are not fetched automatically. They remain listed as not downloaded for manual retrieval.

On first launch, bundled PSI file bytes are moved into `~/.orbital_ember/psi/` (override with `ORBITAL_EMBER_PSI_DIR`) so the archive is not stored twice. If the install directory is read-only, the app falls back to copying. Runtime updates are written to the per-user cache.

## File analysis

CSV, TSV, JSON, JSONL and ZIP files can be analyzed with bounded descriptive statistics. PDFs and other supporting documents remain downloadable reference material; Orbital Ember does not pretend to analyze them as numerical tables. ZIP members are inspected in memory, not extracted to disk.

The analysis reports row/column counts, missing values, numeric min/max/mean/median, categorical frequencies, a small preview and simple within-column trend plots. These are descriptive computations, not validated physical models. The software does not infer units, experimental conditions, calibration, uncertainty, causality or safety thresholds. Consult the source documentation, DOI, data dictionary and experimental conditions before interpreting measurements.

## API

- `GET /api/v1/investigations?q=smoke`
- `GET /api/v1/psi/archive` — PSI-only storage usage and file queue
- `POST /api/v1/investigations/sync` — check PSI catalogue and download next batch
- `GET /api/v1/psi/files/{sha256}/download` — download a locally cached PSI file
- `GET /api/v1/resources` — separate non-PSI resource store
- `GET /api/v1/resources/{id}/analysis` — analyze supported tabular data
- `POST /api/v1/resources/import` — import an external research dataset with source URL

## Source and limitations

Source of truth:

`https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation`

NASA's PSI guide describes the search result list, page-size options (25, 50 or 100) and investigation detail navigation. Individual PSI pages expose metadata, publications, version history and file/document sections. NASA may change the UI markup; this integration therefore supports HTML links, embedded page data and sitemap fallback, but is not a claim of a stable PSI REST API. If the site changes or is unreachable, the bundled archive remains available and the app reports the update issue instead of fabricating records.

A live download of the full PSI archive must be performed on an internet-connected build machine. The current development environment has no DNS/network access to NASA, so this source package contains the archive manifest and builder but cannot truthfully claim to contain the full downloaded PSI dataset yet.
