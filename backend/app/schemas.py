"""Pydantic request/response models. Mirrored in frontend/src/types.ts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class JobParams(BaseModel):
    detector: Literal["hybrid", "classical"] = "hybrid"
    min_crown_diameter_m: float = Field(3.0, ge=1.0, le=20.0)
    veg_index: Literal["exg", "vari", "ndvi"] = "exg"
    threshold_mode: Literal["otsu", "manual"] = "otsu"
    threshold_manual: float | None = Field(None, ge=-1.0, le=1.0)
    tile_zoom: Literal[18, 19] = 18
    acquisition_datetime_utc: str | None = None
    enable_height: bool = True


class JobCreate(BaseModel):
    aoi: dict | None = None
    params: JobParams = JobParams()


class JobCreated(BaseModel):
    job_id: str
    status: str


class StageInfo(BaseModel):
    name: str
    label: str
    seconds: float | None = None


class JobStatusOut(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: str | None
    stage_index: int
    stage_total: int
    message: str
    elapsed_s: float
    stages: list[StageInfo]
    error_code: str | None = None
    error_message: str | None = None


class ValidateIn(BaseModel):
    bbox: list[float] = Field(..., min_length=4, max_length=4, description="[west, south, east, north]")
    clicks: list[list[float]]


class ProjectCreate(BaseModel):
    name: str = Field("Untitled project", max_length=120)
    aoi: dict | None = None
    template: Literal["sample"] | None = None
    params: JobParams = JobParams()
    start_run: bool = True


class ProjectRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class RunCreate(BaseModel):
    params: JobParams = JobParams()
