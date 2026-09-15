"""Project store: create, runs, rename, delete, restart handling and the one-time sample seed."""

import json

from app.pipeline import ingest
from app.projects import SAMPLE_DIR, ProjectStore

AOI = {"type": "Polygon", "coordinates": [[[-5.9505, 39.9295], [-5.9495, 39.9295], [-5.9495, 39.9303], [-5.9505, 39.9303], [-5.9505, 39.9295]]]}
PARAMS = {"min_crown_diameter_m": 3.0, "veg_index": "exg", "threshold_mode": "otsu", "threshold_manual": None, "tile_zoom": 18, "acquisition_datetime_utc": None, "enable_height": True}


def _drawn():
    geom = ingest.parse_geojson(AOI)
    return ingest.ParsedInput("drawn", geom, None, ingest.sha256_bytes(json.dumps(AOI).encode()), None)


def test_project_lifecycle(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("  North ridge  ", _drawn(), None, PARAMS)
    assert project["name"] == "North ridge"
    assert project["source"]["kind"] == "drawn"
    assert project["run_count"] == 0

    store.add_run(project["id"], "j_one", PARAMS)
    summary = {"summary": {"canopy_cover_pct": 21.5, "crown_count": 40, "crown_count_range": [35, 46], "extra": 1}}
    store.finish_run("j_one", summary)
    store.add_run(project["id"], "j_two", {**PARAMS, "min_crown_diameter_m": 4.0})
    store.finish_run("j_two", None, "tile_fetch_failed", "A tile could not be fetched.")

    got = store.get(project["id"])
    assert [r["number"] for r in got["runs"]] == [1, 2]
    assert got["latest_succeeded_run_id"] == "j_one"
    assert got["latest_summary"]["crown_count"] == 40
    assert "extra" not in got["latest_summary"]
    assert got["runs"][1]["status"] == "failed"
    assert got["params"]["min_crown_diameter_m"] == 4.0  # last-used parameters are remembered

    assert store.rename(project["id"], "Renamed")["name"] == "Renamed"
    assert store.delete(project["id"]) is True
    assert store.get(project["id"]) is None
    assert store.run("j_one") is None


def test_uploaded_source_is_reparsed_identically(tmp_path):
    store = ProjectStore(tmp_path)
    raw = json.dumps(AOI).encode()
    parsed = ingest.parse_upload("area.geojson", raw)
    project = store.create("From file", parsed, raw, PARAMS)
    again = store.parsed_input(project["id"])
    assert again.kind == "geojson"
    assert again.sha256 == parsed.sha256
    assert again.aoi_lonlat.equals(parsed.aoi_lonlat)


def test_interrupted_runs_are_marked_failed(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("P", _drawn(), None, PARAMS)
    store.add_run(project["id"], "j_live", PARAMS, status="running")
    store.mark_interrupted()
    run = store.run("j_live")
    assert run["status"] == "failed" and run["error_code"] == "interrupted"


def test_sample_seeds_once_and_is_readdressed(tmp_path):
    if not (SAMPLE_DIR / "result.json").exists():
        return
    store = ProjectStore(tmp_path)
    store.seed_sample_once()
    store.seed_sample_once()
    projects = store.list()
    assert len(projects) == 1
    run_id = projects[0]["latest_succeeded_run_id"]
    result, _ = store.load_result(run_id)
    assert result["job_id"] == run_id
    assert result["crowns_geojson_url"] == f"/api/jobs/{run_id}/crowns.geojson"
    # The seeded crowns are the committed sample, byte for byte.
    assert (tmp_path / "runs" / run_id / "crowns.geojson").read_bytes() == (SAMPLE_DIR / "crowns.geojson").read_bytes()
