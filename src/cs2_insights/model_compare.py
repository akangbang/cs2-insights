"""Can machine learning predict round wins better than Getleanpeek's simple model?

The round win chance behind every death verdict comes from a hand-written logistic regression on
three numbers: players alive on each side and whether the bomb is down (fights.FightModel). This
module tests it against three standard models that also see the round clock, the side, both teams'
equipment and the map:

- scikit-learn LogisticRegression (the same kind of model, more inputs),
- scikit-learn HistGradientBoostingClassifier (gradient-boosted trees),
- XGBoost (gradient-boosted trees, the usual winner on tabular data).

Every model is scored the same way as the accuracy page: leave-one-match-out, so a model never sees
the match it predicts, and rounds of one match never leak between training and testing. Every state
is seen from both teams' side; the ML models' two answers are averaged so they always add up to 100%.

The result is saved to docs/model_comparison.json, which the "How accurate is it?" page shows. The
app itself doesn't need scikit-learn or XGBoost: they're in requirements-ml.txt.

Usage: python -m cs2_insights.model_compare
"""

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from cs2_insights import db
from cs2_insights.demo import ParsedDemo
from cs2_insights.fights import fit_fight_model

OUT = Path(__file__).resolve().parents[2] / "docs" / "model_comparison.json"
CURRENT = "Current model"
MODELS = {
    CURRENT: "Hand-written logistic regression: players alive and the bomb (3 inputs)",
    "Logistic regression": "scikit-learn, with the round clock, side, both teams' equipment and the map",
    "Gradient boosting": "scikit-learn HistGradientBoostingClassifier, same inputs",
    "XGBoost": "XGBoost gradient-boosted trees, same inputs",
}
NUMERIC = ["alive_diff", "alive_log_ratio", "plant", "is_t", "round_seconds", "equip_k", "enemy_equip_k"]
INPUT_NAMES = {
    "alive_diff": "Players alive: difference", "alive_log_ratio": "Players alive: ratio", "plant": "Bomb planted",
    "is_t": "Side (T or CT)", "round_seconds": "Round clock", "equip_k": "Your team's equipment", "enemy_equip_k": "Their equipment",
}
SEED = 7


def states(matches: list[ParsedDemo]) -> pd.DataFrame:
    """One row per team per death: the situation just before it, and whether that team won the round."""
    frames = []
    for m in matches:
        if m.deaths.empty or m.team_rounds.empty:
            continue
        teams = m.team_rounds.drop(columns="match_id", errors="ignore")[["round", "team", "side", "equip_value", "won"]]
        d = m.deaths.drop(columns="match_id", errors="ignore")
        d = d[(d["team_alive"] > 0) & (d["enemies_alive"] > 0)]
        mine = d.merge(teams.rename(columns={"team": "victim_team"}), on=["round", "victim_team"], how="inner")
        theirs = teams.rename(columns={"team": "killer_team", "side": "enemy_side", "equip_value": "enemy_equip", "won": "enemy_won"})
        mine = mine.merge(theirs, on=["round", "killer_team"], how="left")
        mine["enemy_equip"] = mine["enemy_equip"].fillna(mine["equip_value"])
        mine = mine.dropna(subset=["won"])
        planted = mine["bomb_planted"].astype(bool)
        is_t = (mine["side"] == "T").astype(int)
        base = pd.DataFrame({
            "match_id": str(m.match.iloc[0]["match_id"]),
            "map": str(m.match.iloc[0]["map"]),
            "round": mine["round"].to_numpy(),
            "round_seconds": mine["round_seconds"].astype(float).to_numpy(),
        })
        victim = base.assign(
            team_alive=mine["team_alive"].to_numpy(), enemies_alive=mine["enemies_alive"].to_numpy(),
            plant=np.where(planted, np.where(is_t == 1, 1, -1), 0), is_t=is_t.to_numpy(),
            equip_k=mine["equip_value"].to_numpy() / 1000, enemy_equip_k=mine["enemy_equip"].to_numpy() / 1000,
            won=mine["won"].astype(bool).to_numpy(), view=0,
        )
        killer = victim.assign(
            team_alive=victim["enemies_alive"], enemies_alive=victim["team_alive"], plant=-victim["plant"],
            is_t=1 - victim["is_t"], equip_k=victim["enemy_equip_k"], enemy_equip_k=victim["equip_k"], won=~victim["won"], view=1,
        )
        frames += [victim, killer]
    if not frames:
        return pd.DataFrame(columns=["match_id", "map", "round", "round_seconds", "team_alive", "enemies_alive", "plant", "is_t",
                                     "equip_k", "enemy_equip_k", "won", "view", "alive_diff", "alive_log_ratio"])
    out = pd.concat(frames, ignore_index=True)
    out["alive_diff"] = out["team_alive"] - out["enemies_alive"]
    out["alive_log_ratio"] = np.log((out["team_alive"] + 0.5) / (out["enemies_alive"] + 0.5))
    return out


