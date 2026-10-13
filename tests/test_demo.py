from pathlib import Path

import pytest

from cs2_insights.demo import buy_type, match_id_from_path, parse_demo

REPLAYS = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\replays")
LOCAL_DEMOS = sorted(REPLAYS.glob("*.dem")) if REPLAYS.exists() else []


def test_match_id_from_valve_name():
    path = Path("match730_003837219510624976953_1410174210_389.dem")
    assert match_id_from_path(path) == "3837219510624976953"


def test_match_id_falls_back_to_file_name():
    assert match_id_from_path(Path("faceit_match.dem")) == "faceit_match"


@pytest.mark.parametrize(
    "round_number, equip, expected",
    [(1, 4_000, "pistol"), (13, 4_000, "pistol"), (2, 4_999, "eco"), (2, 5_000, "force"), (2, 20_000, "force"), (2, 20_001, "full")],
)
def test_buy_type(round_number, equip, expected):
    assert buy_type(round_number, {1, 13}, equip) == expected


@pytest.mark.skipif(not LOCAL_DEMOS, reason="no local CS2 demos")
def test_parse_local_demo():
    parsed = parse_demo(LOCAL_DEMOS[-1])
    match = parsed.match.iloc[0]
    assert max(match["team_a_score"], match["team_b_score"]) >= 13
    assert match["rounds"] == match["team_a_score"] + match["team_b_score"]
    assert len(parsed.team_rounds) == 2 * match["rounds"]
    # Exactly one team wins each round, and the two teams are on opposite sides.
    per_round = parsed.team_rounds.groupby("round")
    assert (per_round["won"].sum() == 1).all()
    assert (per_round["side"].nunique() == 2).all()
    assert set(parsed.team_rounds[parsed.team_rounds["buy_type"] == "pistol"]["round"]) == {1, 13}
