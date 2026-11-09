from io import BytesIO

import pandas as pd
import pytest
from PIL import Image

from cs2_insights.proof import CARD_SIZE, IMPROVED, NO_BASELINE, SAME, WAITING, WORSE, build_proof, change_words, latest_match, proof_card


def _past(repeeks, rate=None, ids=None):
    return pd.DataFrame({
        "match_id": ids or [str(1000 + i) for i in range(len(repeeks))],
        "repeeks": repeeks,
        "set_up_rate": rate or [0.4] * len(repeeks),
    })


def test_counts_only_matches_after_the_focus_was_picked():
    proof = build_proof(_past([3, 3, 3, 1, 1, 1]), "repeek", "1002")
    assert proof.status == IMPROVED
    assert (proof.before_matches, proof.after_matches) == (3, 3)
    assert proof.change.earlier == 3 and proof.change.recent == 1


def test_makes_no_claim_until_enough_matches_are_played():
    proof = build_proof(_past([3, 3, 3, 0, 0]), "repeek", "1002")
    assert proof.status == WAITING and proof.after_matches == 2 and proof.change is None


def test_needs_matches_from_before_to_compare_with():
    assert build_proof(_past([1, 1, 1, 1]), "repeek", "1000").status == NO_BASELINE


def test_reports_when_the_habit_got_worse():
    assert build_proof(_past([1, 1, 1, 4, 4, 4]), "repeek", "1002").status == WORSE


def test_a_normal_swing_is_not_progress():
    assert build_proof(_past([2, 3, 2, 3, 2, 3]), "repeek", "1002").status == SAME


def test_compares_with_the_recent_matches_before_the_focus():
    proof = build_proof(_past([9] * 3 + [1] * 5 + [1] * 3), "repeek", "1007")
    assert proof.before_matches == 5 and proof.change.earlier == 1  # the old 9s are out of the window


def test_uploads_do_not_count_because_their_order_is_unknown():
    proof = build_proof(_past([3, 3, 1, 1, 1, 0], ids=["1000", "1001", "1002", "1003", "1004", "upload_ab"]), "repeek", "1001")
    assert proof.after_matches == 3 and proof.change.recent == 1


def test_compares_ids_as_numbers():
    ids = ["999", "1000", "1001", "1002", "1003"]
    assert build_proof(_past([3, 3, 1, 1, 1], ids=ids), "repeek", "1000").after_matches == 3
    assert latest_match(_past([1, 1], ids=["999", "1000"])) == "1000"


def test_latest_match_ignores_uploads():
    assert latest_match(_past([1, 1], ids=["1000", "upload_ab"])) == "1000"
    assert latest_match(pd.DataFrame()) is None


def test_describes_a_higher_share_in_points():
    proof = build_proof(_past([1] * 6, rate=[0.2, 0.2, 0.2, 0.7, 0.7, 0.7]), "coverage", "1002")
    assert proof.status == IMPROVED and change_words(proof.change) == "50 points higher"


def test_card_is_a_share_sized_png():
    proof = build_proof(_past([3, 3, 3, 1, 1, 1]), "repeek", "1002")
    assert change_words(proof.change) == "2.0 fewer per match"
    image = Image.open(BytesIO(proof_card(proof)))
    assert image.format == "PNG" and image.size == CARD_SIZE


@pytest.mark.parametrize("since", ["1005", "2000"])
def test_nothing_after_the_focus_yet(since):
    assert build_proof(_past([1] * 6), "repeek", since).status == WAITING
