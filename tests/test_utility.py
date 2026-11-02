import pandas as pd

from cs2_insights.utility import team_flashes, utility_summary


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
