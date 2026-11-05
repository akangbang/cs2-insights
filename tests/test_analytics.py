from pathlib import Path

import pandas as pd
import pytest

from cs2_insights import analytics, db
from tests.test_habits import ME, SAVE_AFTER_PISTOL, _match


def test_build_has_one_row_per_player_per_match_and_ordered_matches():
    matches = [_match(f"m{i}", SAVE_AFTER_PISTOL) for i in (2, 1)]
    tables = analytics.build(matches)
    facts = tables["fact_player_match"]
    assert len(facts) == 4  # two players in each of two matches
    assert set(facts.columns) >= {"match_id", "steamid", "won", "buy_calls", "buy_calls_wrong"}
    assert tables["dim_match"].set_index("match_id")["match_order"].to_dict() == {"m1": 1, "m2": 2}
    assert tables["dim_player"].set_index("steamid").at[ME, "matches"] == 2
    assert facts.loc[facts["steamid"] == ME, "buy_calls_wrong"].tolist() == [1, 1]


def _connect():
    try:
        return db.connect()
    except Exception:
        return None


@pytest.mark.skipif(_connect() is None, reason="PostgreSQL not running (docker compose up -d)")
def test_refresh_tables_agree_with_each_other():
    conn = _connect()
    counts = analytics.refresh(conn)
    q = lambda sql: conn.execute(sql).fetchone()[0]
    assert counts["fact_player_match"] == q("SELECT count(*) FROM analytics.fact_player_match")
    if counts["fact_death"]:
        assert q("SELECT count(*) FROM analytics.fact_death WHERE verdict_group = 'Avoidable'") == q(
            "SELECT coalesce(sum(avoidable_deaths), 0) FROM analytics.fact_player_match")
        assert q("SELECT count(*) FROM analytics.fact_clutch WHERE outcome = 'Won'") == q(
            "SELECT coalesce(sum(clutches_won), 0) FROM analytics.fact_player_match")
    conn.commit()


@pytest.mark.skipif(_connect() is None, reason="PostgreSQL not running (docker compose up -d)")
def test_dashboard_role_reads_analytics_only():
    conn = _connect()
    analytics.refresh(conn)
    can = lambda table: conn.execute("SELECT has_table_privilege('analytics_reader', %s, 'SELECT')", (table,)).fetchone()[0]
    assert can("analytics.fact_player_match") and can("analytics.v_funnel") and can("analytics.v_retention_weekly")
    assert not can("public.app_events") and not can("public.linked_accounts") and not can("public.player_rounds")
    conn.commit()


@pytest.mark.skipif(_connect() is None, reason="PostgreSQL not running (docker compose up -d)")
def test_retention_counts_accounts_when_hosted_and_players_when_local():
    conn = _connect()
    analytics.refresh(conn)
    session = "pytest_retention"
    before = conn.execute("SELECT coalesce(sum(players), 0) FROM analytics.v_retention_weekly").fetchone()[0]
    db.log_event(conn, session, "report_viewed", steamid="pytest_a", user_id="pytest_account")
    db.log_event(conn, session, "report_viewed", steamid="pytest_b", user_id="pytest_account")  # same person, two players
    db.log_event(conn, session, "report_viewed", steamid="pytest_c", user_id="local")
    after = conn.execute("SELECT coalesce(sum(players), 0) FROM analytics.v_retention_weekly").fetchone()[0]
    assert after - before == 2
    conn.execute("DELETE FROM app_events WHERE session_id = %s", (session,))
    conn.commit()


def test_user_pages_never_read_the_analytics_schema():
    source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
    assert "FROM analytics." not in source and "v_funnel" not in source and "app_events" not in source.replace("(app_events)", "")
