"""Where a player's misses happen: on CT or T, and on which maps.

A "miss" is the same list the Second-half plan uses (halfplan.miss_events): avoidable deaths, deaths far
from teammates, flashes that only hurt the team, dying with unused grenades and wrong buy calls. Rates are
per half (12 rounds) so a side or map played more often doesn't look worse just for that.
"""

from dataclasses import dataclass

import pandas as pd

from cs2_insights.demo import ParsedDemo
from cs2_insights.fights import FightModel, judge_deaths
from cs2_insights.grade import grade_decisions
from cs2_insights.halfplan import ITEMS, miss_events
from cs2_insights.rates import DEFAULT_EQUIPMENT_SLOPE
from cs2_insights.utility import review_team_flashes

HALF = 12  # rounds
AVOIDABLE_KEYS = ("repeek", "alone", "gear")
# One side counts as clearly worse when it has at least this many misses, this ratio and this gap per half.
MIN_SIDE_MISSES = 3
SIDE_RATIO = 1.5
SIDE_GAP = 0.5
MIN_MAP_MATCHES = 2  # a map needs this many matches before it's called best or worst


@dataclass
class Misses:
    events: pd.DataFrame  # match_id, map, round, side, key
    rounds: pd.DataFrame  # match_id, map, round, side: every round the player played
    matches: pd.DataFrame  # match_id, map, won


def collect(matches: list[ParsedDemo], steamid: str, model: FightModel | None = None, slope: float = DEFAULT_EQUIPMENT_SLOPE) -> Misses:
    """Every miss `steamid` made across `matches`, tagged with the side and map it happened on."""
    model = model or FightModel()
    events, rounds, results = [], [], []
    for parsed in matches:
        me = parsed.player_rounds[parsed.player_rounds["steamid"] == steamid]
        if me.empty:
            continue
        match = parsed.match.iloc[0]
        tags = {"match_id": match["match_id"], "map": match["map"]}
        team = me["team"].mode().iat[0]
        sides = me.set_index("round")["side"]
        rounds.append(me[["round", "side"]].assign(**tags))
        mine = parsed.team_rounds[parsed.team_rounds["team"] == team]["won"].astype(bool).sum()
        theirs = parsed.team_rounds[parsed.team_rounds["team"] != team]["won"].astype(bool).sum()
        results.append({**tags, "won": bool(mine > theirs)})
        judged = judge_deaths(parsed.deaths, parsed.trade_chances, parsed.team_rounds, model) if len(parsed.deaths) else pd.DataFrame()
        deaths = judged[judged["victim"] == steamid] if len(judged) else judged
        flashes = review_team_flashes(parsed.blinds, judged, steamid) if len(parsed.blinds) else pd.DataFrame()
        found = miss_events(deaths, parsed.trade_chances, grade_decisions(parsed.team_rounds, team, slope), flashes)
        events.append(found.assign(side=found["round"].map(sides), **tags))
    return Misses(
        events=pd.concat(events, ignore_index=True) if events else pd.DataFrame(columns=["match_id", "map", "round", "side", "key"]),
        rounds=pd.concat(rounds, ignore_index=True) if rounds else pd.DataFrame(columns=["match_id", "map", "round", "side"]),
        matches=pd.DataFrame(results, columns=["match_id", "map", "won"]),
    )


def side_breakdown(misses: Misses) -> pd.DataFrame:
    """Per miss and side: how many, and how many per half on that side."""
    columns = ["key", "label", "side", "count", "rounds", "per_half"]
    played = misses.rounds.groupby("side").size()
    if misses.events.empty or played.empty:
        return pd.DataFrame(columns=columns)
    counts = misses.events.groupby(["key", "side"]).size()
    rows = []
    for key in ITEMS:
        if key not in counts.index.get_level_values("key"):
            continue
        for side in ("CT", "T"):
            n, r = int(counts.get((key, side), 0)), int(played.get(side, 0))
            rows.append({"key": key, "label": ITEMS[key][0], "side": side, "count": n, "rounds": r, "per_half": n / r * HALF if r else 0.0})
    return pd.DataFrame(rows, columns=columns)


def side_notes(table: pd.DataFrame) -> list[str]:
    """Misses that clearly happen more on one side."""
    notes = []
    for key, group in table.groupby("key", sort=False):
        rates = group.set_index("side")["per_half"]
        counts = group.set_index("side")["count"]
        if len(rates) < 2:
            continue
        worse, better = ("T", "CT") if rates["T"] > rates["CT"] else ("CT", "T")
        if counts[worse] >= MIN_SIDE_MISSES and rates[worse] - rates[better] >= SIDE_GAP and rates[worse] >= SIDE_RATIO * max(rates[better], 0.01):
            notes.append(f"**{ITEMS[key][0]}** happens mostly on **{worse}**: {rates[worse]:.1f} per half there, {rates[better]:.1f} on {better}.")
    return notes


def map_breakdown(misses: Misses) -> pd.DataFrame:
    """Per map: matches, win rate, avoidable deaths per match, and the most common miss with what to do about it."""
    columns = ["map", "matches", "win_rate", "avoidable_per_match", "top_key", "top_label", "top_per_match", "tip"]
    if misses.matches.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for name, games in misses.matches.groupby("map"):
        found = misses.events[misses.events["map"] == name]
        n = len(games)
        avoidable = int(found["key"].isin(AVOIDABLE_KEYS).sum())
        top = found["key"].value_counts()
        key = top.index[0] if len(top) else None
        rows.append({
            "map": name, "matches": n, "win_rate": float(games["won"].mean()), "avoidable_per_match": avoidable / n,
            "top_key": key, "top_label": ITEMS[key][0] if key else None, "top_per_match": float(top.iloc[0]) / n if key else 0.0,
            "tip": ITEMS[key][1] if key else None,
        })
    return pd.DataFrame(rows, columns=columns).sort_values(["matches", "map"], ascending=[False, True]).reset_index(drop=True)


def best_and_worst(table: pd.DataFrame) -> tuple[pd.Series | None, pd.Series | None]:
    """The maps with the fewest and most avoidable deaths per match, among maps played often enough."""
    enough = table[table["matches"] >= MIN_MAP_MATCHES]
    if len(enough) < 2:
        return None, None
    ranked = enough.sort_values(["avoidable_per_match", "win_rate"], ascending=[True, False])
    return ranked.iloc[0], ranked.iloc[-1]
