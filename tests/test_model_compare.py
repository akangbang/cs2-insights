"""The machine-learning comparison on made-up matches where more players alive usually wins."""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("xgboost")

from cs2_insights.demo import ParsedDemo  # noqa: E402
from cs2_insights.model_compare import CURRENT, MODELS, _mirror, compare, predictions, states  # noqa: E402


def _match(i: int, rng: np.random.Generator) -> ParsedDemo:
    """24 rounds; team A wins more often when its equipment is higher, and deaths go to the losing side more often."""
    rounds, deaths = [], []
    for r in range(1, 25):
        a_equip, b_equip = rng.integers(5_000, 25_000, size=2)
        a_won = rng.random() < 0.5 + (a_equip - b_equip) / 50_000
        side_a = "CT" if r <= 12 else "T"
        for team, equip, won, side in (("A", a_equip, a_won, side_a), ("B", b_equip, not a_won, "T" if side_a == "CT" else "CT")):
            rounds.append({"round": r, "team": team, "side": side, "players": 5, "equip_value": int(equip), "won": won})
        alive = {"A": 5, "B": 5}
        for k in range(6):
            loser = "B" if a_won else "A"
            victim_team = loser if rng.random() < 0.7 else ("A" if loser == "B" else "B")
            if alive[victim_team] <= 0 or alive["A" if victim_team == "B" else "B"] <= 0:
                break
            deaths.append({"round": r, "tick": r * 1000 + k, "round_seconds": 10.0 * (k + 1), "victim": f"{victim_team}{k}",
                           "killer": "x", "victim_team": victim_team, "killer_team": "A" if victim_team == "B" else "B",
                           "team_alive": alive[victim_team], "enemies_alive": alive["A" if victim_team == "B" else "B"],
                           "bomb_planted": False, "traded_by": None, "trade_seconds": None})
            alive[victim_team] -= 1
    match = pd.DataFrame([{"match_id": f"m{i}", "map": "de_dust2" if i % 2 else "de_mirage"}])
    empty = pd.DataFrame(columns=["round", "tick", "victim", "mate", "distance_to_killer", "distance_to_victim", "aim_angle"])
    return ParsedDemo(match=match, rounds=pd.DataFrame(), team_rounds=pd.DataFrame(rounds), player_rounds=pd.DataFrame(),
                      deaths=pd.DataFrame(deaths), trade_chances=empty)


MATCHES = [_match(i, np.random.default_rng(i)) for i in range(6)]


def test_every_state_is_seen_from_both_sides():
    data = states(MATCHES)
    victim, killer = data[data["view"] == 0].reset_index(drop=True), data[data["view"] == 1].reset_index(drop=True)
    assert len(victim) == len(killer) > 0
    assert (victim["won"] != killer["won"]).all()
    assert (victim["alive_diff"] == -killer["alive_diff"]).all()
    assert (victim["equip_k"] == killer["enemy_equip_k"]).all()


def test_mirroring_twice_gives_back_the_same_states():
    data = states(MATCHES)
    columns = ["team_alive", "enemies_alive", "plant", "is_t", "equip_k", "enemy_equip_k", "alive_diff", "alive_log_ratio"]
    pd.testing.assert_frame_equal(_mirror(_mirror(data))[columns], data[columns])


def test_predictions_never_see_the_match_they_predict_and_add_up_for_both_sides():
    preds = predictions(MATCHES)
    assert set(preds["match_id"]) == {f"m{i}" for i in range(6)}
    for name in MODELS:
        assert preds[name].between(0, 1).all()
    data = states(MATCHES)
    # Rows come out in the same order as states(): victims then killers per match. Each pair adds up to 1.
    for match_id, group in preds.groupby("match_id", sort=False):
        half = len(group) // 2
        for name in MODELS:
            p = group[name].to_numpy()
            assert np.allclose(p[:half] + p[half:], 1, atol=1e-6), name
    assert len(preds) == len(data)


def test_compare_reports_every_model_and_a_per_match_check():
    result = compare(MATCHES)
    assert [m["model"] for m in result["models"]] == list(MODELS)
    assert result["matches"] == 6 and result["best"] in MODELS
    if result["best"] != CURRENT:
        assert result["per_match"]["of"] == 6
    assert result["importance"] and abs(sum(row["share"] for row in result["importance"]) - 1) < 0.2
