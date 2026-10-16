"""Linking and sync against the local PostgreSQL with a fake Steam server."""

import pytest

from cs2_insights import db, link
from cs2_insights.sharecode import ShareCode, encode
from cs2_insights.steam import SteamAPIError, resolve_steam64
from tests.test_steam import FakeResponse, FakeSession

STEAM64 = "76561190000000001"
AUTH_CODE = "ABCD-EFGHI-JKLM"
CODES = [encode(ShareCode(900_000 + i, 800_000 + i, 1000 + i)) for i in range(4)]

try:
    conn = db.connect()
except Exception:
    conn = None


@pytest.fixture
def clean_conn():
    if conn is None:
        pytest.skip("PostgreSQL not running (docker compose up -d)")
    db.init_schema(conn)
    yield conn
    conn.execute("DELETE FROM share_codes WHERE steamid = %s", (STEAM64,))
    conn.execute("DELETE FROM linked_accounts WHERE steamid = %s", (STEAM64,))
    conn.commit()


def _queued(c):
    rows = c.execute("SELECT share_code FROM share_codes WHERE steamid = %s ORDER BY match_id", (STEAM64,))
    return [row[0] for row in rows]


def test_link_then_sync_queues_new_matches_once(clean_conn):
    chain = {CODES[0]: CODES[1], CODES[1]: CODES[2]}
    link.link_account(clean_conn, "key", STEAM64, AUTH_CODE, CODES[0], session=FakeSession(chain))
    assert link.sync_account(clean_conn, "key", STEAM64, session=FakeSession(chain)) == 2
    assert _queued(clean_conn) == CODES[:3]

    # A new match appears later; only it gets queued.
    chain[CODES[2]] = CODES[3]
    assert link.sync_account(clean_conn, "key", STEAM64, session=FakeSession(chain)) == 1
    assert _queued(clean_conn) == CODES
    last = clean_conn.execute(
        "SELECT last_share_code FROM linked_accounts WHERE steamid = %s", (STEAM64,)
    ).fetchone()[0]
    assert last == CODES[3]


def test_link_rejected_by_steam_saves_nothing(clean_conn):
    with pytest.raises(SteamAPIError):
        link.link_account(
            clean_conn, "key", STEAM64, AUTH_CODE, CODES[0], session=FakeSession({}, status_code=403)
        )
    count = clean_conn.execute(
        "SELECT count(*) FROM linked_accounts WHERE steamid = %s", (STEAM64,)
    ).fetchone()[0]
    assert count == 0


class VanitySession:
    def __init__(self, body):
        self.body = body

    def get(self, url, params, timeout):
        return FakeResponse(200, self.body)


def test_resolve_steam64_from_vanity_and_direct_link():
    session = VanitySession({"response": {"success": 1, "steamid": STEAM64}})
    assert resolve_steam64("key", "https://steamcommunity.com/id/someone", session=session) == STEAM64
    assert resolve_steam64("key", f"https://steamcommunity.com/profiles/{STEAM64}") == STEAM64
    with pytest.raises(SteamAPIError):
        resolve_steam64("key", "steamcommunity.com/id/nobody", session=VanitySession({"response": {"success": 42}}))
