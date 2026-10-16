"""Demo download queue, with a fake bot and fake Valve download server."""

from pathlib import Path

import pytest

from cs2_insights import db, fetch, link
from cs2_insights.sharecode import ShareCode, encode
from tests.test_demo import LOCAL_DEMOS

STEAMID = "76561190000000002"

try:
    conn = db.connect()
except Exception:
    conn = None


class FakeDownload:
    def __init__(self, status_code, data=b""):
        self.status_code = status_code
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i : i + chunk_size]


class FakeValve:
    """Serves files by URL; anything else is a 404."""

    def __init__(self, files=None):
        self.files = files or {}

    def get(self, url, stream, timeout):
        if url in self.files:
            return FakeDownload(200, Path(self.files[url]).read_bytes())
        return FakeDownload(404)


@pytest.fixture
def queue():
    if conn is None:
        pytest.skip("PostgreSQL not running (docker compose up -d)")
    db.init_schema(conn)
    created = []

    def add(match_id):
        code = encode(ShareCode(match_id, 1, 1))
        link.queue_share_code(conn, code, STEAMID)
        conn.commit()
        created.append(str(match_id))
        return code

    yield add
    conn.execute("DELETE FROM share_codes WHERE steamid = %s", (STEAMID,))
    for match_id in created:
        conn.execute("DELETE FROM matches WHERE match_id = %s", (match_id,))
    conn.commit()


def _status(code):
    return conn.execute("SELECT status, error FROM share_codes WHERE share_code = %s", (code,)).fetchone()


def test_bot_errors_mark_expired_or_failed(queue, tmp_path):
    expired, broken = queue(111), queue(222)
    answers = {expired: {"share_code": expired, "error": "no demo URL (expired or not recorded)"}}
    counts = fetch.process_queue(conn, url_fetcher=lambda codes: answers, session=FakeValve(), demo_dir=tmp_path)
    assert counts == {"parsed": 0, "expired": 1, "failed": 1}
    assert _status(expired)[0] == "expired"
    assert _status(broken) == ("failed", "no answer from the demo bot")


def test_missing_download_marks_expired(queue, tmp_path):
    code = queue(333)
    answers = {code: {"share_code": code, "demo_url": "http://replay1.valve.net/730/gone.dem.bz2"}}
    counts = fetch.process_queue(conn, url_fetcher=lambda codes: answers, session=FakeValve(), demo_dir=tmp_path)
    assert counts["expired"] == 1
    assert _status(code)[0] == "expired"


@pytest.mark.skipif(not LOCAL_DEMOS, reason="no local CS2 demos")
def test_full_path_downloads_parses_and_loads(queue, tmp_path):
    match_id = 444_000_000_000_000_001
    code = queue(match_id)
    url = "http://replay1.valve.net/730/fake_match.dem"
    answers = {code: {"share_code": code, "demo_url": url}}

    counts = fetch.process_queue(
        conn, url_fetcher=lambda codes: answers, session=FakeValve({url: LOCAL_DEMOS[-1]}), demo_dir=tmp_path
    )

    assert counts == {"parsed": 1, "expired": 0, "failed": 0}
    assert _status(code)[0] == "parsed"
    source, rounds = conn.execute(
        "SELECT source, rounds FROM matches WHERE match_id = %s", (str(match_id),)
    ).fetchone()
    assert source == "valve" and rounds > 0
    assert list(tmp_path.iterdir()) == []  # downloaded file removed after parsing
