"""Recap: your latest matches against the ones before, and what moved.

Demos don't say when they were played, so a recap compares matches, not calendar weeks. Only
matches with a Valve match ID are used: those IDs increase over time, while an uploaded demo's
position in time is unknown.
"""

from dataclasses import dataclass, field

import pandas as pd

from cs2_insights.progress import FOCUS, RECENT_MATCHES

MIN_MATCHES = 4
# A change has to be at least this many standard errors to count as moved rather than noise.
MOVED = 1.0
# The smallest standard error assumed, so one quiet stretch of matches can't look like a big change.
FLOOR = {"count": 0.25, "rate": 0.05}


@dataclass
class Change:
    key: str  # a progress.FOCUS key
    label: str
    earlier: float
    recent: float
    lower_is_better: bool
    kind: str  # "count" (per match) or "rate" (share)
    score: float  # standard errors of change; positive means better

    def value(self, number: float | None = None) -> str:
        number = self.recent if number is None else number
        return f"{number:.0%}" if self.kind == "rate" else f"{number:.1f}"

    @property
    def difference(self) -> float:
        return self.recent - self.earlier


@dataclass
class Recap:
    window: int  # matches in each of the two groups
    win_rate: float
    earlier_win_rate: float
    avoidable: float | None
    earlier_avoidable: float | None
    changes: list[Change] = field(default_factory=list)
    improved: Change | None = None
    slipped: Change | None = None
    skipped_uploads: int = 0

    @property
    def headline(self) -> str:
        def moved(change: Change) -> str:
            unit = "" if change.kind == "rate" else " per match"
            return f"**{change.label.lower()}** ({change.value(change.earlier)} → {change.value()}{unit})"

        if self.improved and self.slipped:
            return f"Better at {moved(self.improved)}, but watch {moved(self.slipped)}."
        if self.improved:
            return f"Better at {moved(self.improved)}, and nothing clearly slipped."
        if self.slipped:
            return f"Watch {moved(self.slipped)}: nothing else clearly moved."
        return "Nothing clearly moved either way. A few matches is a small sample."


def _numbers(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce").dropna() if column in frame else pd.Series(dtype=float)


def _average(frame: pd.DataFrame, column: str) -> float | None:
    numbers = _numbers(frame, column)
    return float(numbers.mean()) if len(numbers) else None


def _change(key: str, earlier: pd.DataFrame, recent: pd.DataFrame) -> Change | None:
    label, column, lower_is_better = FOCUS[key]
    before, after = _numbers(earlier, column), _numbers(recent, column)
    if before.empty or after.empty:
        return None
    kind = "rate" if column.endswith("_rate") else "count"
    spread = (before.var(ddof=1) / len(before) if len(before) > 1 else 0.0) + (after.var(ddof=1) / len(after) if len(after) > 1 else 0.0)
    score = (after.mean() - before.mean()) / max(spread ** 0.5, FLOOR[kind])
    return Change(key, label, float(before.mean()), float(after.mean()), lower_is_better, kind, float(-score if lower_is_better else score))


def build_recap(past: pd.DataFrame, window: int = RECENT_MATCHES) -> Recap | None:
    """Compare the latest matches in progress.history() with the same number before them."""
    if past.empty:
        return None
    ordered = past[past["match_id"].astype(str).str.isdigit()]
    if len(ordered) < MIN_MATCHES:
        return None
    size = min(window, len(ordered) // 2)
    recent, earlier = ordered.iloc[-size:], ordered.iloc[-2 * size:-size]
    changes = [c for c in (_change(key, earlier, recent) for key in FOCUS) if c]
    ranked = sorted(changes, key=lambda c: c.score)
    return Recap(
        window=size,
        win_rate=float(recent["won"].astype(bool).mean()),
        earlier_win_rate=float(earlier["won"].astype(bool).mean()),
        avoidable=_average(recent, "avoidable"),
        earlier_avoidable=_average(earlier, "avoidable"),
        changes=changes,
        improved=ranked[-1] if ranked and ranked[-1].score >= MOVED else None,
        slipped=ranked[0] if ranked and ranked[0].score <= -MOVED else None,
        skipped_uploads=len(past) - len(ordered),
    )
