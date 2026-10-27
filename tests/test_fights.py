import numpy as np
import pandas as pd
import pytest

from cs2_insights import fights
from cs2_insights.fights import FightModel, coverage, coverage_summary, fit_fight_model, judge_deaths

MODEL = FightModel()


def _death(round_, tick, victim, killer, victim_team="A", **overrides):
    row = {
        "round": round_, "tick": tick, "round_seconds": 10.0, "victim": victim, "killer": killer,
        "victim_team": victim_team, "killer_team": "B" if victim_team == "A" else "A", "weapon": "ak47",
        "headshot": False, "victim_place": "Ramp", "killer_place": "Ramp", "victim_equip": 1_000,
        "victim_blind": False, "victim_speed": 0.0, "victim_x": 0.0, "victim_y": 0.0, "killer_x": 500.0,
        "killer_y": 0.0, "team_alive": 5, "enemies_alive": 5, "bomb_planted": False, "traded_by": None,
        "trade_seconds": None,
    }
    row.update(overrides)
    return row


def _chance(round_, tick, victim, mate, distance, angle, distance_to_victim=300.0):
    return {"round": round_, "tick": tick, "victim": victim, "mate": mate, "distance_to_killer": distance,
            "distance_to_victim": distance_to_victim, "aim_angle": angle, "mate_x": 0.0, "mate_y": 0.0, "mate_yaw": 0.0}


def _team_rounds(rounds, a_won):
    return pd.DataFrame(
        [{"round": r, "team": t, "side": "CT" if t == "A" else "T", "won": (w if t == "A" else not w)}
         for r, w in zip(rounds, a_won) for t in "AB"]
    )


CHANCE_COLUMNS = ["round", "tick", "victim", "mate", "distance_to_killer", "distance_to_victim", "aim_angle", "mate_x", "mate_y", "mate_yaw"]


def test_win_chance_is_symmetric_and_sensible():
    assert MODEL.win_chance(5, 5)[0] == pytest.approx(0.5)
    assert MODEL.win_chance(4, 3)[0] + MODEL.win_chance(3, 4)[0] == pytest.approx(1.0)
    assert MODEL.win_chance(1, 3)[0] < MODEL.win_chance(3, 3)[0] < MODEL.win_chance(5, 4)[0]
    assert MODEL.win_chance(0, 2)[0] == 0.0 and MODEL.win_chance(2, 0)[0] == 1.0
    assert MODEL.win_chance(2, 2, plant=1)[0] > 0.5 > MODEL.win_chance(2, 2, plant=-1)[0]  # the bomb helps T


def test_trade_chance_falls_with_distance_and_aim():
    near, far = MODEL.trade_chance([200, 1500], 5)
    assert near > 0.4 and far < 0.1
    facing, away = MODEL.trade_chance(450, [5, 120])
    assert facing > 10 * away


def test_grades_follow_the_cut_points():
    assert MODEL.grade(0.0) == "F"
    assert MODEL.grade(MODEL.setup_cuts[2] + 1e-6) == "B"
    assert MODEL.grade(1.0) == "A"


