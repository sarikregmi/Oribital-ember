import json

from fastapi.testclient import TestClient

from app.models import ResearchSource
from app.main import app
from app.psi import normalize_record
from app import research
from app.ai import _is_fire_research_question
from app.resource_store import MAX_RESOURCE_BYTES, _is_safe_remote_url, load_saved_resource_sources, list_downloaded_resources, get_downloaded_resource


client = TestClient(app)


def _install_test_catalog():
    from app.catalog import set_live_catalog
    from app.models import Investigation
    set_live_catalog([
        Investigation(id="FLEX", name="Flame Extinguishment Experiment", description="Tests droplet flame extinction and suppression using gas dilution.", domain="suppression", gravity=["microgravity"], fuels=["liquid fuel droplets"], conditions=["carbon dioxide dilution", "helium dilution"], measurements=["extinction diameter", "burning rate"], hardware=["Combustion Integrated Rack"], source_url="https://psi.nasa.gov/physci/repo/data/investigations/FLEX", keywords=["suppression", "extinguishment"]),
        Investigation(id="BASS", name="Burning and Suppression of Solids", description="Studies ignition, flame spread, and suppression of solid materials in reduced gravity.", domain="flammability", gravity=["microgravity", "normal gravity"], fuels=["fabrics", "plastics"], conditions=["elevated oxygen"], measurements=["flame spread", "ignition"], hardware=["Microgravity Science Glovebox"], source_url="https://psi.nasa.gov/physci/repo/data/investigations/BASS", keywords=["flammability", "fire safety"]),
    ])


def test_health_reports_seed_catalog():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_startup_resource_bootstrap_is_scoped(monkeypatch):
    async def fake_discover():
        return {"psi": [], "osdr": []}

    async def fake_download(_: list[ResearchSource]) -> list[str]:
        return ["startup.resource"]

    monkeypatch.setattr("app.main.discover_nasa_sources", fake_discover)
    monkeypatch.setattr("app.main.download_sources", fake_download)
    import app.main as main_module
    main_module._startup_resources = None
    response = client.post("/api/v1/resources/bootstrap")
    assert response.status_code == 200
    assert response.json()["query"] == "NASA spacecraft fire combustion microgravity 0g"


def test_frontend_is_served_by_local_app():
    response = client.get("/")
    assert response.status_code == 200
    assert "Orbital Ember" in response.text


def test_frontend_exposes_main_menu_ask_ai():
    response = client.get("/")
    assert "Ask AI" in response.text
    assert "question" in response.text
    assert "Custom scenario" in response.text
    assert "Search data" in response.text
    assert "Evidence" in response.text


def test_frontend_does_not_depend_on_current_working_directory(monkeypatch):
    monkeypatch.chdir("/tmp")
    response = client.get("/")
    assert response.status_code == 200
    assert "Orbital Ember" in response.text


def test_temporary_synthetic_ui_is_removed():
    assert client.get("/temp-ui/").status_code == 404
    assert client.get("/temp-ui").status_code == 404


