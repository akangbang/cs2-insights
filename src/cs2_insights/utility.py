"""Utility: how a player's grenades and flashes helped or hurt their team in one match.

Facts come from demo.parse_utility (per player and round) and the deaths table (grenades still
carried at death). Numbers are compared with the other players in the same match.
"""

import pandas as pd

# Dying with at least this much unused utility is worth pointing out.
UNUSED_WORTH_MENTION = 400

FLASH_COST_TEAMMATE, FLASH_TRADE_OFF, FLASH_WASTED = "Cost a teammate", "Trade-off", "Wasted"
FLASH_FIXES = {
    FLASH_COST_TEAMMATE: "Say \"flashing\" before you throw, and wait until your teammate has turned away or stepped back.",
    FLASH_TRADE_OFF: "It caught an enemy too, so it may have been worth it. Warn your teammate so only the enemy is blind.",
    FLASH_WASTED: "Check where your teammates are before you throw. A flash that only blinds your team gives the enemy a free fight.",
}
TICKS_PER_SECOND = 64


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


def review_team_flashes(blinds: pd.DataFrame, deaths: pd.DataFrame, steamid: str) -> pd.DataFrame:
    """One row per teammate this player flashed: did the flash also catch enemies, and did the teammate die blind?"""
    columns = ["round", "tick", "blinded", "seconds", "enemies_caught", "died_blind", "death_cost", "verdict",
               "thrower_x", "thrower_y", "blinded_x", "blinded_y"]
    hits = team_flashes(blinds, steamid)
    if hits.empty:
        return pd.DataFrame(columns=columns)
    enemies = blinds[(blinds["thrower"] == steamid) & ~blinds["teammate"].astype(bool)].groupby("tick").size()
    rows = []
    for hit in hits.to_dict("records"):
        blind_until = hit["tick"] + hit["seconds"] * TICKS_PER_SECOND
        killed = deaths[(deaths["victim"] == hit["blinded"]) & (deaths["tick"] >= hit["tick"]) & (deaths["tick"] <= blind_until)] if len(deaths) else deaths
        caught = int(enemies.get(hit["tick"], 0))
        verdict = FLASH_COST_TEAMMATE if len(killed) else FLASH_TRADE_OFF if caught else FLASH_WASTED
        rows.append({
            "round": hit["round"], "tick": hit["tick"], "blinded": hit["blinded"], "seconds": hit["seconds"],
            "enemies_caught": caught, "died_blind": bool(len(killed)),
            "death_cost": float(killed["cost"].iloc[0]) if len(killed) and "cost" in killed else 0.0,
            "verdict": verdict, **{c: hit.get(c) for c in columns[-4:]},
        })
    return pd.DataFrame(rows, columns=columns)
