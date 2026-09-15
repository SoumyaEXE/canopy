# CANOPY: counting trees, and saying how sure we are

*Two-page writeup, draft. Page breaks are marked.*

## What it does

CANOPY looks at satellite imagery of an area and outlines each tree crown it can see. You give it an area drawn on a map, a boundary file, or your own GeoTIFF. It gives back:

- the share of the area covered by canopy
- a tree count stated as a range
- a confidence score for every crown
- heights where shadows allow
- a bundle recording exactly how each number was produced

## How it works

1. **Input.** The area is repaired if its geometry is invalid. It is rejected if it has several parts, or is larger than 1 km². Its area is measured in the local UTM zone. A GeoTIFF without a coordinate system is refused rather than guessed at.

2. **Imagery.** Esri World Imagery tiles at zoom 18 (at most 64) are stitched and cropped to the area. If any tile fails, the job fails. There is no blank patch.

3. **Ground resolution.** For tiles, `m_per_px = 156543.03392804097 × cos(latitude) / 2^zoom`. This was checked against a building of published size, and was within 10% per axis.

4. **Vegetation index.** Excess Green (`2g − r − b` on brightness-normalised colour) by default. VARI is optional, and NDVI when a near-infrared band exists.

5. **Canopy mask.** Otsu's threshold splits vegetation from ground. Sarle's bimodality coefficient says whether that split is real (above 5/9) or forced, and a weak split is shown as a warning. A 0.5 m morphological clean-up removes specks and fills pinholes.

6. **Crowns.** A distance transform of the mask is smoothed. Its peaks, spaced by half the minimum crown diameter, seed a watershed that divides touching canopy into individual crowns.

7. **Filtering.** Regions that are too small, larger than 400 m², or too irregular (solidity below 0.35) are rejected. They are counted and shown as their own map layer, never deleted.

8. **Height.** Height is attempted only when the acquisition time is known. The NOAA algorithm places the sun, three rays trace each crown's shadow, and `height = shadow_length × tan(sun_elevation)`. Occluded, too-short and implausible measurements are rejected and counted. The fraction measured is always shown.

9. **Confidence.** Each crown is scored from shape (0.30), size relative to its 8 neighbours (0.25), separation (0.25) and shadow plausibility (0.20). The count range runs from high + medium up to high + medium + 2 × low, because low-confidence regions are usually two trees merged.

Identical inputs produce byte-identical outputs. This was verified by diffing repeated runs.

---

## Where it is accurate, and where it is not

**Accurate.**

- Canopy cover and canopy area in open woodland, where crowns stand against bare ground or dry grass.
- Crown delineation for isolated trees.

On the sample (Monfragüe dehesa), 20.8% cover and 532 crowns (range 479–585) match visual inspection of the imagery.

**Weak.**

- **Closed canopy.** Adjacent crowns merge, so counts drop. Low-confidence crowns and the count range are designed to show this.
- **Lawns and crops.** Irrigated lawns and green crops pass as canopy in RGB imagery.
- **Heights.** Heights run low by about a crown radius times the tangent of sun elevation. They are unavailable for basemap tiles, whose capture time is unknown.

**Validation.**

The built-in validation mode compares your own tree marks against the detections, giving precision, recall, F1 and a correction factor.

> TODO before submission: run validation mode by hand on at least two patches (one open, one dense) and put the real precision/recall numbers here. No human-marked validation has been run yet; the automated test only checks that the metrics compute.

## What it refuses to compute, and why

**Carbon.** CANOPY does not output tonnes of CO₂, biomass or credit figures, not even roughly. Converting crown area to biomass needs:

- species-specific allometric equations
- wood density values
- local calibration plots
- a root-to-shoot ratio

The tool has none of these. A carbon number built on these outputs would inherit every error listed here, add the conversion's own uncertainty, and look far more precise than it is.

**Species, age and health.** These need spectral bands, ground survey, or both.

**Invented metadata.** If the capture time is unknown, height is switched off, not estimated from a default. If a file has no coordinate system, it is rejected.

**False precision.**

- Tree counts are a range, not a single number.
- Canopy area is given to a tenth of a hectare.
- Every figure on screen can be traced to a parameter shown in the interface and recorded in the audit manifest.

**Hidden losses.** Every rejected region and every failed shadow measurement is counted and reported. A tool that quietly drops what it cannot handle overstates its own accuracy.
