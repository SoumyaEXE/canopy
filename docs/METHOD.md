# CANOPY method

Every number CANOPY reports comes from the steps below. Each parameter named here is written into `manifest.json` in the audit bundle, and the ones a user can change are in the control rail.

Canopy area and cover come from classical computer vision only. Crown detection has two paths (section 6): a pretrained tree detector (DeepForest) on fine imagery, and classical blob markers elsewhere. Both are deterministic: given the same input and parameters, the pipeline produces byte-identical `crowns.geojson`. This is checked by `backend/scripts/build_sample.py`, `tests/test_determinism.py`, and the API end-to-end script.

## Optional local calibration model

The validation panel can fit a small regularized logistic regression using NumPy only. It learns from the marked patch which detected regions matched a human mark, using explainable features such as area, diameter, solidity, confidence and separation. With at least four matched and four unmatched detections, it reports a local calibrated count range and writes the validation inputs and result to `validation.json` beside the run outputs.

This is not a replacement for crown detection or a pretrained general-purpose AI model. It is deliberately CPU-friendly for local Intel i3 machines, and the raw detector count remains the primary result.

## 1. Input and area of interest

Four inputs are accepted:

- A polygon drawn on the map.
- A GeoJSON, KML or KMZ file. These are treated as an area of interest (AOI), and imagery is fetched for it.
- A GeoTIFF. This is analysed at its own resolution.

AOI rules:

- Invalid geometry is repaired with `make_valid`.
- Multi-part polygons are rejected rather than silently merged.
- Holes are dropped, and this is recorded.
- Area is computed in the local UTM zone: `zone = floor((lon + 180) / 6) + 1`, EPSG 326xx north or 327xx south.
- The accepted range is 100 m² to 1 km². Above the cap, the error explains why the cap exists.

GeoTIFF rules:

- A GeoTIFF without a CRS is rejected. CANOPY does not guess where it is.
- Band interpretation:
  - 3 bands: RGB.
  - 4 uint8 bands: RGBA.
  - 4 bands of any other type: RGB + NIR, unless band 4 is flagged as alpha.
  - 5 or more bands: matched by band description.
- The interpretation is shown to the user.
- Geographic and Web Mercator rasters are reprojected to UTM, so a pixel has one true ground size.

## 2. Imagery acquisition

For drawn and vector AOIs, tiles come from Esri World Imagery (XYZ, `{z}/{y}/{x}` order):

- Zoom 18 by default. Zoom 19 is optional and carries a warning, because it is often upsampled.
- At most 64 tiles, fetched with retries.
- If a tile still fails, the whole job fails. There is no blank patch.
- Tiles are mosaicked into one image, georeferenced in EPSG:3857 from the top-left tile's origin, and cropped to the AOI bounding box.

The tile source, zoom and fetch time are recorded. Basemap tiles carry no acquisition date, so the imagery date is reported as unknown.

## 3. Ground resolution

For tiles:

```
m_per_px = 156543.03392804097 * cos(latitude) / 2^zoom
```

This is evaluated at the AOI centroid. The spread of this value between the AOI's northern and southern edges is recorded.

For GeoTIFFs, the pixel size comes from the (UTM) transform.

This was checked against a real object of known size; see NOTES.md.

## 4. Vegetation index

| Index | Formula | When |
|---|---|---|
| ExG (default) | `2g − r − b` on chromatic coordinates (`r = R/(R+G+B)` and so on) | any RGB |
| VARI | `(G − R) / (G + R − B)`, denominator clamped away from 0, clipped to ±1 | any RGB |
| NDVI | `(NIR − R) / (NIR + R)` | only when a NIR band exists |

The 1st and 99th percentiles of the index inside the AOI set the range of the threshold slider.

## 5. Threshold and canopy mask

Threshold:

