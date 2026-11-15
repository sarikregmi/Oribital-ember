import asyncio
import json
from pathlib import Path

from app.models import Investigation
from app.psi import _FileTableParser, _LinkParser, _extract_file_links
from app import psi_archive as archive


def _record(identifier: str) -> Investigation:
    return Investigation(
        id=identifier, name=f"NASA PSI {identifier}", description="NASA PSI record",
        domain="flammability", gravity=["microgravity"], fuels=[], conditions=[],
        measurements=[], hardware=[], source_url=f"https://psi.nasa.gov/physci/repo/data/investigations/{identifier}",
    )


class FakeProvider:
    def __init__(self, records):
        self.records = records
        self.checked = []
        self.headers = {"User-Agent": "test"}
        self.last_catalog_complete = True
        self.last_catalog_total = len(records)

    async def fetch_investigations(self):
        return self.records

    async def fetch_investigation_details(self, record):
        self.checked.append(record.id)
        return record, []


def test_psi_archive_stores_real_catalogue_records_and_exact_quota(tmp_path):
    provider = FakeProvider([_record("PSI-1"), _record("PSI-2")])
    result = asyncio.run(archive.sync_psi_archive(provider, directory=tmp_path, full=True))
    assert result["catalog_count"] == 2
    assert result["files_downloaded"] == 0
    assert archive.PSI_QUOTA_BYTES == 12_000_000_000
    assert [r.id for r in archive.get_archive_catalog(tmp_path)] == ["PSI-1", "PSI-2"]
    assert archive.archive_status(tmp_path)["investigations"] == 2


def test_psi_runtime_sync_rotates_through_records_instead_of_repeating_first_page(tmp_path):
    provider = FakeProvider([_record(f"PSI-{n}") for n in range(1, 6)])
    asyncio.run(archive.sync_psi_archive(provider, directory=tmp_path, investigation_limit=2, file_limit=0))
    asyncio.run(archive.sync_psi_archive(provider, directory=tmp_path, investigation_limit=2, file_limit=0))
    assert provider.checked == ["PSI-1", "PSI-2", "PSI-3", "PSI-4"]


def test_psi_archive_manifest_is_written_atomically(tmp_path):
    provider = FakeProvider([_record("PSI-9")])
    asyncio.run(archive.sync_psi_archive(provider, directory=tmp_path, full=True))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["provider"] == "NASA Physical Sciences Informatics"
    assert manifest["investigations"]["PSI-9"]["record"]["id"] == "PSI-9"
    assert not (tmp_path / "manifest.json.tmp").exists()


def test_psi_file_parser_finds_direct_pdf_and_view_content_row_links():
    html = '''
    <table>
      <tr><td>PSI-98_Science Documents_SAFFIRE Strategy.pdf</td>
          <td><a href="/physci/repo/file/content?id=123">View Content</a></td></tr>
      <tr><td>PSI-98_Raw Data_results.csv</td>
          <td><a href="https://psi.nasa.gov/download/results.csv">results.csv</a></td></tr>
    </table>
    <a href="https://psi.nasa.gov/files/guide.pdf">Download guide</a>
    '''
    parser = _LinkParser()
    parser.feed(html)
    files = _extract_file_links(html, parser, "PSI-98")
    names = {item["name"] for item in files}
    assert any(name.endswith("SAFFIRE Strategy.pdf") for name in names)
    assert any(name.endswith("results.csv") for name in names)
    assert any(name == "Download guide" for name in names)
    assert all(item["investigation_id"] == "PSI-98" for item in files)


def test_psi_quota_eviction_removes_file_bytes_but_preserves_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "PSI_QUOTA_BYTES", 7)
    files = tmp_path / "files"
    files.mkdir()
    first = files / "old.pdf"
    second = files / "new.csv"
    first.write_bytes(b"old")
    second.write_bytes(b"new")
    manifest = {"files": {
        "old": {"path": "files/old.pdf", "downloaded_at": "2025-01-01T00:00:00+00:00", "name": "old.pdf"},
        "new": {"path": "files/new.csv", "downloaded_at": "2026-01-01T00:00:00+00:00", "name": "new.csv"},
    }}
    archive._evict_oldest(tmp_path, manifest, 4)
    assert not first.exists()
    assert second.exists()
    assert manifest["files"]["old"]["path"] is None
    assert manifest["files"]["old"]["name"] == "old.pdf"


