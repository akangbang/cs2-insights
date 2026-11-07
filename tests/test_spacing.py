import pandas as pd
import pytest

from cs2_insights import spacing


def test_bands_and_alone():
    assert spacing.band(120) == "Close (under 300)"
    assert spacing.band(450) == "Near (300-600)"
    assert spacing.band(750) == "Far (600-900)"
    assert spacing.band(1_400) == "Alone (900+)"
    assert spacing.band(None) == "Alone (900+)"  # no teammate alive


def test_separation_is_the_angle_seen_from_the_killer():
    killer = (0, 0)
    assert spacing.separation((100, 0), (300, 0), killer) == pytest.approx(0)  # same line
    assert spacing.separation((100, 0), (0, 100), killer) == pytest.approx(90)  # crossfire


def _deaths(rows):
    return pd.DataFrame([{"round": r, "tick": t, "victim": v, "victim_x": 0.0, "victim_y": 0.0, "killer_x": 500.0, "killer_y": 0.0,
                          "trade_seconds": ts} for r, t, v, ts in rows])


def _chances(rows):
    return pd.DataFrame([{"tick": t, "victim": v, "mate": m, "distance_to_victim": dv, "distance_to_killer": dk,
                          "mate_x": mx, "mate_y": my} for t, v, m, dv, dk, mx, my in rows])


def test_death_spacing_finds_nearest_teammate_and_crossfire():
    deaths = _deaths([(1, 10, "me", 1.0), (2, 20, "me", None), (3, 30, "me", None)])
    chances = _chances([
        (10, "me", "a", 150.0, 400.0, -150.0, 0.0),  # close, same line behind me
        (10, "me", "b", 900.0, 600.0, 500.0, 600.0),  # in range of the killer, at 90 degrees: a crossfire
        (20, "me", "a", 1_200.0, 1_500.0, -1_200.0, 0.0),  # far away
    ])  # round 3: nobody alive
    rows = spacing.death_spacing(deaths, chances).set_index("round")
    assert rows.at[1, "band"] == "Close (under 300)" and rows.at[1, "traded"] and rows.at[1, "crossfire"]
    assert rows.at[2, "band"] == "Alone (900+)" and not rows.at[2, "traded"]
    assert rows.at[3, "band"] == "Alone (900+)" and pd.isna(rows.at[3, "nearest"])


def test_rates_fall_back_when_thin_and_summary_counts_far_deaths():
    pool = pd.DataFrame({"band": ["Close (under 300)"] * 40 + ["Alone (900+)"] * 5, "traded": [True] * 20 + [False] * 25,
                         "widest_angle": [None] * 45, "crossfire": [False] * 45})
    rates = spacing.spacing_rates(pool)
    assert rates["Close (under 300)"] == pytest.approx(0.5)  # 20 of 40, enough to measure
    assert rates["Alone (900+)"] == spacing.DEFAULT_RATES["Alone (900+)"]  # only 5: default
    mine = pd.DataFrame({"band": ["Close (under 300)", "Alone (900+)", "Far (600-900)"], "nearest": [100.0, None, 700.0]})
    summary = spacing.spacing_summary(mine, rates)
    assert (summary["deaths"], summary["close"], summary["far"]) == (3, 1, 2)
    assert summary["extra_trades_if_close"] == pytest.approx(round(0.5 - rates["Alone (900+)"] + 0.5 - rates["Far (600-900)"], 1))
    assert spacing.crossfire_finding(pool) is None  # no deaths with a teammate in range
