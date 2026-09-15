"""Web Mercator math, ground resolution, UTM selection and area helpers.

Every area figure in CANOPY is a function of metres-per-pixel, so this module
is deliberately small, pure, and covered by tests/test_geo.py.
"""

from __future__ import annotations

import math

from pyproj import CRS, Transformer
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import transform as shp_transform

EARTH_RADIUS_M = 6378137.0
# Ground resolution of one pixel at zoom 0 on the equator, for 256px tiles.
MERCATOR_RES_Z0 = 156543.03392804097
ORIGIN_SHIFT = math.pi * EARTH_RADIUS_M  # 20037508.342789244
TILE_SIZE = 256


def mercator_m_per_px(lat_deg: float, zoom: int) -> float:
    """Ground metres per pixel for a Web Mercator XYZ tile at a latitude."""
    return (MERCATOR_RES_Z0 * math.cos(math.radians(lat_deg))) / (2**zoom)


def mercator_nominal_px(zoom: int) -> float:
    """Size of one pixel in EPSG:3857 projected units (not ground metres)."""
    return MERCATOR_RES_Z0 / (2**zoom)


def lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    """Standard slippy-map tile index containing a lon/lat."""
    n = 2**zoom
    x = int(math.floor((lon + 180.0) / 360.0 * n))
    lat_r = math.radians(lat)
    y = int(math.floor((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n))
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def lonlat_to_mercator(lon: float, lat: float) -> tuple[float, float]:
    x = math.radians(lon) * EARTH_RADIUS_M
    y = math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0)) * EARTH_RADIUS_M
    return x, y


def mercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = math.degrees(x / EARTH_RADIUS_M)
    lat = math.degrees(2.0 * math.atan(math.exp(y / EARTH_RADIUS_M)) - math.pi / 2.0)
    return lon, lat


def tile_origin_mercator(tx: int, ty: int, zoom: int) -> tuple[float, float]:
    """EPSG:3857 coordinate of a tile's top-left corner."""
    res = mercator_nominal_px(zoom)
    return tx * TILE_SIZE * res - ORIGIN_SHIFT, ORIGIN_SHIFT - ty * TILE_SIZE * res


def utm_epsg(lon: float, lat: float) -> int:
    """EPSG code of the UTM zone containing a lon/lat."""
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    zone = min(max(zone, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


def _transformer(src: CRS | str | int, dst: CRS | str | int) -> Transformer:
    return Transformer.from_crs(CRS.from_user_input(src), CRS.from_user_input(dst), always_xy=True)


def reproject_geom(geom, src, dst):
    t = _transformer(src, dst)
    return shp_transform(lambda x, y, z=None: t.transform(x, y), geom)


def polygon_area_m2(poly_lonlat: Polygon) -> float:
    """Planar area in the AOI's own UTM zone. Accurate to well under 0.1% for AOIs under 1 km²."""
    c = poly_lonlat.centroid
    return float(reproject_geom(poly_lonlat, 4326, utm_epsg(c.x, c.y)).area)


def latitude_resolution_spread(poly_lonlat: Polygon, zoom: int) -> dict:
    """Min/max ground resolution across the AOI's latitude span (a stated error source)."""
    minx, miny, maxx, maxy = poly_lonlat.bounds
    r_top = mercator_m_per_px(maxy, zoom)
    r_bot = mercator_m_per_px(miny, zoom)
    lo, hi = min(r_top, r_bot), max(r_top, r_bot)
    return {
        "lat_span_deg": round(maxy - miny, 6),
        "m_per_px_min": round(lo, 6),
        "m_per_px_max": round(hi, 6),
        "relative_variation_pct": round(100.0 * (hi - lo) / hi, 4) if hi else 0.0,
    }


def geojson_to_shape(geojson: dict):
    return shape(geojson)


def shape_to_geojson(geom) -> dict:
    return mapping(geom)
