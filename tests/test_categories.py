import pandas as pd
import pytest

from cs2_insights.categories import ALL, category_counts, category_of, filter_matches, match_category
from cs2_insights.demo import COMPETITIVE, FACEIT, OTHER, PREMIER, ParsedDemo, classify_match


def _demo(kind):
    empty = pd.DataFrame()
    return ParsedDemo(match=pd.DataFrame([{"match_id": str(kind), "match_type": kind}]), rounds=empty, team_rounds=empty, player_rounds=empty)


@pytest.mark.parametrize("server, ranks, expected", [
    ("Valve Counter-Strike 2 us_east Server", [11] * 10, PREMIER),
    ("Valve Counter-Strike 2 us_east Server", [12] * 10, COMPETITIVE),
    ("FACEIT.com register to play here", [0] * 10, FACEIT),
    ("faceit server", [11] * 10, FACEIT),  # the server decides, whatever the rank field says
    ("Some community server", [7] * 10, OTHER),
    (None, [], OTHER),
])
def test_classifies_matches(server, ranks, expected):
    assert classify_match(server, pd.Series(ranks, dtype=float)) == expected


def test_a_stray_rank_value_does_not_change_the_category():
    assert classify_match("Valve", pd.Series([11] * 9 + [0], dtype=float)) == PREMIER


def test_old_matches_count_as_other():
    assert category_of(None) == OTHER and category_of(float("nan")) == OTHER and category_of("wingman") == OTHER
    assert match_category(_demo(None)) == OTHER


def test_counts_only_categories_that_have_matches_in_display_order():
    matches = [_demo(COMPETITIVE), _demo(PREMIER), _demo(PREMIER)]
    assert list(category_counts(matches).items()) == [(PREMIER, 2), (COMPETITIVE, 1)]


def test_filters_by_category():
    matches = [_demo(COMPETITIVE), _demo(PREMIER), _demo(FACEIT)]
    assert [match_category(m) for m in filter_matches(matches, PREMIER)] == [PREMIER]
    assert len(filter_matches(matches, ALL)) == 3 and len(filter_matches(matches, None)) == 3
