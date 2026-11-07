"""Match-by-match numbers for one player: what progress and the weekly focus are tracked on."""

import pandas as pd

from cs2_insights import fights, spacing
from cs2_insights.demo import ParsedDemo
from cs2_insights.fights import FightModel, coverage, judge_deaths
from cs2_insights.grade import SHOULD_FORCE, SHOULD_SAVE, grade_decisions
from cs2_insights.rates import DEFAULT_EQUIPMENT_SLOPE

RECENT_MATCHES = 5

# A habit to focus on: label, history column, and whether lower is better.
FOCUS = {
    "repeek": ("Re-peeking after a kill", "repeeks", True),
    "alone": ("Pushing without support", "pushed_alone", True),
    "gear": ("Dying with gear in lost rounds", "lost_gear", True),
    "coverage": ("Being in position to trade", "set_up_rate", False),
    "team_flash": ("Flashing teammates", "team_flashes", True),
    "unused": ("Dying with unused grenades", "unused_deaths", True),
    "spacing": ("Dying far from teammates", "far_deaths", True),
    "buy_calls": ("Wrong buy calls", "wrong_calls", True),
}


def match_numbers(parsed: ParsedDemo, steamid: str, model: FightModel | None = None, slope: float = DEFAULT_EQUIPMENT_SLOPE) -> dict | None:
    """One match's numbers for `steamid`, or None if they didn't play in it."""
    me = parsed.player_rounds[parsed.player_rounds["steamid"] == steamid]
    if me.empty:
        return None
    model = model or FightModel()
    team = me["team"].mode().iat[0]
    match = parsed.match.iloc[0]
    calls = grade_decisions(parsed.team_rounds, team, slope)
    row = {
        "match_id": match["match_id"],
        "map": match["map"],
        "won": int(match["team_a_score"] if team == "A" else match["team_b_score"])
        > int(match["team_b_score"] if team == "A" else match["team_a_score"]),
        "wrong_calls": int(calls["grade"].isin([SHOULD_FORCE, SHOULD_SAVE]).sum()),
        "fights_parsed": bool(len(parsed.deaths)),
    }
    if len(parsed.deaths):
        judged = judge_deaths(parsed.deaths, parsed.trade_chances, parsed.team_rounds, model)
        mine = judged[judged["victim"] == steamid]
        cover = coverage(judged, parsed.trade_chances, steamid, model)
        set_up = (cover["distance_to_killer"] <= fights.TRADE_RANGE) & (cover["aim_angle"] <= fights.FACING_ANGLE) if len(cover) else pd.Series(dtype=bool)
        row.update({
            "deaths": len(mine),
            "avoidable": int(mine["label"].isin(fights.AVOIDABLE).sum()),
            "repeeks": int((mine["label"] == fights.REPEEK).sum()),
            "pushed_alone": int((mine["label"] == fights.ALONE).sum()),
            "lost_gear": int((mine["label"] == fights.SHOULD_SAVE).sum()),
            "traded": int((mine["label"] == fights.TRADED).sum()),
            "coverage_score": float(cover["chance"].mean()) if len(cover) else None,
            "set_up_rate": float(set_up.mean()) if len(cover) else None,
            "unused_deaths": int((mine.get("unused_utility", pd.Series(0, index=mine.index)) >= 400).sum()),
            "far_deaths": int(spacing.death_spacing(mine, parsed.trade_chances)["band"].isin(spacing.BAND_LABELS[2:]).sum())
            if len(mine) else 0,
        })
    if len(parsed.utility):
        u = parsed.utility[parsed.utility["steamid"] == steamid]
        row.update({"team_flashes": int(u["teammates_blinded"].sum()), "enemies_flashed": int(u["enemies_blinded"].sum())})
    return row


def history(matches: list[ParsedDemo], steamid: str, model: FightModel | None = None, slope: float = DEFAULT_EQUIPMENT_SLOPE) -> pd.DataFrame:
    """One row per match `steamid` played, oldest first (Valve match IDs increase over time)."""
    rows = [r for r in (match_numbers(m, steamid, model, slope) for m in matches) if r]
    return pd.DataFrame(rows).sort_values("match_id").reset_index(drop=True) if rows else pd.DataFrame()


def recent_average(past: pd.DataFrame, exclude_match_id: str | None = None, n: int = RECENT_MATCHES) -> pd.Series:
    """Average of the player's last `n` other matches (empty when there are none)."""
    if past.empty:
        return pd.Series(dtype=float)
    others = past[past["match_id"] != exclude_match_id].tail(n)
    return others.select_dtypes("number").mean() if len(others) else pd.Series(dtype=float)
