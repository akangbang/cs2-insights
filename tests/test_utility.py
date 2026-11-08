import pandas as pd

from cs2_insights.utility import FLASH_COST_TEAMMATE, FLASH_TRADE_OFF, FLASH_WASTED, review_team_flashes, team_flashes, utility_summary


def _utility(rows):
    columns = ["round", "steamid", "flashes", "smokes", "hes", "molotovs", "enemies_blinded", "enemy_blind_seconds",
               "teammates_blinded", "utility_damage"]
    return pd.DataFrame(rows, columns=columns)


def test_summary_totals_and_match_averages():
    utility = _utility([
        (1, "me", 2, 1, 0, 0, 3, 6.0, 1, 0),
        (2, "me", 1, 0, 1, 1, 0, 0.0, 0, 40),
        (1, "mate", 0, 0, 0, 0, 0, 0.0, 0, 0),
    ])
    deaths = pd.DataFrame({"victim": ["me", "me"], "unused_utility": [600, 200]})
    u = utility_summary(utility, deaths, "me")
    assert u["thrown"] == {"flashes": 3, "smokes": 1, "hes": 1, "molotovs": 1} and u["grenades"] == 6
    assert u["enemies_blinded"] == 3 and u["per_flash"] == 1.0 and u["teammates_blinded"] == 1
    assert u["match_grenades"] == 3.0  # 6 thrown by me, 0 by my teammate
    assert (u["unused_deaths"], u["unused_value"]) == (1, 600)  # the $200 death is under the threshold
    assert utility_summary(utility, deaths, "nobody") == {}


def test_team_flashes_are_only_your_flashes_on_teammates():
    blinds = pd.DataFrame({"round": [1, 1, 2], "tick": [30, 10, 50], "thrower": ["me", "me", "mate"],
                           "blinded": ["mate", "enemy", "me"], "seconds": [2.0, 3.0, 1.5], "teammate": [True, False, True]})
    flashes = team_flashes(blinds, "me")
    assert flashes["blinded"].tolist() == ["mate"]


def _blind(tick, blinded, teammate, seconds=2.0):
    return {"round": 1, "tick": tick, "thrower": "me", "blinded": blinded, "seconds": seconds, "teammate": teammate,
            "thrower_x": 0.0, "thrower_y": 0.0, "blinded_x": 10.0, "blinded_y": 10.0}


def test_team_flash_verdicts():
    blinds = pd.DataFrame([
        _blind(100, "mate1", True),                     # teammate dies while blind
        _blind(500, "mate2", True), _blind(500, "enemy", False),  # also caught an enemy
        _blind(900, "mate3", True),                     # only the teammate
    ])
    # mate1 dies 1 s after the flash (64 ticks), inside the 2 s blind; mate3 dies long after theirs.
    deaths = pd.DataFrame({"victim": ["mate1", "mate3"], "tick": [164, 2_000], "cost": [0.19, 0.2]})
    review = review_team_flashes(blinds, deaths, "me").set_index("blinded")
    assert review.at["mate1", "verdict"] == FLASH_COST_TEAMMATE and review.at["mate1", "death_cost"] == 0.19
    assert review.at["mate2", "verdict"] == FLASH_TRADE_OFF and review.at["mate2", "enemies_caught"] == 1
    assert review.at["mate2", "enemy_spots"] == [(10.0, 10.0)]
    assert review.at["mate3", "verdict"] == FLASH_WASTED and not review.at["mate3", "died_blind"]


def test_no_team_flashes_gives_an_empty_review():
    blinds = pd.DataFrame([_blind(100, "enemy", False)])
    assert review_team_flashes(blinds, pd.DataFrame(columns=["victim", "tick", "cost"]), "me").empty
