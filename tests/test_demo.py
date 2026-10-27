from pathlib import Path

import pandas as pd
import pytest

from cs2_insights.demo import (
    TRADE_LOOK_SECONDS,
    aim_angle,
    assign_teams,
    buy_type,
    first_rounds_of_halves,
    match_id_from_path,
    pair_rounds,
    parse_demo,
)

REPLAYS = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\replays")
LOCAL_DEMOS = sorted(REPLAYS.glob("*.dem")) if REPLAYS.exists() else []


def test_match_id_from_valve_name():
    path = Path("match730_003837219510624976953_1410174210_389.dem")
    assert match_id_from_path(path) == "3837219510624976953"


def test_match_id_falls_back_to_file_name():
    assert match_id_from_path(Path("faceit_match.dem")) == "faceit_match"


@pytest.mark.parametrize(
    "round_number, equip, expected",
    [(1, 4_000, "pistol"), (13, 4_000, "pistol"), (2, 7_999, "eco"), (2, 8_000, "force"), (2, 18_999, "force"), (2, 19_000, "full")],
)
def test_buy_type(round_number, equip, expected):
    assert buy_type(round_number, {1, 13}, equip) == expected


def test_buy_type_is_per_player():
    # $15,000 is a force for five players but a full buy for four.
    assert buy_type(5, {1, 13}, 15_000, players=5) == "force"
    assert buy_type(5, {1, 13}, 15_200, players=4) == "full"


def test_overtime_halves_are_not_pistols():
    # Overtime halves start at rounds 25, 28, ... with set money, so they are graded by equipment.
    assert buy_type(25, {1, 13, 25, 28}, 25_000) == "full"
    assert buy_type(28, {1, 13, 25, 28}, 4_000) == "eco"


def test_pair_rounds_skips_warmup_and_numbers_without_gaps():
    ends = pd.DataFrame(
        {"tick": [100, 300, 500, 700], "winner": ["CT", "T", "T", "CT"], "reason": ["t_killed", "ct_killed", "bomb_exploded", "t_killed"]}
    )
    # 50 is a warmup freeze end; round end 500 has no freeze end of its own.
    rounds = pair_rounds(ends, [50, 80, 200, 600])
    assert [r["round"] for r in rounds] == [1, 2, 3]
    assert [r["freeze_end_tick"] for r in rounds] == [80, 200, 600]
    assert [r["end_tick"] for r in rounds] == [100, 300, 700]


def _player_rounds(rows):
    return pd.DataFrame(rows, columns=["round", "steamid", "side"])


def test_assign_teams_follows_side_swap():
    players = _player_rounds([(1, "a1", "CT"), (1, "b1", "T"), (13, "a1", "T"), (13, "b1", "CT")])
    assert assign_teams(players).tolist() == ["A", "B", "A", "B"]


def test_assign_teams_puts_late_joiner_on_their_side():
    # "a2" joins team A in round 5 while A is CT, then swaps with them at halftime.
    players = _player_rounds(
        [(1, "a1", "CT"), (1, "b1", "T"), (5, "a1", "CT"), (5, "a2", "CT"), (5, "b1", "T"), (13, "a1", "T"), (13, "a2", "T"), (13, "b1", "CT")]
    )
    assert assign_teams(players).tolist() == ["A", "B", "A", "A", "B", "A", "A", "B"]


def test_first_rounds_of_halves_includes_overtime():
    sides = pd.Series(["CT"] * 12 + ["T"] * 12 + ["CT"] * 3 + ["T"] * 3, index=range(1, 31))
    assert first_rounds_of_halves(sides) == {1, 13, 25, 28}


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


def test_aim_angle():
    eye = (0, 0, 64)
    assert aim_angle(eye, 0, 0, (500, 0, 64)) == pytest.approx(0, abs=1e-6)  # yaw 0 looks along +X
    assert aim_angle(eye, 0, 90, (500, 0, 64)) == pytest.approx(90)
    assert aim_angle(eye, 0, 180, (500, 0, 64)) == pytest.approx(180)
    assert aim_angle(eye, 45, 0, (100, 0, -36)) == pytest.approx(0, abs=1e-6)  # positive pitch looks down


@pytest.mark.skipif(not LOCAL_DEMOS, reason="no local CS2 demos")
def test_parse_local_demo_fights():
    parsed = parse_demo(LOCAL_DEMOS[-1])
    deaths, chances = parsed.deaths, parsed.trade_chances
    assert len(deaths) >= 5 * parsed.match.iloc[0]["rounds"]  # at least half of everyone dies each round
    # The first death of each round happens with everyone alive (a team may be short if someone left).
    first = deaths.sort_values("tick").groupby("round").head(1)
    players = parsed.team_rounds.set_index(["round", "team"])["players"]
    enemy = first["victim_team"].map({"A": "B", "B": "A"})
    assert (first["team_alive"].to_numpy() == [players[(r, t)] for r, t in zip(first["round"], first["victim_team"])]).all()
    assert (first["enemies_alive"].to_numpy() == [players[(r, t)] for r, t in zip(first["round"], enemy)]).all()
    assert deaths["trade_seconds"].dropna().between(0, TRADE_LOOK_SECONDS).all()
    assert 0.02 < deaths["trade_seconds"].le(2).mean() < 0.4
    assert set(chances["mate"]) <= set(parsed.player_rounds["steamid"])
    assert chances["aim_angle"].between(0, 180).all() and (chances["distance_to_killer"] > 0).all()
