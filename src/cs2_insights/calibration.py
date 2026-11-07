"""Do the predictions match reality? A test on matches the models haven't seen.

For each match, the models are fitted on every other match and then predict the held-out one
(leave-one-match-out). Predictions are grouped into 10% buckets: if a model is honest, the
situations it calls "30%" should come true about 30% of the time.

Usage: python -m cs2_insights.calibration
"""

import sys

import numpy as np
import pandas as pd

from cs2_insights import db
from cs2_insights.demo import ParsedDemo
from cs2_insights.fights import TRADE_SECONDS, fit_fight_model
from cs2_insights.rates import equipment_slope, equipment_win_rate

MODELS = {
    "equipment": "Round win chance from each team's equipment, before the round starts",
    "alive": "Round win chance during the round, from players alive and the bomb",
    "trade": "Chance a teammate trades a death, from distance and aim",
}
MIN_BUCKET = 10  # buckets with fewer predictions than this are too thin to read anything into


def predictions(matches: list[ParsedDemo]) -> pd.DataFrame:
    """One row per prediction on a held-out match: model, predicted chance, what actually happened."""
    rows = []
    usable = [m for m in matches if len(m.deaths)]
    for held_out in usable:
        others = [m for m in usable if m is not held_out]
        if not others:
            continue
        rounds = pd.concat([m.team_rounds for m in others], ignore_index=True)
        model = fit_fight_model(
            pd.concat([m.deaths for m in others], ignore_index=True),
            pd.concat([m.trade_chances for m in others], ignore_index=True),
            rounds,
        )
        slope = equipment_slope(rounds)
        rows += _predict_match(held_out, model, slope)
    return pd.DataFrame(rows, columns=["model", "predicted", "happened"])


def _predict_match(parsed: ParsedDemo, model, slope: float) -> list[dict]:
    rows = []
    teams = parsed.team_rounds.set_index(["round", "team"])
    # Equipment: once per round from team A's side (team B's view is the mirror image), pistols excluded.
    for r in parsed.team_rounds[(parsed.team_rounds["team"] == "A") & (parsed.team_rounds["buy_type"] != "pistol")].itertuples():
        if (r.round, "B") in teams.index:
            them = teams.loc[(r.round, "B")]
            rows.append({
                "model": "equipment",
                "predicted": equipment_win_rate(r.equip_value / max(r.players, 1), them["equip_value"] / max(them["players"], 1), slope),
                "happened": bool(r.won),
            })
    # Alive: the state before each death, from both teams' sides. Looking only from the side about to
    # lose a player would leak the outcome: that team is about to be a player down.
    for d in parsed.deaths.itertuples():
        if (d.round, d.victim_team) not in teams.index or d.team_alive <= 0 or d.enemies_alive <= 0:
            continue
        team = teams.loc[(d.round, d.victim_team)]
        plant = (1 if team["side"] == "T" else -1) if d.bomb_planted else 0
        chance = float(model.win_chance(d.team_alive, d.enemies_alive, plant)[0])
        rows.append({"model": "alive", "predicted": chance, "happened": bool(team["won"])})
        rows.append({"model": "alive", "predicted": 1 - chance, "happened": not bool(team["won"])})
    # Trade: every living teammate at every death.
    deaths = parsed.deaths.set_index(["tick", "victim"])
    for c in parsed.trade_chances.itertuples():
        if (c.tick, c.victim) in deaths.index:
            d = deaths.loc[(c.tick, c.victim)]
            traded = d["traded_by"] == c.mate and pd.notna(d["trade_seconds"]) and d["trade_seconds"] <= TRADE_SECONDS
            rows.append({"model": "trade", "predicted": float(model.trade_chance(c.distance_to_killer, c.aim_angle)[0]), "happened": bool(traded)})
    return rows


def buckets(preds: pd.DataFrame) -> pd.DataFrame:
    """Predicted vs actual per 10% bucket and model."""
    if preds.empty:
        return pd.DataFrame(columns=["model", "bucket", "predicted", "actual", "n", "thin"])
    out = preds.assign(bucket=(preds["predicted"].clip(0, 0.999) * 10).astype(int) * 10, happened=preds["happened"].astype(float))
    table = out.groupby(["model", "bucket"]).agg(predicted=("predicted", "mean"), actual=("happened", "mean"), n=("happened", "size")).reset_index()
    table["thin"] = table["n"] < MIN_BUCKET
    return table


def scores(preds: pd.DataFrame) -> pd.DataFrame:
    """Per model: average miss between predicted and actual, and accuracy against a naive baseline.

    `brier` is the mean squared error of the predictions (lower is better). `baseline` is the same
    for always guessing the overall rate, so `skill` above 0 means the model beats knowing nothing.
    """
    rows = []
    for name, group in preds.groupby("model"):
        happened = group["happened"].astype(float).to_numpy()
        predicted = group["predicted"].to_numpy()
        brier = float(np.mean((predicted - happened) ** 2))
        baseline = float(np.mean((happened.mean() - happened) ** 2))
        table = buckets(group)
        miss = float(np.average((table["predicted"] - table["actual"]).abs(), weights=table["n"]))
        rows.append({"model": name, "predictions": len(group), "brier": brier, "baseline": baseline,
                     "skill": 1 - brier / baseline if baseline else 0.0, "average_miss": miss})
    return pd.DataFrame(rows, columns=["model", "predictions", "brier", "baseline", "skill", "average_miss"])


def main() -> int:
    with db.connect() as conn:
        matches = db.load_matches(conn)
    preds = predictions(matches)
    print(f"{sum(1 for m in matches if len(m.deaths))} matches, leave-one-match-out\n")
    print(scores(preds).round(3).to_string(index=False))
    print()
    print(buckets(preds).round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
