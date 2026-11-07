"""Spacing and crossfires: how far you play from your teammates, and from which angle.

Measured on the first 13 stored matches (2-second trades):
- Spacing decides trades. A death with a teammate within 150 units was traded 38% of the time,
  150-300 units 26%, 600-900 units 8%, past 1,600 almost never.
- Crossfires (a teammate at 45 degrees or more from you, seen from the killer) did NOT produce more
  quick trades than playing the same line (22% vs 26% of deaths). A crossfire's value is likely
  stopping the kill in the first place, which death data can't measure, so crossfires are shown,
  not graded.

Trade rates per distance band are computed from the pool (spacing_rates), like the other models.
"""

import numpy as np
import pandas as pd

from cs2_insights.fights import TRADE_SECONDS

# Nearest teammate's distance to you when you die, in game units.
BANDS = [0, 300, 600, 900, 100_000]
BAND_LABELS = ["Close (under 300)", "Near (300-600)", "Far (600-900)", "Alone (900+)"]
CLOSE_ENOUGH = 300
CROSSFIRE_ANGLE = 45  # degrees between you and a teammate, seen from the killer
# Fallback trade rates per band (first 13 matches) when the pool is too small to measure.
DEFAULT_RATES = {"Close (under 300)": 0.29, "Near (300-600)": 0.18, "Far (600-900)": 0.08, "Alone (900+)": 0.04}
MIN_DEATHS_PER_BAND = 30


def band(distance: float | None) -> str:
    """The spacing band for a nearest-teammate distance; no teammate alive counts as alone."""
    if distance is None or pd.isna(distance):
        return BAND_LABELS[-1]
    return BAND_LABELS[int(np.searchsorted(BANDS, distance, side="right")) - 1]


def separation(victim_xy, mate_xy, killer_xy) -> float:
    """Degrees between the victim and a teammate, seen from the killer: wide means a crossfire."""
    v = np.subtract(victim_xy, killer_xy)
    m = np.subtract(mate_xy, killer_xy)
    norms = np.linalg.norm(v) * np.linalg.norm(m)
    return float(np.degrees(np.arccos(np.clip(v @ m / norms, -1, 1)))) if norms else 0.0


def death_spacing(deaths: pd.DataFrame, chances: pd.DataFrame) -> pd.DataFrame:
    """Per death: the nearest living teammate's distance, its band, whether the death was traded,
    and whether any teammate in trading range had a crossfire on the killer."""
    keys = ["match_id", "tick", "victim"] if "match_id" in deaths and "match_id" in chances else ["tick", "victim"]
    rows = deaths[keys + ["round", "victim_x", "victim_y", "killer_x", "killer_y", "trade_seconds"]].copy()
    if len(chances):
        nearest = chances.groupby(keys)["distance_to_victim"].min().rename("nearest")
        rows = rows.merge(nearest, left_on=keys, right_index=True, how="left")
        merged = chances.merge(rows[keys + ["victim_x", "victim_y", "killer_x", "killer_y"]], on=keys)
        merged = merged[(merged["distance_to_killer"] <= 900) & merged["mate_x"].notna() & merged["victim_x"].notna()]
        merged["angle"] = [separation((r.victim_x, r.victim_y), (r.mate_x, r.mate_y), (r.killer_x, r.killer_y))
                           for r in merged.itertuples()]
        widest = merged.groupby(keys)["angle"].max().rename("widest_angle")
        rows = rows.merge(widest, left_on=keys, right_index=True, how="left")
    else:
        rows["nearest"] = np.nan
        rows["widest_angle"] = np.nan
    rows["band"] = rows["nearest"].map(band)
    rows["traded"] = rows["trade_seconds"].le(TRADE_SECONDS)
    rows["crossfire"] = rows["widest_angle"] >= CROSSFIRE_ANGLE
    return rows


def spacing_rates(pool_spacing: pd.DataFrame) -> dict[str, float]:
    """Share of deaths traded within 2 s in each band across the pool; thin bands fall back to defaults."""
    rates = dict(DEFAULT_RATES)
    for name, group in pool_spacing.groupby("band"):
        if len(group) >= MIN_DEATHS_PER_BAND:
            rates[name] = float(group["traded"].mean())
    return rates


def crossfire_finding(pool_spacing: pd.DataFrame) -> tuple[float, float, int] | None:
    """Trade rates for deaths with and without a crossfire set up, among deaths with a teammate in range."""
    in_range = pool_spacing.dropna(subset=["widest_angle"])
    if len(in_range) < 2 * MIN_DEATHS_PER_BAND:
        return None
    cross = in_range[in_range["crossfire"]]["traded"].mean()
    line = in_range[~in_range["crossfire"]]["traded"].mean()
    return float(cross), float(line), len(in_range)


def spacing_summary(mine: pd.DataFrame, rates: dict[str, float]) -> dict:
    """Your deaths by spacing, and the trades you'd expect if the far ones had been close."""
    if mine.empty:
        return {"deaths": 0}
    counts = mine["band"].value_counts().reindex(BAND_LABELS, fill_value=0)
    far = mine[mine["band"].isin(BAND_LABELS[2:])]
    gained = sum(rates[BAND_LABELS[0]] - rates[b] for b in far["band"])
    return {
        "deaths": len(mine),
        "close": int(counts[BAND_LABELS[0]]),
        "far": len(far),
        "median_nearest": float(mine["nearest"].median()) if mine["nearest"].notna().any() else None,
        "counts": counts.to_dict(),
        "extra_trades_if_close": round(float(gained), 1),
    }
