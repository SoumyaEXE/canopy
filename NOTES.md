# Build notes

Decisions, verifications and deviations from `CANOPY_Build_Spec.pdf`, so nothing about the build is implicit.

## Open items for the owner

- **Deadline.** The spec itself flags that the brief's "Monday, 16 September" is inconsistent with the date it was written. Confirm the real deadline.
- **Esri World Imagery terms.** Esri's terms of use must be confirmed before shipping a public demo that fetches its tiles. Attribution is shown on the map at all times.
- **CARTO basemap key.** CARTO now requires an API key on its raster basemaps; without one, tiles carry an "API KEY REQUIRED" watermark. A key is set locally in `frontend/.env.local` (gitignored). Add the same `VITE_CARTO_API_KEY` in Vercel's environment settings. It ships in the browser bundle, as all basemap keys do, so restrict it to the production domain in the CARTO dashboard.
- **Font licence.** The display face is TWK Lausanne Pan 800 (`frontend/src/assets/fonts/`), a commercial typeface. Confirm the licence covers web embedding before deploying. Only the 800 cut was supplied, so it is used for the wordmark only; figures and titles use Inter Tight in light weights.
- **Persistent storage for projects.** Render’s free tier has no persistent disk, so projects disappear on each redeploy or restart. Attach a disk (paid) and set `CANOPY_DATA_DIR` to it, or accept projects as demo-ephemeral.
- **Deployment.** Not done: it needs your Render, Vercel and GitHub accounts. `render.yaml`, `backend/Dockerfile`, `frontend/vercel.json` and `.github/workflows/keepalive.yml` are ready. The Docker image has not been test-built, because Docker is not installed on the build machine.

## Verifications

### M3: metres per pixel against a real object

Victoria Memorial, Kolkata, at zoom 18 (`m_per_px ≈ 0.55` at 22.5° N).

| | Measured from mosaic | Published |
|---|---|---|
| Footprint (E–W × N–S) | ≈ 95 × 76 m | 103 × 69 m |
| Area | ≈ 7,220 m² | ≈ 7,107 m² |

The error is under 10% per axis and about 2% on area. That is consistent with an off-nadir view of a tall building and with the published figures describing the building rather than its plinth. The scale is accepted.

### M4: mosaic orientation

The mosaic was saved and inspected. Roads and buildings are continuous across tile seams, so `{z}/{y}/{x}` ordering is correct.

### M5: canopy mask and choice of sample area

The Victoria Memorial test showed ExG also marks irrigated lawns as canopy. That is an expected RGB limitation, already in LIMITATIONS.md.

The sample area was therefore chosen in open dehesa at Monfragüe, Extremadura: scattered holm oaks on dry grass and bare tracks. It has:

- a clear boundary between canopy and ground
- mixed density
- 532 crowns, inside the spec's 200–600 range

Sample result:

- AOI 11.07 ha, cover 20.8%
- 532 crowns, range 479–585
- confidence: high 275 / medium 204 / low 53
- 137 rejected regions

Esri's identify endpoint reports GeoEye-1 imagery dated 2024-08-25, but gives no time of day. Height is therefore disabled for the sample, as the spec requires.

### Threshold confidence rule

A first version compared between-class variance to total variance. On a unimodal Gaussian that ratio is still about 0.64, so it could not tell a real split from a forced one. Valley depth was also tried and was unstable.

The final rule is Sarle's bimodality coefficient with the standard 5/9 cutoff, plus a 5% minimum on each side of the split. On test scenes:

- A near-uniform grass scene (the Maidan, Kolkata) reads **low**.
- The sample reads 0.565, **high**.

### Determinism

`crowns.geojson` is byte-identical across two runs in all three checks:

- `scripts/build_sample.py` (two in-process runs)
- `tests/test_determinism.py`
- `scripts/e2e_check.py` (two API jobs)

### Test status (15 Sep 2026)

