# The spec names python:3.11-slim; the pinned numpy/scipy/rasterio/pyproj wheels require 3.12 (see NOTES.md).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CANOPY_JOB_DIR=/tmp/canopy_jobs \
    CANOPY_TILE_CACHE=/tmp/canopy_tiles

WORKDIR /app

# Wheel path first: rasterio's manylinux wheel bundles GDAL, PROJ and GEOS.
# Only if that ever breaks, fall back to: apt-get install gdal-bin libgdal-dev libgeos-dev libproj-dev
COPY requirements.txt .
RUN pip install --only-binary=:all: -r requirements.txt

COPY app ./app

EXPOSE 8000

# WARNING: keep --workers 1. The job store is an in-process dict: a second worker would not see
# jobs created by the first, so status polls would 404 at random. Before adding workers, move the
# JobStore in app/jobs.py to Redis (or another shared store).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
