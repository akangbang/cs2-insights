import pandas as pd

from cs2_insights import fights
from cs2_insights.halfplan import DID_IT, NO_CHANGE, SOME_PROGRESS, TOO_FEW, build_plan
from cs2_insights.utility import FLASH_TRADE_OFF, FLASH_WASTED


def _rounds(first=12, second=12):
    return pd.DataFrame({"round": range(1, first + second + 1), "side": ["CT"] * first + ["T"] * second})


def _deaths(*rows):
    return pd.DataFrame([{"round": r, "tick": r * 1000 + i, "victim": "me", "label": label, "cost": cost, "unused_utility": 0}
                         for i, (r, label, cost) in enumerate(rows)])


NONE = pd.DataFrame()


def _plan(rounds, deaths=NONE, calls=NONE, flashes=NONE):
    return build_plan(rounds, deaths, NONE, calls, flashes)


def test_the_plan_only_uses_the_first_half():
    plan = _plan(_rounds(), _deaths((2, fights.REPEEK, 0.2), (5, fights.REPEEK, 0.2), (15, fights.ALONE, 0.9), (16, fights.ALONE, 0.9)))
    assert [i.key for i in plan.items] == ["repeek"]
    assert (plan.first_rounds, plan.second_rounds, plan.last_first_round, plan.next_side) == (12, 12, 12, "T")


def test_the_biggest_misses_come_first_and_stop_at_three():
    deaths = _deaths(*[(r, label, cost) for label, cost in ((fights.ALONE, 0.05), (fights.REPEEK, 0.3), (fights.SHOULD_SAVE, 0.2)) for r in (1, 2)])
    calls = pd.DataFrame({"round": [3, 4], "grade": ["Should have forced", "Should have saved"], "cost": [0.01, 0.01]})
    assert [i.key for i in _plan(_rounds(), deaths, calls).items] == ["repeek", "gear", "alone"]


def test_a_single_miss_is_only_used_when_nothing_repeated():
    deaths = _deaths((1, fights.REPEEK, 0.5), (2, fights.ALONE, 0.1), (3, fights.ALONE, 0.1))
    assert [i.key for i in _plan(_rounds(), deaths).items] == ["alone"]
    assert [i.key for i in _plan(_rounds(), _deaths((1, fights.REPEEK, 0.5))).items] == ["repeek"]


def test_follow_through_compares_rates_per_round():
    four_then = lambda n: _deaths(*[(r, fights.REPEEK, 0.2) for r in (1, 2, 3, 4)], *[(r, fights.REPEEK, 0.2) for r in range(13, 13 + n)])
    assert _plan(_rounds(), four_then(1)).items[0].status == DID_IT
    assert _plan(_rounds(), four_then(3)).items[0].status == SOME_PROGRESS
    assert _plan(_rounds(), four_then(4)).items[0].status == NO_CHANGE
    assert _plan(_rounds(), four_then(1)).items[0].second == 1


def test_a_short_second_half_is_not_judged():
    deaths = _deaths((1, fights.REPEEK, 0.2), (2, fights.REPEEK, 0.2))
    assert _plan(_rounds(second=3), deaths).items[0].status == TOO_FEW


def test_a_match_that_never_reached_the_second_half():
    item = _plan(_rounds(first=8, second=0), _deaths((1, fights.REPEEK, 0.2), (2, fights.REPEEK, 0.2))).items[0]
    assert item.second is None and item.status is None


def test_overtime_is_left_out():
    rounds = pd.DataFrame({"round": range(1, 29), "side": ["CT"] * 12 + ["T"] * 12 + ["CT", "CT", "T", "T"]})
    deaths = _deaths((1, fights.REPEEK, 0.2), (2, fights.REPEEK, 0.2), (26, fights.REPEEK, 0.2))
    plan = _plan(rounds, deaths)
    assert plan.second_rounds == 12 and plan.items[0].second == 0


def test_flashes_that_caught_an_enemy_are_not_counted():
    flashes = pd.DataFrame({"round": [1, 2, 3], "verdict": [FLASH_WASTED, FLASH_WASTED, FLASH_TRADE_OFF], "death_cost": [0.0, 0.0, 0.0]})
    assert _plan(_rounds(), flashes=flashes).items[0].first == 2


def test_a_clean_first_half_has_nothing_to_change():
    assert _plan(_rounds()).items == []
