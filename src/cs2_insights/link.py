"""Link a player's Valve match history and queue every new match for download.

Usage:
  python -m cs2_insights.link add <steam profile link or Steam64> <share code> [--auth-code CODE]
  python -m cs2_insights.link sync
The auth code defaults to STEAM_AUTH_CODE in .env.
"""

import argparse
import os
import sys

import psycopg
import requests
from dotenv import load_dotenv

from cs2_insights import db, sharecode, steam


def queue_share_code(conn: psycopg.Connection, code: str, steamid: str) -> bool:
    """Add a share code to the download queue. Returns False if it was already there."""
    decoded = sharecode.decode(code)
    inserted = conn.execute(
        """INSERT INTO share_codes (share_code, match_id, outcome_id, tv_port, steamid)
           VALUES (%s, %s, %s, %s, %s) ON CONFLICT (share_code) DO NOTHING""",
        (code, str(decoded.match_id), str(decoded.outcome_id), decoded.tv_port, steamid),
    ).rowcount
    return inserted == 1


def link_account(
    conn: psycopg.Connection,
    api_key: str,
    steam64: str,
    auth_code: str,
    share_code: str,
    session: requests.Session | None = None,
) -> None:
    """Check the details with Steam, then save the account and queue its first match.

    Raises ValueError or steam.SteamAPIError with a message for the player if Steam refuses.
    """
    # One call proves the auth code and share code belong to this player.
    steam.get_next_share_code(api_key, steam64, auth_code, share_code, session=session)
    with conn.transaction():
        conn.execute(
            """INSERT INTO linked_accounts (steamid, auth_code, last_share_code) VALUES (%s, %s, %s)
               ON CONFLICT (steamid) DO UPDATE
               SET auth_code = EXCLUDED.auth_code, last_share_code = EXCLUDED.last_share_code""",
            (steam64, auth_code.strip(), share_code.strip()),
        )
        queue_share_code(conn, share_code.strip(), steam64)


def sync_account(
    conn: psycopg.Connection, api_key: str, steamid: str, session: requests.Session | None = None
) -> int:
    """Queue every match played since the last sync. Returns how many new share codes were queued."""
    auth_code, last_code = conn.execute(
        "SELECT auth_code, last_share_code FROM linked_accounts WHERE steamid = %s", (steamid,)
    ).fetchone()
    queued = 0
    for code in steam.iter_share_codes(api_key, steamid, auth_code, last_code, session=session):
        # Save progress after each code, so a Steam error mid-walk keeps what was found.
        with conn.transaction():
            queued += queue_share_code(conn, code, steamid)
            conn.execute(
                "UPDATE linked_accounts SET last_share_code = %s WHERE steamid = %s", (code, steamid)
            )
    conn.execute("UPDATE linked_accounts SET last_synced_at = now() WHERE steamid = %s", (steamid,))
    conn.commit()
    return queued


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Link Valve match history and queue new matches.")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add")
    add.add_argument("profile")
    add.add_argument("share_code")
    add.add_argument("--auth-code", default=os.getenv("STEAM_AUTH_CODE"))
    commands.add_parser("sync")
    opts = parser.parse_args(argv)

    api_key = os.getenv("STEAM_API_KEY")
    if not api_key:
        print("STEAM_API_KEY isn't set; add it to .env.")
        return 1

    with db.connect() as conn:
        db.init_schema(conn)
        try:
            if opts.command == "add":
                if not opts.auth_code:
                    print("No auth code: pass --auth-code or set STEAM_AUTH_CODE in .env.")
                    return 1
                steam64 = steam.resolve_steam64(api_key, opts.profile)
                link_account(conn, api_key, steam64, opts.auth_code, opts.share_code)
                print(f"Linked {steam64}.")
                print(f"Queued {sync_account(conn, api_key, steam64)} newer matches.")
            else:
                steamids = [row[0] for row in conn.execute("SELECT steamid FROM linked_accounts")]
                for steamid in steamids:
                    print(f"{steamid}: queued {sync_account(conn, api_key, steamid)} new matches.")
        except (ValueError, steam.SteamAPIError) as error:
            print(f"Error: {error}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
