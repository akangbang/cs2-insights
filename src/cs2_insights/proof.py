"""Habit proof: has the habit you chose to work on changed since you chose it?

Demos carry no dates, so "since you chose it" is measured in match IDs: when a focus is picked, the
newest stored match ID is remembered, and only matches with a higher ID count as after. Valve IDs
increase over time; uploads have no place in that order and are left out, as in the recap.
"""

from dataclasses import dataclass

import pandas as pd

from cs2_insights.progress import FOCUS, RECENT_MATCHES
from cs2_insights.recap import MOVED, Change, measure_change

MIN_BEFORE = 2  # matches from before the focus needed to compare with
MIN_AFTER = 3  # one or two good matches can be luck, so no claim before this many
WAITING, NO_BASELINE, IMPROVED, SAME, WORSE = "waiting", "no baseline", "improved", "same", "worse"


@dataclass(frozen=True)
class Proof:
    status: str
    label: str
    before_matches: int
    after_matches: int
    change: Change | None = None


def _ordered(past: pd.DataFrame) -> pd.DataFrame:
    return past[past["match_id"].astype(str).str.isdigit()] if len(past) else past


def latest_match(past: pd.DataFrame) -> str | None:
    """The newest match with a known place in time: where a new focus starts counting from."""
    ordered = _ordered(past)
    return str(max(ordered["match_id"].astype(str), key=int)) if len(ordered) else None


def build_proof(past: pd.DataFrame, key: str, since: str) -> Proof:
    """Compare a focus habit before and after match ID `since`."""
    label, column, _ = FOCUS[key]
    ordered = _ordered(past)
    if len(ordered) and column in ordered:
        ordered = ordered[pd.to_numeric(ordered[column], errors="coerce").notna()]
    else:
        ordered = ordered.iloc[:0]
    start = int(since)
    is_after = ordered["match_id"].astype(str).map(lambda m: int(m) > start).astype(bool)
    before, after = ordered[~is_after].tail(RECENT_MATCHES), ordered[is_after]
    if len(after) < MIN_AFTER:
        return Proof(WAITING, label, len(before), len(after))
    if len(before) < MIN_BEFORE:
        return Proof(NO_BASELINE, label, len(before), len(after))
    change = measure_change(key, before, after)
    status = IMPROVED if change.score >= MOVED else WORSE if change.score <= -MOVED else SAME
    return Proof(status, label, len(before), len(after), change)
