"""FastAPI app: routes, CORS, upload cap. Image processing never runs in a request handler."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from . import assistant, config, jobs
from .projects import store as projects
from .pipeline import LIMITATIONS_MD, STAGES, PipelineError, ingest
from .pipeline.validate import validate as run_validation
from .schemas import ChatIn, JobCreate, JobCreated, JobParams, JobStatusOut, ProjectCreate, ProjectRename, RunCreate, StageInfo, ValidateIn

SAMPLE_DIR = Path(__file__).resolve().parent / "samples" / "sample"
SAMPLE_ID = "sample"
_sample_cache: dict | None = None

ALLOWED_FILES = {
    "crowns.geojson": "application/geo+json",
    "rejected.geojson": "application/geo+json",
    "crowns.csv": "text/csv",
    "imagery.png": "image/png",
    "canopy_layer.png": "image/png",
    "canopy_mask.png": "image/png",
    "overlay.png": "image/png",
    "audit.zip": "application/zip",
    **{f"stage_{k}.png": "image/png" for k in ("index", "threshold", "mask", "detections", "markers", "segments", "crowns")},
}


class UploadLimitMiddleware:
    """Rejects oversized bodies before they are buffered: by Content-Length, and by counting streamed bytes."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        cl = headers.get(b"content-length")
        too_big = JSONResponse(
            {"error_code": "file_too_large", "error_message": "The upload is larger than the 100 MB limit."}, status_code=413
        )
        if cl is not None and cl.isdigit() and int(cl) > self.max_bytes + 1_000_000:
            return await too_big(scope, receive, send)
        seen = 0

        async def limited_receive():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_bytes + 1_000_000:
                    raise HTTPException(413, "The upload is larger than the 100 MB limit.")
            return msg

        return await self.app(scope, limited_receive, send)


app = FastAPI(title="CANOPY", version=config.APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)
app.add_middleware(UploadLimitMiddleware, max_bytes=config.MAX_UPLOAD_BYTES)


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error_code": code, "error_message": message}, status_code=status)


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": config.APP_VERSION}


@app.get("/api/limitations")
def limitations():
    return Response(LIMITATIONS_MD, media_type="text/markdown; charset=utf-8")


@app.post("/api/jobs", status_code=202, response_model=JobCreated)
async def create_job(request: Request):
    ctype = request.headers.get("content-type", "")
    try:
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            params = JobParams(**json.loads(form.get("params") or "{}"))
            aoi_raw = form.get("aoi")
            aoi_geom = ingest.parse_geojson(json.loads(aoi_raw)) if aoi_raw else None
            if upload is None or not hasattr(upload, "read"):
                if aoi_geom is None:
                    return _err(400, "no_input", "Please upload a file or draw an area.")
                parsed = ingest.ParsedInput("drawn", aoi_geom, None, ingest.sha256_bytes(aoi_raw.encode()), None)
            else:
                data = await upload.read()
                parsed = ingest.parse_upload(upload.filename or "upload", data)
                if parsed.kind == "geotiff" and aoi_geom is not None:
                    parsed.aoi_lonlat = aoi_geom
        else:
            body = JobCreate(**(await request.json()))
            params = body.params
            if body.aoi is None:
                return _err(400, "no_input", "Please upload a file or draw an area.")
            geom = ingest.parse_geojson(body.aoi)
            parsed = ingest.ParsedInput("drawn", geom, None, ingest.sha256_bytes(json.dumps(body.aoi, sort_keys=True).encode()), None)
        if parsed.aoi_lonlat is not None:
            ingest.validate_aoi(parsed.aoi_lonlat)
        if params.veg_index == "ndvi" and parsed.kind != "geotiff":
            return _err(400, "ndvi_unavailable", "NDVI needs a near-infrared band. Basemap imagery is RGB only; choose ExG or VARI.")
    except PipelineError as exc:
        return _err(422, exc.code, exc.message)
    except ValidationError as exc:
        return _err(422, "bad_params", f"Some parameters are out of range: {exc.errors()[0].get('msg')}")
    except (json.JSONDecodeError, ValueError) as exc:
        return _err(400, "bad_request", f"The request could not be read: {exc}")

    job = jobs.submit(parsed, params.model_dump())
    return JobCreated(job_id=job.job_id, status=job.status.value)


def _job_or_404(job_id: str) -> jobs.Job:
    job = jobs.store.get(job_id)
    if job is None:
        run = projects.run(job_id)
        if run is not None:
            # A finished project run from before a restart: rebuild enough of the job to report it.
            status = jobs.JobStatus(run["status"]) if run["status"] in ("succeeded", "failed") else jobs.JobStatus.failed
            return jobs.Job(job_id=job_id, status=status, message="Done" if status == jobs.JobStatus.succeeded else "Failed",
                            error_code=run["error_code"], error_message=run["error_message"], base_dir=projects.runs_dir)
        raise HTTPException(404, "Job not found. Jobs are kept in memory and are lost when the server restarts.")
    return job


