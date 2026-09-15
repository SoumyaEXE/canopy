import math

import pytest
from shapely.geometry import box

from app.pipeline import geo


@pytest.mark.parametrize(
    "lat,zoom,expected",
    [
        # Published Web Mercator ground resolution table (Bing Maps Tile System, 256px tiles).
        (0.0, 0, 156543.03),
        (0.0, 18, 0.5972),
        (0.0, 19, 0.2986),
        (60.0, 18, 0.2986),
    ],
)
def test_resolution_table(lat, zoom, expected):
    assert geo.mercator_m_per_px(lat, zoom) == pytest.approx(expected, rel=1e-3)


def test_cosine_term_matters_at_kolkata():
    # Ignoring cos(lat) at 22.5 degrees inflates linear size by 1/cos, about 8.2%.
    assert 1 / math.cos(math.radians(22.5)) == pytest.approx(1.0824, abs=1e-3)
    assert geo.mercator_m_per_px(22.5, 18) == pytest.approx(0.5972 * math.cos(math.radians(22.5)), rel=1e-3)


@pytest.mark.parametrize(
    "lon,lat,zoom,xy",
    [
        (0.0, 0.0, 1, (1, 1)),
        (-180.0, 85.0, 3, (0, 0)),
        (13.4050, 52.5200, 12, (2200, 1343)),  # Berlin
    ],
)
def test_tile_index(lon, lat, zoom, xy):
    assert geo.lonlat_to_tile(lon, lat, zoom) == xy


def test_tile_contains_point_and_pixel_round_trip():
    zoom = 18
    lon, lat = 88.3426, 22.5448
    tx, ty = geo.lonlat_to_tile(lon, lat, zoom)
    ox, oy = geo.tile_origin_mercator(tx, ty, zoom)
    res = geo.mercator_nominal_px(zoom)
    mx, my = geo.lonlat_to_mercator(lon, lat)
    col, row = (mx - ox) / res, (oy - my) / res
    assert 0 <= col < 256 and 0 <= row < 256
    lon2, lat2 = geo.mercator_to_lonlat(ox + col * res, oy - row * res)
    assert lon2 == pytest.approx(lon, abs=1e-9)
    assert lat2 == pytest.approx(lat, abs=1e-9)


@pytest.mark.parametrize(
    "lon,lat,epsg",
    [
        (-180.0, 10.0, 32601),
        (-174.0001, 10.0, 32601),
        (-174.0, 10.0, 32602),
        (0.0, 0.0, 32631),
        (0.0, -0.0001, 32731),
        (88.36, 22.57, 32645),
        (179.9999, -45.0, 32760),
    ],
)
def test_utm_zone(lon, lat, epsg):
    assert geo.utm_epsg(lon, lat) == epsg


def test_polygon_area_one_hectare():
    d_lat = 100 / 110574.0
    d_lon = 100 / 111320.0
    a = geo.polygon_area_m2(box(10, 0.001, 10 + d_lon, 0.001 + d_lat))
    assert a == pytest.approx(10000, rel=0.01)
