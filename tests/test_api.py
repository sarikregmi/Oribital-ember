import json

from fastapi.testclient import TestClient

from app.models import ResearchSource
from app.main import app
from app.psi import normalize_record
from app import research
from app.ai import _is_fire_research_question
from app.resource_store import MAX_RESOURCE_BYTES, _is_safe_remote_url, load_saved_resource_sources


client = TestClient(app)


def test_health_reports_seed_catalog():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_startup_resource_bootstrap_is_scoped(monkeypatch):
    async def fake_search(_: str) -> list[ResearchSource]:
        return []

    async def fake_download(_: list[ResearchSource]) -> list[str]:
        return ["startup.resource"]

    monkeypatch.setattr("app.main.search_nasa", fake_search)
    monkeypatch.setattr("app.main.search_web", fake_search)
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


def test_temporary_friend_ui_is_available_but_separate():
    response = client.get("/temp-ui/")
    assert response.status_code == 200
    assert "Synthetic-data demo" in response.text


def test_fire_safety_search_prioritizes_suppression():
    response = client.get("/api/v1/investigations", params={"q": "suppression"})
    assert response.status_code == 200
    assert response.json()["results"][0]["id"] == "FLEX"


def test_saved_resources_endpoint_returns_downloaded_records_only():
    response = client.get("/api/v1/resources")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_main_menu_ask_uses_local_catalog_first():
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


def test_resource_download_limit_is_one_gigabyte():
    assert MAX_RESOURCE_BYTES == 1_000_000_000


def test_resource_downloader_rejects_private_destinations():
    assert not _is_safe_remote_url("http://127.0.0.1/private")
    assert not _is_safe_remote_url("http://localhost/private")


def test_downloaded_resource_index_seeds_local_source_records(monkeypatch, tmp_path):
    import app.resource_store as resource_store
    index_path = tmp_path / "index.json"
    monkeypatch.setattr(resource_store, "INDEX_PATH", index_path)
    index_path.write_text(json.dumps({
        "https://nasa.gov/fire": {
            "path": str(tmp_path / "fire.resource"),
            "title": "NASA fire study",
            "snippet": "Saved fire research",
            "source_type": "nasa",
        },
    }), encoding="utf-8")
    assert load_saved_resource_sources()[0].title == "NASA fire study"


def test_explanation_is_grounded_and_has_limitations():
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
    response = client.post(
        "/api/v1/investigations/BASS/explain-file",
        files={"file": ("notes.txt", b"oxygen concentration was elevated", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["detailed_analysis"][-1].endswith("yes.")


def test_file_explanation_rejects_files_over_one_megabyte():
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
