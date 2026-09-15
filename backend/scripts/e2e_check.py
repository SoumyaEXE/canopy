"""End-to-end API check against a running server: every input type, the size error, validation, the audit zip.

Run from backend/ with the API on :8000:  python scripts/e2e_check.py
"""

import io
import json
import sys
import time
import zipfile

import numpy as np
import rasterio
import requests
from PIL import Image
from rasterio.transform import from_origin

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PARAMS = {"min_crown_diameter_m": 3.0, "veg_index": "exg", "threshold_mode": "otsu", "tile_zoom": 18, "enable_height": True}
# A small patch inside the sample AOI (tiles are cached after build_sample.py).
W, S, E, N = -5.9510, 39.9290, -5.9490, 39.9305
RING = [[W, S], [E, S], [E, N], [W, N], [W, S]]
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def wait(job_id, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = requests.get(f"{API}/api/jobs/{job_id}").json()
        if st["status"] in ("succeeded", "failed"):
            return st
        time.sleep(0.5)
    return {"status": "timeout"}


t = time.time()
r = requests.get(f"{API}/api/sample")
check("sample returns fast", r.ok and time.time() - t < 1.0, f"{(time.time() - t) * 1000:.0f} ms")
sample = r.json()

# Drawn AOI (JSON)
r = requests.post(f"{API}/api/jobs", json={"aoi": {"type": "Polygon", "coordinates": [RING]}, "params": PARAMS})
check("drawn: 202", r.status_code == 202, r.text[:120])
st = wait(r.json()["job_id"])
check("drawn: succeeded", st["status"] == "succeeded", st.get("error_message") or "")
res = requests.get(f"{API}/api/jobs/{st['job_id']}/result").json()
check("drawn: crowns found", res["summary"]["crown_count"] > 0, str(res["summary"]["crown_count"]))
drawn_id = st["job_id"]

# Height with a supplied datetime
p2 = dict(PARAMS, acquisition_datetime_utc="2024-08-25T11:05:00Z")
r = requests.post(f"{API}/api/jobs", json={"aoi": {"type": "Polygon", "coordinates": [RING]}, "params": p2})
st = wait(r.json()["job_id"])
res2 = requests.get(f"{API}/api/jobs/{st['job_id']}/result").json()
check("height: runs with datetime", st["status"] == "succeeded" and res2["summary"]["height_available"], f"measured {res2['summary']['height_measured_count']}/{res2['summary']['crown_count']}, sun {res2['provenance']['sun_elevation_deg']}°")

# Determinism via API
r = requests.post(f"{API}/api/jobs", json={"aoi": {"type": "Polygon", "coordinates": [RING]}, "params": PARAMS})
st = wait(r.json()["job_id"])
a = requests.get(f"{API}/api/jobs/{drawn_id}/crowns.geojson").content
b = requests.get(f"{API}/api/jobs/{st['job_id']}/crowns.geojson").content
check("determinism: identical crowns.geojson via API", a == b and len(a) > 100, f"{len(a)} bytes")

# KML
kml = f"""<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>{' '.join(f'{x},{y},0' for x, y in RING)}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>"""
r = requests.post(f"{API}/api/jobs", files={"file": ("aoi.kml", kml.encode())}, data={"params": json.dumps(PARAMS)})
st = wait(r.json()["job_id"]) if r.status_code == 202 else {"status": r.text}
check("kml: succeeded", st["status"] == "succeeded", str(st.get("error_message") or ""))

# KMZ
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("doc.kml", kml)
r = requests.post(f"{API}/api/jobs", files={"file": ("aoi.kmz", buf.getvalue())}, data={"params": json.dumps(PARAMS)})
st = wait(r.json()["job_id"]) if r.status_code == 202 else {"status": r.text}
check("kmz: succeeded", st["status"] == "succeeded", str(st.get("error_message") or ""))

# GeoJSON file
gj = {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [RING]}}
r = requests.post(f"{API}/api/jobs", files={"file": ("aoi.geojson", json.dumps(gj).encode())}, data={"params": json.dumps(PARAMS)})
st = wait(r.json()["job_id"]) if r.status_code == 202 else {"status": r.text}
check("geojson: succeeded", st["status"] == "succeeded", str(st.get("error_message") or ""))

