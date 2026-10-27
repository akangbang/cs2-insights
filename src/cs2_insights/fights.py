"""Deaths and trades: which of your deaths were avoidable, and how well you cover teammates.

The facts come from demo.parse_fights: every death, and where each living teammate stood and
aimed at that moment. Calibrated on 1,539 kills in the first stored matches: only 12% of
deaths were traded within 2 seconds. A teammate within 300 units of the killer traded 39% of
the time, at 600-900 units 10%, past 1,200 almost never; a crosshair within 10 degrees of the
killer more than doubled the chance, and one facing more than 35 degrees away traded about 3%.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADE_SECONDS = 2  # a death is traded when a teammate kills the killer this soon after
TRADE_RANGE = 900  # units from the killer; trades get rare beyond this
FACING_ANGLE = 35  # degrees between your aim and the killer; trades get rare beyond this
NEAR_TEAMMATE = 1_600  # a teammate dying farther away than this isn't yours to trade
REPEEK_SECONDS = 4
MOVING_SPEED = 100  # units per second: pushing or clearing rather than holding an angle
LOST_CAUSE = 0.15  # round win chance below which your gun is worth more than the fight
GEAR_WORTH_SAVING = 3_000
MIN_COVERAGE_CHANCES = 3  # teammate deaths near you before a match gets a coverage grade

# Your deaths, most actionable first.
TRADED = "Traded"
REPEEK = "Re-peeked after a kill"
SHOULD_SAVE = "Died with gear in a lost round"
ALONE = "Pushed without support"
NOT_TRADED = "Teammates didn't trade"
DUEL = "Lost a duel"
OTHER = "Other"  # team kills, falls, the bomb
AVOIDABLE = (REPEEK, SHOULD_SAVE, ALONE)

# Your coverage of each teammate who died near you.
COVER_TRADED = "You traded"
COVER_OTHER_TRADED = "A teammate traded"
COVER_SET_UP = "Set up, no trade"
COVER_FACING_AWAY = "Facing away"
COVER_TOO_FAR = "Too far to trade"

# Fitted on the first 11 stored matches; fit_fight_model() refits on bigger pools.
# Round win chance: sigmoid(w . [alive difference, log alive ratio, bomb planted for you]).
DEFAULT_ALIVE_WEIGHTS = (0.214, 2.822, 0.564)
# Trade chance: sigmoid(w . [1, distance / 1000, min(angle, 90) / 90]).
DEFAULT_TRADE_WEIGHTS = (1.092, -2.688, -4.061)
# Per-match coverage scores (mean trade chance) at the 20th, 40th, 60th and 80th percentile.
DEFAULT_SETUP_CUTS = (0.046, 0.059, 0.070, 0.084)
GRADES = "FDCBA"
MIN_STATES_TO_FIT = 500
MIN_CHANCES_TO_FIT = 1_000
MIN_SCORES_FOR_CUTS = 40


def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


def _alive_features(team_alive, enemies_alive, plant):
    a, b, plant = np.broadcast_arrays(*(np.atleast_1d(np.asarray(v, float)) for v in (team_alive, enemies_alive, plant)))
    return np.column_stack([a - b, np.log((a + 0.5) / (b + 0.5)), plant])


def _trade_features(distance, angle):
    distance, angle = np.broadcast_arrays(np.atleast_1d(np.asarray(distance, float)), np.atleast_1d(np.asarray(angle, float)))
    return np.column_stack([np.ones_like(distance), distance / 1000, np.minimum(angle, 90) / 90])


@dataclass(frozen=True)
class FightModel:
    alive_weights: tuple = DEFAULT_ALIVE_WEIGHTS
    trade_weights: tuple = DEFAULT_TRADE_WEIGHTS
    setup_cuts: tuple = DEFAULT_SETUP_CUTS

    def win_chance(self, team_alive, enemies_alive, plant=0) -> np.ndarray:
        """Chance the team wins the round. `plant`: +1 bomb planted and you're T, -1 and you're CT."""
        a, b, plant = np.broadcast_arrays(*(np.atleast_1d(np.asarray(v, float)) for v in (team_alive, enemies_alive, plant)))
        p = _sigmoid(_alive_features(a, b, plant) @ np.array(self.alive_weights))
        return np.where(a <= 0, 0.0, np.where(b <= 0, 1.0, p))

    def trade_chance(self, distance, angle) -> np.ndarray:
        """Chance a teammate this far from the killer, aiming this many degrees off, trades within 2 s."""
        return _sigmoid(_trade_features(distance, angle) @ np.array(self.trade_weights))

    def grade(self, setup: float) -> str:
        return GRADES[int(np.searchsorted(self.setup_cuts, setup, side="right"))]


def _newton(X: np.ndarray, y: np.ndarray, start: tuple) -> tuple:
    w = np.array(start, float)
    for _ in range(30):
        p = _sigmoid(X @ w)
        w += np.linalg.solve((X * (p * (1 - p))[:, None]).T @ X + 1e-6 * np.eye(len(w)), X.T @ (y - p))
    return tuple(float(v) for v in w)


def _with_sides(deaths: pd.DataFrame, team_rounds: pd.DataFrame) -> pd.DataFrame:
    """Deaths plus the victim team's side and round result, and the bomb feature from their view."""
    keys = ["match_id", "round"] if "match_id" in deaths and "match_id" in team_rounds else ["round"]
    sides = team_rounds[keys + ["team", "side", "won"]].rename(columns={"team": "victim_team"})
    out = deaths.merge(sides, on=keys + ["victim_team"], how="left")
    out["plant"] = np.where(out["bomb_planted"].astype(bool), np.where(out["side"] == "T", 1, -1), 0)
    return out


