"""Delete a user's data on request: their account's records, and their Steam identity in matches.

Two separate actions, because a match holds ten players' data:
- delete_account removes what belongs to one app account (settings, usage events, disagreements,
  match ownership) and any match no one else added.
- forget_player replaces one Steam ID everywhere with a random ID and their name with
  "Removed player". Their anonymous numbers stay in the pool, so other players' stats still add up,
  but nothing links them back to that Steam account.
"""

import uuid

import psycopg

from cs2_insights.db import DEATH_COLUMNS

REMOVED_NAME = "Removed player"


def delete_account(conn: psycopg.Connection, user_id: str, local: bool = False) -> dict[str, int]:
    """Delete one account's data. `local`: the single-user copy, whose settings have no user prefix."""
    counts = {}
    with conn.transaction():
        if local:
            counts["settings"] = conn.execute("DELETE FROM settings WHERE key NOT LIKE '%%:%%'").rowcount
        else:
            counts["settings"] = conn.execute("DELETE FROM settings WHERE key LIKE %s", (f"{user_id}:%",)).rowcount
        counts["usage_events"] = conn.execute("DELETE FROM app_events WHERE user_id = %s", (user_id,)).rowcount
        counts["disagreements"] = conn.execute("DELETE FROM verdict_feedback WHERE user_id = %s", (user_id,)).rowcount
        # Matches only this account added go too; a match someone else also added stays.
        only_mine = [row[0] for row in conn.execute(
            """SELECT match_id FROM user_matches WHERE user_id = %s
               AND match_id NOT IN (SELECT match_id FROM user_matches WHERE user_id <> %s)""", (user_id, user_id))]
        counts["matches"] = conn.execute("DELETE FROM matches WHERE match_id = ANY(%s)", (only_mine,)).rowcount
        counts["match_links"] = conn.execute("DELETE FROM user_matches WHERE user_id = %s", (user_id,)).rowcount
    return counts


def forget_player(conn: psycopg.Connection, steamid: str) -> str:
    """Replace a Steam ID everywhere with a random one and drop their name. Returns the new ID."""
    new = f"removed-{uuid.uuid4().hex[:16]}"  # random, so it can't be traced back to the Steam ID
    with conn.transaction():
        conn.execute("INSERT INTO players (steamid, last_name) VALUES (%s, %s)", (new, REMOVED_NAME))
        conn.execute("UPDATE player_rounds SET steamid = %s WHERE steamid = %s", (new, steamid))
        # deaths.victim is part of the key trade_chances points at: copy the rows, move the children, drop the originals.
        columns = ", ".join(DEATH_COLUMNS)
        copied = ", ".join("%s" if c == "victim" else c for c in DEATH_COLUMNS)
        conn.execute(f"INSERT INTO deaths ({columns}) SELECT {copied} FROM deaths WHERE victim = %s", (new, steamid))
        conn.execute("UPDATE trade_chances SET victim = %s WHERE victim = %s", (new, steamid))
        conn.execute("DELETE FROM deaths WHERE victim = %s", (steamid,))
        for table, column in [
            ("deaths", "killer"), ("deaths", "traded_by"), ("trade_chances", "mate"), ("player_utility", "steamid"),
            ("blinds", "thrower"), ("blinds", "blinded"), ("app_events", "steamid"), ("verdict_feedback", "steamid"),
        ]:
            conn.execute(f"UPDATE {table} SET {column} = %s WHERE {column} = %s", (new, steamid))
        conn.execute("DELETE FROM players WHERE steamid = %s", (steamid,))
        conn.execute("DELETE FROM linked_accounts WHERE steamid = %s", (steamid,))
        conn.execute("DELETE FROM share_codes WHERE steamid = %s", (steamid,))
        conn.execute("DELETE FROM settings WHERE value = %s", (steamid,))  # "This is me"
        # The dashboard copy is rebuilt from the tables above; until then, drop it there too.
        for table, column in [("dim_player", "steamid"), ("fact_player_match", "steamid"), ("fact_death", "steamid"),
                              ("fact_death", "killer"), ("fact_clutch", "steamid"), ("fact_opening", "steamid")]:
            if conn.execute("SELECT to_regclass(%s)", (f"analytics.{table}",)).fetchone()[0]:
                conn.execute(f"DELETE FROM analytics.{table} WHERE {column} = %s", (steamid,))
    return new
