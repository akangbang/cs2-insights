import pandas as pd
import pytest

from cs2_insights.recap import build_recap


def _past(repeeks, far=None, rate=None, ids=None, won=None):
    n = len(repeeks)
    return pd.DataFrame({
        "match_id": ids or [str(1000 + i) for i in range(n)],
        "won": won or [True, False] * (n // 2) + [True] * (n % 2),
        "avoidable": repeeks,
        "repeeks": repeeks,
        "far_deaths": far or [2] * n,
        "set_up_rate": rate or [0.4] * n,
    })


def test_compares_the_latest_matches_with_the_ones_before():
    recap = build_recap(_past([3, 3, 3, 3, 3, 1, 1, 1, 1, 1]))
    assert recap.window == 5
    assert recap.avoidable == 1 and recap.earlier_avoidable == 3
    assert recap.improved.key == "repeek" and recap.slipped is None
    assert "re-peeking after a kill" in recap.headline and "3.0 → 1.0" in recap.headline


def test_the_groups_shrink_to_fit_the_matches_played():
    assert build_recap(_past([2, 2, 1, 1, 1])).window == 2


def test_needs_enough_matches():
    assert build_recap(_past([2, 2, 2])) is None
    assert build_recap(pd.DataFrame()) is None


def test_a_higher_share_is_better_when_higher_is_better():
    recap = build_recap(_past([2] * 6, far=[2] * 6, rate=[0.2, 0.2, 0.2, 0.7, 0.7, 0.7]))
    assert recap.improved.key == "coverage"
    assert recap.improved.value() == "70%"


def test_reports_what_got_worse():
    recap = build_recap(_past([2] * 6, far=[1, 1, 1, 4, 4, 4]))
    assert recap.slipped.key == "spacing" and recap.improved is None
    assert recap.slipped.difference == pytest.approx(3)
    assert recap.headline.startswith("Watch")


def test_small_wobbles_do_not_count_as_moving():
    recap = build_recap(_past([2, 3, 2, 3, 2, 3, 3, 2]))
    assert recap.improved is None and recap.slipped is None
    assert "Nothing clearly moved" in recap.headline


def test_uploads_are_left_out_because_their_order_is_unknown():
    ids = ["1000", "1001", "1002", "1003", "upload_ab"]
    recap = build_recap(_past([3, 3, 1, 1, 9], ids=ids))
    assert recap.skipped_uploads == 1
    assert recap.avoidable == 1  # the upload's 9 isn't counted as the latest match
