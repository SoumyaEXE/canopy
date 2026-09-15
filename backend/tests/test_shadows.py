import math
from datetime import datetime, timezone

import numpy as np
import pytest

from app.pipeline import shadows


def test_height_from_known_shadow():
    m = 0.5
    labels = np.zeros((200, 200), dtype=np.int32)
    yy, xx = np.ogrid[:200, :200]
    crown = (yy - 100) ** 2 + (xx - 100) ** 2 <= 8**2
    labels[crown] = 1
    shadow = np.zeros_like(crown)
    # Sun due south (azimuth 180) -> shadow falls north, i.e. up the image.
    L_px = 20
    for x in range(90, 111):
        col = crown[:, x]
        top = int(np.argmax(col)) if col.any() else 100
        shadow[top - L_px : top, x] = True
    crown_list = [{"label": 1, "centroid_px": [100.0, 100.0], "_eq_radius_px": 8.0}]
    elevation = 40.0
    info = shadows.measure_heights(crown_list, labels, shadow, m, elevation, 180.0)
    expected = L_px * m * math.tan(math.radians(elevation))
    assert info["outcomes"]["measured"] == 1
    assert crown_list[0]["height_m"] == pytest.approx(expected, rel=0.08)


def test_high_sun_disables_height():
    labels = np.zeros((20, 20), dtype=np.int32)
    labels[8:12, 8:12] = 1
    crown_list = [{"label": 1, "centroid_px": [10.0, 10.0], "_eq_radius_px": 2.0}]
    info = shadows.measure_heights(crown_list, labels, np.zeros((20, 20), bool), 0.5, 75.0, 180.0)
    assert info["global_gate"] is not None
    assert crown_list[0]["height_m"] is None


def test_solar_noon_geometry():
    # At the June solstice near local solar noon, elevation = 90 - |lat - declination(23.44)|, sun due south.
    el, az = shadows.solar_position(datetime(2020, 6, 21, 12, 2, tzinfo=timezone.utc), 40.0, 0.0)
    assert el == pytest.approx(90 - (40.0 - 23.44), abs=0.3)
    assert az == pytest.approx(180.0, abs=2.0)


def test_morning_sun_in_east():
    el, az = shadows.solar_position(datetime(2020, 6, 21, 14, 0, tzinfo=timezone.utc), 40.0, -105.0)
    assert 60 < az < 110 and el > 10
