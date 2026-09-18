"""Throw hostile and odd inputs at a running API and check each one ends cleanly.

"Cleanly" means: the upload is refused with a 4xx and a plain-language message, or it is accepted and its run
either succeeds or fails with a named error code. Never a 500, a hang, or a Python traceback in the message.

    python scripts/robustness_check.py            # against http://localhost:8000
    python scripts/robustness_check.py --api http://host:8000
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile

import numpy as np
import rasterio
import requests
from rasterio.transform import from_origin

LON, LAT = -5.930, 39.8297  # open dehesa at Monfragüe, the sample area


def tif(arr: np.ndarray, crs="EPSG:32630", res=0.3, dtype=None, nodata=None, desc=None, origin=(254_000, 4_412_000)) -> bytes:
    arr = arr if arr.ndim == 3 else arr[None]
    buf = io.BytesIO()
    with rasterio.MemoryFile() as mf:
        kw = dict(driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0], dtype=dtype or arr.dtype, transform=from_origin(origin[0], origin[1], res, res))
        if crs:
            kw["crs"] = crs
        if nodata is not None:
            kw["nodata"] = nodata
        with mf.open(**kw) as dst:
            dst.write(arr.astype(dtype or arr.dtype))
            if desc:
                dst.descriptions = desc
        buf.write(mf.read())
    return buf.getvalue()


def ring(dlon=0.0015, dlat=0.0012, lon=LON, lat=LAT):
    return [[lon, lat], [lon + dlon, lat], [lon + dlon, lat + dlat], [lon, lat + dlat], [lon, lat]]


def kml(body: str) -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>{body}</Document></kml>'.encode()


def placemark(coords, name="Plot") -> str:
    c = " ".join(f"{x},{y}" for x, y in coords)
    return f"<Placemark><name>{name}</name><Polygon><outerBoundaryIs><LinearRing><coordinates>{c}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"


def kmz(kml_bytes: bytes, inner="doc.kml") -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(inner, kml_bytes)
    return b.getvalue()


def cases() -> list[tuple[str, str, bytes]]:
    rng = np.random.default_rng(0)
    rgb = (rng.random((3, 300, 300)) * 255).astype(np.uint8)
    gj = lambda geom: json.dumps({"type": "Feature", "properties": {}, "geometry": geom}).encode()  # noqa: E731
    bowtie = [[LON, LAT], [LON + 0.001, LAT + 0.001], [LON + 0.001, LAT], [LON, LAT + 0.001], [LON, LAT]]
    return [
        # --- files that are not what they claim
        ("empty file", "empty.kml", b""),
        ("binary junk as .tif", "junk.tif", rng.bytes(5000)),
        ("html renamed .kml", "page.kml", b"<html><body>not a kml</body></html>"),
        ("truncated KML", "cut.kml", kml(placemark(ring()))[:120]),
        ("unsupported extension", "trees.shp", b"\x00" * 100),
        ("PNG renamed .tif", "img.tif", b"\x89PNG\r\n\x1a\n" + rng.bytes(200)),
        ("zip that is not KMZ", "a.kmz", kmz(b"hello", inner="readme.txt")),
        ("corrupt zip as KMZ", "b.kmz", b"PK\x03\x04" + rng.bytes(300)),
        ("XML entity bomb", "bomb.kml", b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;"><!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">]><kml>&d;</kml>'),
        ("external entity (XXE)", "xxe.kml", b'<?xml version="1.0"?><!DOCTYPE k [<!ENTITY x SYSTEM "file:///etc/passwd">]><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>&x;</name></Document></kml>'),
        # --- boundaries that are valid files but bad areas
        ("KML with no polygon", "pt.kml", kml("<Placemark><Point><coordinates>-5.93,39.83</coordinates></Point></Placemark>")),
        ("self-intersecting (bow-tie)", "bowtie.kml", kml(placemark(bowtie))),
        ("tiny area (< 100 m²)", "tiny.geojson", gj({"type": "Polygon", "coordinates": [ring(0.00005, 0.00005)]})),
        ("huge area (> 1 km²)", "huge.geojson", gj({"type": "Polygon", "coordinates": [ring(0.05, 0.05)]})),
        ("lat/lon swapped", "swap.geojson", gj({"type": "Polygon", "coordinates": [[[y, x] for x, y in ring()]]})),
        ("coordinates out of range", "oob.geojson", gj({"type": "Polygon", "coordinates": [[[200, 95], [201, 95], [201, 96], [200, 95]]]})),
        ("open ring (unclosed)", "open.geojson", gj({"type": "Polygon", "coordinates": [ring()[:-1]]})),
        ("two-point polygon", "line.geojson", gj({"type": "Polygon", "coordinates": [[[LON, LAT], [LON + 0.001, LAT], [LON, LAT]]]})),
        ("empty FeatureCollection", "fc.geojson", json.dumps({"type": "FeatureCollection", "features": []}).encode()),
        ("GeoJSON with NaN", "nan.geojson", b'{"type":"Polygon","coordinates":[[[NaN,1],[2,2],[3,1],[NaN,1]]]}'),
        ("3D coordinates + holes", "hole.geojson", gj({"type": "Polygon", "coordinates": [[[x, y, 400] for x, y in ring()], [[x, y, 400] for x, y in ring(0.0003, 0.0003, LON + 0.0005, LAT + 0.0004)]]})),
        ("KMZ with nested folder", "nested.kmz", kmz(kml(placemark(ring())), inner="files/doc/plot.kml")),
        ("multi-placemark KML", "multi.kml", kml(placemark(ring(), "A") + placemark(ring(lon=LON + 0.003), "B"))),
        # --- rasters
        ("GeoTIFF without CRS", "nocrs.tif", tif(rgb, crs=None)),
        ("single-band GeoTIFF", "gray.tif", tif(rgb[:1])),
        ("2-band GeoTIFF", "two.tif", tif(rgb[:2])),
        ("all-black image", "black.tif", tif(np.zeros((3, 300, 300), np.uint8))),
        ("all-white image", "white.tif", tif(np.full((3, 300, 300), 255, np.uint8))),
        ("uniform green (all canopy)", "green.tif", tif(np.stack([np.full((300, 300), v, np.uint8) for v in (40, 110, 35)]))),
        ("1×1 pixel image", "px.tif", tif(rgb[:, :1, :1])),
        ("16-bit RGB", "u16.tif", tif((rgb.astype(np.uint16) * 257))),
        ("float RGB with NaN nodata", "f32.tif", tif(np.where(rng.random((3, 300, 300)) < 0.2, np.nan, rgb / 255.0).astype(np.float32), dtype="float32", nodata=np.nan)),
        ("RGBA with transparent half", "rgba.tif", tif(np.concatenate([rgb, np.where(np.arange(300)[None, None, :] < 150, 0, 255).repeat(300, 1).astype(np.uint8)]))),
        ("geographic CRS GeoTIFF", "wgs.tif", tif(rgb, crs="EPSG:4326", res=0.000003, origin=(LON, LAT + 0.0009))),
        ("very coarse (10 m) GeoTIFF", "coarse.tif", tif(rgb[:, :50, :50], res=10)),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--timeout", type=float, default=240)
    args = ap.parse_args()
    bad = 0
    for label, name, data in cases():
        try:
            r = requests.post(f"{args.api}/api/projects", files={"file": (name, data)}, data={"name": f"[robustness] {label}", "params": "{}"}, timeout=120)
        except requests.RequestException as exc:
            print(f"FAIL  {label:32s} request error {exc}")
            bad += 1
            continue
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 500:
            print(f"FAIL  {label:32s} HTTP {r.status_code}: {r.text[:160]}")
            bad += 1
            continue
        if r.status_code >= 400:
            msg = body.get("error_message", "")
            ok = bool(msg) and "Traceback" not in msg
            print(f"{'ok  ' if ok else 'FAIL'}  {label:32s} refused  {r.status_code} {body.get('error_code')}: {msg[:110]}")
            bad += not ok
            continue
        run = body.get("run")
        pid = body["project"]["id"]
        if not run:
            print(f"ok    {label:32s} accepted (area picker, no run started)")
            requests.delete(f"{args.api}/api/projects/{pid}", timeout=30)
            continue
        t0, status = time.time(), {}
        while time.time() - t0 < args.timeout:
            status = requests.get(f"{args.api}/api/jobs/{run['id']}", timeout=30).json()
            if status["status"] in ("succeeded", "failed"):
                break
            time.sleep(1.5)
        st = status.get("status")
        msg = status.get("error_message") or ""
        ok = st == "succeeded" or (st == "failed" and status.get("error_code") not in (None, "internal_error") and "Traceback" not in msg)
        detail = f"{status.get('error_code')}: {msg[:100]}" if st == "failed" else ""
        print(f"{'ok  ' if ok else 'FAIL'}  {label:32s} run {st} {detail}")
        bad += not ok
        requests.delete(f"{args.api}/api/projects/{pid}", timeout=30)
    print(f"\n{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