def _mirror(rows: pd.DataFrame) -> pd.DataFrame:
    """The same states from the other team's side."""
    return rows.assign(
        team_alive=rows["enemies_alive"], enemies_alive=rows["team_alive"], plant=-rows["plant"], is_t=1 - rows["is_t"],
        equip_k=rows["enemy_equip_k"], enemy_equip_k=rows["equip_k"],
        alive_diff=-rows["alive_diff"], alive_log_ratio=-rows["alive_log_ratio"],
    )


def _ml_models() -> dict:
    """Name -> function that builds a fresh, unfitted model. Imported here so the app never needs these libraries."""
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    from xgboost import XGBClassifier

    def encoded(scale: bool):
        numeric = StandardScaler() if scale else "passthrough"
        return ColumnTransformer([("num", numeric, NUMERIC), ("map", OneHotEncoder(handle_unknown="ignore", sparse_output=False), ["map"])])

    return {
        "Logistic regression": lambda: make_pipeline(encoded(True), LogisticRegression(max_iter=2_000)),
        "Gradient boosting": lambda: make_pipeline(encoded(False), HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.05, max_iter=200, l2_regularization=1.0, random_state=SEED)),
        "XGBoost": lambda: make_pipeline(encoded(False), XGBClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            reg_lambda=1.0, eval_metric="logloss", random_state=SEED, n_jobs=1)),
    }


def predictions(matches: list[ParsedDemo]) -> pd.DataFrame:
    """Leave-one-match-out predictions from every model: one row per state and model."""
    data = states(matches)
    usable = [m for m in matches if len(m.deaths) and str(m.match.iloc[0]["match_id"]) in set(data["match_id"])]
    builders = _ml_models()
    rows = []
    for held_out in usable:
        match_id = str(held_out.match.iloc[0]["match_id"])
        train, test = data[data["match_id"] != match_id], data[data["match_id"] == match_id]
        if train.empty or test.empty or train["won"].nunique() < 2:
            continue
        others = [m for m in usable if m is not held_out]
        current = fit_fight_model(pd.concat([m.deaths for m in others], ignore_index=True),
                                  pd.concat([m.trade_chances for m in others], ignore_index=True),
                                  pd.concat([m.team_rounds for m in others], ignore_index=True))
        out = test[["match_id", "won"]].copy()
        out[CURRENT] = current.win_chance(test["team_alive"], test["enemies_alive"], test["plant"])
        X = train[NUMERIC + ["map"]]
        for name, build in builders.items():
            model = build().fit(X, train["won"].astype(int))
            p = model.predict_proba(test[NUMERIC + ["map"]])[:, 1]
            p_other = model.predict_proba(_mirror(test)[NUMERIC + ["map"]])[:, 1]
            out[name] = (p + 1 - p_other) / 2  # both sides' answers, so they add up to 100%
        rows.append(out)
    if not rows:
        return pd.DataFrame(columns=["match_id", "won", *MODELS])
    return pd.concat(rows, ignore_index=True)


