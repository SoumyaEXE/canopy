# CANOPY

CANOPY finds tree crowns in satellite imagery and reports how sure it is about each one.

Give it an area (drawn on the map, or a GeoJSON, KML or KMZ file) or a GeoTIFF. It returns:

- canopy cover and canopy area
- a crown count, given as a range
- per-crown confidence
- shadow-derived heights, only where they can be measured
- a downloadable audit bundle that records every parameter behind every number

Work is organised into **projects**: each keeps its uploaded file or drawn area, its parameters, and a history of runs you can compare, reopen and download. The map workspace offers dark, light, streets and satellite basemaps, and colours crowns by confidence, area, diameter, height or solidity on perceptually uniform scales (viridis, cividis, magma, greens, turbo).

Core detection uses classical computer vision, with an optional NumPy-only local calibration model trained from validation marks. It does not estimate carbon, biomass or credits; the "What this tool cannot do" panel explains why.

- Method: [docs/METHOD.md](docs/METHOD.md)
- Limitations: [docs/LIMITATIONS.md](docs/LIMITATIONS.md)
- Build decisions and verifications: [NOTES.md](NOTES.md)

## Run locally

Backend (Python ≥ 3.12):

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt      # Windows: .venv\Scripts\pip
# optional, for the AI tree detector (Auto mode on imagery of 0.2 m/px or finer):
.venv/bin/pip install -r requirements-ai.txt --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
.venv/bin/uvicorn app.main:app --port 8000
```

Measured accuracy against 61 hand-labelled trees: `.venv/bin/python scripts/benchmark.py` (results and caveats in [docs/METHOD.md](docs/METHOD.md#measured-accuracy)).

Frontend (Node ≥ 20):

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to :8000
```

The precomputed sample loads on first visit. No tile fetch is needed for it.

### Checks

```bash
cd backend
.venv/bin/pytest                          # unit tests, including the determinism test
.venv/bin/python scripts/e2e_check.py     # full API check against a running server (fetches tiles)
.venv/bin/python scripts/build_sample.py  # regenerates app/samples/sample and verifies determinism
```

## Data and projects

Projects live in SQLite plus files under `CANOPY_DATA_DIR` (default: `<temp>/canopy_data`). Each run writes its outputs to `runs/<run id>/`, so every past run stays downloadable. On first start the committed sample is seeded as a ready-made project. Point `CANOPY_DATA_DIR` at a persistent volume in production; on hosts without one, projects are lost on restart.

## Larger areas

The public demo caps areas at 1 km² and 64 tiles. Above that, processing can exceed the free instance's timeout. To analyse more, run locally and raise `MAX_AOI_KM2` and `MAX_TILES` in `backend/app/config.py`. Memory use grows with area.

## Deploy

**Backend: Render.**

1. Create a service from `render.yaml`. It builds `backend/Dockerfile`.
2. Set `CANOPY_CORS_ORIGINS` to the Vercel production URL plus `http://localhost:5173`. Never `*`.

**Frontend: Vercel.**

1. Set the project root to `frontend/`.
2. Set `VITE_API_BASE` to the Render URL.
3. Optionally set `VITE_CARTO_API_KEY`.
4. After deploying, open the site and confirm in the network panel that requests go to the Render URL, not localhost.

**Keepalive.** In GitHub, set the repository variable `API_URL`. `.github/workflows/keepalive.yml` then pings `/healthz` every 10 minutes. Check the Actions tab to confirm the pings actually succeed.

## Known operational limits

- Jobs live in memory. A restart or redeploy loses running and finished jobs, and results are swept after 6 hours. The sample is unaffected.
- The API must run with a single worker. A second worker needs a shared job store (for example Redis) first.
- Free-tier instances sleep when idle. A cold start can take about 50 seconds; the keepalive workflow exists for this.
- Basemap tiles have no reliable acquisition date, so height is off unless you enter the acquisition time.

## Attribution

- Basemap © CARTO, © OpenStreetMap contributors.
- Imagery © Esri World Imagery.

Check each provider's current terms before public use.

UI components are from [BoardUI](https://www.boardui.com/components/).
