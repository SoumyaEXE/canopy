"""In-process job queue.

A ThreadPoolExecutor and a module-level dict are enough for a single-instance demo.
The store sits behind JobStore so moving to Redis is a one-file change. Jobs do not
survive a restart; that is documented in the README rather than engineered around.
"""

from __future__ import annotations

import logging
import secrets
import shutil
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from . import config
from .pipeline import STAGES, PipelineError, ingest, run_pipeline

log = logging.getLogger("canopy.jobs")
JOB_TTL_S = 6 * 3600


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


@dataclass
class Job:
    job_id: str
    status: JobStatus = JobStatus.queued
    stage: str | None = None
    stage_index: int = 0
    message: str = "Waiting for a worker"
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    stage_times: dict = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    result: dict | None = None
    # Project runs write to the persistent run directory; ad-hoc jobs use the temp job directory.
    base_dir: Path | None = None

    @property
    def dir(self) -> Path:
        return (self.base_dir or config.JOB_DIR) / self.job_id


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(job_id="j_" + secrets.token_hex(4))
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for k, v in fields.items():
                setattr(job, k, v)

    def set_result(self, job_id: str, result: dict) -> None:
        self.update(job_id, result=result, status=JobStatus.succeeded, finished=time.time(), message="Done")

    def sweep(self) -> None:
        cutoff = time.time() - JOB_TTL_S
        with self._lock:
            old = [j for j in self._jobs.values() if j.created < cutoff]
            for j in old:
                self._jobs.pop(j.job_id, None)
        for j in old:
            if j.base_dir is None:  # project run outputs are kept
                shutil.rmtree(j.dir, ignore_errors=True)


store = JobStore()
executor = ThreadPoolExecutor(max_workers=config.JOB_WORKERS, thread_name_prefix="canopy-job")
STAGE_INDEX = {name: i for i, (name, _) in enumerate(STAGES, start=1)}


OnFinish = Callable[["Job"], None]


def _run(job_id: str, parsed: ingest.ParsedInput, params: dict, on_finish: OnFinish | None = None) -> None:
    job = store.get(job_id)
    assert job is not None
    store.update(job_id, status=JobStatus.running, started=time.time())
    last = {"stage": None, "t": time.time()}

    def progress(stage: str, message: str) -> None:
        now = time.time()
        times = dict(store.get(job_id).stage_times)
        if last["stage"]:
            times[last["stage"]] = round(now - last["t"], 2)
        last.update(stage=stage, t=now)
        store.update(job_id, stage=stage, stage_index=STAGE_INDEX[stage], message=message, stage_times=times)

    try:
        result = run_pipeline(job_id, job.dir, parsed, params, progress)
        times = dict(store.get(job_id).stage_times)
        if last["stage"]:
            times[last["stage"]] = round(time.time() - last["t"], 2)
        store.update(job_id, stage_times=times)
        store.set_result(job_id, result)
    except PipelineError as exc:
        store.update(job_id, status=JobStatus.failed, error_code=exc.code, error_message=exc.message, finished=time.time())
    except Exception:  # noqa: BLE001
        log.error("job %s crashed:\n%s", job_id, traceback.format_exc())
        store.update(
            job_id,
            status=JobStatus.failed,
            error_code="internal_error",
            error_message="Something went wrong inside the analysis. The error has been logged. Please try a different area or file.",
            finished=time.time(),
        )
    finally:
        if on_finish is not None:
            try:
                on_finish(store.get(job_id))
            except Exception:  # noqa: BLE001
                log.error("on_finish for %s failed:\n%s", job_id, traceback.format_exc())


def submit(
    parsed: ingest.ParsedInput,
    params: dict,
    base_dir: Path | None = None,
    on_start: OnFinish | None = None,
    on_finish: OnFinish | None = None,
) -> Job:
    store.sweep()
    job = store.create()
    if base_dir is not None:
        store.update(job.job_id, base_dir=base_dir)
    if on_start is not None:
        on_start(job)
    executor.submit(_run, job.job_id, parsed, params, on_finish)
    return job