@app.get("/api/jobs/{job_id}", response_model=JobStatusOut)
def job_status(job_id: str):
    job = _job_or_404(job_id)
    end = job.finished or time.time()
    stages = [StageInfo(name=n, label=l, seconds=job.stage_times.get(n)) for n, l in STAGES]
    return JobStatusOut(
        job_id=job.job_id,
        status=job.status.value,
        stage=job.stage,
        stage_index=job.stage_index,
        stage_total=len(STAGES),
        message=job.message,
        elapsed_s=round(end - (job.started or job.created), 1),
        stages=stages,
        error_code=job.error_code,
        error_message=job.error_message,
    )


def _load_sample() -> dict:
    global _sample_cache
    if _sample_cache is None:
        _sample_cache = json.loads((SAMPLE_DIR / "result.json").read_text(encoding="utf-8"))
    return _sample_cache


def _result(job_id: str) -> tuple[dict, Path]:
    if job_id == SAMPLE_ID:
        if not (SAMPLE_DIR / "result.json").exists():
            raise HTTPException(404, "The sample result has not been generated. Run scripts/build_sample.py.")
        return _load_sample(), SAMPLE_DIR
    stored = projects.load_result(job_id)
    if stored is not None:
        return stored
    job = _job_or_404(job_id)
    if job.status != jobs.JobStatus.succeeded or job.result is None:
        raise HTTPException(409, f"Job is {job.status.value}, no result yet.")
    return job.result, job.dir


@app.get("/api/sample")
def sample():
    return _result(SAMPLE_ID)[0]


@app.get("/api/jobs/{job_id}/result")
def job_result(job_id: str):
    return _result(job_id)[0]


@app.get("/api/jobs/{job_id}/{filename}")
def job_file(job_id: str, filename: str, download: bool = False):
    if filename not in ALLOWED_FILES:
        raise HTTPException(404, "Unknown file.")
    _, d = _result(job_id)
    path = d / filename
    if not path.exists():
        raise HTTPException(404, "File not found.")
    headers = {}
    # The map loads the PNG/GeoJSON inline; the download menu asks for ?download=1, because browsers
    # ignore <a download> across origins (Vercel frontend, Render API).
    if download or filename in ("audit.zip", "crowns.csv"):
        headers["Content-Disposition"] = f'attachment; filename="{job_id}_{filename}"'
    return FileResponse(path, media_type=ALLOWED_FILES[filename], headers=headers)


