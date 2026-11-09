"""Second-half plan: the things to change after the first half, then whether they changed.

The plan uses only the first half, as it would be written at the side switch. Overtime isn't
counted. One half is a small sample, so the follow-up reports what happened, not a verdict on skill.
"""

from dataclasses import dataclass, field

import pandas as pd

from cs2_insights import fights, spacing
from cs2_insights.demo import REGULATION_ROUNDS
from cs2_insights.grade import SHOULD_FORCE, SHOULD_SAVE
from cs2_insights.utility import FLASH_TRADE_OFF

MAX_ITEMS = 3
MIN_SECOND_ROUNDS = 6  # a half cut short by the match ending can't show much
DID_IT, SOME_PROGRESS, NO_CHANGE, TOO_FEW = "Did it", "Some progress", "No change", "Too few rounds"
UNUSED_GRENADES = 400

ITEMS = {
    "repeek": ("Re-peeking after a kill", "After a kill, move: fall back or swing a different angle."),
    "alone": ("Pushing without support", "Wait until a teammate is close enough to trade you before you clear the next angle."),
    "gear": ("Dying with gear in lost rounds", "When the round is lost, hide and keep your gun."),
    "far": ("Dying far from teammates", "Take your fights with a teammate a few steps behind you."),
    "flash": ("Flashing teammates", "Check where your teammates are and say you're flashing before you throw."),
    "unused": ("Dying with unused grenades", "Throw a flash or molotov before you take the fight."),
    "buy": ("Wrong buy calls", "Before each buy, check what the enemy can afford, and agree: everyone buys or everyone saves."),
}
# How much each kind of miss counts when choosing what to work on. Avoidable deaths and buy calls are
# measured in round win chance. A far death only loses what a trade would win back (about 30% of deaths with
# someone close get traded); unused grenades are a smaller miss and this share is a judgement call.
FAR_WEIGHT = 0.3
UNUSED_WEIGHT = 0.2
WASTED_FLASH_COST = 0.03


@dataclass
class Item:
    key: str
    label: str
    action: str
    first: int
    second: int | None = None
    status: str | None = None


@dataclass
class Plan:
    first_rounds: int
    second_rounds: int
    last_first_round: int
    next_side: str
    items: list[Item] = field(default_factory=list)


def _halves(rounds: pd.DataFrame) -> tuple[list[int], list[int]]:
    regulation = rounds[rounds["round"] <= REGULATION_ROUNDS].sort_values("round")
    if regulation.empty:
        return [], []
    start = regulation["side"].iloc[0]
    switched = regulation[regulation["side"] != start]
    if switched.empty:
        return regulation["round"].tolist(), []
    pivot = int(switched["round"].iloc[0])
    return [r for r in regulation["round"] if r < pivot], [r for r in regulation["round"] if r >= pivot]


def _events(deaths: pd.DataFrame, chances: pd.DataFrame, calls: pd.DataFrame, flashes: pd.DataFrame) -> pd.DataFrame:
    """One row per miss: round, kind and how much it counts."""
    rows = []
    if len(deaths):
        for key, label in (("repeek", fights.REPEEK), ("alone", fights.ALONE), ("gear", fights.SHOULD_SAVE)):
            rows.extend({"round": d.round, "key": key, "weight": d.cost} for d in deaths[deaths["label"] == label].itertuples())
        if "unused_utility" in deaths:
            rows.extend({"round": d.round, "key": "unused", "weight": d.cost * UNUSED_WEIGHT}
                        for d in deaths[deaths["unused_utility"] >= UNUSED_GRENADES].itertuples())
        if "victim_x" in deaths:
            near = spacing.death_spacing(deaths, chances)
            far_ticks = set(near[near["band"].isin(spacing.BAND_LABELS[2:])]["tick"])
            # A death already counted as avoidable, or one that got traded, isn't a spacing miss as well.
            spaced = deaths[deaths["tick"].isin(far_ticks) & ~deaths["label"].isin([*fights.AVOIDABLE, fights.TRADED])]
            rows.extend({"round": d.round, "key": "far", "weight": d.cost * FAR_WEIGHT} for d in spaced.itertuples())
    if len(calls):
        rows.extend({"round": c.round, "key": "buy", "weight": c.cost} for c in calls[calls["grade"].isin([SHOULD_FORCE, SHOULD_SAVE])].itertuples())
    if len(flashes):
        rows.extend({"round": f.round, "key": "flash", "weight": f.death_cost + WASTED_FLASH_COST} for f in flashes[flashes["verdict"] != FLASH_TRADE_OFF].itertuples())
    return pd.DataFrame(rows, columns=["round", "key", "weight"])


def _status(first: int, first_rounds: int, second: int, second_rounds: int) -> str:
    if second_rounds < MIN_SECOND_ROUNDS:
        return TOO_FEW
    before, after = first / first_rounds, second / second_rounds
    if after <= before / 2:
        return DID_IT
    return SOME_PROGRESS if after < before else NO_CHANGE


def build_plan(rounds: pd.DataFrame, deaths: pd.DataFrame, chances: pd.DataFrame, calls: pd.DataFrame, flashes: pd.DataFrame) -> Plan | None:
    """The plan from the first half and, if the match reached it, how the second half went."""
    first, second = _halves(rounds)
    if not first:
        return None
    side = rounds.sort_values("round")["side"].iloc[0]
    events = _events(deaths, chances, calls, flashes)
    early, late = events[events["round"].isin(first)], events[events["round"].isin(second)]
    totals = early.groupby("key").agg(count=("key", "size"), weight=("weight", "sum")).reset_index().sort_values(["weight", "count"], ascending=False)
    repeated = totals[totals["count"] >= 2]
    chosen = (repeated if len(repeated) else totals).head(MAX_ITEMS)
    items = []
    for row in chosen.itertuples():
        label, action = ITEMS[row.key]
        item = Item(row.key, label, action, int(row.count))
        if second:
            item.second = int((late["key"] == row.key).sum())
            item.status = _status(item.first, len(first), item.second, len(second))
        items.append(item)
    return Plan(len(first), len(second), max(first), "T" if side == "CT" else "CT", items)