def test_newer_build_snapshot_is_copied_into_existing_runtime_cache(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    runtime = tmp_path / "runtime"
    (bundle / "files" / "PSI-8").mkdir(parents=True)
    (bundle / "files" / "PSI-8" / "paper.pdf").write_bytes(b"%PDF bundled")
    bundle_manifest = {
        "schema": 1, "provider": "NASA Physical Sciences Informatics",
        "source_url": "https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation",
        "updated_at": "2026-11-14T00:00:00+00:00", "catalog_checked_at": "2026-11-14T00:00:00+00:00",
        "catalog_count": 1, "investigations": {"PSI-8": {"record": _record("PSI-8").model_dump()}},
        "files": {"a" * 64: {"name": "paper.pdf", "path": "files/PSI-8/paper.pdf", "url": "https://psi.nasa.gov/paper.pdf", "size_bytes": 12}},
    }
    (bundle / "manifest.json").write_text(json.dumps(bundle_manifest))
    runtime.mkdir()
    (runtime / "manifest.json").write_text(json.dumps({"schema": 1, "provider": "NASA PSI", "updated_at": "2025-01-01", "catalog_checked_at": "2025-01-01", "investigations": {}, "files": {}}))
    monkeypatch.setattr(archive, "BUNDLE_DIR", bundle)
    monkeypatch.setattr(archive, "RUNTIME_DIR", runtime)
    archive.seed_runtime_from_bundle()
    assert (runtime / "files" / "PSI-8" / "paper.pdf").read_bytes() == b"%PDF bundled"
    assert [item.id for item in archive.get_archive_catalog(runtime)] == ["PSI-8"]


def test_completed_catalog_scan_removes_investigations_nasa_no_longer_lists(tmp_path):
    old_file = tmp_path / "files" / "PSI-OLD" / "old.pdf"
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old")
    manifest = archive._empty_manifest()
    manifest["investigations"]["PSI-OLD"] = {"record": _record("PSI-OLD").model_dump()}
    manifest["files"]["b" * 64] = {"investigation_id": "PSI-OLD", "path": "files/PSI-OLD/old.pdf", "url": "https://psi.nasa.gov/old.pdf", "name": "old.pdf"}
    archive._write_manifest(tmp_path, manifest)
    provider = FakeProvider([_record("PSI-NEW")])
    provider.last_catalog_complete = True
    asyncio.run(archive.sync_psi_archive(provider, directory=tmp_path, full=True))
    updated = archive.get_archive_manifest(tmp_path)
    assert "PSI-OLD" not in updated["investigations"]
    assert "b" * 64 not in updated["files"]
    assert not old_file.exists()


def test_incomplete_live_scan_preserves_existing_complete_snapshot(tmp_path):
    manifest = archive._empty_manifest()
    manifest["investigations"]["PSI-OLD"] = {"record": _record("PSI-OLD").model_dump()}
    archive._write_manifest(tmp_path, manifest)

    class IncompleteProvider(FakeProvider):
        def __init__(self, records):
            super().__init__(records)
            self.last_catalog_complete = False
            self.last_catalog_total = 133

    provider = IncompleteProvider([_record("PSI-PAGE-ONE")])
    result = asyncio.run(archive.sync_psi_archive(provider, directory=tmp_path, full=False))
    assert result["status"] == "incomplete"
    assert result["catalog_found_count"] == 1
    assert [item.id for item in archive.get_archive_catalog(tmp_path)] == ["PSI-OLD"]
    assert provider.checked == []


def test_nasa_elasticsearch_catalogue_response_is_unwrapped_and_normalized():
    from app.psi import _json_total, _walk_json_records, normalize_record

    payload = {
        "hits": {
            "total": {"value": 133, "relation": "eq"},
            "hits": [{
                "_id": "JMlqm5kBuqYijXJPQ3tv",
                "_source": {
                    "Accession": "PSI-117",
                    "Title": "Cool Flame Dynamics",
                    "Objectives": "Study cool flames in microgravity.",
                    "Approach": "A three-dimensional CFD analysis.",
                    "Keywords": "Cool Flames     Droplet combustion     FLEX",
                    "Research Area": "Combustion Science",
                    "SubResearch Area": "Droplet",
                    "Project Type": "Ground Investigation",
                    "Experiment Hardware": {"Name": "FLEX", "Link": ""},
                },
            }],
        }
    }

    records = list(_walk_json_records(payload))
    assert _json_total(payload) == 133
    assert len(records) == 1
    record = normalize_record(records[0])
    assert record.id == "PSI-117"
    assert record.name == "Cool Flame Dynamics"
    assert "Study cool flames" in record.description
    assert "three-dimensional CFD" in record.description
    assert record.hardware == ["FLEX"]
    assert "Combustion Science" in record.keywords
    assert record.source_url.endswith("/PSI-117")
    assert record.gravity == ["microgravity"]


def test_nasa_elasticsearch_total_accepts_integer_and_missing_total():
    from app.psi import _json_total

    assert _json_total({"hits": {"total": 133, "hits": []}}) == 133
    assert _json_total({"hits": {"hits": []}}) is None


def test_psi_provider_uses_nasa_from_size_pagination_and_verifies_total(monkeypatch):
    import app.psi as psi

    requests = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get(self, url, params=None):
            params = dict(params or {})
            requests.append((url, params))
            offset = int(params.get("from", 0))
            size = int(params.get("size", 25))
            total = 133
            hits = []
            for number in range(offset, min(offset + size, total)):
                accession = f"PSI-{number + 1}"
                hits.append({"_id": f"doc-{number}", "_source": {
                    "Accession": accession,
                    "Title": f"Investigation {number + 1}",
                    "Objectives": "A microgravity investigation.",
                    "Research Area": "Combustion Science",
                }})
            return FakeResponse({"hits": {"total": {"value": total}, "hits": hits}})

    monkeypatch.setattr(psi.httpx, "AsyncClient", FakeClient)
    provider = psi.PSIProvider()
    records = asyncio.run(provider.fetch_investigations())

    assert len(records) == 133
    assert provider.last_catalog_total == 133
    assert provider.last_catalog_complete is True
    assert [int(params.get("from", 0)) for _, params in requests] == [0, 25, 50, 75, 100, 125]
    assert all(int(params.get("size", 25)) == 25 for _, params in requests)
    assert records[0].id == "PSI-1"
    assert records[-1].id == "PSI-133"
