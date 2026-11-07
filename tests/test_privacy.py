"""Deleting a user's data, against the local PostgreSQL (skipped when it isn't running)."""

import pandas as pd
import pytest

from cs2_insights import db, privacy
from tests.test_db import MATCH_ID, _fake_demo

try:
    conn = db.connect()
except Exception:
    conn = None

pytestmark = pytest.mark.skipif(conn is None, reason="PostgreSQL not running (docker compose up -d)")
ME, OTHER = "pytest_1", "pytest_2"


def _death(tick, victim, killer, victim_team, killer_team):
    return {"match_id": MATCH_ID, "round": 1, "tick": tick, "round_seconds": 1.0, "victim": victim, "killer": killer,
            "victim_team": victim_team, "killer_team": killer_team, "weapon": "ak47", "headshot": False, "victim_place": "Ramp",
            "killer_place": "Ramp", "victim_equip": 3_000, "victim_blind": False, "victim_speed": 0.0, "victim_x": 0.0, "victim_y": 0.0,
            "killer_x": 1.0, "killer_y": 1.0, "team_alive": 1, "enemies_alive": 1, "bomb_planted": False, "traded_by": None,
            "trade_seconds": None, "plant_seconds": None, "unused_utility": 0}


@pytest.fixture
def stored():
    db.init_schema(conn)
    parsed = _fake_demo()
    parsed.deaths = pd.DataFrame([_death(15, ME, OTHER, "A", "B"), _death(16, OTHER, ME, "B", "A")])
    parsed.trade_chances = pd.DataFrame([
        {"match_id": MATCH_ID, "round": 1, "tick": 15, "victim": ME, "mate": "pytest_mate", "distance_to_killer": 400.0,
         "distance_to_victim": 100.0, "aim_angle": 5.0, "mate_x": 0.0, "mate_y": 0.0, "mate_yaw": 0.0},
        {"match_id": MATCH_ID, "round": 1, "tick": 16, "victim": OTHER, "mate": ME, "distance_to_killer": 400.0,
         "distance_to_victim": 100.0, "aim_angle": 5.0, "mate_x": 0.0, "mate_y": 0.0, "mate_yaw": 0.0},
    ])
    parsed.blinds = pd.DataFrame([{"match_id": MATCH_ID, "round": 1, "tick": 14, "thrower": ME, "blinded": OTHER, "seconds": 2.0, "teammate": False}])
    db.load_parsed(conn, parsed)
    db.add_user_match(conn, "pytest_user", MATCH_ID)
    db.set_setting(conn, "pytest_user:me", ME)
    db.log_event(conn, "pytest_session", "report_viewed", steamid=ME, match_id=MATCH_ID, user_id="pytest_user")
    db.add_feedback(conn, "pytest_user", MATCH_ID, 1, 15, ME, "death", "Lost a duel", "Something else")
    conn.commit()
    yield
    conn.execute("DELETE FROM matches WHERE match_id = %s", (MATCH_ID,))
    conn.execute("DELETE FROM players WHERE steamid LIKE 'pytest_%%' OR last_name = %s", (privacy.REMOVED_NAME,))
    for table in ("user_matches", "verdict_feedback", "app_events"):
        conn.execute(f"DELETE FROM {table} WHERE user_id LIKE 'pytest_%%'")
    conn.execute("DELETE FROM settings WHERE key LIKE 'pytest_%%'")
    conn.commit()


def _mentions(steamid):
    """Every place a Steam ID can appear."""
    checks = {
        "players": "SELECT count(*) FROM players WHERE steamid = %s",
        "player_rounds": "SELECT count(*) FROM player_rounds WHERE steamid = %s",
        "deaths": "SELECT count(*) FROM deaths WHERE %s IN (victim, killer, coalesce(traded_by, ''))",
        "trade_chances": "SELECT count(*) FROM trade_chances WHERE %s IN (victim, mate)",
        "blinds": "SELECT count(*) FROM blinds WHERE %s IN (thrower, blinded)",
        "app_events": "SELECT count(*) FROM app_events WHERE steamid = %s",
        "verdict_feedback": "SELECT count(*) FROM verdict_feedback WHERE steamid = %s",
        "settings": "SELECT count(*) FROM settings WHERE value = %s",
    }
    return {name: conn.execute(sql, (steamid,)).fetchone()[0] for name, sql in checks.items()}


def test_forget_player_leaves_no_trace_but_keeps_the_match_whole(stored):
    assert sum(_mentions(ME).values()) > 0
    new = privacy.forget_player(conn, ME)
    assert sum(_mentions(ME).values()) == 0
    assert new.startswith("removed-") and ME not in new
    # The match still adds up: same rows, now under the anonymous ID.
    assert conn.execute("SELECT count(*) FROM player_rounds WHERE match_id = %s", (MATCH_ID,)).fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM deaths WHERE victim = %s", (new,)).fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM trade_chances WHERE victim = %s OR mate = %s", (new, new)).fetchone()[0] == 2
    assert conn.execute("SELECT last_name FROM players WHERE steamid = %s", (new,)).fetchone()[0] == privacy.REMOVED_NAME


def test_delete_account_removes_its_records_and_matches_only_it_added(stored):
    counts = privacy.delete_account(conn, "pytest_user")
    assert counts["matches"] == 1 and counts["settings"] == 1 and counts["usage_events"] == 1 and counts["disagreements"] == 1
    assert not db.match_exists(conn, MATCH_ID)


def test_delete_account_keeps_a_match_someone_else_also_added(stored):
    db.add_user_match(conn, "pytest_friend", MATCH_ID)
    conn.commit()
    assert privacy.delete_account(conn, "pytest_user")["matches"] == 0
    assert db.match_exists(conn, MATCH_ID)
    assert [m.match.iloc[0]["match_id"] for m in db.load_matches(conn, user_id="pytest_friend")] == [MATCH_ID]
