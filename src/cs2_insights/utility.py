"""Utility: how a player's grenades and flashes helped or hurt their team in one match.

Facts come from demo.parse_utility (per player and round) and the deaths table (grenades still
carried at death). Numbers are compared with the other players in the same match.
"""

import pandas as pd

# Dying with at least this much unused utility is worth pointing out.
UNUSED_WORTH_MENTION = 400


def utility_summary(utility: pd.DataFrame, deaths: pd.DataFrame, steamid: str) -> dict:
    """Totals for one player, plus the per-player average across the match for comparison."""
    per_player = utility.groupby("steamid")[
        ["flashes", "smokes", "hes", "molotovs", "enemies_blinded", "teammates_blinded", "enemy_blind_seconds", "utility_damage"]
    ].sum()
    if steamid not in per_player.index:
        return {}
    mine = per_player.loc[steamid]
    match = per_player.mean()
    my_deaths = deaths[deaths["victim"] == steamid] if len(deaths) else deaths
    unused = my_deaths[my_deaths["unused_utility"] >= UNUSED_WORTH_MENTION] if len(my_deaths) and "unused_utility" in my_deaths else my_deaths.iloc[:0]

    def per_flash(row):
        return row["enemies_blinded"] / row["flashes"] if row["flashes"] else 0.0

    return {
        "thrown": {k: int(mine[k]) for k in ("flashes", "smokes", "hes", "molotovs")},
        "grenades": int(mine[["flashes", "smokes", "hes", "molotovs"]].sum()),
        "match_grenades": round(float(match[["flashes", "smokes", "hes", "molotovs"]].sum()), 1),
        "enemies_blinded": int(mine["enemies_blinded"]),
        "teammates_blinded": int(mine["teammates_blinded"]),
        "match_teammates_blinded": round(float(match["teammates_blinded"]), 1),
        "enemy_blind_seconds": round(float(mine["enemy_blind_seconds"]), 1),
        "per_flash": round(per_flash(mine), 2),
        "match_per_flash": round(float(match["enemies_blinded"].sum() / max(match["flashes"].sum(), 1)), 2),
        "utility_damage": int(mine["utility_damage"]),
        "match_utility_damage": round(float(match["utility_damage"]), 0),
        "unused_deaths": len(unused),
        "unused_value": int(unused["unused_utility"].sum()) if len(unused) else 0,
    }


def team_flashes(blinds: pd.DataFrame, steamid: str) -> pd.DataFrame:
    """Every time this player's flash blinded a teammate for a second or more."""
    if blinds.empty:
        return blinds
    return blinds[(blinds["thrower"] == steamid) & blinds["teammate"].astype(bool)].sort_values("tick").reset_index(drop=True)
