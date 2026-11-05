"""Rebuild the Power BI star schema (sql/analytics.sql) from every stored match.

The numbers come from the same functions the app uses (fights.py, grade.py, utility.py), so a
dashboard and a match report never disagree.

Usage: python -m cs2_insights.analytics
"""

import sys
from pathlib import Path

import pandas as pd
import psycopg

from cs2_insights import db, fights
from cs2_insights.demo import ParsedDemo
from cs2_insights.fights import FightModel, clutches, coverage, coverage_summary, fit_fight_model, judge_deaths, opening_duels
from cs2_insights.grade import GOOD_CALL, SHOULD_FORCE, SHOULD_SAVE, grade_decisions
from cs2_insights.rates import equipment_slope
from cs2_insights.report import DEATH_GROUPS

ANALYTICS_FILE = Path(__file__).resolve().parents[2] / "sql" / "analytics.sql"
TABLES = ["dim_player", "dim_match", "fact_player_match", "fact_death", "fact_clutch", "fact_opening", "fact_buy_call"]


def match_tables(parsed: ParsedDemo, model: FightModel, slope: float) -> dict[str, pd.DataFrame]:
    """Every analytics row one match contributes (all players, both teams)."""
    match = parsed.match.iloc[0]
    match_id = match["match_id"]
    calls = {team: grade_decisions(parsed.team_rounds, team, slope) for team in "AB"}
    has_fights = len(parsed.deaths) > 0
    judged = judge_deaths(parsed.deaths, parsed.trade_chances, parsed.team_rounds, model) if has_fights else pd.DataFrame()
    all_clutches = clutches(parsed.deaths, parsed.player_rounds, parsed.team_rounds, model, slope) if has_fights else pd.DataFrame()
    utility = parsed.utility.groupby("steamid").sum(numeric_only=True) if len(parsed.utility) else pd.DataFrame()

    players = parsed.player_rounds.groupby("steamid").agg(team=("team", lambda t: t.mode().iat[0]), rounds=("round", "nunique")).reset_index()
    rows, openings = [], []
    for p in players.itertuples():
        score = {"A": int(match["team_a_score"]), "B": int(match["team_b_score"])}
        my_calls = calls[p.team]
        row = {
            "match_id": match_id, "steamid": p.steamid, "team": p.team, "won": score[p.team] > score["B" if p.team == "A" else "A"],
            "rounds": int(p.rounds), "buy_calls": len(my_calls), "buy_calls_right": int((my_calls["grade"] == GOOD_CALL).sum()),
            "buy_calls_wrong": int(my_calls["grade"].isin([SHOULD_FORCE, SHOULD_SAVE]).sum()),
            "rounds_lost_calls": float(my_calls["cost"].sum()),
        }
        if has_fights:
            mine = judged[judged["victim"] == p.steamid]
            avoidable = mine[mine["label"].isin(fights.AVOIDABLE)]
            cover = coverage_summary(coverage(judged, parsed.trade_chances, p.steamid, model), model)
            mine_clutch = all_clutches[all_clutches["player"] == p.steamid] if len(all_clutches) else all_clutches
            od = opening_duels(parsed.deaths, parsed.team_rounds, p.steamid)
            openings.append(od.assign(match_id=match_id, steamid=p.steamid))
            row.update({
                "deaths": len(mine), "traded_deaths": int((mine["label"] == fights.TRADED).sum()), "avoidable_deaths": len(avoidable),
                "repeeks": int((mine["label"] == fights.REPEEK).sum()), "pushed_alone": int((mine["label"] == fights.ALONE).sum()),
                "lost_gear": int((mine["label"] == fights.SHOULD_SAVE).sum()), "rounds_lost_avoidable": float(avoidable["cost"].sum()),
                "coverage_chances": cover["chances"], "coverage_set_up": cover["set_up"], "coverage_trades": cover["trades"],
                "coverage_score": cover["score"] if cover["chances"] else None, "coverage_grade": cover["grade"],
                "unused_utility_deaths": int((mine["unused_utility"] >= 400).sum()) if "unused_utility" in mine else None,
                "clutches": len(mine_clutch), "clutches_won": int((mine_clutch["outcome"] == "Won").sum()) if len(mine_clutch) else 0,
                "clutch_mistakes": int(mine_clutch["verdict"].isin([fights.CLUTCH_SHOULD_SAVE, fights.CLUTCH_SHOULD_PLAY]).sum()) if len(mine_clutch) else 0,
                "opening_duels": len(od), "opening_wins": int(od["won"].sum()) if len(od) else 0,
            })
        if p.steamid in utility.index:
            u = utility.loc[p.steamid]
            row.update({
                "grenades": int(u[["flashes", "smokes", "hes", "molotovs"]].sum()), "flashes": int(u["flashes"]),
                "enemies_flashed": int(u["enemies_blinded"]), "teammates_flashed": int(u["teammates_blinded"]),
                "utility_damage": int(u["utility_damage"]),
            })
        rows.append(row)

    deaths = pd.DataFrame()
    if has_fights:
        enemy = judged[judged["label"] != fights.OTHER]
        deaths = pd.DataFrame({
            "match_id": match_id, "round": enemy["round"], "tick": enemy["tick"], "steamid": enemy["victim"], "killer": enemy["killer"],
            "side": enemy["side"], "place": enemy["victim_place"], "verdict": enemy["label"],
            "verdict_group": enemy["label"].map(DEATH_GROUPS), "cost": enemy["cost"],
        })
    clutch_rows = pd.DataFrame()
    if len(all_clutches):
        clutch_rows = all_clutches.rename(columns={"player": "steamid"})[
            ["round", "steamid", "side", "enemies", "outcome", "gear", "win_chance", "save_value", "verdict"]].assign(match_id=match_id)
    buy_calls = pd.concat([c.assign(team=t) for t, c in calls.items()], ignore_index=True)
    return {
        "fact_player_match": pd.DataFrame(rows),
        "fact_death": deaths,
        "fact_clutch": clutch_rows,
        "fact_opening": pd.concat(openings, ignore_index=True) if openings else pd.DataFrame(),
        "fact_buy_call": buy_calls.assign(match_id=match_id)[["match_id", "round", "team", "made", "money_each", "their_buy", "grade", "cost"]]
        if len(buy_calls) else pd.DataFrame(),
    }


