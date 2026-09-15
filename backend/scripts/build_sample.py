"""Precompute the sample forest result served by GET /api/sample, and verify determinism.

Run from backend/:  python scripts/build_sample.py
"""

import filecmp
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import ingest, run_pipeline  # noqa: E402

HERE = Path(__file__).resolve().parents[1] / "app" / "samples"
spec = json.loads((HERE / "sample_aoi.json").read_text(encoding="utf-8"))
aoi = ingest.parse_geojson(spec["aoi"])
parsed = ingest.ParsedInput("drawn", aoi, None, ingest.sha256_bytes(json.dumps(spec["aoi"], sort_keys=True).encode()), None)

out = HERE / "sample"
tmp = Path(tempfile.mkdtemp())
for d in (out, tmp):
    if d.exists():
        shutil.rmtree(d)
    run_pipeline("sample", d, parsed, spec["params"], lambda s, m: print(f"  {s}: {m}"), created_utc="2026-09-14T00:00:00Z")

same = filecmp.cmp(out / "crowns.geojson", tmp / "crowns.geojson", shallow=False)
print("Determinism check (crowns.geojson byte-identical across two runs):", "PASS" if same else "FAIL")
shutil.rmtree(tmp)
s = json.loads((out / "result.json").read_text(encoding="utf-8"))["summary"]
print(json.dumps({k: s[k] for k in ("aoi_area_ha", "canopy_cover_pct", "crown_count", "crown_count_range", "confidence_breakdown", "rejected_regions")}))
sys.exit(0 if same else 1)
