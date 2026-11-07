import numpy as np
import pandas as pd

from cs2_insights import calibration
from cs2_insights.demo import ParsedDemo


def _preds(model, predicted, happened):
    return pd.DataFrame({"model": model, "predicted": predicted, "happened": happened})


def test_an_honest_model_scores_well_and_a_useless_one_doesnt():
    rng = np.random.default_rng(0)
    chance = rng.uniform(0, 1, 5_000)
    happened = rng.random(5_000) < chance
    honest = calibration.scores(_preds("honest", chance, happened)).iloc[0]
    assert honest["average_miss"] < 0.03 and honest["skill"] > 0.2
    backwards = calibration.scores(_preds("backwards", 1 - chance, happened)).iloc[0]
    assert backwards["average_miss"] > 0.3 and backwards["skill"] < 0


def test_buckets_group_by_ten_percent_and_flag_thin_ones():
    preds = _preds("m", [0.05] * 20 + [0.95] * 3, [False] * 20 + [True] * 3)
    table = calibration.buckets(preds).set_index("bucket")
    assert table.at[0, "n"] == 20 and table.at[0, "actual"] == 0 and not table.at[0, "thin"]
    assert table.at[90, "n"] == 3 and table.at[90, "thin"]
    assert calibration.buckets(_preds("m", [], [])).empty


def _match(match_id, a_won):
    team_rounds = pd.DataFrame([
        {"round": 2, "team": t, "side": "CT" if t == "A" else "T", "players": 5, "equip_value": 20_000, "won": a_won if t == "A" else not a_won,
         "buy_type": "full"} for t in "AB"
    ])
    deaths = pd.DataFrame([{"match_id": match_id, "round": 2, "tick": 100, "victim": "a1", "victim_team": "A", "team_alive": 5, "enemies_alive": 4,
                            "bomb_planted": False, "traded_by": None, "trade_seconds": None}])
    chances = pd.DataFrame([{"match_id": match_id, "round": 2, "tick": 100, "victim": "a1", "mate": "a2", "distance_to_killer": 400.0,
                             "distance_to_victim": 300.0, "aim_angle": 10.0}])
    return ParsedDemo(pd.DataFrame(), pd.DataFrame(), team_rounds.assign(match_id=match_id), pd.DataFrame(), deaths, chances)


def test_predictions_view_each_moment_from_both_sides():
    """Only checking the team about to lose a player would leak the outcome."""
    preds = calibration.predictions([_match("m1", True), _match("m2", False)])
    alive = preds[preds["model"] == "alive"]
    assert len(alive) == 4  # two matches, one death each, both teams' views
    assert (alive["predicted"].iloc[0] + alive["predicted"].iloc[1]) == 1.0
    assert alive["happened"].iloc[0] != alive["happened"].iloc[1]
    assert set(preds["model"]) == {"equipment", "alive", "trade"}