def build(matches: list[ParsedDemo], parsed_at: dict | None = None) -> dict[str, pd.DataFrame]:
    """All analytics tables for a list of matches, with models fitted on the whole pool."""
    with_fights = [m for m in matches if len(m.deaths)]
    team_rounds = pd.concat([m.team_rounds for m in matches], ignore_index=True)
    model = fit_fight_model(
        pd.concat([m.deaths for m in with_fights], ignore_index=True),
        pd.concat([m.trade_chances for m in with_fights], ignore_index=True),
        team_rounds,
    ) if with_fights else FightModel()
    slope = equipment_slope(team_rounds)

    parts = [match_tables(m, model, slope) for m in matches]
    tables = {}
    for name in parts[0] if parts else []:
        frames = [p[name] for p in parts if len(p[name])]
        tables[name] = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    ordered = sorted(matches, key=lambda m: m.match.iloc[0]["match_id"])
    tables["dim_match"] = pd.DataFrame([{
        "match_id": m.match.iloc[0]["match_id"], "match_order": i, "map": m.match.iloc[0]["map"], "rounds": int(m.match.iloc[0].get("rounds") or m.team_rounds["round"].nunique()),
        "team_a_score": int(m.match.iloc[0]["team_a_score"]), "team_b_score": int(m.match.iloc[0]["team_b_score"]),
        "source": m.match.iloc[0].get("source"), "parsed_at": (parsed_at or {}).get(m.match.iloc[0]["match_id"]),
    } for i, m in enumerate(ordered, start=1)])
    names = pd.concat([m.player_rounds[["steamid", "name", "match_id"]] for m in matches], ignore_index=True)
    tables["dim_player"] = names.groupby("steamid").agg(name=("name", "last"), matches=("match_id", "nunique")).reset_index()
    return tables


def refresh(conn: psycopg.Connection) -> dict[str, int]:
    """Rebuild every analytics table from the stored matches in one transaction. Returns row counts."""
    db.init_schema(conn)  # the views below depend on the base tables being current
    conn.execute(ANALYTICS_FILE.read_text(encoding="utf-8"))
    conn.commit()
    matches = db.load_matches(conn)
    parsed_at = dict(conn.execute("SELECT match_id, parsed_at FROM matches").fetchall())
    conn.commit()
    tables = build(matches, parsed_at) if matches else {}
    counts = {}
    with conn.transaction(), conn.cursor() as cur:
        for name in TABLES:
            cur.execute(f"DELETE FROM analytics.{name}")
            frame = tables.get(name, pd.DataFrame())
            if len(frame):
                columns = [c[0] for c in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = %s "
                    "ORDER BY ordinal_position", (name,)).fetchall()]
                db._insert(cur, f"analytics.{name}", frame.reindex(columns=columns), columns)
            counts[name] = len(frame)
    return counts


def main() -> int:
    with db.connect() as conn:
        db.init_schema(conn)
        for name, n in refresh(conn).items():
            print(f"{name:20} {n:6,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
