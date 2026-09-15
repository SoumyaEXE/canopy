"""Stage 6: shadow-derived crown height. Pure trigonometry, no learning.

height_m = shadow_length_m * tan(sun_elevation)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
from skimage.color import rgb2hsv
from skimage.filters import threshold_otsu

MAX_SHADOW_M = 60.0
MIN_SHADOW_PX = 3
MIN_ELEVATION = 10.0
MAX_ELEVATION = 70.0
MIN_HEIGHT_M = 1.0
MAX_HEIGHT_M = 80.0
SHADOW_MAX_SATURATION = 0.5


def solar_position(dt_utc: datetime, lat: float, lon: float) -> tuple[float, float]:
    """NOAA solar position algorithm (the NOAA Solar Calculator spreadsheet equations).

    Returns (elevation_deg, azimuth_deg clockwise from true north). Elevation
    includes the NOAA atmospheric refraction approximation.
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    dt_utc = dt_utc.astimezone(timezone.utc)
    # Julian day
    y, m = dt_utc.year, dt_utc.month
    d = dt_utc.day + (dt_utc.hour + dt_utc.minute / 60 + dt_utc.second / 3600) / 24
    if m <= 2:
        y, m = y - 1, m + 12
    a = y // 100
    b = 2 - a + a // 4
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5
    jc = (jd - 2451545.0) / 36525.0

    geom_mean_long = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    geom_mean_anom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    ecc = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    mrad = math.radians(geom_mean_anom)
    eq_ctr = (
        math.sin(mrad) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
        + math.sin(2 * mrad) * (0.019993 - 0.000101 * jc)
        + math.sin(3 * mrad) * 0.000289
    )
    true_long = geom_mean_long + eq_ctr
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    mean_obliq = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    obliq_corr = mean_obliq + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(obliq_corr)) * math.sin(math.radians(app_long))))
    var_y = math.tan(math.radians(obliq_corr / 2)) ** 2
    lrad = math.radians(geom_mean_long)
    eq_time = 4 * math.degrees(
        var_y * math.sin(2 * lrad)
        - 2 * ecc * math.sin(mrad)
        + 4 * ecc * var_y * math.sin(mrad) * math.cos(2 * lrad)
        - 0.5 * var_y * var_y * math.sin(4 * lrad)
        - 1.25 * ecc * ecc * math.sin(2 * mrad)
    )
    minutes = dt_utc.hour * 60 + dt_utc.minute + dt_utc.second / 60
    true_solar_time = (minutes + eq_time + 4 * lon) % 1440
    hour_angle = true_solar_time / 4 - 180 if true_solar_time / 4 >= 0 else true_solar_time / 4 + 180

    lat_r, decl_r, ha_r = math.radians(lat), math.radians(decl), math.radians(hour_angle)
    cos_zen = math.sin(lat_r) * math.sin(decl_r) + math.cos(lat_r) * math.cos(decl_r) * math.cos(ha_r)
    zenith = math.degrees(math.acos(max(-1.0, min(1.0, cos_zen))))
    elev = 90 - zenith
    # Atmospheric refraction (NOAA approximation)
    if elev > 85:
        refr = 0.0
    else:
        te = math.tan(math.radians(elev))
        if elev > 5:
            refr = 58.1 / te - 0.07 / te**3 + 0.000086 / te**5
        elif elev > -0.575:
            refr = 1735 + elev * (-518.2 + elev * (103.4 + elev * (-12.79 + elev * 0.711)))
        else:
            refr = -20.772 / te
        refr /= 3600
    elev_corr = elev + refr

    zr = math.radians(zenith)
    denom = math.cos(lat_r) * math.sin(zr)
    if abs(denom) < 1e-9:
        az = 180.0
    else:
        cos_az = (math.sin(lat_r) * math.cos(zr) - math.sin(decl_r)) / denom
        az_raw = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
        az = (az_raw + 180) % 360 if hour_angle > 0 else (540 - az_raw) % 360
    return elev_corr, az


def shadow_mask(rgb: np.ndarray, canopy: np.ndarray, aoi: np.ndarray) -> tuple[np.ndarray, dict]:
    hsv = rgb2hsv(rgb)
    s, v = hsv[..., 1], hsv[..., 2]
    ground = (~canopy) & aoi
    vals = v[ground]
    v_thr = float(threshold_otsu(vals)) if vals.size > 16 and vals.min() < vals.max() else 0.0
    mask = (~canopy) & (v < v_thr) & (s < SHADOW_MAX_SATURATION)
    return mask, {
        "shadow_v_threshold_otsu_on_non_canopy": round(v_thr, 4),
        "shadow_max_saturation": SHADOW_MAX_SATURATION,
        "shadow_pixels": int(mask.sum()),
    }


