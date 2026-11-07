import pandas as pd

from cs2_insights.progress import FOCUS, history, match_numbers, recent_average
from tests.test_habits import ME, SAVE_AFTER_PISTOL, _match


def test_history_has_one_row_per_match_played_oldest_first():
    matches = [_match(f"m{i}", SAVE_AFTER_PISTOL) for i in (3, 1, 2)]
    past = history(matches, ME)
    assert past["match_id"].tolist() == ["m1", "m2", "m3"]
    assert history(matches, "nobody").empty
    # These test matches have no fight data, so only buy calls are tracked.
    assert past["wrong_calls"].tolist() == [1, 1, 1] and not past["fights_parsed"].any()


def test_recent_average_skips_the_current_match():
    past = pd.DataFrame({"match_id": ["a", "b", "c"], "avoidable": [4, 2, 9]})
    assert recent_average(past, "c")["avoidable"] == 3
    assert recent_average(past, "c", n=1)["avoidable"] == 2
    assert recent_average(past.iloc[:0]).empty


def test_every_focus_points_at_a_tracked_number():
    row = match_numbers(_match("m", SAVE_AFTER_PISTOL), ME)
    tracked = set(row) | {"deaths", "avoidable", "repeeks", "pushed_alone", "lost_gear", "set_up_rate", "unused_deaths", "team_flashes",
                          "far_deaths"}
    assert {column for _, column, _ in FOCUS.values()} <= tracked
