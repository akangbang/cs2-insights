import numpy as np
import pandas as pd
import pytest

from cs2_insights.grade import (
    CLOSE, GOOD_CALL, KEPT_LOST, KILL_MONEY_LOST, KILL_MONEY_WON, SHOULD_FORCE, SHOULD_SAVE, WIN_REWARD,
    Economy, economy_states, grade_decisions,
)
from cs2_insights.rates import DEFAULT_EQUIPMENT_SLOPE, equipment_slope, equipment_win_rate


def _team_rounds(specs):
    """specs: list of (side_a, a_won, a, b) where a/b = (equip, bank, start_equip, cash_spent) team totals."""
    rows = []
    score = {"A": 0, "B": 0}
    for number, (side_a, a_won, a, b) in enumerate(specs, start=1):
        for team, side, won, (equip, bank, start_equip, spent) in (
            ("A", side_a, a_won, a), ("B", "T" if side_a == "CT" else "CT", not a_won, b),
        ):
            rows.append({
                "match_id": "m", "round": number, "team": team, "side": side, "players": 5,
                "equip_value": equip, "bank": bank, "start_equip_value": start_equip, "cash_spent": spent,
                "won": won, "score": score[team], "opponent_score": score["B" if team == "A" else "A"],
                "buy_type": "pistol" if number == 1 else ("full" if equip / 5 >= 3_800 else "force" if equip / 5 >= 1_600 else "eco"),
            })
        score["A" if a_won else "B"] += 1
    return pd.DataFrame(rows)


FULL = (25_000, 5_000, 5_000, 20_000)  # $5,000 each on a full buy, $1,000 each left over
ECO = (1_000, 4_000, 1_000, 0)


def test_loss_counter_and_half_tracking():
    specs = [("CT", False, ECO, ECO), ("CT", False, ECO, ECO), ("CT", True, ECO, ECO), ("T", False, ECO, ECO), ("T", True, ECO, ECO)]
    states = economy_states(_team_rounds(specs))
    a = states[states["team"] == "A"].set_index("round")
    assert a["loss_counter"].tolist() == [1, 2, 3, 1, 2]  # resets to 1 at the half
    assert a["rounds_left_in_half"].tolist() == [2, 1, 0, 1, 0]
    assert a["start_money"].tolist() == [4_000] * 5


def test_economy_after_a_round():
    team = Economy(money=10_000, carried=1_000, loss_counter=1, players=5)
    lost = team.after(equip=8_000, bank=2_000, won=False)
    assert lost.money == 2_000 + 5 * (1_900 + KILL_MONEY_LOST)
    assert lost.carried == pytest.approx(8_000 * KEPT_LOST)
    assert lost.loss_counter == 2
    won = team.after(equip=8_000, bank=2_000, won=True)
    assert won.money == 2_000 + 5 * (WIN_REWARD + KILL_MONEY_WON) and won.loss_counter == 0
    # Below a full buy the standard choice is to save; with enough money, buy.
    assert team.buy(spend_all=False) == (1_000, 10_000)
    assert Economy(30_000, 0, 0, 5).buy(spend_all=False) == (25_000, 5_000)


def test_saving_on_the_last_round_of_a_half_is_wrong():
    # Round 3 is the last round of the half: the team has $2,600 each, saves, and money resets after.
    save = (1_000, 12_000, 1_000, 0)
    specs = [("CT", True, ECO, ECO), ("CT", False, FULL, FULL), ("CT", False, save, FULL), ("T", True, ECO, ECO)]
    calls = grade_decisions(_team_rounds(specs), "A")
    call = calls.set_index("round").loc[3]
    assert call["made"] == "save" and call["rounds_counted"] == 1
    assert call["grade"] == SHOULD_FORCE
    assert call["force_wins"] > call["save_wins"]


def test_a_half_buy_into_a_full_buy_is_wrong():
    # $3,400 each, but only $1,600 each spent: a weak force against a full buy, while saving
    # all of it would have meant a full buy next round.
    half_buy = (9_000, 8_000, 1_000, 8_000)
    specs = [("CT", True, ECO, ECO), ("CT", True, FULL, ECO), ("CT", False, FULL, FULL), ("CT", False, half_buy, FULL)]
    specs += [("CT", True, FULL, FULL)] * 8
    calls = grade_decisions(_team_rounds(specs), "A").set_index("round")
    call = calls.loc[4]
    assert call["made"] == "force"
    assert call["save_wins"] > call["force_wins"]
    assert call["grade"] in (CLOSE, SHOULD_SAVE)


def test_forcing_against_a_weak_buy_is_a_good_call():
    force = (15_000, 0, 1_000, 14_000)
    weak = (6_000, 3_000, 1_000, 5_000)
    specs = [("CT", False, ECO, ECO), ("CT", False, force, weak)] + [("CT", True, FULL, FULL)] * 10
    calls = grade_decisions(_team_rounds(specs), "A").set_index("round")
    assert calls.at[2, "grade"] == GOOD_CALL


def test_equipment_win_rate_is_symmetric_and_monotonic():
    assert equipment_win_rate(4_000, 4_000) == pytest.approx(0.5)
    assert equipment_win_rate(2_000, 5_000) + equipment_win_rate(5_000, 2_000) == pytest.approx(1.0)
    assert equipment_win_rate(1_000, 5_000) < equipment_win_rate(3_000, 5_000) < 0.5


def test_equipment_slope_recovers_a_known_slope():
    rng = np.random.default_rng(0)
    rows = []
    for number in range(2_000):
        a, b = rng.uniform(500, 6_000, 2)
        a_won = rng.random() < equipment_win_rate(a, b, slope=1.5)
        for team, equip, won in (("A", a, a_won), ("B", b, not a_won)):
            rows.append({"match_id": "m", "round": number, "team": team, "players": 1, "equip_value": equip, "buy_type": "full", "won": won})
    assert equipment_slope(pd.DataFrame(rows)) == pytest.approx(1.5, abs=0.15)
    # Too few rounds to fit: fall back to the default.
    assert equipment_slope(pd.DataFrame(rows[:20])) == DEFAULT_EQUIPMENT_SLOPE
