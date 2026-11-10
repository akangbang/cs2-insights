"""Round-loss chain: your team's chance to win a round, traced through every death and the bomb plant.

The chance comes from the fight model (players alive on each side and the bomb). It doesn't know
positions, health or utility, so it shows where a round swung, not exactly why.
"""

import pandas as pd

from cs2_insights.fights import FightModel

COLUMNS = ["seconds", "kind", "victim", "mine", "place", "before", "after", "change"]
DEATH, PLANT = "death", "plant"


def _chance(model: FightModel, mine: int, theirs: int, plant: int) -> float:
    return float(model.win_chance(mine, theirs, plant)[0])


def round_chain(deaths: pd.DataFrame, number: int, team: str, side: str, model: FightModel | None = None) -> pd.DataFrame:
    """One row per moment the win chance moved in round `number`, from `team`'s point of view (`side` is its side that round)."""
    model = model or FightModel()
    rows = deaths[deaths["round"] == number].sort_values("tick") if len(deaths) else deaths
    if rows.empty:
        return pd.DataFrame(columns=COLUMNS)
    first = rows.iloc[0]
    mine, theirs = (int(first["team_alive"]), int(first["enemies_alive"])) if first["victim_team"] == team else (int(first["enemies_alive"]), int(first["team_alive"]))
    plant, out = 0, []
    for d in rows.itertuples():
        if d.bomb_planted and not plant:
            planted = 1 if side == "T" else -1
            at = d.round_seconds - d.plant_seconds if pd.notna(getattr(d, "plant_seconds", None)) else d.round_seconds
            before, after = _chance(model, mine, theirs, 0), _chance(model, mine, theirs, planted)
            out.append({"seconds": float(at), "kind": PLANT, "victim": None, "mine": side == "T", "place": None,
                        "before": before, "after": after, "change": after - before})
            plant = planted
        ours = d.victim_team == team
        before = _chance(model, mine, theirs, plant)
        mine, theirs = (mine - 1, theirs) if ours else (mine, theirs - 1)
        after = _chance(model, mine, theirs, plant)
        out.append({"seconds": float(d.round_seconds), "kind": DEATH, "victim": d.victim, "mine": bool(ours), "place": d.victim_place,
                    "before": before, "after": after, "change": after - before})
    return pd.DataFrame(out, columns=COLUMNS)


def start_chance(chain: pd.DataFrame) -> float | None:
    return float(chain["before"].iloc[0]) if len(chain) else None


def turning_point(chain: pd.DataFrame, won: bool) -> pd.Series | None:
    """The biggest swing toward the result: the largest drop in a lost round, the largest rise in a won one."""
    if chain.empty:
        return None
    pick = chain["change"].idxmax() if won else chain["change"].idxmin()
    swing = chain.loc[pick]
    return swing if (swing["change"] > 0 if won else swing["change"] < 0) else None
