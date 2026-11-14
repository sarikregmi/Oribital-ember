import asyncio
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .ai import RECOMMENDED_DATA_SOURCES, ask_question, explain_investigation
from .catalog import NASA_PSI_SOURCE, get_catalog
from .models import AskRequest, AskResponse, ExplainOptions, ExplanationResponse, InvestigationResult, ResearchSource, SearchResponse, StartupResourcesResponse
from .ranking import rank_investigations
from .research import search_nasa, search_web
from .resource_store import download_sources, load_saved_resource_sources


# Resolve bundled frontend files from the application package, not the shell's cwd.
STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMP_UI_DIR = Path(__file__).resolve().parent.parent / "temp_ui"
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
# Keep the friend's synthetic prototype available for temporary comparison only.
if TEMP_UI_DIR.exists():
    app.mount("/temp-ui", StaticFiles(directory=TEMP_UI_DIR, html=True), name="temp-ui")


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    # A single local origin makes the app easy to package in a desktop shell.
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/temp-ui", include_in_schema=False)
def temporary_ui_redirect() -> RedirectResponse:
    """Use a trailing slash so the prototype's relative CSS/JS paths resolve."""
    if not TEMP_UI_DIR.exists():
        raise HTTPException(status_code=404, detail="Temporary UI is not included in this build")
    return RedirectResponse("/temp-ui/")


@app.get("/health")
def health() -> dict[str, str]:
    # Keep health cheap so a desktop shell can poll it while starting up.
    return {"status": "ok", "catalog": "seed", "source": NASA_PSI_SOURCE}


@app.post("/api/v1/resources/bootstrap", response_model=StartupResourcesResponse)
async def bootstrap_resources() -> StartupResourcesResponse:
    """Collect scoped fire-research resources once for this app process."""
    global _startup_resources
    if _startup_resources is not None:
        return _startup_resources
    nasa_sources, web_sources = await asyncio.gather(
        search_nasa(STARTUP_QUERY),
        search_web(STARTUP_QUERY),
    )
    sources = [*RECOMMENDED_DATA_SOURCES, *nasa_sources, *web_sources]
    saved_resources = await download_sources(sources)
    _startup_resources = StartupResourcesResponse(
        status="ready",
        query=STARTUP_QUERY,
        sources_found=len(sources),
        saved_resources=saved_resources,
    )
    return _startup_resources


@app.get("/api/v1/investigations", response_model=SearchResponse)
def search_investigations(
    q: str = Query(default="", description="Terms such as smoke, suppression, oxygen, or habitat."),
    domain: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> SearchResponse:
    # Search stays synchronous and deterministic for predictable frontend state.
    catalog = get_catalog()
    if domain:
        catalog = [item for item in catalog if item.domain == domain]
    results = rank_investigations(catalog, q)[:limit]
    return SearchResponse(query=q, total=len(results), results=results)


@app.get("/api/v1/resources", response_model=list[ResearchSource])
def saved_resources() -> list[ResearchSource]:
    """Return downloaded sources without presenting them as investigations."""
    return load_saved_resource_sources()


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
