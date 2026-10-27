import pandas as pd
import pytest

from cs2_insights.habits import MIN_MATCHES, build_habits
from tests.test_grade import ECO, FULL, _team_rounds
from cs2_insights.demo import ParsedDemo

ME = "me"


def _match(match_id, specs, my_balance=500):
    team_rounds = _team_rounds(specs).assign(match_id=match_id)
    player_rounds = pd.DataFrame([
        {"match_id": match_id, "round": r.round, "steamid": ME if r.team == "A" else "them", "name": "Me" if r.team == "A" else "Them",
         "team": r.team, "side": r.side, "balance": my_balance, "equip_value": r.equip_value / 5}
        for r in team_rounds.itertuples()
    ])
    score = team_rounds.groupby("team")["won"].sum()
    match = pd.DataFrame([{"match_id": match_id, "map": "de_test", "team_a_score": int(score["A"]), "team_b_score": int(score["B"])}])
    return ParsedDemo(match, pd.DataFrame(), team_rounds, player_rounds)


# A lost pistol, then a save of $2,600 each against the pistol winners' force.
SAVE_AFTER_PISTOL = [("CT", False, ECO, ECO), ("CT", False, (1_000, 12_000, 1_000, 0), (13_000, 2_000, 1_000, 12_000))]
SAVE_AFTER_PISTOL += [("CT", True, FULL, FULL)] * 4 + [("T", True, FULL, FULL)]


def test_habits_group_wrong_calls_by_situation():
    matches = [_match(f"m{i}", SAVE_AFTER_PISTOL) for i in range(MIN_MATCHES)]
    habits = build_habits(matches, ME)
    assert habits.matches == MIN_MATCHES and habits.name == "Me"
    assert set(habits.calls["match_id"]) == {"m0", "m1", "m2"}
    top = habits.fixes[0]
    assert top.title == "You save after a lost pistol when you should force"
    assert top.detail.startswith(f"{MIN_MATCHES} of your {MIN_MATCHES} saves after a lost pistol were the wrong call")
    assert top.cost > 0
    assert habits.strengths and habits.strengths[0].kind == "good"


def test_money_left_on_the_last_round_of_a_half_is_flagged():
    matches = [_match(f"m{i}", SAVE_AFTER_PISTOL, my_balance=2_000) for i in range(MIN_MATCHES)]
    titles = [h.title for h in build_habits(matches, ME).fixes]
    assert "You keep money that's about to reset" in titles


def test_too_few_matches_gives_no_habits():
    habits = build_habits([_match("m0", SAVE_AFTER_PISTOL)], ME)
    assert habits.matches == 1 and habits.fixes == []
    with pytest.raises(ValueError):
        build_habits([_match("m0", SAVE_AFTER_PISTOL)], "nobody")