- The default threshold is Otsu's method on the in-AOI index values. The user can override it with a manual value.
- Threshold confidence uses Sarle's bimodality coefficient, `(skew² + 1) / (kurtosis + 3(n−1)²/((n−2)(n−3)))`.
- Confidence is high when the coefficient is above 5/9 and each side of the split holds at least 5% of the AOI pixels. Otherwise it is low, and the UI says so.

Cleaning the mask:

1. Opening, then closing, with a disk of radius `max(1, round(0.5 m / m_per_px))`.
2. Remove objects and fill holes smaller than the minimum crown area.

Outputs:

- Canopy area = mask pixels × `m_per_px²`.
- Canopy cover = canopy area / AOI area.

## 6. Crown detection and segmentation

The `detector` parameter is `hybrid` (shown as **Auto**, the default) or `classical`. Auto picks by resolution, because each method was measured to win in a different range (see *Measured accuracy* below):

| Pixel size | Auto uses | Why |
|---|---|---|
| ≤ 0.20 m | DeepForest + canopy mask | F1 0.76 at 0.1 m, against 0.56 for blobs |
| > 0.20 m (all satellite basemaps) | Classical blob markers | DeepForest falls to F1 0.37 at 0.25 m and under 0.1 at 0.5 m; blobs hold 0.68 at 0.5 m |

If torch or deepforest is not installed, Auto uses classical and adds a warning.

**DeepForest path** (`pipeline/detector.py`):

1. `weecology/deepforest-tree` (RetinaNet trained on 0.1 m airborne RGB) predicts tree boxes. Images larger than 400 px run as 400 px patches with 25% overlap, and duplicates are merged by NMS at IoU 0.15. Boxes scoring below 0.3 are dropped.
2. Each box's inscribed ellipse claims pixels. Where ellipses overlap, a pixel goes to the box with the smaller normalised elliptical distance.
3. Each ellipse is trimmed to the canopy mask grown by 0.5 m (crown edges are darker than centres). If the mask covers under 35% of the ellipse, the mask missed that tree and the ellipse itself is the outline.
4. The size filter uses a 1 m minimum diameter, because the detector already vouches for each tree.

**Classical path** (`crowns.segment_blobs`):

1. Response = `clip(index − threshold, 0) × (0.5 + brightness)`. Sunlit crowns are greenest and brightest in the middle.
2. Laplacian-of-Gaussian blobs, radius from `d/2` (half the minimum crown diameter) to 6 m, 12 scales, threshold 0.02. Blobs whose centre is not on canopy are dropped.
3. Watershed of the smoothed negated response from each blob, inside the canopy mask and within 1.4 blob radii of its centre.
4. The size filter uses `d/2` as the minimum diameter.

This replaced distance-transform peaks, which only find a centre where the mask has a waist, so touching crowns merged (15 of 61 trees found on the benchmark tile).

## 7. Crown filtering and polygons

Each region is kept or rejected:

- **Too small:** area below `π(d_min/2)²`, where `d_min` is 1 m (DeepForest) or `d/2` (classical); see section 6.
- **Too large:** area above 400 m².
- **Low solidity:** solidity below 0.35.

Rejected regions are never dropped. They are counted, reported as a warning, and drawn as their own map layer.

Crowns touching the AOI edge are kept and flagged, because their area is truncated.

Polygons:

- Traced from the region boundary and simplified to a 1-pixel tolerance.
- Converted to lon/lat, with coordinates rounded to 7 decimals (about 1 cm).

## 8. Shadow height

Height is attempted only when the acquisition time is known: from the user, or from GeoTIFF metadata. Otherwise it is disabled and the UI says why.

Sun position:

- Sun elevation and azimuth come from the NOAA solar position algorithm, with refraction correction.
- The scene is skipped if elevation is outside 10–70°.

Shadow mask:

- HSV value below an Otsu threshold (computed on non-canopy pixels), and saturation below 0.5.

Measurement:

- Three rays are cast from each crown's edge in the anti-solar direction, capped at 60 m.
- A ray that runs into another crown counts as occluded. Two or more occluded rays reject the crown.
- The median shadow length `L` gives:

```
height_m = L * tan(sun_elevation)
```

