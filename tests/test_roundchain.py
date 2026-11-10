import pandas as pd
import pytest

from cs2_insights.fights import FightModel
from cs2_insights.roundchain import DEATH, PLANT, round_chain, start_chance, turning_point

MODEL = FightModel()


def _death(tick, victim, victim_team, team_alive, enemies_alive, seconds, planted=False, plant_seconds=None, round_=3):
    return {"round": round_, "tick": tick, "victim": victim, "victim_team": victim_team, "team_alive": team_alive, "enemies_alive": enemies_alive,
            "round_seconds": seconds, "bomb_planted": planted, "plant_seconds": plant_seconds, "victim_place": "Long"}


def chance(a, b, plant=0):
    return float(MODEL.win_chance(a, b, plant)[0])


def test_follows_alive_counts_from_your_teams_side():
    deaths = pd.DataFrame([
        _death(100, "e1", "B", 5, 5, 10.0),  # an enemy dies: 5v4 for us
        _death(200, "me", "A", 5, 4, 20.0),  # we lose one: 4v4
    ])
    chain = round_chain(deaths, 3, "A", "CT", MODEL)
    assert list(chain["kind"]) == [DEATH, DEATH] and list(chain["mine"]) == [False, True]
    assert chain.at[0, "before"] == pytest.approx(chance(5, 5)) and chain.at[0, "after"] == pytest.approx(chance(5, 4))
    assert chain.at[1, "after"] == pytest.approx(chance(4, 4))
    assert start_chance(chain) == pytest.approx(0.5, abs=0.01)


def test_the_bomb_plant_is_its_own_step():
    deaths = pd.DataFrame([_death(100, "ct1", "B", 5, 5, 60.0, planted=True, plant_seconds=15.0)])
    chain = round_chain(deaths, 3, "A", "T", MODEL)
    assert list(chain["kind"]) == [PLANT, DEATH]
    assert chain.at[0, "seconds"] == 45.0
    assert chain.at[0, "after"] == pytest.approx(chance(5, 5, 1))
    assert chain.at[0, "after"] > chain.at[0, "before"]


def test_turning_point_is_the_biggest_drop_in_a_lost_round_and_rise_in_a_won_one():
    deaths = pd.DataFrame([
        _death(100, "e1", "B", 5, 5, 10.0),
        _death(200, "m1", "A", 5, 4, 20.0),
        _death(300, "m2", "A", 4, 4, 30.0),
        _death(400, "m3", "A", 3, 4, 40.0),
    ])
    chain = round_chain(deaths, 3, "A", "CT", MODEL)
    lost = turning_point(chain, won=False)
    assert lost["change"] == chain["change"].min() and lost["mine"]
    won = turning_point(chain, won=True)
    assert won["victim"] == "e1"


def test_other_rounds_and_empty_rounds():
    deaths = pd.DataFrame([_death(100, "e1", "B", 5, 5, 10.0, round_=4)])
    assert round_chain(deaths, 3, "A", "CT", MODEL).empty
    assert turning_point(round_chain(deaths, 3, "A", "CT", MODEL), won=False) is None
