"""Pure math tests."""

import pytest

from custom_components.solar_savings.calc import kept_by_source, meter_delta


def test_kept_is_production_minus_export() -> None:
    assert kept_by_source({"a": 10.0}, 4.0) == {"a": pytest.approx(6.0)}


def test_kept_never_negative() -> None:
    assert kept_by_source({"a": 2.0}, 5.0) == {"a": 0.0}


def test_export_split_by_production_share() -> None:
    kept = kept_by_source({"a": 6.0, "b": 2.0}, 4.0)
    assert kept["a"] == pytest.approx(3.0)
    assert kept["b"] == pytest.approx(1.0)


def test_no_production() -> None:
    assert kept_by_source({"a": 0.0}, 1.0) == {"a": 0.0}
    assert kept_by_source({}, 1.0) == {}


@pytest.mark.parametrize(
    ("last", "current", "expected"),
    [
        (None, 100.0, (0.0, 100.0)),
        (100.0, 105.0, (5.0, 105.0)),
        (105.0, 0.0, (0.0, 0.0)),  # reset to zero
        (105.0, 2.0, (2.0, 2.0)),  # reset, already counting again
        (105.0, 104.9, (0.0, 105.0)),  # small glitch is ignored
    ],
)
def test_meter_delta(last, current, expected) -> None:
    assert meter_delta(last, current) == pytest.approx(expected)
