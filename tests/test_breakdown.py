import pandas as pd

from cs2_insights.breakdown import Misses, best_and_worst, map_breakdown, side_breakdown, side_notes


def _rounds(ct=12, t=12, match_id="m1", map_name="de_dust2"):
    return pd.DataFrame({"match_id": match_id, "map": map_name, "round": range(1, ct + t + 1), "side": ["CT"] * ct + ["T"] * t})


def _events(*rows, match_id="m1", map_name="de_dust2"):
    return pd.DataFrame([{"match_id": match_id, "map": map_name, "round": i, "side": side, "key": key} for i, (key, side) in enumerate(rows, 1)])


def test_rates_are_per_half_on_each_side():
    misses = Misses(_events(("repeek", "T"), ("repeek", "T"), ("repeek", "CT")), _rounds(ct=12, t=6), pd.DataFrame())
    table = side_breakdown(misses).set_index("side")
    assert table.at["T", "count"] == 2 and table.at["T", "per_half"] == 4.0  # 2 in 6 rounds
    assert table.at["CT", "count"] == 1 and table.at["CT", "per_half"] == 1.0


def test_a_note_only_when_one_side_is_clearly_worse():
    worse_t = Misses(_events(*[("repeek", "T")] * 4, ("repeek", "CT")), _rounds(), pd.DataFrame())
    notes = side_notes(side_breakdown(worse_t))
    assert len(notes) == 1 and "mostly on **T**" in notes[0]
    even = Misses(_events(*[("repeek", "T")] * 3, *[("repeek", "CT")] * 3), _rounds(), pd.DataFrame())
    assert side_notes(side_breakdown(even)) == []
    few = Misses(_events(("repeek", "T"), ("repeek", "T")), _rounds(), pd.DataFrame())
    assert side_notes(side_breakdown(few)) == []  # under 3 misses is too few to call


def test_no_misses_gives_an_empty_table():
    assert side_breakdown(Misses(pd.DataFrame(columns=["key", "side"]), _rounds(), pd.DataFrame())).empty


def _maps():
    matches = pd.DataFrame({"match_id": ["a", "b", "c", "d", "e"], "map": ["de_dust2", "de_dust2", "de_nuke", "de_nuke", "de_inferno"],
                            "won": [True, True, False, True, False]})
    events = pd.concat([
        _events(("repeek", "T"), match_id="a", map_name="de_dust2"),
        _events(("alone", "T"), ("alone", "CT"), ("far", "CT"), match_id="c", map_name="de_nuke"),
        _events(("alone", "T"), ("alone", "T"), match_id="d", map_name="de_nuke"),
        _events(*[("gear", "T")] * 9, match_id="e", map_name="de_inferno"),
    ], ignore_index=True)
    return Misses(events, pd.DataFrame(), matches)


def test_maps_show_win_rate_avoidable_deaths_and_the_main_miss():
    table = map_breakdown(_maps()).set_index("map")
    assert table.at["de_dust2", "win_rate"] == 1.0 and table.at["de_dust2", "avoidable_per_match"] == 0.5
    assert table.at["de_nuke", "avoidable_per_match"] == 2.0  # far deaths aren't avoidable deaths
    assert table.at["de_nuke", "top_key"] == "alone" and table.at["de_nuke", "top_per_match"] == 2.0
    assert table.at["de_nuke", "tip"]


def test_best_and_worst_ignore_maps_played_once():
    best, worst = best_and_worst(map_breakdown(_maps()))
    assert best["map"] == "de_dust2" and worst["map"] == "de_nuke"  # inferno's 9 in one match doesn't count


def test_best_and_worst_need_two_maps():
    one = map_breakdown(Misses(_events(("repeek", "T")), pd.DataFrame(), pd.DataFrame({"match_id": ["m1", "m2"], "map": ["de_dust2"] * 2, "won": [True, False]})))
    assert best_and_worst(one) == (None, None)
