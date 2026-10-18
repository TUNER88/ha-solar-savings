"""Pure math for Solar Savings. No Home Assistant imports."""

from __future__ import annotations

from collections.abc import Mapping

from .const import RESET_THRESHOLD


def kept_by_source(production: Mapping[str, float], export: float) -> dict[str, float]:
    """Split one hour's kept solar across sources.

    Kept solar for the hour is max(0, produced - exported). The hour's export is
    shared by production share, so each source keeps
    produced_i * (1 - exported / produced), floored at zero.
    """
    produced = {key: max(value, 0.0) for key, value in production.items()}
    total = sum(produced.values())
    export = max(export, 0.0)
    if total <= 0.0:
        return dict.fromkeys(produced, 0.0)
    share_kept = max(0.0, total - export) / total
    return {key: value * share_kept for key, value in produced.items()}


def meter_delta(last: float | None, current: float) -> tuple[float, float]:
    """Return (growth in kWh, new reference reading) for a cumulative meter.

    - No reference yet: start counting from here, no growth.
    - Rising: the difference is growth.
    - Falling below RESET_THRESHOLD of the last reading: a meter reset. The new
      reading is growth since the reset, so there is no spike.
    - Falling a little: a glitch. Ignore it and keep the old reference, so the
      recovery is not counted twice.
    """
    if last is None:
        return 0.0, current
    if current >= last:
        return current - last, current
    if current < last * RESET_THRESHOLD:
        return max(current, 0.0), current
    return 0.0, last