- `pytest`: 34 passed (includes the project store).
- `scripts/e2e_check.py`: 19/19 pass. It covers:
  - the sample, drawn AOI, KML, KMZ, GeoJSON and GeoTIFF inputs
  - GeoTIFF without a CRS rejected
  - oversize error text
  - validation metrics and the 15-click minimum
  - audit zip contents, manifest fields, and no carbon terms
- Frontend: `tsc -b` and `vite build` are clean.
- Driven in headless Chromium:
  - sample render
  - crown popups, both numeric and low-confidence sentence
  - live re-run with named stages
  - download menu
  - validation flow
  - KML upload and the oversize error notification
  - Draw AOI
  - light and dark themes
  - 390 px phone layout

## Deviations from the spec

| Spec | Built | Why |
|---|---|---|
| React 18 | React 19 | The BoardUI components target React 19. |
| `tailwind.config.js` | Tailwind v4, CSS-first `@theme` | BoardUI is a Tailwind v4 design system. |
| "No component library beyond what is needed" | BoardUI components copied into `src/components` unchanged | The project owner asked for BoardUI's components, fonts and styling exactly. A dialog shell was lifted from BoardUI's settings modal, which has no standalone modal component. |
| Docker `python:3.11-slim` | `python:3.12-slim` | The pinned numpy 2.5, scipy 1.18, rasterio 1.5 and pyproj 3.8 wheels require Python ≥ 3.12. Local development ran on 3.14. |
| Basemap dropdown `[Dark▾]` | BoardUI `ThemeToggle` (segmented) | One control switches both the app theme and Dark Matter / Positron. |
| Progress overlay | Also lists "Validating input" and "Writing outputs" | These are real stages that take measurable time. |
| Three-column single screen (6.4) | Projects home plus per-project tabs (Overview, Map with parameters on the left, Crowns, Validation, Runs, Audit) and a Limitations page; the rail collapses to icons on wide pages | Requested by the project owner. The Overview keeps the 6.5 reading order, and "What this tool cannot do" is still one click from the results. |
| “No database of past jobs beyond ephemeral storage” (1.3) | Projects: SQLite + files under `CANOPY_DATA_DIR`, each with its input, last-used parameters and every run | Requested by the project owner (multiple projects per file/area, re-analysis history). Still single-tenant, no accounts. Runs in flight when the server stops are marked failed on restart rather than left spinning. |
| Live re-run on parameter change (M12) | Kept, as a “Re-run on change” switch (on by default) plus an explicit Run button | Each re-run is now a recorded run, so the explicit button avoids flooding the history when users prefer it. |
| — | Place search on the draw page via OpenStreetMap Nominatim | Light interactive use only (debounced, one request in flight), attributed in the results list. Check Nominatim’s usage policy before heavy public traffic. |
| Display type | Inter Tight 200–500 for figures and titles; TWK Lausanne 800 for the wordmark only | The owner asked for thin numerals; only the 800 Lausanne cut exists in the repo. |
| BoardUI blue accent | Accent tokens re-pointed to graphite (light) and deep lime (dark) in `src/index.css` | BoardUI exposes the accent as a swap point; no component was edited. |
| — | `?download=1` on job files | Browsers ignore `<a download>` across origins (Vercel → Render), so the API sends `Content-Disposition: attachment` when asked. |

## Known behaviour worth stating

- **Heights are biased low.** Shadow length is measured from the crown edge, as the spec's formula implies. The bias is roughly `crown_radius × tan(elevation)` and is stated in LIMITATIONS.md and in the UI caption.
- **Simulated upload progress.** BoardUI's `FileUpload` shows a simulated progress ring before handing the file over. The real upload starts after it; the stage overlay then shows server progress.
- **Jobs are in memory.** They are lost on restart and swept after 6 hours. The API must run with one worker; see the Dockerfile comment.
- **Tile cache flag.** The tile cache is on local disk. Whether a tile came from the cache is not yet recorded in the manifest.

## Deferred ideas (out of scope, not built)

- Record tile cache hits in the manifest.
- Drag-to-draw validation rectangle. It is currently two clicks, which also works on touch.
- A per-crown shadow-ray overlay, for auditing height measurements visually.
