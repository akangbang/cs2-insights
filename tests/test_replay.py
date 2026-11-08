import pandas as pd
import pytest

from cs2_insights import fights
from cs2_insights.fights import FightModel
from cs2_insights.replay import ROUNDS, WIN, call_replay, clutch_replay, death_replay

MODEL = FightModel()


def _call(**overrides):
    return pd.Series({"round": 5, "rounds_counted": 4, "made": "save", "force_wins": 1.6, "save_wins": 1.2, "force_now": 0.4, "save_now": 0.15, **overrides})


def _clutch(**overrides):
    return pd.Series({"win_chance": 0.3, "save_value": 0.2, "save_rounds": 4, "outcome": "Died", **overrides})


def _death(label, team=3, enemies=3, **overrides):
    before = float(MODEL.win_chance(team, enemies, 0)[0])
    after = float(MODEL.win_chance(team - 1, enemies, 0)[0])
    return pd.Series({"label": label, "win_before": before, "cost": before - after, "team_alive": team, "enemies_alive": enemies, "plant": 0,
                      "save_value": 0.0, "save_rounds": 0, **overrides})


def test_a_buy_call_replay_shows_both_choices():
    replay = call_replay(_call())
    assert replay.unit == ROUNDS
    assert [(o.label, o.value, o.taken) for o in replay.options] == [("Force", 1.6, False), ("Save", 1.2, True)]
    assert "**Force** comes out about **0.40 rounds** ahead over rounds 5–8" in replay.takeaway


def test_a_good_buy_call_says_so():
    assert "What you did was the better option" in call_replay(_call(made="force")).takeaway


def test_a_close_buy_call_is_too_close_to_call():
    assert call_replay(_call(force_wins=1.25)).takeaway.startswith("Too close to call")


def test_a_clutch_compares_fighting_with_the_value_of_the_gun():
    fight, save = clutch_replay(_clutch()).options
    assert fight.taken and fight.value == pytest.approx(0.3 * 1.2)
    assert not save.taken and save.value == pytest.approx(0.2)


def test_a_saved_clutch_marks_saving_as_what_you_did():
    fight, save = clutch_replay(_clutch(outcome="Saved")).options
    assert save.taken and not fight.taken


def test_no_replay_for_a_won_clutch():
    assert clutch_replay(_clutch(outcome="Won")) is None


def test_a_lost_cause_says_so_when_the_numbers_favour_fighting():
    death = _death(fights.SHOULD_SAVE, team=3, enemies=4, save_value=0.01, save_rounds=4)
    replay = death_replay(death, MODEL, 0.3)
    assert replay.disputes_verdict and "rule of thumb" in replay.takeaway
    agrees = death_replay(_death(fights.SHOULD_SAVE, team=2, enemies=4, save_value=0.6, save_rounds=4), MODEL, 0.3)
    assert not agrees.disputes_verdict


def test_no_clutch_replay_when_money_is_about_to_reset():
    assert clutch_replay(_clutch(save_rounds=0)) is None


def test_a_repeek_compares_what_happened_a_trade_and_staying_alive():
    death = _death(fights.REPEEK)
    replay = death_replay(death, MODEL, 0.3)
    did, traded, lived = replay.options
    assert replay.unit == WIN and did.taken and lived.best_case
    assert did.value < traded.value < lived.value
    assert did.value == pytest.approx(death["win_before"] - death["cost"])
    expected = 0.3 * float(MODEL.win_chance(2, 2, 0)[0]) + 0.7 * did.value
    assert traded.value == pytest.approx(expected)
    assert "best case" in lived.label.lower()


def test_no_trade_option_when_nobody_is_left_to_trade():
    replay = death_replay(_death(fights.REPEEK, team=1), MODEL, 0.3)
    assert len(replay.options) == 2
    assert "teammate" not in replay.takeaway


def test_a_lost_cause_counts_the_team_playing_on_without_you():
    death = _death(fights.SHOULD_SAVE, team=2, enemies=4, save_value=0.4, save_rounds=4)
    fight, hide = death_replay(death, MODEL, 0.3).options
    assert fight.taken
    assert fight.value == pytest.approx(death["win_before"] * 1.4)
    assert hide.value == pytest.approx(death["win_before"] - death["cost"] + 0.4)


def test_no_replay_when_the_gun_was_worth_nothing():
    assert death_replay(_death(fights.SHOULD_SAVE, save_rounds=0), MODEL, 0.3) is None


@pytest.mark.parametrize("label", [fights.TRADED, fights.DUEL, fights.NOT_TRADED, fights.OTHER])
def test_deaths_that_were_not_a_decision_get_no_replay(label):
    assert death_replay(_death(label), MODEL, 0.3) is None
