"""Projects: a named input (uploaded file, drawn area, or the sample) with its history of analysis runs.

Stored in SQLite plus files on disk under CANOPY_DATA_DIR. Run outputs live in their own directories
so every run stays reproducible and downloadable. On hosts with ephemeral disks (Render free tier)
set CANOPY_DATA_DIR to a persistent volume, or projects vanish on redeploy.
"""

from __future__ import annotations

import json
import secrets
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .pipeline import ingest
from .pipeline.geo import shape_to_geojson

SAMPLE_DIR = Path(__file__).resolve().parent / "samples" / "sample"
SAMPLE_AOI = Path(__file__).resolve().parent / "samples" / "sample_aoi.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  updated_utc TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_name TEXT,
  source_bytes INTEGER,
  source_sha256 TEXT NOT NULL,
  aoi_json TEXT,
  params_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  number INTEGER NOT NULL,
  created_utc TEXT NOT NULL,
  finished_utc TEXT,
  status TEXT NOT NULL,
  params_json TEXT NOT NULL,
  summary_json TEXT,
  error_code TEXT,
  error_message TEXT
);
CREATE INDEX IF NOT EXISTS runs_project ON runs(project_id, number);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# The summary fields a project card and the runs table need; the full result stays in result.json.
SUMMARY_KEYS = (
    "aoi_area_ha",
    "canopy_area_ha",
    "canopy_cover_pct",
    "crown_count",
    "crown_count_range",
    "confidence_breakdown",
    "rejected_regions",
    "height_available",
    "height_measured_count",
    "median_crown_diameter_m",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProjectStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.projects_dir = data_dir / "projects"
        self.runs_dir = data_dir / "runs"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(data_dir / "canopy.db", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._db.commit()

    # ---- helpers --------------------------------------------------------------------------------

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple = ()) -> None:
        with self._lock:
            self._db.execute(sql, args)
            self._db.commit()

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    @staticmethod
    def _run_out(r: sqlite3.Row) -> dict:
        return {
            "id": r["id"],
            "project_id": r["project_id"],
            "number": r["number"],
            "created_utc": r["created_utc"],
            "finished_utc": r["finished_utc"],
            "status": r["status"],
            "params": json.loads(r["params_json"]),
            "summary": json.loads(r["summary_json"]) if r["summary_json"] else None,
            "error_code": r["error_code"],
            "error_message": r["error_message"],
        }

    def _project_out(self, p: sqlite3.Row, runs: list[dict] | None = None) -> dict:
        if runs is None:
            runs = [self._run_out(r) for r in self._q("SELECT * FROM runs WHERE project_id=? ORDER BY number", (p["id"],))]
        latest_ok = next((r for r in reversed(runs) if r["status"] == "succeeded"), None)
        return {
            "id": p["id"],
            "name": p["name"],
            "created_utc": p["created_utc"],
            "updated_utc": p["updated_utc"],
            "source": {
                "kind": p["source_kind"],
                "name": p["source_name"],
                "bytes": p["source_bytes"],
                "sha256": p["source_sha256"],
            },
            "aoi": json.loads(p["aoi_json"]) if p["aoi_json"] else None,
            "params": json.loads(p["params_json"]),
            "run_count": len(runs),
            "latest_run": runs[-1] if runs else None,
            "latest_succeeded_run_id": latest_ok["id"] if latest_ok else None,
            "latest_summary": latest_ok["summary"] if latest_ok else None,
        }

    # ---- projects -------------------------------------------------------------------------------

    def list(self) -> list[dict]:
        rows = self._q("SELECT * FROM projects ORDER BY updated_utc DESC")
        return [self._project_out(p) for p in rows]

    def get(self, project_id: str) -> dict | None:
        rows = self._q("SELECT * FROM projects WHERE id=?", (project_id,))
        if not rows:
            return None
        runs = self.runs(project_id)
        return {**self._project_out(rows[0], runs), "runs": runs}

    def create(self, name: str, parsed: ingest.ParsedInput, raw: bytes | None, params: dict) -> dict:
        project_id = "p_" + secrets.token_hex(5)
        folder = self.projects_dir / project_id
        folder.mkdir(parents=True)
        source_name = parsed.filename
        if raw is not None and parsed.filename:
            # Keep the original bytes: every run re-parses them, so nothing is derived twice.
            (folder / "source").mkdir()
            (folder / "source" / Path(parsed.filename).name).write_bytes(raw)
            if parsed.selection is not None:
                (folder / "source" / ".canopy-selection.json").write_text(json.dumps(parsed.selection), encoding="utf-8")
        aoi_json = None
        if parsed.aoi_lonlat is not None:
            aoi_json = json.dumps(shape_to_geojson(parsed.aoi_lonlat))
        ts = now_utc()
        self._x(
            "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                project_id,
                name.strip()[:120] or "Untitled project",
                ts,
                ts,
                parsed.kind,
                source_name,
                len(raw) if raw is not None else None,
                parsed.sha256,
                aoi_json,
                json.dumps(params, sort_keys=True),
            ),
        )
        return self.get(project_id)  # type: ignore[return-value]

    def rename(self, project_id: str, name: str) -> dict | None:
        self._x("UPDATE projects SET name=?, updated_utc=? WHERE id=?", (name.strip()[:120] or "Untitled project", now_utc(), project_id))
        return self.get(project_id)

    def delete(self, project_id: str) -> bool:
        runs = self._q("SELECT id FROM runs WHERE project_id=?", (project_id,))
        rows = self._q("SELECT id FROM projects WHERE id=?", (project_id,))
        if not rows:
            return False
        self._x("DELETE FROM runs WHERE project_id=?", (project_id,))
        self._x("DELETE FROM projects WHERE id=?", (project_id,))
        for r in runs:
            shutil.rmtree(self.run_dir(r["id"]), ignore_errors=True)
        shutil.rmtree(self.projects_dir / project_id, ignore_errors=True)
        return True

    def parsed_input(self, project_id: str) -> ingest.ParsedInput:
        """Rebuilds the input exactly as it was uploaded or drawn."""
        p = self._q("SELECT * FROM projects WHERE id=?", (project_id,))[0]
        source = self.projects_dir / project_id / "source"
        if p["source_name"] and source.exists():
            path = source / Path(p["source_name"]).name
            selection_path = source / ".canopy-selection.json"
            selection = json.loads(selection_path.read_text(encoding="utf-8")) if selection_path.exists() else None
            return ingest.parse_upload(p["source_name"], path.read_bytes(), selection)
        geom = ingest.parse_geojson(json.loads(p["aoi_json"]))
        return ingest.ParsedInput(p["source_kind"], geom, None, p["source_sha256"], None)

    # ---- runs -----------------------------------------------------------------------------------

    def runs(self, project_id: str) -> list[dict]:
        return [self._run_out(r) for r in self._q("SELECT * FROM runs WHERE project_id=? ORDER BY number", (project_id,))]

    def run(self, run_id: str) -> dict | None:
        rows = self._q("SELECT * FROM runs WHERE id=?", (run_id,))
        return self._run_out(rows[0]) if rows else None

    def add_run(self, project_id: str, run_id: str, params: dict, status: str = "queued") -> dict:
        number = (self._q("SELECT COALESCE(MAX(number),0) AS n FROM runs WHERE project_id=?", (project_id,))[0]["n"]) + 1
        ts = now_utc()
        self._x(
            "INSERT INTO runs (id, project_id, number, created_utc, status, params_json) VALUES (?,?,?,?,?,?)",
            (run_id, project_id, number, ts, status, json.dumps(params, sort_keys=True)),
        )
        self._x("UPDATE projects SET updated_utc=?, params_json=? WHERE id=?", (ts, json.dumps(params, sort_keys=True), project_id))
        return self.run(run_id)  # type: ignore[return-value]

    def set_run_status(self, run_id: str, status: str) -> None:
        self._x("UPDATE runs SET status=? WHERE id=?", (status, run_id))

    def finish_run(self, run_id: str, result: dict | None, error_code: str | None = None, error_message: str | None = None) -> None:
        summary = {k: result["summary"].get(k) for k in SUMMARY_KEYS} if result else None
        status = "succeeded" if result else "failed"
        ts = now_utc()
        self._x(
            "UPDATE runs SET status=?, finished_utc=?, summary_json=?, error_code=?, error_message=? WHERE id=?",
            (status, ts, json.dumps(summary) if summary else None, error_code, error_message, run_id),
        )
        rows = self._q("SELECT project_id FROM runs WHERE id=?", (run_id,))
        if rows:
            self._x("UPDATE projects SET updated_utc=? WHERE id=?", (ts, rows[0]["project_id"]))

    def load_result(self, run_id: str) -> tuple[dict, Path] | None:
        d = self.run_dir(run_id)
        f = d / "result.json"
        if not f.exists():
            return None
        return json.loads(f.read_text(encoding="utf-8")), d

    def mark_interrupted(self) -> None:
        """Runs that were in flight when the server stopped cannot resume; say so instead of spinning forever."""
        self._x(
            "UPDATE runs SET status='failed', error_code='interrupted', "
            "error_message='The server restarted while this run was in progress. Start it again.' "
            "WHERE status IN ('queued','running')"
        )

    # ---- sample ---------------------------------------------------------------------------------

    def seed_sample_once(self) -> None:
        """First start only: a ready-made project from the committed sample, so the app never opens empty."""
        if self._q("SELECT value FROM meta WHERE key='sample_seeded'") or not (SAMPLE_DIR / "result.json").exists():
            return
        spec = json.loads(SAMPLE_AOI.read_text(encoding="utf-8"))
        geom = ingest.parse_geojson(spec["aoi"])
        parsed = ingest.ParsedInput(
            "drawn", geom, None, ingest.sha256_bytes(json.dumps(spec["aoi"], sort_keys=True).encode()), None
        )
        project = self.create("Monfragüe dehesa (sample)", parsed, None, spec["params"])
        run_id = "j_" + secrets.token_hex(4)
        self.add_run(project["id"], run_id, spec["params"], status="running")
        dest = self.run_dir(run_id)
        shutil.copytree(SAMPLE_DIR, dest)
        # The committed sample is addressed as job "sample"; re-address its URLs to this run.
        result_path = dest / "result.json"
        text = result_path.read_text(encoding="utf-8").replace("/api/jobs/sample/", f"/api/jobs/{run_id}/")
        result = json.loads(text)
        result["job_id"] = run_id
        result_path.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        self.finish_run(run_id, result)
        self._x("INSERT OR REPLACE INTO meta VALUES ('sample_seeded', ?)", (now_utc(),))


store = ProjectStore(config.DATA_DIR)