def _traded_by_mate(chances: pd.DataFrame, deaths: pd.DataFrame) -> pd.Series:
    keys = ["match_id", "tick", "victim"] if "match_id" in chances and "match_id" in deaths else ["tick", "victim"]
    joined = chances.merge(deaths[keys + ["traded_by", "trade_seconds"]], on=keys, how="left")
    return ((joined["traded_by"] == joined["mate"]) & (joined["trade_seconds"] <= TRADE_SECONDS)).to_numpy()


def fit_fight_model(deaths: pd.DataFrame, chances: pd.DataFrame, team_rounds: pd.DataFrame) -> FightModel:
    """Refit the round, trade and grading models on a pool of matches; small pools keep the defaults."""
    model = FightModel()
    if len(deaths) and len(team_rounds):
        d = _with_sides(deaths, team_rounds).dropna(subset=["won"])
        d = d[(d["team_alive"] > 0) & (d["enemies_alive"] > 0)]
        if len(d) * 2 >= MIN_STATES_TO_FIT:
            # Every state appears from both teams' side, so no intercept: even numbers are a coin flip.
            X = np.vstack([_alive_features(d["team_alive"], d["enemies_alive"], d["plant"]),
                           _alive_features(d["enemies_alive"], d["team_alive"], -d["plant"])])
            y = np.concatenate([d["won"].astype(float), 1 - d["won"].astype(float)])
            model = FightModel(_newton(X, y, DEFAULT_ALIVE_WEIGHTS), model.trade_weights, model.setup_cuts)
    if len(chances) >= MIN_CHANCES_TO_FIT:
        y = _traded_by_mate(chances, deaths).astype(float)
        weights = _newton(_trade_features(chances["distance_to_killer"], chances["aim_angle"]), y, DEFAULT_TRADE_WEIGHTS)
        model = FightModel(model.alive_weights, weights, model.setup_cuts)
        scores = setup_scores(chances, model)
        if len(scores) >= MIN_SCORES_FOR_CUTS:
            model = FightModel(model.alive_weights, model.trade_weights, tuple(float(q) for q in np.quantile(scores, [0.2, 0.4, 0.6, 0.8])))
    return model


def setup_scores(chances: pd.DataFrame, model: FightModel) -> pd.Series:
    """Per player and match: mean trade chance over teammate deaths near them (the coverage score)."""
    near = chances[_near(chances)]
    keys = ["match_id", "mate"] if "match_id" in near else ["mate"]
    score = near.assign(chance=model.trade_chance(near["distance_to_killer"], near["aim_angle"])).groupby(keys)["chance"]
    counts = score.size()
    return score.mean()[counts >= MIN_COVERAGE_CHANCES]


def _near(chances: pd.DataFrame) -> pd.Series:
    distance = chances["distance_to_victim"].fillna(chances["distance_to_killer"])
    return distance <= NEAR_TEAMMATE


