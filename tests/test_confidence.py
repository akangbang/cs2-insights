import pandas as pd

from cs2_insights import fights
from cs2_insights.confidence import (
    HIGH,
    LOW,
    MEDIUM,
    call_confidence,
    clutch_confidence,
    death_confidence,
    describe,
    grade_confidence,
    habit_confidence,
)


def test_death_confidence_follows_how_clear_the_facts_are():
    repeek = {"label": fights.REPEEK, "repeek_gap": 1.0, "closest_mate": None, "win_before": 0.5}
    assert death_confidence(pd.Series(repeek))[0] == HIGH
    assert death_confidence(pd.Series({**repeek, "repeek_gap": 3.5}))[0] == MEDIUM
    alone = {"label": fights.ALONE, "repeek_gap": None, "closest_mate": 2_000.0, "win_before": 0.5}
    assert death_confidence(pd.Series(alone))[0] == HIGH
    assert death_confidence(pd.Series({**alone, "closest_mate": 1_000.0}))[0] == MEDIUM
    assert death_confidence(pd.Series({**alone, "closest_mate": None}))[0] == HIGH  # nobody near at all
    lost = {"label": fights.SHOULD_SAVE, "repeek_gap": None, "closest_mate": None, "win_before": 0.03}
    assert death_confidence(pd.Series(lost))[0] == HIGH
    assert death_confidence(pd.Series({**lost, "win_before": 0.12}))[0] == MEDIUM
    assert death_confidence(pd.Series({**repeek, "label": fights.DUEL})) is None


def test_clutch_confidence_uses_the_gap_between_fighting_and_saving():
    base = {"outcome": "Died", "save_value": 0.25}
    assert clutch_confidence(pd.Series({**base, "win_chance": 0.01}))[0] == HIGH  # edge about -0.24
    assert clutch_confidence(pd.Series({**base, "win_chance": 0.14}))[0] == MEDIUM  # edge about -0.08
    assert clutch_confidence(pd.Series({**base, "win_chance": 0.20}))[0] == LOW  # edge exactly 0
    assert clutch_confidence(pd.Series({**base, "outcome": "Won", "win_chance": 0.5})) is None


def test_call_confidence_uses_the_simulated_gap():
    call = {"rounds_counted": 4, "force_wins": 2.0, "save_wins": 1.5}
    assert call_confidence(pd.Series(call))[0] == HIGH
    assert call_confidence(pd.Series({**call, "save_wins": 1.75}))[0] == MEDIUM
    assert call_confidence(pd.Series({**call, "save_wins": 1.9}))[0] == LOW
    assert call_confidence(pd.Series({**call, "rounds_counted": 1, "save_wins": 1.9}))[0] == HIGH


def test_grades_and_habits_need_enough_examples():
    assert [grade_confidence(n)[0] for n in (20, 8, 2)] == [HIGH, MEDIUM, LOW]
    assert habit_confidence(10, 6)[0] == HIGH
    assert habit_confidence(10, 3)[0] == MEDIUM  # many examples, but few matches
    assert habit_confidence(2, 6)[0] == LOW
    assert habit_confidence(1, 1)[1] == "Only 1 example in 1 match. Could be chance so far."


def test_describe_reads_as_one_line():
    assert describe(LOW, "Thin data.") == "●○○ Confidence: low. Thin data."