# GeoTIFF: synthesize a real georeferenced RGB file in UTM from the sample imagery.
img = np.asarray(Image.open("app/samples/sample/imagery.png").convert("RGB"))[:400, :400]
buf = io.BytesIO()
with rasterio.io.MemoryFile() as mem:
    with mem.open(driver="GTiff", height=400, width=400, count=3, dtype="uint8", crs="EPSG:32630", transform=from_origin(246000, 4424000, 0.45, 0.45)) as dst:
        for i in range(3):
            dst.write(img[..., i], i + 1)
    tif = mem.read()
r = requests.post(f"{API}/api/jobs", files={"file": ("scene.tif", tif)}, data={"params": json.dumps(PARAMS)})
st = wait(r.json()["job_id"]) if r.status_code == 202 else {"status": r.text}
check("geotiff: succeeded", st["status"] == "succeeded", str(st.get("error_message") or ""))
if st["status"] == "succeeded":
    rt = requests.get(f"{API}/api/jobs/{st['job_id']}/result").json()
    check("geotiff: m_per_px from transform", abs(rt["provenance"]["m_per_px"] - 0.45) < 1e-6, str(rt["provenance"]["m_per_px"]))
    check("geotiff: interpretation surfaced", "RGB, 3 bands, uint8" in (rt["provenance"]["interpreted_as"] or ""), rt["provenance"]["interpreted_as"])

# GeoTIFF with no CRS -> rejected
with rasterio.io.MemoryFile() as mem:
    with mem.open(driver="GTiff", height=50, width=50, count=3, dtype="uint8") as dst:
        dst.write(np.zeros((3, 50, 50), dtype=np.uint8))
    nocrs = mem.read()
r = requests.post(f"{API}/api/jobs", files={"file": ("nocrs.tif", nocrs)}, data={"params": json.dumps(PARAMS)})
st = wait(r.json()["job_id"]) if r.status_code == 202 else {"status": "failed", "error_message": r.json().get("error_message")}
check("geotiff without CRS rejected", st["status"] == "failed" and "coordinate reference system" in (st.get("error_message") or ""), st.get("error_message") or "")

# Oversize AOI -> human-readable error, no job
big = [[-6.0, 39.9], [-5.98, 39.9], [-5.98, 39.92], [-6.0, 39.92], [-6.0, 39.9]]
r = requests.post(f"{API}/api/jobs", json={"aoi": {"type": "Polygon", "coordinates": [big]}, "params": PARAMS})
msg = r.json().get("error_message", "")
check("oversize AOI: readable error", r.status_code == 422 and "square kilometres" in msg and "maximum is 1.0" in msg, msg[:90])

# Validation on sample
feats = requests.get(f"{API}/api/jobs/sample/crowns.geojson").json()["features"]
cw, cs, ce, cn = -5.9505, 39.9295, -5.9490, 39.9310
inside = [f["properties"]["centroid_lonlat"] for f in feats if cw < f["properties"]["centroid_lonlat"][0] < ce and cs < f["properties"]["centroid_lonlat"][1] < cn]
clicks = inside[: max(15, int(len(inside) * 0.8))] + [[cw + 0.0001, cs + 0.0001]]
r = requests.post(f"{API}/api/jobs/sample/validate", json={"bbox": [cw, cs, ce, cn], "clicks": clicks})
v = r.json()
check("validation: metrics computed", v.get("ok") and v["precision"] > 0 and v["correction_factor"] is not None, v.get("summary", str(v))[:160])
r = requests.post(f"{API}/api/jobs/sample/validate", json={"bbox": [cw, cs, ce, cn], "clicks": clicks[:5]})
check("validation: requires 15 clicks", r.json().get("ok") is False, r.json().get("message", ""))

# Audit zip completeness
z = zipfile.ZipFile(io.BytesIO(requests.get(f"{API}/api/jobs/{drawn_id}/audit.zip").content))
names = set(z.namelist())
need = {"manifest.json", "crowns.geojson", "crowns.csv", "canopy_mask.png", "overlay.png", "summary.txt", "LIMITATIONS.md"}
check("audit zip complete", need <= names, ", ".join(sorted(names)))
man = json.loads(z.read("manifest.json"))
keys = ["job_id", "created_utc", "software", "input", "aoi_geojson", "m_per_px", "vegetation_index", "canopy_mask", "segmentation", "solar", "library_versions"]
check("manifest has required fields", all(k in man for k in keys) and "sha256" in man["input"], "")
txt = z.read("summary.txt").decode() + json.dumps(man) + json.dumps(sample)
check("no carbon figures", not any(w in txt.lower() for w in ("tco2", "co2e", "tonnes of carbon", "biomass:")), "")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