@app.post("/api/jobs/{job_id}/validate")
def job_validate(job_id: str, body: ValidateIn):
    result, d = _result(job_id)
    w, s, e, n = body.bbox
    if not (w < e and s < n):
        return _err(422, "bad_bbox", "The validation rectangle is invalid. Please draw it again.")
    fc = json.loads((d / "crowns.geojson").read_text(encoding="utf-8"))
    validation = run_validation(fc["features"], body.bbox, body.clicks, result["summary"]["crown_count"])
    (d / "validation.json").write_text(
        json.dumps({"bbox": body.bbox, "clicks": body.clicks, "result": validation}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return validation


# ---- projects ---------------------------------------------------------------------------------------

projects.mark_interrupted()
projects.seed_sample_once()


def _live_run(run: dict) -> dict:
    """Queued and running runs report the in-memory job's stage, so polling one endpoint is enough."""
    if run["status"] in ("queued", "running"):
        job = jobs.store.get(run["id"])
        if job is not None:
            run = {**run, "status": job.status.value if job.status.value in ("queued", "running") else run["status"], "stage_message": job.message}
    return run


def _project_or_404(project_id: str) -> dict:
    project = projects.get(project_id)
    if project is None:
        raise HTTPException(404, "Project not found.")
    project["runs"] = [_live_run(r) for r in project["runs"]]
    if project["latest_run"]:
        project["latest_run"] = _live_run(project["latest_run"])
    return project


def _start_run(project_id: str, parsed: ingest.ParsedInput, params: JobParams) -> dict:
    if params.veg_index == "ndvi" and parsed.kind != "geotiff":
        raise PipelineError("ndvi_unavailable", "NDVI needs a near-infrared band. Basemap imagery is RGB only; choose ExG or VARI.")
    holder: dict = {}

    def on_start(job: jobs.Job) -> None:
        holder["run"] = projects.add_run(project_id, job.job_id, params.model_dump())

    def on_finish(job: jobs.Job) -> None:
        if job.status == jobs.JobStatus.succeeded:
            projects.finish_run(job.job_id, job.result)
        else:
            projects.finish_run(job.job_id, None, job.error_code, job.error_message)

    jobs.submit(parsed, params.model_dump(), base_dir=projects.runs_dir, on_start=on_start, on_finish=on_finish)
    return holder["run"]


@app.get("/api/projects")
def list_projects():
    items = projects.list()
    for p in items:
        if p["latest_run"]:
            p["latest_run"] = _live_run(p["latest_run"])
    return {"projects": items}


@app.post("/api/projects", status_code=201)
async def create_project(request: Request):
    ctype = request.headers.get("content-type", "")
    try:
        raw = None
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            name = str(form.get("name") or "")
            params = JobParams(**json.loads(form.get("params") or "{}"))
            if upload is None or not hasattr(upload, "read"):
                return _err(400, "no_input", "Please choose a file to upload.")
            raw = await upload.read()
            selection_raw = form.get("selection")
            selection = json.loads(selection_raw) if selection_raw else None
            if selection is not None and (not isinstance(selection, list) or not all(isinstance(i, int) for i in selection)):
                return _err(400, "bad_selection", "The selected areas could not be read. Please choose them again.")
            parsed = ingest.parse_upload(upload.filename or "upload", raw, selection)
            name = name or Path(upload.filename or "Untitled").stem
            start = True
        else:
            body = ProjectCreate(**(await request.json()))
            params, name, start = body.params, body.name, body.start_run
            if body.template == "sample":
                spec = json.loads((Path(__file__).resolve().parent / "samples" / "sample_aoi.json").read_text(encoding="utf-8"))
                body.aoi = spec["aoi"]
            if body.aoi is None:
                return _err(400, "no_input", "Please upload a file or draw an area.")
            geom = ingest.parse_geojson(body.aoi)
            parsed = ingest.ParsedInput("drawn", geom, None, ingest.sha256_bytes(json.dumps(body.aoi, sort_keys=True).encode()), None)
        if parsed.aoi_lonlat is not None:
            ingest.validate_aoi(parsed.aoi_lonlat)
        if parsed.kind == "geotiff":
            # Fail on a missing CRS or unreadable raster now, not after the project exists.
            ingest.load_geotiff(parsed, None)
        project = projects.create(name, parsed, raw, params.model_dump())
        run = _start_run(project["id"], parsed, params) if start else None
    except PipelineError as exc:
        return _err(422, exc.code, exc.message)
    except ValidationError as exc:
        return _err(422, "bad_params", f"Some parameters are out of range: {exc.errors()[0].get('msg')}")
    except (json.JSONDecodeError, ValueError) as exc:
        return _err(400, "bad_request", f"The request could not be read: {exc}")
    return {"project": _project_or_404(project["id"]), "run": run}


@app.post("/api/uploads/inspect")
async def inspect_upload(request: Request):
    """Read vector upload metadata so the client can choose areas before creating a project."""
    ctype = request.headers.get("content-type", "")
    if not ctype.startswith("multipart/form-data"):
        return _err(400, "no_input", "Please upload a file to inspect.")
    try:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return _err(400, "no_input", "Please choose a file to inspect.")
        raw = await upload.read()
        if len(raw) > config.MAX_UPLOAD_BYTES:
            return _err(413, "file_too_large", "The upload is larger than the 100 MB limit.")
        kind, features = ingest.read_features(upload.filename or "upload", raw)
        return {
            "kind": kind,
            "areas": [{"index": feature.index, "name": feature.name} for feature in features],
        }
    except PipelineError as exc:
        return _err(422, exc.code, exc.message)
    except (json.JSONDecodeError, ValueError) as exc:
        return _err(400, "bad_request", f"The upload could not be inspected: {exc}")


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    return _project_or_404(project_id)


@app.patch("/api/projects/{project_id}")
def rename_project(project_id: str, body: ProjectRename):
    _project_or_404(project_id)
    projects.rename(project_id, body.name)
    return _project_or_404(project_id)


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: str):
    project = _project_or_404(project_id)
    if any(r["status"] in ("queued", "running") for r in project["runs"]):
        return _err(409, "run_in_progress", "This project has a run in progress. Wait for it to finish, then delete.")
    projects.delete(project_id)
    return Response(status_code=204)


@app.post("/api/projects/{project_id}/runs", status_code=202)
def create_run(project_id: str, body: RunCreate):
    _project_or_404(project_id)
    try:
        parsed = projects.parsed_input(project_id)
        run = _start_run(project_id, parsed, body.params)
    except PipelineError as exc:
        return _err(422, exc.code, exc.message)
    return run


# ---- workspace assistant --------------------------------------------------------------------------


@app.get("/api/projects/{project_id}/assistant")
def assistant_info(project_id: str):
    _project_or_404(project_id)
    ok, why = assistant.available()
    return {"available": ok, "reason": why, "model": assistant.MODEL, "suggestions": assistant.suggestions(project_id)}


@app.post("/api/projects/{project_id}/assistant/chat")
def assistant_chat(project_id: str, body: ChatIn):
    _project_or_404(project_id)
    ok, why = assistant.available()
    if not ok:
        return _err(503, "assistant_unavailable", why or "Canopy AI is not configured on this server.")
    try:
        # Validate the history and build the context before streaming, so bad input is a clean 4xx.
        stream = assistant.stream_chat(project_id, body.run_id, body.messages)
        first = next(stream)
    except assistant.AssistantError as exc:
        return _err(exc.status, exc.code, exc.message)

    def events():
        yield first
        yield from stream

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
