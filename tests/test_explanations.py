"""The plain-language reasons shown on death, coverage and clutch cards."""

import pandas as pd

from cs2_insights import fights
from cs2_insights.report import clock, clutch_reasons, cover_reasons, death_reasons, pct, place_label

NAMES = {"me": "Me", "mate": "Mate", "killer": "Killer"}
NO_CHANCES = pd.DataFrame(columns=["tick", "victim", "mate", "distance_to_killer", "aim_angle"])


def _death(**overrides):
    row = {"label": fights.DUEL, "victim": "me", "tick": 100, "victim_place": "TopofMid", "traded_by": None,
           "trade_seconds": None, "moving": False, "repeek_gap": None, "team_alive": 3, "enemies_alive": 3,
           "bomb_planted": False, "win_before": 0.5, "victim_equip": 4_700, "victim_speed": 0.0, "closest_mate": None,
           "victim_blind": False, "side": "CT"}
    row.update(overrides)
    return pd.Series(row)


def test_formatting_helpers():
    assert place_label("TopofMid") == "Top of Mid"
    assert place_label("BombsiteA") == "Bombsite A"
    assert place_label(None) == "somewhere"
    assert clock(75.9) == "1:15"
    assert pct(0.004) == "under 1%" and pct(0.42) == "42%"


def test_death_reasons_quote_the_facts():
    traded = death_reasons(_death(label=fights.TRADED, traded_by="mate", trade_seconds=1.25, moving=True), NO_CHANCES, NAMES)
    assert traded[0] == "Mate killed your killer 1.2s later." and "entry" in traded[1]

    repeek = death_reasons(_death(label=fights.REPEEK, repeek_gap=1.8), NO_CHANCES, NAMES)
    assert repeek[0] == "You got a kill from Top of Mid 1.8s earlier."

    alone = death_reasons(_death(label=fights.ALONE, victim_speed=180.0, closest_mate=1_450.0), NO_CHANCES, NAMES)
    assert "1,450 units" in alone[1]

    lost = death_reasons(_death(label=fights.SHOULD_SAVE, team_alive=1, enemies_alive=3, win_before=0.06, bomb_planted=True), NO_CHANCES, NAMES)
    assert lost[0].startswith("It was 1 vs 3 with the bomb planted") and "$4,700" in lost[1]


def test_untraded_death_names_the_teammate_who_could_have_traded():
    chances = pd.DataFrame({"tick": [100], "victim": ["me"], "mate": ["mate"], "distance_to_killer": [420.0], "aim_angle": [95.0]})
    reasons = death_reasons(_death(label=fights.NOT_TRADED), chances, NAMES)
    assert reasons == ["Mate was 420 units from your killer, aiming 95° away from him, and didn't trade."]


def test_duel_wording_depends_on_side_and_movement():
    assert "normal on CT" in death_reasons(_death(side="CT"), NO_CHANCES, NAMES)[0]
    assert "normal on CT" not in death_reasons(_death(side="T"), NO_CHANCES, NAMES)[0]
    assert "moving into the fight" in death_reasons(_death(moving=True), NO_CHANCES, NAMES)[0]
    assert death_reasons(_death(victim_blind=True), NO_CHANCES, NAMES)[-1] == "You were flashed when you died."


def test_cover_reasons_describe_distance_aim_and_outcome():
    row = pd.Series({"distance_to_killer": 500.0, "aim_angle": 120.0, "chance": 0.02, "chance_if_facing": 0.31,
                     "verdict": fights.COVER_FACING_AWAY, "traded_by": None, "trade_seconds": None})
    reasons = cover_reasons(row, NAMES)
    assert "close enough to trade" in reasons[0] and "looking somewhere else" in reasons[1]
    assert reasons[-1] == "Facing the fight from where you stood would have made it 31%."


def test_clutch_reasons_explain_the_save_threshold():
    base = {"enemies": 3, "side": "CT", "plant_seconds": None, "win_chance": 0.06, "gear": 4_700, "outcome": "Died"}
    worth = clutch_reasons(pd.Series({**base, "save_value": 0.25, "save_rounds": 4}))
    assert any("over the next 4 rounds" in r for r in worth)
    assert any("more than 20% of the time" in r for r in worth)  # 0.25 / 1.25
    last_round = clutch_reasons(pd.Series({**base, "save_value": 0.0, "save_rounds": 0}))
    assert any("money resets" in r for r in last_round)
    rich = clutch_reasons(pd.Series({**base, "save_value": 0.0, "save_rounds": 3}))
    assert any("changed little" in r for r in rich)
    planted = clutch_reasons(pd.Series({**base, "plant_seconds": 32.0, "save_value": 0.0, "save_rounds": 0}))
    assert any("8s left on it" in r for r in planted)