def trace_ray(
    start_x: float, start_y: float, dx: float, dy: float, own_label: int, labels: np.ndarray, shadow: np.ndarray, max_px: int
) -> tuple[int, str]:
    """March outward from a point inside a crown. Returns (consecutive shadow px, outcome)."""
    h, w = labels.shape
    step = 0
    # Leave the crown first.
    while True:
        step += 1
        col, row = int(round(start_x + dx * step)), int(round(start_y + dy * step))
        if not (0 <= row < h and 0 <= col < w):
            return 0, "left_image"
        if labels[row, col] != own_label:
            break
        if step > max_px * 4:
            return 0, "no_edge"
    count = 0
    while count < max_px:
        col, row = int(round(start_x + dx * step)), int(round(start_y + dy * step))
        if not (0 <= row < h and 0 <= col < w):
            return count, "left_image"
        lab = labels[row, col]
        if lab != 0 and lab != own_label:
            return count, "occluded"
        if not shadow[row, col]:
            return count, "ok"
        count += 1
        step += 1
    return count, "cap"


def measure_heights(
    crowns: list[dict],
    labels: np.ndarray,
    shadow: np.ndarray,
    m_per_px: float,
    sun_elevation: float,
    sun_azimuth: float,
) -> dict:
    """Mutates each crown with height_m (or None) and height_reason. Returns aggregate counts."""
    shadow_dir = (sun_azimuth + 180.0) % 360.0
    dx = math.sin(math.radians(shadow_dir))
    dy = -math.cos(math.radians(shadow_dir))
    px, py = -dy, dx  # perpendicular unit vector
    max_px = int(MAX_SHADOW_M / m_per_px)
    outcomes = {"measured": 0, "occluded": 0, "too_short": 0, "implausible_height": 0, "no_shadow": 0}

    global_reason = None
    if sun_elevation > MAX_ELEVATION:
        global_reason = f"sun elevation {sun_elevation:.1f}° is above {MAX_ELEVATION:.0f}°: shadows too short to measure"
    elif sun_elevation < MIN_ELEVATION:
        global_reason = f"sun elevation {sun_elevation:.1f}° is below {MIN_ELEVATION:.0f}°: shadows overlap everything"

    tan_el = math.tan(math.radians(sun_elevation))
    for c in crowns:
        if global_reason:
            c["height_m"], c["shadow_length_m"], c["height_reason"] = None, None, "sun_angle"
            continue
        cx, cy = c["centroid_px"]
        off = c["_eq_radius_px"] / 4.0
        starts = [(cx, cy), (cx + px * off, cy + py * off), (cx - px * off, cy - py * off)]
        lengths, occluded = [], 0
        for sx, sy in starts:
            n, outcome = trace_ray(sx, sy, dx, dy, c["label"], labels, shadow, max_px)
            if outcome == "occluded":
                occluded += 1
            else:
                lengths.append(n)
        if occluded >= 2 or not lengths:
            c["height_m"], c["shadow_length_m"], c["height_reason"] = None, None, "occluded"
            outcomes["occluded"] += 1
            continue
        med = float(np.median(lengths))
        if med == 0:
            c["height_m"], c["shadow_length_m"], c["height_reason"] = None, None, "no_shadow"
            outcomes["no_shadow"] += 1
            continue
        if med < MIN_SHADOW_PX:
            c["height_m"], c["shadow_length_m"], c["height_reason"] = None, None, "too_short"
            outcomes["too_short"] += 1
            continue
        length_m = med * m_per_px
        h = length_m * tan_el
        if not (MIN_HEIGHT_M <= h <= MAX_HEIGHT_M):
            c["height_m"], c["shadow_length_m"], c["height_reason"] = None, round(length_m, 3), "implausible_height"
            outcomes["implausible_height"] += 1
            continue
        c["height_m"], c["shadow_length_m"], c["height_reason"] = round(h, 2), round(length_m, 3), "measured"
        outcomes["measured"] += 1

    return {
        "shadow_direction_deg": round(shadow_dir, 3),
        "max_shadow_trace_m": MAX_SHADOW_M,
        "rays_per_crown": 3,
        "ray_offset": "quarter of equivalent crown radius, perpendicular to shadow direction",
        "global_gate": global_reason,
        "outcomes": outcomes,
        "gates": {
            "sun_elevation_deg": [MIN_ELEVATION, MAX_ELEVATION],
            "min_shadow_px": MIN_SHADOW_PX,
            "height_m": [MIN_HEIGHT_M, MAX_HEIGHT_M],
            "occluded_if": "2 or more of 3 rays end inside another crown",
        },
    }
