"""Pooled buy-matchup win rates: how often each buy wins against each opposing buy."""

import numpy as np
import pandas as pd

# Pooled win rates are shrunk toward the buy type's overall rate by this many rounds,
# so a matchup seen only a few times doesn't swing to 0% or 100%.
SMOOTHING_ROUNDS = 10
# Win chance from equipment: sigmoid(slope * ln(your equipment / theirs)), per player.
# The default slope is the fit on the first 12 stored matches; smaller pools fall back to it.
DEFAULT_EQUIPMENT_SLOPE = 1.18
MIN_ROUNDS_TO_FIT = 150
EQUIPMENT_FLOOR = 200  # a default pistol, so an empty loadout isn't divided by zero


def pooled_rates(team_rounds: pd.DataFrame) -> pd.DataFrame:
    """Win counts per (buy_type, opponent_buy_type) from team-round rows of many matches."""
    opponents = team_rounds[["match_id", "round", "team", "buy_type"]].rename(
        columns={"team": "opp_team", "buy_type": "opponent_buy_type"}
    )
    paired = team_rounds.merge(opponents, on=["match_id", "round"])
    paired = paired[paired["team"] != paired["opp_team"]]
    return (
        paired.groupby(["buy_type", "opponent_buy_type"])
        .agg(rounds=("won", "size"), wins=("won", "sum"))
        .reset_index()
    )


def expected_win_rate(pool: pd.DataFrame, buy: str, opponent_buy: str) -> tuple[float, int]:
    """Smoothed pooled win rate for a matchup, and how many rounds it's based on.

    The prior averages "how often this buy wins" with "how often the opponent's buy loses",
    so a matchup and its mirror always sum to 1 and both teams' expected wins add up to the
    rounds played.
    """

    def overall(buy_type: str) -> float:
        rows = pool[pool["buy_type"] == buy_type]
        return rows["wins"].sum() / rows["rounds"].sum() if rows["rounds"].sum() else 0.5

    prior = (overall(buy) + 1 - overall(opponent_buy)) / 2
    match = pool[(pool["buy_type"] == buy) & (pool["opponent_buy_type"] == opponent_buy)]
    wins, rounds = (int(match["wins"].iat[0]), int(match["rounds"].iat[0])) if not match.empty else (0, 0)
    return (wins + SMOOTHING_ROUNDS * prior) / (rounds + SMOOTHING_ROUNDS), rounds


def equipment_win_rate(your_equip: float, their_equip: float, slope: float = DEFAULT_EQUIPMENT_SLOPE) -> float:
    """Win chance for one team given both teams' average equipment value per player."""
    ratio = max(your_equip, EQUIPMENT_FLOOR) / max(their_equip, EQUIPMENT_FLOOR)
    return float(1 / (1 + np.exp(-slope * np.log(ratio))))


def equipment_slope(team_rounds: pd.DataFrame) -> float:
    """Fit the equipment curve's slope to pooled non-pistol rounds (logistic regression, no intercept).

    Each round appears once per team with the mirrored ratio, so no intercept is needed: equal
    equipment is a coin flip.
    """
    rounds = team_rounds[team_rounds["buy_type"] != "pistol"]
    per_player = rounds["equip_value"] / rounds["players"]
    opponents = rounds[["match_id", "round", "team"]].assign(their=per_player)
    paired = rounds.assign(mine=per_player).merge(opponents, on=["match_id", "round"], suffixes=("", "_opp"))
    paired = paired[paired["team"] != paired["team_opp"]]
    if len(paired) < MIN_ROUNDS_TO_FIT:
        return DEFAULT_EQUIPMENT_SLOPE
    x = np.log(paired["mine"].clip(lower=EQUIPMENT_FLOOR) / paired["their"].clip(lower=EQUIPMENT_FLOOR)).to_numpy()
    y = paired["won"].astype(float).to_numpy()
    slope = DEFAULT_EQUIPMENT_SLOPE
    for _ in range(25):  # Newton's method on the log-likelihood
        p = 1 / (1 + np.exp(-slope * x))
        slope += (x @ (y - p)) / max((x * x) @ (p * (1 - p)), 1e-9)
    return float(slope)