def score(preds: pd.DataFrame) -> pd.DataFrame:
    """Per model: Brier score (lower is better), skill against guessing the average, log loss and AUC."""
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    y = preds["won"].astype(int).to_numpy()
    baseline = float(np.mean((y.mean() - y) ** 2))
    rows = []
    for name in MODELS:
        p = np.clip(preds[name].to_numpy(float), 1e-6, 1 - 1e-6)
        brier = float(brier_score_loss(y, p))
        rows.append({"model": name, "brier": brier, "skill": 1 - brier / baseline if baseline else 0.0,
                     "log_loss": float(log_loss(y, p)), "auc": float(roc_auc_score(y, p))})
    return pd.DataFrame(rows)


def per_match(preds: pd.DataFrame, model: str) -> dict:
    """Is `model` better match after match, or only on average? The Brier gain over the current model, per match."""
    err = preds.assign(new=(preds[model] - preds["won"]) ** 2, old=(preds[CURRENT] - preds["won"]) ** 2)
    gain = err.groupby("match_id")[["old", "new"]].mean().eval("old - new")
    se = float(gain.std(ddof=1) / np.sqrt(len(gain))) if len(gain) > 1 else 0.0
    return {"better_in": int((gain > 0).sum()), "of": int(len(gain)),
            "mean_gain": round(float(gain.mean()), 4), "standard_error": round(se, 4)}


def importance(matches: list[ParsedDemo]) -> pd.DataFrame:
    """Which inputs XGBoost leans on most, fitted on every match (gain, as a share of the total)."""
    data = states(matches)
    model = _ml_models()["XGBoost"]().fit(data[NUMERIC + ["map"]], data["won"].astype(int))
    names = model[0].get_feature_names_out()
    gains = model[-1].get_booster().get_score(importance_type="total_gain")
    table = pd.DataFrame({"input": names, "gain": [gains.get(f"f{i}", 0.0) for i in range(len(names))]})
    table["input"] = [INPUT_NAMES.get(n.removeprefix("num__"), n.replace("map__map_", "Map: ")) for n in table["input"]]
    table = table.assign(share=table["gain"] / table["gain"].sum()).sort_values("share", ascending=False)
    return table[["input", "share"]].reset_index(drop=True)


def compare(matches: list[ParsedDemo]) -> dict:
    preds = predictions(matches)
    table = score(preds)
    best = table.sort_values("brier").iloc[0]
    current = table.set_index("model").loc[CURRENT]
    return {
        "date": date.today().isoformat(),
        "matches": int(preds["match_id"].nunique()),
        "states": int(len(preds)),
        "models": [{**row, "about": MODELS[row["model"]]} for row in table.round(4).to_dict("records")],
        "best": str(best["model"]),
        "brier_gain": round(float(current["brier"] - best["brier"]), 4),
        "per_match": per_match(preds, str(best["model"])) if best["model"] != CURRENT else None,
        "importance": importance(matches).head(8).round(4).to_dict("records"),
    }


def main() -> int:
    with db.connect() as conn:
        matches = db.load_matches(conn)
    result = compare(matches)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['matches']} matches, {result['states']} states, leave-one-match-out\n")
    print(pd.DataFrame(result["models"]).drop(columns="about").to_string(index=False))
    print(f"\nBest: {result['best']} (Brier {result['brier_gain']:+.4f} better than the current model)")
    if result["per_match"]:
        pm = result["per_match"]
        print(f"Better in {pm['better_in']} of {pm['of']} matches; mean gain {pm['mean_gain']:+.4f} ± {pm['standard_error']:.4f} per match")
    print(pd.DataFrame(result["importance"]).to_string(index=False))
    print(f"\nSaved {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
