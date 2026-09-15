from app.pipeline.calibration import calibrate


def _crown(index: int, positive: bool) -> dict:
    return {
        "properties": {
            "id": index,
            "area_m2": 30 if positive else 180,
            "equivalent_diameter_m": 6 if positive else 15,
            "solidity": 0.9 if positive else 0.5,
            "confidence": 0.9 if positive else 0.3,
            "signals": {
                "separation": 0.9 if positive else 0.3,
                "size": 0.9 if positive else 0.2,
                "shape": 0.9 if positive else 0.4,
            },
        }
    }


def test_calibration_scales_to_full_detector_count():
    crowns = [_crown(i, i < 5) for i in range(10)]
    result = calibrate(crowns, set(range(5)), recall=0.8, total_count=100)

    assert result["available"] is True
    assert result["estimated_count"] > len(crowns)
    assert result["estimated_count"] < 100
    assert result["estimated_range"][1] >= result["estimated_count"]


def test_calibration_requires_both_classes():
    crowns = [_crown(i, True) for i in range(8)]
    result = calibrate(crowns, set(range(8)), recall=1.0, total_count=100)

    assert result["available"] is False