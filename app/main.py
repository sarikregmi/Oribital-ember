from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ai import ask_question, explain_investigation
from .catalog import NASA_PSI_SOURCE, get_catalog, get_live_catalog, set_live_catalog, set_bundled_catalog, catalog_source
from .psi import PSIProvider
from .psi_archive import archive_status, get_archive_catalog, get_archive_manifest, list_archive_files, resolve_archive_file, seed_runtime_from_bundle, sync_psi_archive
from .models import AskRequest, AskResponse, ExplainOptions, ExplanationResponse, InvestigationResult, ResearchSource, SearchResponse, StartupResourcesResponse
from .ranking import rank_investigations
from .resource_store import download_sources, load_saved_resource_sources, list_downloaded_resources, get_downloaded_resource, store_uploaded_resource
from .dataset_analysis import analyze_dataset
from .nasa_sync import discover_nasa_sources


# Resolve bundled frontend files from the application package, not the shell's cwd.
STATIC_DIR = Path(__file__).resolve().parent / "static"
STARTUP_QUERY = "NASA spacecraft fire combustion microgravity 0g"
_startup_resources: StartupResourcesResponse | None = None


app = FastAPI(
    title="Orbital Ember API",
    version="0.1.0",
    description="Grounded search and fire-safety interpretation for NASA PSI combustion investigations.",
)

# Desktop shells and local Node frontends can call the API without proxy setup.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the bundled HTML interface from the same local process as the API.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    # A single local origin makes the app easy to package in a desktop shell.
    return FileResponse(STATIC_DIR / "index.html")


@app.on_event("startup")
async def load_live_psi_catalog() -> None:
    """Load the bundled PSI snapshot first, then hydrate a small update batch."""
    runtime = seed_runtime_from_bundle()
    set_bundled_catalog(get_archive_catalog(runtime))
    try:
        await sync_psi_archive(directory=runtime, full=False, investigation_limit=2, file_limit=5)
        set_live_catalog(get_archive_catalog(runtime))
    except Exception:
        # Offline startup remains usable from the build-time bundled snapshot.
        set_live_catalog([])


@app.get("/health")
def health() -> dict[str, str | int]:
    records = get_catalog()
    return {"status": "ok", "catalog": catalog_source(), "records": len(records), "source": NASA_PSI_SOURCE}


@app.post("/api/v1/investigations/sync")
async def sync_psi_catalog():
    """Refresh PSI metadata and download the next bounded file batch."""
    try:
        runtime = seed_runtime_from_bundle()
        result = await sync_psi_archive(directory=runtime, full=False, investigation_limit=5, file_limit=20)
        set_live_catalog(get_archive_catalog(runtime))
        return result
    except Exception as exc:
        return {"status": "unavailable", "count": len(get_catalog()), "detail": str(exc)[:300],
                "storage": archive_status()}


@app.get("/api/v1/psi/archive")
def psi_archive():
    return {"status": "ready" if get_catalog() else "unavailable", "storage": archive_status(),
            "files": list_archive_files()}


@app.get("/api/v1/psi/files/{file_id}/download")
def download_psi_file(file_id: str):
    import re
    manifest = get_archive_manifest()
    if not re.fullmatch(r"[a-f0-9]{64}", file_id):
        raise HTTPException(status_code=404, detail="PSI file not found")
    record = manifest.get("files", {}).get(file_id)
    if not record or not record.get("path"):
        raise HTTPException(status_code=404, detail="PSI file is listed but not downloaded")
    root = seed_runtime_from_bundle()
    path = resolve_archive_file(root, record["path"])
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="PSI file not downloaded")
    return FileResponse(path, filename=record.get("name") or path.name)


@app.post("/api/v1/resources/bootstrap", response_model=StartupResourcesResponse)
async def bootstrap_resources() -> StartupResourcesResponse:
    """Collect scoped fire-research resources once for this app process."""
    global _startup_resources
    if _startup_resources is not None:
        return _startup_resources
    # Only actual downloadable files discovered through NASA dataset APIs enter
    # the downloaded-data panel. Catalog pages, image results and web links are
    # not dataset files and must not be presented as downloaded records.
    nasa_catalogs = await discover_nasa_sources()
    sources = [*nasa_catalogs.get("psi", []), *nasa_catalogs.get("osdr", [])]
    saved_resources = await download_sources(sources)
    _startup_resources = StartupResourcesResponse(
        status="ready",
        query=STARTUP_QUERY,
        sources_found=len(sources),
        saved_resources=saved_resources,
    )
    return _startup_resources


