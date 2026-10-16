"""PostgreSQL access: create the schema and load parsed demos."""

import os
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

from cs2_insights.demo import ParsedDemo

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"

MATCH_COLUMNS = ["match_id", "source", "map", "server", "patch_version", "rounds", "team_a_score", "team_b_score", "demo_file"]
ROUND_COLUMNS = ["match_id", "round", "freeze_end_tick", "end_tick", "winner_side", "reason"]
TEAM_ROUND_COLUMNS = [
    "match_id", "round", "team", "side", "players", "equip_value", "bank", "start_equip_value",
    "cash_spent", "won", "score", "opponent_score", "buy_type",
]
PLAYER_ROUND_COLUMNS = [
    "match_id", "round", "steamid", "team", "side", "balance", "equip_value", "start_equip_value",
    "cash_spent", "armor", "has_helmet", "has_defuser",
]


def connect(url: str | None = None) -> psycopg.Connection:
    load_dotenv()
    url = url or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL isn't set; add it to .env.")
    return psycopg.connect(url)


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
    conn.commit()


def _rows(frame: pd.DataFrame, columns: list[str]) -> list[tuple]:
    """DataFrame rows as plain Python values (numpy ints and bools don't adapt to SQL)."""
    out = frame[columns].astype(object).where(frame[columns].notna(), None)
    return [tuple(v.item() if hasattr(v, "item") else v for v in row) for row in out.itertuples(index=False)]


def _insert(cur: psycopg.Cursor, table: str, frame: pd.DataFrame, columns: list[str]) -> None:
    placeholders = ", ".join(["%s"] * len(columns))
    cur.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", _rows(frame, columns))


def match_exists(conn: psycopg.Connection, match_id: str) -> bool:
    return conn.execute("SELECT 1 FROM matches WHERE match_id = %s", (match_id,)).fetchone() is not None


def load_parsed(conn: psycopg.Connection, parsed: ParsedDemo) -> None:
    """Replace one match's rows in a single transaction, so a re-parse never leaves half a match."""
    match_id = parsed.match.iloc[0]["match_id"]
    names = parsed.player_rounds.drop_duplicates("steamid", keep="last")[["steamid", "name"]]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("DELETE FROM matches WHERE match_id = %s", (match_id,))
        cur.executemany(
            """INSERT INTO players (steamid, last_name) VALUES (%s, %s)
               ON CONFLICT (steamid) DO UPDATE SET last_name = EXCLUDED.last_name, updated_at = now()""",
            _rows(names, ["steamid", "name"]),
        )
        _insert(cur, "matches", parsed.match, MATCH_COLUMNS)
        _insert(cur, "rounds", parsed.rounds, ROUND_COLUMNS)
        _insert(cur, "team_rounds", parsed.team_rounds, TEAM_ROUND_COLUMNS)
        _insert(cur, "player_rounds", parsed.player_rounds, PLAYER_ROUND_COLUMNS)
