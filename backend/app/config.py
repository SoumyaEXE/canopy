"""Settings from environment variables. Defaults are for local development."""

from __future__ import annotations

import os
from pathlib import Path

APP_VERSION = "1.0.0"
GIT_SHA = os.environ.get("GIT_SHA") or os.environ.get("RENDER_GIT_COMMIT") or "unknown"

JOB_DIR = Path(os.environ.get("CANOPY_JOB_DIR", Path(os.environ.get("TMPDIR", os.environ.get("TEMP", "/tmp"))) / "canopy_jobs"))
TILE_CACHE_DIR = Path(os.environ.get("CANOPY_TILE_CACHE", JOB_DIR.parent / "canopy_tiles"))
# Projects and their run outputs. Point this at a persistent volume in production.
DATA_DIR = Path(os.environ.get("CANOPY_DATA_DIR", JOB_DIR.parent / "canopy_data"))

CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CANOPY_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_AOI_KM2 = 1.0
MAX_TILES = 64
JOB_WORKERS = 2
TILE_FETCH_WORKERS = 6
TILE_TIMEOUT_S = 10
TILE_RETRIES = 2

TILE_SOURCE_NAME = "Esri World Imagery"
TILE_URL_TEMPLATE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
TILE_USER_AGENT = f"CANOPY/{APP_VERSION} (tree crown analysis research demo; contact via repository)"

JOB_DIR.mkdir(parents=True, exist_ok=True)
TILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
