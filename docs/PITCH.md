# CANOPY: pitch pack

## In one line

CANOPY counts tree crowns from imagery, measures its own accuracy against real labelled trees, shows every step it took, and says plainly what it cannot measure.

## The problem

Anyone can draw circles on trees. The hard part is trusting the number. A crown count with no accuracy figure and no way to see how it was made can't be audited, and in carbon work, what can't be audited doesn't count.

## What it does

1. **You give it an area**: upload a KML, KMZ, GeoJSON or GeoTIFF, or draw on the map.
2. **It finds the trees**: canopy cover, a crown count given as a range, and a confidence score for each crown.
3. **It shows its work**: the Pipeline tab steps through each of the 7 stages as images you can inspect.
4. **You can ask it**: Canopy AI answers questions about your workspace from its own data, and can suggest a better run that you apply with one click.
5. **Everything is auditable**: a downloadable bundle holds every parameter, and re-running the same input gives byte-identical output.

## Why it is different

| | Typical submission | CANOPY |
|---|---|---|
| Accuracy | A count | **Precision and recall against 61 hand-labelled trees** |
| Detector | One model, or one classical method | **Picks by resolution**: DeepForest AI on fine imagery, and a classical blob detector on satellite imagery, where it measured better |
| Explainability | Final map only | **Every stage as an image, with its numbers** |
| Bad input | Crashes or silent nonsense | **35 hostile files tested, 0 crashes**, each refused with a plain reason |
| Reproducibility | – | Byte-identical re-runs, audit zip |
| Honesty | – | No carbon claims; a limitations page for every number |
| Interface | Streamlit script | A full web app with projects, run history, a map and an AI assistant |

## The numbers (DeepForest benchmark tile, 61 hand-labelled trees)

| Input | Before | Now: trees found | Matched to a real tree | Precision | Recall |
|---|---|---|---|---|---|
| Original 0.1 m image | 15 | 55 | 44 | 0.80 | 0.72 |
| Same image, WGS84 | 25 | 64 | 47 | 0.73 | 0.77 |
| 9-copy mosaic (549 trees) | 129 | 504 | 377 | 0.75 | 0.69 |
| Satellite-like 0.5 m | – | 54 | 39 | 0.72 | 0.64 |
| 1 m | 21 | 38 | 23 | 0.61 | 0.38 |

Plain DeepForest gives 55 trees on the original image, about the same as us, but it finds almost nothing at 0.5 m (1 tree in our test). We find 54.

## Demo script (7 minutes)

1. **Projects page** (30 s). Click New project and upload `docs/demo/dehesa_plot.kml`, and the growing-folder animation plays. *"The first run starts straight away; imagery is fetched for the boundary."*
2. **Overview** (1 min). Canopy cover, the crown range, the confidence split and the warnings. *"Every number has a range and a reason."*
3. **Pipeline tab** (1.5 min). Press play: imagery, greenness, threshold, mask, crown centres, segments, crowns. Drag the blend slider. *"Nothing is a black box."*
4. **OSBS benchmark project** (1.5 min). Open it, show 55 found against 61 labelled, then the AI boxes stage. *"Here's measured precision and recall, not just a count."*
5. **Ask AI** (Ctrl+I) (1.5 min). Click "How can I get a more accurate crown count here?", then click **Apply and run** on the suggestion.
6. **Break it** (30 s). Upload `docs/demo/broken.kml` and a clear error appears. *"We tested 35 hostile inputs."*
7. **Audit tab** (30 s). Download the audit zip. *"Same input, same bytes."*

## Hard questions and straight answers

- **"Did you tune on the test image?"** Partly, and we say so. The 0.2 m switch point and two settings were chosen on it. The benchmark script is in the repo, so run it on your own labelled tiles.
- **"Why did the sample go from 532 to 1,107 crowns?"** The new detector finds small crowns the old one merged, and it also splits some big oaks. That scene has no labels, so we use the Validation tab to measure it rather than guess.
- **"Why is 1 m weak?"** At 1 m a 3 m crown is 3 pixels. We warn about it and keep canopy cover, which is still reliable.
- **"Carbon?"** No. Crown area isn't biomass, and the Limitations page explains why.
- **"Is the AI making things up?"** It answers from this workspace's data first. Any web facts come with numbered source links, it can't run anything without your click, and it can't see pixels.

## Before the demo (checklist)

- [ ] `backend/.env` holds `CANOPY_AI_PROVIDER=youcom` and `YDC_API_KEY=...` (already set). Each question costs about 1.2¢, using You.com Research at the lite tier.
- [ ] Start the backend (`uvicorn app.main:app --port 8000`) and the frontend (`npm run dev`), then open http://localhost:5173.
- [ ] Run the OSBS project once, so the AI model (about 230 MB) is downloaded and warm.
- [ ] Check internet access, needed for Esri imagery and Canopy AI.
- [ ] Keep `docs/demo/` open in Explorer for drag-and-drop.
- [ ] Optional proof: `python scripts/benchmark.py` and `python scripts/robustness_check.py`.