def test_investigation_search_does_not_present_seed_examples_as_live_records():
    from app.catalog import set_live_catalog
    set_live_catalog([])
    response = client.get("/api/v1/investigations", params={"q": "suppression"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_saved_resources_endpoint_returns_downloaded_records_only():
    response = client.get("/api/v1/resources")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_main_menu_ask_uses_local_catalog_first():
    _install_test_catalog()
    response = client.post(
        "/api/v1/ask",
        json={
            "question": "How does suppression work?",
            "scenario": {"oxygen_percent": 30, "gravity_g": 0.16},
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["search_path"] == "local"
    assert body["matched_investigations"][0]["id"] == "FLEX"
    assert body["scenario"]["oxygen_percent"] == 30
    assert body["needs_external_search"] is False


def test_main_menu_ask_can_stay_offline_when_no_local_match():
    response = client.post(
        "/api/v1/ask",
        json={"question": "quantum propulsion history", "allow_external_search": False},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["search_path"] == "local"
    assert body["matched_investigations"] == []
    assert body["needs_external_search"] is True


def test_main_menu_ask_does_not_use_incidental_fire_word_match():
    response = client.post(
        "/api/v1/ask",
        json={"question": "why fire occur in space", "allow_external_search": False},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["matched_investigations"] == []


def test_main_menu_ask_adds_nasa_and_web_sources_when_local_misses(monkeypatch):
    async def fake_nasa_search(_: str) -> list[ResearchSource]:
        return [ResearchSource(title="NASA result", url="https://nasa.gov", snippet="NASA context", source_type="nasa")]

    async def fake_web_search(_: str) -> list[ResearchSource]:
        return [ResearchSource(title="Web result", url="https://example.com", snippet="Web context", source_type="web")]

    monkeypatch.setattr("app.ai.search_nasa", fake_nasa_search)
    monkeypatch.setattr("app.ai.search_web", fake_web_search)
    response = client.post(
        "/api/v1/ask",
        json={
            "question": "quantum propulsion history",
            "allow_external_search": True,
            "include_nasa_search": True,
            "include_web_search": True,
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["search_path"] == "local+nasa-web"
    assert {source["source_type"] for source in body["sources"]} == {"nasa", "web"}
    assert body["needs_external_search"] is False


def test_research_sources_are_saved_and_reused(monkeypatch, tmp_path):
    cache_path = tmp_path / "research_cache.json"
    monkeypatch.setattr(research, "CACHE_PATH", cache_path)
    saved = [ResearchSource(title="NASA fire study", url="https://nasa.gov/fire", snippet="saved", source_type="nasa")]
    research.save_cached_sources("microgravity fire", saved)
    loaded = research.load_cached_sources("microgravity fire safety")
    assert loaded[0].title == "NASA fire study"


def test_resource_collection_is_limited_to_fire_research_topics():
    assert _is_fire_research_question("why does combustion behave differently at 0g")
    assert _is_fire_research_question("spacecraft smoke detection")
    assert not _is_fire_research_question("unrelated astronomy history")


def test_resource_download_limit_is_25_megabytes():
    assert MAX_RESOURCE_BYTES == 25_000_000


def test_resource_downloader_rejects_private_destinations():
    assert not _is_safe_remote_url("http://127.0.0.1/private")
    assert not _is_safe_remote_url("http://localhost/private")


def test_downloaded_resource_index_seeds_local_source_records(monkeypatch, tmp_path):
    import app.resource_store as resource_store
    index_path = tmp_path / "index.json"
    monkeypatch.setattr(resource_store, "RESOURCE_DIR", tmp_path.resolve())
    monkeypatch.setattr(resource_store, "INDEX_PATH", index_path)
    (tmp_path / "fire.csv").write_text("time,temperature\n0,20\n", encoding="utf-8")
    index_path.write_text(json.dumps({
        "https://nasa.gov/fire": {
            "path": str(tmp_path / "fire.csv"),
            "title": "NASA fire study",
            "snippet": "Saved fire research",
            "source_type": "nasa",
        },
    }), encoding="utf-8")
    assert load_saved_resource_sources()[0].title == "NASA fire study"


def test_explanation_is_grounded_and_has_limitations():
    _install_test_catalog()
    response = client.post(
        "/api/v1/investigations/BASS/explain",
        json={"question": "How does elevated oxygen change material risk?"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["ai_mode"] in {"grounded-heuristic", "local-llm"}
    assert body["limitations"]
    assert body["detailed_analysis"]
    assert body["recommendations"]
    assert body["sources"][0]["source_type"] == "local"
    assert "elevated oxygen" in body["detailed_analysis"][2]
    assert body["direct_answer"]
    assert not body["direct_answer"].startswith("In plain language:")
    assert body["follow_up_questions"]
    assert body["recommended_data_sources"]


def test_file_explanation_accepts_local_text_without_storing_it():
    _install_test_catalog()
    response = client.post(
        "/api/v1/investigations/BASS/explain-file",
        files={"file": ("notes.txt", b"oxygen concentration was elevated", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["detailed_analysis"][-1].endswith("yes.")


def test_file_explanation_rejects_files_over_one_megabyte():
    _install_test_catalog()
    response = client.post(
        "/api/v1/investigations/BASS/explain-file",
        files={"file": ("large.txt", b"x" * 1_000_001, "text/plain")},
    )
    assert response.status_code == 413


def test_psi_export_fields_normalize_to_stable_schema():
    investigation = normalize_record({
        "identifier": "PSI-TEST",
        "title": "Test investigation",
        "summary": "A PSI export record.",
        "domain": "detection",
        "gravity": ["microgravity"],
        "url": "https://psi.nasa.gov/test",
    })
    assert investigation.id == "PSI-TEST"
    assert investigation.name == "Test investigation"
    assert investigation.domain == "detection"


def test_catalog_endpoint_is_live_only_and_not_a_five_record_fallback():
    from app.catalog import set_live_catalog
    set_live_catalog([])
    response = client.get("/api/v1/investigations")
    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_downloaded_resource_record_contains_local_file_metadata(monkeypatch, tmp_path):
    import app.resource_store as store
    monkeypatch.setattr(store, "RESOURCE_DIR", tmp_path.resolve())
    monkeypatch.setattr(store, "INDEX_PATH", tmp_path / "index.json")
    data_file = tmp_path / "sample.csv"
    data_file.write_text("time,temperature\n0,20\n1,22\n2,24\n", encoding="utf-8")
    store._write_index({"https://nasa.gov/sample.csv": {
        "id": "sample123", "path": str(data_file), "title": "Sample measurements",
        "snippet": "Test dataset", "source_type": "nasa", "filename": "sample.csv"
    }})
    records = store.list_downloaded_resources()
    assert len(records) == 1
    assert records[0].id == "sample123"
    assert records[0].analysis_supported is True
    assert store.get_downloaded_resource("sample123")[1] == data_file


def test_resource_index_cannot_escape_managed_directory(monkeypatch, tmp_path):
    import app.resource_store as store
    outside = tmp_path / "secret.csv"
    outside.write_text("secret", encoding="utf-8")
    managed = tmp_path / "resources"
    managed.mkdir()
    monkeypatch.setattr(store, "RESOURCE_DIR", managed.resolve())
    monkeypatch.setattr(store, "INDEX_PATH", managed / "index.json")
    store._write_index({"https://nasa.gov/x": {"id": "escape", "path": str(outside), "title": "bad"}})
    assert store.list_downloaded_resources() == []
    assert store.get_downloaded_resource("escape") is None


def test_csv_dataset_analysis_returns_statistics_and_series(tmp_path):
    from app.dataset_analysis import analyze_dataset
    path = tmp_path / "measurements.csv"
    path.write_text("time,temp,mode\n0,20,A\n1,22,A\n2,24,B\n", encoding="utf-8")
    result = analyze_dataset(path)
    assert result["row_count"] == 3
    temp = next(column for column in result["columns"] if column["name"] == "temp")
    assert temp["mean"] == 22
    assert temp["min"] == 20 and temp["max"] == 24
    assert temp["series"] == [20, 22, 24]


def test_json_dataset_analysis_flattens_records(tmp_path):
    from app.dataset_analysis import analyze_dataset
    path = tmp_path / "measurements.json"
    path.write_text(json.dumps({"data": [{"oxygen": 20.9}, {"oxygen": 21.1}]}), encoding="utf-8")
    result = analyze_dataset(path)
    assert result["format"] == "JSON"
    assert result["row_count"] == 2
    assert result["columns"][0]["mean"] == 21


def test_dataset_analysis_rejects_oversized_files(tmp_path):
    from app.dataset_analysis import analyze_dataset, MAX_ANALYSIS_BYTES
    path = tmp_path / "large.csv"
    path.write_bytes(b"x" * (MAX_ANALYSIS_BYTES + 1))
    try:
        analyze_dataset(path)
        assert False, "Expected size limit rejection"
    except ValueError as error:
        assert "10 MB" in str(error)


def test_resource_download_and_analysis_api_routes(monkeypatch, tmp_path):
    import app.resource_store as store
    monkeypatch.setattr(store, "RESOURCE_DIR", tmp_path.resolve())
    monkeypatch.setattr(store, "INDEX_PATH", tmp_path / "index.json")
    dataset = tmp_path / "real-sample.csv"
    dataset.write_text("elapsed_s,temperature_c\n0,20\n1,22\n2,24\n", encoding="utf-8")
    store._write_index({"https://data.nasa.gov/real-sample.csv": {
        "id": "api-sample", "path": str(dataset), "title": "NASA sample data",
        "snippet": "Downloaded CSV test", "source_type": "nasa", "filename": dataset.name,
    }})
    downloaded = client.get("/api/v1/resources/api-sample/download")
    assert downloaded.status_code == 200
    assert downloaded.content == dataset.read_bytes()
    analysis = client.get("/api/v1/resources/api-sample/analysis")
    assert analysis.status_code == 200
    assert analysis.json()["analysis"]["row_count"] == 3
    assert analysis.json()["analysis"]["columns"][1]["mean"] == 22


def test_analysis_endpoint_rejects_reference_only_download(monkeypatch, tmp_path):
    import app.resource_store as store
    monkeypatch.setattr(store, "RESOURCE_DIR", tmp_path.resolve())
    monkeypatch.setattr(store, "INDEX_PATH", tmp_path / "index.json")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 placeholder")
    store._write_index({"https://nasa.gov/paper.pdf": {
        "id": "pdf-only", "path": str(pdf), "title": "NASA paper",
        "snippet": "Reference", "source_type": "nasa", "filename": pdf.name,
    }})
    response = client.get("/api/v1/resources/pdf-only/analysis")
    assert response.status_code == 415


def test_frontend_replaces_synthetic_demo_with_download_records():
    response = client.get("/")
    assert "DOWNLOADED DATA RECORDS" not in response.text  # Rendered only when real records load.
    assert "saved-resources" in response.text
    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "Analyze dataset" in script.text
    assert "/api/v1/resources/" in script.text
    assert "Synthetic-data demo" not in script.text


def test_zip_dataset_analysis_reads_tabular_members_without_extracting(tmp_path):
    import zipfile
    from app.dataset_analysis import analyze_dataset
    archive_path = tmp_path / "psi-export.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("experiment/measurements.csv", "time_s,flame_temp_k\n0,900\n1,920\n")
        archive.writestr("notes/readme.txt", "metadata notes")
    result = analyze_dataset(archive_path)
    assert result["format"] == "ZIP"
    assert result["file_count"] == 1
    assert result["datasets"][0]["file_name"] == "measurements.csv"
    assert result["datasets"][0]["analysis"]["columns"][1]["mean"] == 910


def test_zip_dataset_analysis_rejects_archive_without_tabular_files(tmp_path):
    import zipfile
    from app.dataset_analysis import analyze_dataset
    archive_path = tmp_path / "docs.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("readme.txt", "no data")
    try:
        analyze_dataset(archive_path)
        assert False, "Expected unsupported archive rejection"
    except ValueError as error:
        assert "no supported" in str(error)


def test_manual_nasa_dataset_import_creates_download_record(monkeypatch, tmp_path):
    import app.resource_store as store
    monkeypatch.setattr(store, "RESOURCE_DIR", tmp_path.resolve())
    monkeypatch.setattr(store, "INDEX_PATH", tmp_path / "index.json")
    response = client.post(
        "/api/v1/resources/import",
        data={"source_url": "https://psi.nasa.gov/physci/repo/investigation/FLEX", "title": "FLEX sample"},
        files={"file": ("flex.csv", b"time_s,diameter_mm\n0,2.1\n1,1.8\n", "text/csv")},
    )
    assert response.status_code == 200
    record = response.json()
    assert record["title"] == "FLEX sample"
    assert record["analysis_supported"] is True
    assert client.get(f"/api/v1/resources/{record['id']}/analysis").status_code == 200


def test_manual_dataset_import_rejects_non_nasa_source(monkeypatch, tmp_path):
    import app.resource_store as store
    monkeypatch.setattr(store, "RESOURCE_DIR", tmp_path.resolve())
    monkeypatch.setattr(store, "INDEX_PATH", tmp_path / "index.json")
    response = client.post(
        "/api/v1/resources/import",
        data={"source_url": "https://example.com/not-nasa", "title": "Untrusted"},
        files={"file": ("data.csv", b"x\n1\n", "text/csv")},
    )
    assert response.status_code == 422


def test_resource_index_ignores_malformed_entries(monkeypatch, tmp_path):
    import app.resource_store as store
    monkeypatch.setattr(store, "RESOURCE_DIR", tmp_path.resolve())
    monkeypatch.setattr(store, "INDEX_PATH", tmp_path / "index.json")
    (tmp_path / "index.json").write_text(json.dumps({"bad-record": "not-an-object"}), encoding="utf-8")
    assert store.list_downloaded_resources() == []


def test_resource_downloader_rejects_unusual_ports_and_credentials():
    assert not _is_safe_remote_url("https://user:pass@nasa.gov/data.csv")
    assert not _is_safe_remote_url("https://nasa.gov:8443/data.csv")
    assert not _is_safe_remote_url("file:///etc/passwd")


def test_nasa_psi_s3_listing_filters_to_small_supported_public_objects():
    from app.nasa_sync import parse_s3_listing

    xml = '''<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
      <Contents><Key>OASIS/measurements.csv</Key><Size>2048</Size></Contents>
      <Contents><Key>DSI/readme.pdf</Key><Size>1024</Size></Contents>
      <Contents><Key>OASIS/large.json</Key><Size>30000000</Size></Contents>
      <Contents><Key>OASIS/data.json</Key><Size>512</Size></Contents>
    </ListBucketResult>'''
    results = parse_s3_listing(xml)
    assert [item.title for item in results] == ["measurements.csv", "data.json"]
    assert all(item.provider == "NASA PSI public S3 bucket" for item in results)
    assert all(item.url.startswith("https://nasa-psi.s3.us-west-2.amazonaws.com/") for item in results)


def test_osdr_search_extracts_accessions_and_downloadable_file_metadata():
    from app.nasa_sync import extract_osd_study_ids, parse_osdr_files

    search_payload = {"studies": {"OSD-137": {"title": "Spaceflight study"}, "OSD-4": {"title": "Another study"}}}
    assert extract_osd_study_ids(search_payload) == ["137", "4"]
    files_payload = {"studies": {"OSD-137": {"study_files": [
        {"file_name": "measurements.csv", "file_size": 2048, "remote_url": "/geode-py/data/measurements.csv"},
        {"file_name": "large.csv", "file_size": 30000000, "remote_url": "/geode-py/data/large.csv"},
    ]}}}
    files = parse_osdr_files(files_payload)
    assert len(files) == 1
    assert files[0].url == "https://osdr.nasa.gov/geode-py/data/measurements.csv"
    assert files[0].provider == "NASA OSDR API"


def test_nasa_sync_endpoint_uses_discovered_official_resources(monkeypatch):
    source = ResearchSource(
        title="NASA PSI data.csv", url="https://nasa-psi.s3.us-west-2.amazonaws.com/data.csv",
        snippet="real object", source_type="nasa", provider="NASA PSI public S3 bucket",
    )

    async def fake_discover():
        return {"psi": [source], "osdr": []}

    async def fake_download(sources):
        assert sources == [source]
        return ["/tmp/fake.csv"]

    monkeypatch.setattr("app.main.discover_nasa_sources", fake_discover)
    monkeypatch.setattr("app.main.download_sources", fake_download)
    response = client.post("/api/v1/resources/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["discovered_count"] == 1
    assert body["new_download_count"] == 1
    assert body["providers"]["NASA PSI public S3 API"] == 1


def test_search_data_ui_exposes_incremental_psi_archive_sync():
    response = client.get("/")
    assert response.status_code == 200
    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "Download next PSI update batch" in script.text
    assert "/api/v1/investigations/sync" in script.text
    assert "12 GB PSI-only limit" in script.text


def test_resource_downloader_rejects_private_redirect_targets(monkeypatch, tmp_path):
    import httpx
    import app.resource_store as store

    monkeypatch.setattr(store, "RESOURCE_DIR", tmp_path.resolve())
    monkeypatch.setattr(store, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr(store, "_is_safe_remote_url", lambda url: url.startswith("https://public.example/"))

    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class MockClient:
        def __init__(self, **kwargs):
            self.client = real_client(transport=transport, **kwargs)

        async def __aenter__(self):
            await self.client.__aenter__()
            return self.client

        async def __aexit__(self, *args):
            return await self.client.__aexit__(*args)

    monkeypatch.setattr(store.httpx, "AsyncClient", MockClient)

    import asyncio
    source = ResearchSource(title="redirect.csv", url="https://public.example/file.csv", snippet="test", source_type="nasa")
    saved = asyncio.run(store.download_sources([source]))
    assert saved == []
    assert json.loads((tmp_path / "index.json").read_text()) == {}
    assert list(tmp_path.glob("*.part")) == []


def test_psi_html_catalog_parser_extracts_investigation_records():
    from app.psi import _InvestigationLinks, _from_catalog_link
    from app.catalog import get_catalog, set_live_catalog
    from app.models import Investigation

    parser = _InvestigationLinks()
    parser.feed('''<div><a href="/physci/repo/data/investigations/PSI-159">Advanced Combustion via Microgravity Experiments / Cool Flames Investigation</a></div>''')
    assert parser.links == [('/physci/repo/data/investigations/PSI-159', 'Advanced Combustion via Microgravity Experiments / Cool Flames Investigation')]
    record = _from_catalog_link('PSI-159', parser.links[0][1], 'https://psi.nasa.gov/physci/repo/data/investigations/PSI-159')
    assert record.id == 'PSI-159'
    assert record.domain == 'flammability'


def test_live_catalog_replaces_bundled_fallback():
    from app.catalog import get_catalog, set_live_catalog
    from app.models import Investigation
    record = Investigation(id='PSI-999', name='NASA test investigation', description='From PSI', domain='fundamental', gravity=[], fuels=[], conditions=[], measurements=[], hardware=[], source_url='https://psi.nasa.gov/')
    set_live_catalog([record])
    assert [item.id for item in get_catalog()] == ['PSI-999']


def test_psi_parser_accepts_current_repository_record_link_variants():
    from app.psi import _InvestigationLinks, _from_catalog_link
    parser = _InvestigationLinks()
    parser.feed('<a href="/physci/repo/data/PSI-117">Effect of External Thermo-Convective Perturbation on Cool Flame Dynamics</a>')
    assert parser.links[0][0] == "/physci/repo/data/PSI-117"
    record = _from_catalog_link("PSI-117", parser.links[0][1], "https://psi.nasa.gov/physci/repo/data/PSI-117")
    assert record.id == "PSI-117"
    assert "Cool Flame" in record.name


def test_downloaded_data_panel_excludes_non_dataset_references(monkeypatch, tmp_path):
    import app.resource_store as store
    monkeypatch.setattr(store, "RESOURCE_DIR", tmp_path.resolve())
    monkeypatch.setattr(store, "INDEX_PATH", tmp_path / "index.json")
    csv_path = tmp_path / "actual.csv"
    pdf_path = tmp_path / "reference.pdf"
    csv_path.write_text("x,y\n1,2\n", encoding="utf-8")
    pdf_path.write_bytes(b"%PDF-reference")
    store._write_index({
        "https://nasa.gov/actual.csv": {"id": "csv1", "path": str(csv_path), "title": "Actual dataset", "filename": csv_path.name, "source_type": "nasa"},
        "https://nasa.gov/reference.pdf": {"id": "pdf1", "path": str(pdf_path), "title": "Reference PDF", "filename": pdf_path.name, "source_type": "nasa"},
    })
    records = store.list_downloaded_resources()
    assert [item.id for item in records] == ["csv1"]


def test_psi_provider_walks_result_pages(monkeypatch):
    import asyncio
    import app.psi as psi

    pages = {
        0: '<a href="/physci/repo/data/PSI-101">First NASA investigation</a><a href="/physci/repo/data/PSI-102">Second NASA investigation</a>',
        1: '<a href="/physci/repo/data/PSI-103">Third NASA investigation</a>',
        2: '<div>No more results</div>',
    }

    class FakeResponse:
        headers = {"content-type": "text/html"}
        def __init__(self, text): self.text = text
        def raise_for_status(self): pass

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            from urllib.parse import urlparse, parse_qs
            page = int(parse_qs(urlparse(url).query).get("page", ["0"])[0])
            return FakeResponse(pages.get(page, ""))

    monkeypatch.setattr(psi.httpx, "AsyncClient", FakeClient)
    records = asyncio.run(psi.PSIProvider().fetch_investigations())
    assert [record.id for record in records] == ["PSI-101", "PSI-102", "PSI-103"]