def judge_deaths(deaths: pd.DataFrame, chances: pd.DataFrame, team_rounds: pd.DataFrame, model: FightModel) -> pd.DataFrame:
    """Every death in one match with its cost in round win chance and a label (TRADED, REPEEK, ...)."""
    if deaths.empty:
        return deaths.assign(label=[], cost=[])
    d = _with_sides(deaths.drop(columns="match_id", errors="ignore"), team_rounds.drop(columns="match_id", errors="ignore"))
    d["win_before"] = model.win_chance(d["team_alive"], d["enemies_alive"], d["plant"])
    d["cost"] = d["win_before"] - model.win_chance(d["team_alive"] - 1, d["enemies_alive"], d["plant"])
    d["traded"] = d["trade_seconds"].le(TRADE_SECONDS)
    enemy_kill = d["killer_team"].notna() & (d["killer_team"] != d["victim_team"])

    c = chances.drop(columns="match_id", errors="ignore").copy()
    c["in_range"] = c["distance_to_killer"] <= TRADE_RANGE
    c["set_up"] = c["in_range"] & (c["aim_angle"] <= FACING_ANGLE)
    per_death = c.groupby(["tick", "victim"]).agg(
        mates_in_range=("in_range", "sum"), mates_set_up=("set_up", "sum"), closest_mate=("distance_to_killer", "min")
    )
    d = d.merge(per_death, on=["tick", "victim"], how="left")
    d[["mates_in_range", "mates_set_up"]] = d[["mates_in_range", "mates_set_up"]].fillna(0).astype(int)

    # Re-peek: you got a kill from the same spot moments before you died.
    kills = d[enemy_kill][["round", "tick", "killer", "killer_place"]].rename(columns={"tick": "kill_tick", "killer": "victim"})
    recent = d[["round", "tick", "victim", "victim_place"]].merge(kills, on=["round", "victim"])
    recent = recent[(recent["kill_tick"] < recent["tick"]) & (recent["kill_tick"] >= recent["tick"] - REPEEK_SECONDS * 64)
                    & (recent["killer_place"] == recent["victim_place"])]
    gaps = ((recent["tick"] - recent["kill_tick"]) / 64).groupby([recent["tick"], recent["victim"]]).min().rename("repeek_gap")
    d = d.merge(gaps, left_on=["tick", "victim"], right_index=True, how="left")
    d["repeek"] = d["repeek_gap"].notna()
    d["moving"] = d["victim_speed"].fillna(0) >= MOVING_SPEED
    d["opening"] = d["tick"] == d.groupby("round")["tick"].transform("min")
    d["lost_cause"] = (d["win_before"] < LOST_CAUSE) & (d["victim_equip"] >= GEAR_WORTH_SAVING) & ~d["won"].astype(bool)

    d["label"] = np.select(
        [
            ~enemy_kill,
            d["traded"],
            d["repeek"],
            d["lost_cause"],
            d["moving"] & (d["mates_in_range"] == 0) & (d["team_alive"] >= 2),
            d["mates_in_range"] > 0,
        ],
        [OTHER, TRADED, REPEEK, SHOULD_SAVE, ALONE, NOT_TRADED],
        default=DUEL,
    )
    return d


def coverage(judged: pd.DataFrame, chances: pd.DataFrame, steamid: str, model: FightModel) -> pd.DataFrame:
    """Every teammate death near `steamid`: where they stood and aimed, the trade chance, and a verdict."""
    mine = chances[(chances["mate"] == steamid)].drop(columns="match_id", errors="ignore")
    mine = mine[_near(mine)]
    if mine.empty:
        return mine.assign(chance=[], verdict=[], lost=[])
    info = judged[["tick", "victim", "round", "round_seconds", "victim_place", "killer_place", "killer", "traded_by", "trade_seconds", "cost"]]
    mine = mine.merge(info, on=["tick", "victim", "round"])
    mine["chance"] = model.trade_chance(mine["distance_to_killer"], mine["aim_angle"])
    mine["chance_if_facing"] = model.trade_chance(mine["distance_to_killer"], 0)
    quick = mine["trade_seconds"].le(TRADE_SECONDS)
    in_range = mine["distance_to_killer"] <= TRADE_RANGE
    facing = mine["aim_angle"] <= FACING_ANGLE
    mine["verdict"] = np.select(
        [quick & (mine["traded_by"] == steamid), quick, in_range & facing, in_range],
        [COVER_TRADED, COVER_OTHER_TRADED, COVER_SET_UP, COVER_FACING_AWAY],
        default=COVER_TOO_FAR,
    )
    # Rounds lost by facing away: the teammate's death, times the trade chance you gave up.
    lost = mine["cost"] * (mine["chance_if_facing"] - mine["chance"]).clip(lower=0)
    mine["lost"] = np.where(mine["verdict"] == COVER_FACING_AWAY, lost, 0.0)
    return mine.sort_values("tick").reset_index(drop=True)


def coverage_summary(cover: pd.DataFrame, model: FightModel) -> dict:
    """Headline coverage numbers and a letter grade (None with too few teammate deaths near you)."""
    n = len(cover)
    in_range = int((cover["distance_to_killer"] <= TRADE_RANGE).sum()) if n else 0
    set_up = int(((cover["distance_to_killer"] <= TRADE_RANGE) & (cover["aim_angle"] <= FACING_ANGLE)).sum()) if n else 0
    score = float(cover["chance"].mean()) if n else 0.0
    return {
        "chances": n,
        "in_range": in_range,
        "set_up": set_up,
        "trades": int((cover["verdict"] == COVER_TRADED).sum()) if n else 0,
        "expected_trades": round(float(cover["chance"].sum()), 1) if n else 0.0,
        "score": round(score, 3),
        "grade": model.grade(score) if n >= MIN_COVERAGE_CHANCES else None,
        "rounds_lost": round(float(cover["lost"].sum()), 2) if n else 0.0,
    }