def test_every_death_gets_the_right_label():
    deaths = pd.DataFrame([
        _death(1, 100, "a1", "b1", traded_by="a2", trade_seconds=1.0, victim_speed=200.0),
        _death(2, 200, "b1", "a1", victim_team="B"),  # a1 gets a kill at Ramp...
        _death(2, 300, "a1", "b2"),  # ...peeks it again and dies
        _death(3, 400, "a1", "b1", team_alive=1, enemies_alive=3, victim_equip=4_500),
        _death(4, 500, "a1", "b1", victim_speed=220.0, team_alive=3),
        _death(5, 600, "a1", "b1"),
        _death(6, 700, "a1", "b1"),
        _death(7, 800, "a1", "a2", killer_team="A"),  # team kill
        _death(8, 900, "a1", "b1", traded_by="a2", trade_seconds=3.5),  # traded, but too late to count
    ])
    chances = pd.DataFrame([_chance(5, 600, "a1", "a2", 400, 10), _chance(6, 700, "a1", "a2", 1_400, 10)], columns=CHANCE_COLUMNS)
    judged = judge_deaths(deaths, chances, _team_rounds(range(1, 9), [True, True, False, True, True, True, True, True]), MODEL)
    labels = dict(zip(zip(judged["round"], judged["victim"]), judged["label"]))
    assert labels[(1, "a1")] == fights.TRADED
    assert labels[(2, "a1")] == fights.REPEEK
    assert labels[(3, "a1")] == fights.SHOULD_SAVE
    assert labels[(4, "a1")] == fights.ALONE
    assert labels[(5, "a1")] == fights.NOT_TRADED
    assert labels[(6, "a1")] == fights.DUEL
    assert labels[(7, "a1")] == fights.OTHER
    assert labels[(8, "a1")] == fights.DUEL
    # The first death of an even round costs about 0.19 of a round.
    assert judged.set_index(["round", "victim"]).at[(5, "a1"), "cost"] == pytest.approx(0.5 - MODEL.win_chance(4, 5)[0])


def test_coverage_verdicts_and_summary():
    deaths = pd.DataFrame([
        _death(1, 100, "a1", "b1", traded_by="me", trade_seconds=0.8),
        _death(2, 200, "a1", "b1"),
        _death(3, 300, "a1", "b1"),
        _death(4, 400, "a1", "b1"),
        _death(5, 500, "a1", "b1", traded_by="a3", trade_seconds=1.5),
        _death(6, 600, "a1", "b1"),
    ])
    chances = pd.DataFrame([
        _chance(1, 100, "a1", "me", 300, 5),
        _chance(2, 200, "a1", "me", 400, 10),
        _chance(3, 300, "a1", "me", 500, 120),
        _chance(4, 400, "a1", "me", 1_300, 5),
        _chance(5, 500, "a1", "me", 600, 20),
        _chance(6, 600, "a1", "me", 400, 10, distance_to_victim=3_000),  # other side of the map: not yours
    ], columns=CHANCE_COLUMNS)
    judged = judge_deaths(deaths, chances, _team_rounds(range(1, 7), [True] * 6), MODEL)
    cover = coverage(judged, chances, "me", MODEL)
    assert cover["verdict"].tolist() == [
        fights.COVER_TRADED, fights.COVER_SET_UP, fights.COVER_FACING_AWAY, fights.COVER_TOO_FAR, fights.COVER_OTHER_TRADED,
    ]
    assert cover["lost"].iloc[2] > 0 and (cover["lost"].drop(index=2) == 0).all()
    summary = coverage_summary(cover, MODEL)
    assert (summary["chances"], summary["in_range"], summary["set_up"], summary["trades"]) == (5, 4, 3, 1)
    assert summary["grade"] in fights.GRADES


def test_fit_recovers_trade_weights_and_falls_back_when_small():
    rng = np.random.default_rng(1)
    true = FightModel(trade_weights=(1.0, -3.0, -4.0))
    n = 4_000
    distance, angle = rng.uniform(100, 2_500, n), rng.uniform(0, 180, n)
    traded = rng.random(n) < true.trade_chance(distance, angle)
    chances = pd.DataFrame({"match_id": "m", "round": 1, "tick": np.arange(n), "victim": "v", "mate": np.where(traded, "t", "x"),
                            "distance_to_killer": distance, "distance_to_victim": 300.0, "aim_angle": angle})
    deaths = pd.DataFrame({"match_id": "m", "tick": np.arange(n), "victim": "v", "traded_by": "t", "trade_seconds": 1.0})
    fitted = fit_fight_model(deaths, chances, pd.DataFrame()).trade_weights
    assert fitted == pytest.approx((1.0, -3.0, -4.0), abs=0.4)
    assert fit_fight_model(deaths, chances.iloc[:50], pd.DataFrame()) == FightModel()
