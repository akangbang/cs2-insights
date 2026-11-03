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