@app.post("/api/v1/resources/sync")
async def sync_nasa_resources():
    """Discover and download small public NASA PSI/OSDR datasets through official APIs."""
    catalogs = await discover_nasa_sources()
    discovered = [*catalogs.get("psi", []), *catalogs.get("osdr", [])]
    saved_paths = await download_sources(discovered)
    return {
        "status": "completed",
        "providers": {
            "NASA PSI public S3 API": len(catalogs.get("psi", [])),
            "NASA OSDR REST API": len(catalogs.get("osdr", [])),
        },
        "discovered_count": len(discovered),
        "new_download_count": len(saved_paths),
        "resources": list_downloaded_resources(),
        "notice": "Only public files with supported tabular/archive extensions and a listed size no greater than 25 MB are downloaded. NASA PSI and NASA OSDR are distinct repositories; this does not imply that every catalog investigation has public files in these endpoints.",
    }


@app.get("/api/v1/investigations", response_model=SearchResponse)
def search_investigations(
    q: str = Query(default="", description="Terms such as smoke, suppression, oxygen, or habitat."),
    domain: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> SearchResponse:
    # Search uses live PSI records, falling back only to the bundled PSI snapshot.
    catalog = get_catalog()
    if domain:
        catalog = [item for item in catalog if item.domain == domain]
    ranked = rank_investigations(catalog, q)
    return SearchResponse(query=q, total=len(ranked), results=ranked[:limit])


@app.get("/api/v1/resources")
def saved_resources():
    """Return verified local download records, separate from the fixed investigation catalog."""
    return list_downloaded_resources()


@app.post("/api/v1/resources/import")
async def import_nasa_resource(
    file: UploadFile = File(...),
    source_url: str = Form(...),
    title: str = Form(default=""),
):
    """Import a dataset downloaded manually from the NASA PSI file browser."""
    content = await file.read(25_000_001)
    if len(content) > 25_000_000:
        raise HTTPException(status_code=413, detail="Upload is limited to 25 MB")
    try:
        record = store_uploaded_resource(file.filename or "dataset.csv", content, title or file.filename or "NASA dataset", source_url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return record


@app.get("/api/v1/resources/{resource_id}/download")
def download_resource(resource_id: str):
    """Serve only a file resolved from the managed resource index."""
    record = get_downloaded_resource(resource_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Downloaded resource not found")
    item, path = record
    return FileResponse(path, filename=item.filename, media_type="application/octet-stream")


@app.get("/api/v1/resources/{resource_id}/analysis")
def analyze_downloaded_resource(resource_id: str):
    """Compute descriptive statistics for a downloaded CSV, TSV, JSON or JSONL file."""
    record = get_downloaded_resource(resource_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Downloaded resource not found")
    item, path = record
    if not item.analysis_supported:
        raise HTTPException(status_code=415, detail="This file type is stored for reference but is not a supported tabular dataset")
    try:
        return {
            "resource_id": item.id, "title": item.title, "source_url": item.url,
            "file_name": item.filename, "file_size_bytes": item.size_bytes,
            "analysis": analyze_dataset(path),
        }
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=415, detail="Dataset must be UTF-8 encoded") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/v1/investigations/{investigation_id}", response_model=InvestigationResult)
def get_investigation(investigation_id: str) -> InvestigationResult:
    results = rank_investigations(get_catalog())
    for result in results:
        if result.id.lower() == investigation_id.lower():
            return result
    raise HTTPException(status_code=404, detail="Investigation not found")


@app.post("/api/v1/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    """Answer a main-menu question using local evidence before external search."""
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="Question cannot be empty")
    return await ask_question(
        request.question,
        get_catalog(),
        request.allow_external_search or request.include_nasa_search or request.include_web_search,
        request.scenario,
        request.include_nasa_search,
        request.include_web_search,
    )


@app.post("/api/v1/investigations/{investigation_id}/explain", response_model=ExplanationResponse)
async def explain(
    investigation_id: str,
    options: ExplainOptions | None = None,
) -> ExplanationResponse:
    # Resolve the record first so the AI never receives an unknown identifier.
    investigation = next(
        (item for item in get_catalog() if item.id.lower() == investigation_id.lower()),
        None,
    )
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return await explain_investigation(investigation, options)


@app.post("/api/v1/investigations/{investigation_id}/explain-file", response_model=ExplanationResponse)
async def explain_file(
    investigation_id: str,
    file: UploadFile = File(...),
    question: str = Query(default="Explain the important fire-safety findings in this file."),
    include_nasa_search: bool = Query(default=False),
    include_web_search: bool = Query(default=False),
) -> ExplanationResponse:
    """Explain a user-provided local text file without storing it on the server."""
    # Resolve the record before reading the upload so unknown IDs fail cheaply.
    investigation = next(
        (item for item in get_catalog() if item.id.lower() == investigation_id.lower()),
        None,
    )
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    # Limit file reads so a mistaken upload cannot consume the desktop app's memory.
    content = await file.read(1_000_001)
    if len(content) > 1_000_000:
        raise HTTPException(status_code=413, detail="File is limited to 1 MB")
    try:
        file_context = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=415, detail="Use a UTF-8 text, CSV, JSON, or Markdown file") from error

    options = ExplainOptions(
        question=question,
        include_nasa_search=include_nasa_search,
        include_web_search=include_web_search,
    )
    return await explain_investigation(investigation, options, file_context)