A measurement is rejected, and counted, if:

- the shadow is shorter than 3 px, or
- the height is outside 1–80 m.

Because `L` is measured from the crown edge, heights are biased low by roughly `crown_radius × tan(elevation)`. Every outcome count is reported.

## 9. Confidence, count range and validation

Confidence per crown is a weighted sum of four signals:

| Signal | Weight | Definition |
|---|---|---|
| Shape | 0.30 | `4π·area / perimeter²`, capped at 1 |
| Size fit | 0.25 | `1 − |area − median(8 nearest)| / (3·max(1.4826·MAD, 0.25·median))`, floored at 0 |
| Separation | 0.25 | distance transform at the centroid / equivalent radius, capped at 1 |
| Shadow | 0.20 | 1 if height/diameter is 0.5–5; 0.4 if measured but outside that; 0 if not measured |

When height is disabled, the shadow weight is set to 0 and the other three are renormalized.

Buckets: high ≥ 0.70, medium ≥ 0.45, low below that. A low-confidence crown's popup names its weakest signal in a plain sentence.

Count range:

- lower = high + medium
- upper = high + medium + 2 × low

Low-confidence regions are most often two merged crowns, so each counts for up to two.

Validation mode:

1. The user draws a patch and clicks every tree they can see, with detections hidden; at least 15 clicks.
2. Clicks are matched to detections greedily, nearest first. A click matches if it is inside the polygon or within 1.5 × the crown's equivalent radius.
3. Reported: precision, recall, F1, and correction factor `(TP + FN) / (TP + FP)`, with a caveat that one person's patch is indicative, not rigorous.

## Outputs

The audit bundle (`audit.zip`) contains:

- `crowns.geojson`, `rejected.geojson`, `crowns.csv`
- `canopy_mask.png`, `overlay.png`
- `manifest.json`: every parameter, threshold statistic, confidence weight, solar value, version and git SHA
- `summary.txt`
- `LIMITATIONS.md`

JSON is written with sorted keys and fixed separators. Zip entries carry a fixed timestamp.

No carbon, biomass or credit figure is computed anywhere. See LIMITATIONS.md.

## Measured accuracy

`backend/scripts/benchmark.py` scores the full pipeline against the 61 hand-labelled crowns of DeepForest's `OSBS_029` tile (NEON, Florida, 0.1 m). A detection matches a label when their boxes overlap at IoU ≥ 0.4, one to one. That is DeepForest's own evaluation rule. Defaults throughout (Auto, minimum crown 3 m, Otsu). Raw numbers are in `docs/benchmark_osbs029.json`.

| Input | Before (distance-transform watershed) | Auto: found / matched | Precision | Recall | F1 |
|---|---|---|---|---|---|
| Native 0.1 m | 15 found | 55 / 44 | 0.80 | 0.72 | 0.76 |
| Same pixels in WGS84 | 25 found | 64 / 47 | 0.73 | 0.77 | 0.75 |
| 3×3 mosaic (549 trees) | 129 found | 504 / 377 | 0.75 | 0.69 | 0.72 |
| Downsampled to 0.5 m | 25 found | 54 / 39 | 0.72 | 0.64 | 0.68 |
| Downsampled to 1 m | 21 found | 38 / 23 | 0.61 | 0.38 | 0.46 |

For reference, DeepForest's own boxes with no CANOPY post-processing score P 0.82 / R 0.74 on the native tile, so the mask-shaped outlines cost almost nothing against boxes while giving real crown areas.

Caveats:

- This is one 40 × 40 m tile of one forest type. The resolution cut-over (0.2 m), the blob threshold and the trim tolerance were chosen on it, so these numbers are optimistic for other scenes.
- The Monfragüe sample went from 532 to 1,107 crowns with the classical blob path. The extra regions are mostly small dark crowns and shrubs the old method merged or rejected. Some large holm oaks are also split into two or three regions. Without labels for that scene, neither count is verified. Use the Validation tab to measure it.
