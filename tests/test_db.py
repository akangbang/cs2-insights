"""Loader tests against the local PostgreSQL (skipped when it isn't running)."""

import pandas as pd
import pytest

from cs2_insights import db
from cs2_insights.demo import PARSER_VERSION, ParsedDemo

MATCH_ID = "pytest_match"


def _connect():
    try:
        return db.connect()
    except Exception:
        return None


conn = _connect()
pytestmark = pytest.mark.skipif(conn is None, reason="PostgreSQL not running (docker compose up -d)")


def _fake_demo(team_a_equip=4_000):
    match = pd.DataFrame([{
        "match_id": MATCH_ID, "source": "upload", "map": "de_test", "server": "test", "patch_version": "1",
        "rounds": 1, "team_a_score": 1, "team_b_score": 0, "demo_file": "test.dem",
    }])
    rounds = pd.DataFrame([{"match_id": MATCH_ID, "round": 1, "freeze_end_tick": 10, "end_tick": 20, "winner_side": "CT", "reason": "t_killed"}])
    team_rounds = pd.DataFrame([
        {"match_id": MATCH_ID, "round": 1, "team": t, "side": s, "players": 1, "equip_value": e, "bank": 0,
         "start_equip_value": 200, "cash_spent": 0, "won": w, "score": 0, "opponent_score": 0, "buy_type": "pistol"}
        for t, s, e, w in [("A", "CT", team_a_equip, True), ("B", "T", 3_000, False)]
    ])
    player_rounds = pd.DataFrame([
        {"match_id": MATCH_ID, "round": 1, "steamid": sid, "name": name, "team": t, "side": s, "balance": 800,
         "equip_value": e, "start_equip_value": 200, "cash_spent": 0, "armor": 100, "has_helmet": False, "has_defuser": False}
        for sid, name, t, s, e in [("pytest_1", "one", "A", "CT", team_a_equip), ("pytest_2", "two", "B", "T", 3_000)]
    ])
    return ParsedDemo(match, rounds, team_rounds, player_rounds)


@pytest.fixture
def clean_conn():
    db.init_schema(conn)
    yield conn
    conn.execute("DELETE FROM matches WHERE match_id = %s", (MATCH_ID,))
    conn.execute("DELETE FROM players WHERE steamid LIKE 'pytest_%%'")
    conn.commit()


def _count(c, table):
    return c.execute(f"SELECT count(*) FROM {table} WHERE match_id = %s", (MATCH_ID,)).fetchone()[0]


def test_load_and_reload_replaces_rows(clean_conn):
    db.load_parsed(clean_conn, _fake_demo())
    assert db.match_exists(clean_conn, MATCH_ID)
    assert [_count(clean_conn, t) for t in ("rounds", "team_rounds", "player_rounds")] == [1, 2, 2]

    db.load_parsed(clean_conn, _fake_demo(team_a_equip=4_500))
    assert [_count(clean_conn, t) for t in ("rounds", "team_rounds", "player_rounds")] == [1, 2, 2]
    equip = clean_conn.execute(
        "SELECT equip_value FROM team_rounds WHERE match_id = %s AND team = 'A'", (MATCH_ID,)
    ).fetchone()[0]
    assert equip == 4_500


def test_failed_load_leaves_nothing_behind(clean_conn):
    bad = _fake_demo()
    bad.team_rounds.loc[0, "buy_type"] = "not_a_buy_type"  # violates the CHECK constraint
    with pytest.raises(Exception):
        db.load_parsed(clean_conn, bad)
    clean_conn.rollback()
    assert not db.match_exists(clean_conn, MATCH_ID)


def test_load_matches_rebuilds_stored_matches(clean_conn):
    db.load_parsed(clean_conn, _fake_demo())
    matches = db.load_matches(clean_conn, steamid="pytest_1")
    clean_conn.commit()
    assert len(matches) == 1
    parsed = matches[0]
    assert parsed.match.iloc[0]["map"] == "de_test"
    assert len(parsed.team_rounds) == 2
    assert set(parsed.player_rounds["name"]) == {"one", "two"}


def test_fights_round_trip_and_parser_version(clean_conn):
    parsed = _fake_demo()
    parsed.match["parser_version"] = PARSER_VERSION
    parsed.deaths = pd.DataFrame([{
        "match_id": MATCH_ID, "round": 1, "tick": 15, "round_seconds": 0.1, "victim": "pytest_2", "killer": "pytest_1",
        "victim_team": "B", "killer_team": "A", "weapon": "ak47", "headshot": True, "victim_place": "Ramp",
        "killer_place": "Ramp", "victim_equip": 3_000, "victim_blind": False, "victim_speed": 120.0, "victim_x": 1.0,
        "victim_y": 2.0, "killer_x": 3.0, "killer_y": 4.0, "team_alive": 1, "enemies_alive": 1, "bomb_planted": False,
        "traded_by": None, "trade_seconds": None,
    }])
    parsed.trade_chances = pd.DataFrame([{
        "match_id": MATCH_ID, "round": 1, "tick": 15, "victim": "pytest_2", "mate": "pytest_1", "distance_to_killer": 400.0,
        "distance_to_victim": 300.0, "aim_angle": 12.5, "mate_x": 0.0, "mate_y": 0.0, "mate_yaw": 90.0,
    }])
    db.load_parsed(clean_conn, parsed)
    assert db.match_is_current(clean_conn, MATCH_ID)
    stored = db.load_matches(clean_conn, steamid="pytest_1")[0]
    clean_conn.commit()
    assert stored.deaths.iloc[0]["weapon"] == "ak47" and stored.deaths.iloc[0]["traded_by"] is None
    assert stored.trade_chances.iloc[0]["aim_angle"] == pytest.approx(12.5)

    db.load_parsed(clean_conn, _fake_demo())  # an old parse: no version, no fights
    assert not db.match_is_current(clean_conn, MATCH_ID)
    assert _count(clean_conn, "deaths") == 0
