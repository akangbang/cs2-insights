import pytest

from cs2_insights.sharecode import ShareCode, encode
from cs2_insights.steam import (
    SteamAPIError,
    SteamProfileRef,
    get_next_share_code,
    iter_share_codes,
    parse_steam_url,
)

STEAM64 = "76561198012345678"
AUTH_CODE = "ABCD-EFGHI-JKLM"
CODES = [encode(ShareCode(1000 + i, 2000 + i, 3000 + i)) for i in range(4)]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("https://steamcommunity.com/profiles/76561198012345678", ("steam64", STEAM64)),
        ("https://steamcommunity.com/id/s1mple", ("vanity", "s1mple")),
        ("steamcommunity.com/id/s1mple", ("vanity", "s1mple")),
        ("http://steamcommunity.com/id/s1mple", ("vanity", "s1mple")),
        ("https://steamcommunity.com/profiles/76561198012345678/", ("steam64", STEAM64)),
        ("https://steamcommunity.com/profiles/76561198012345678/games", ("steam64", STEAM64)),
        ("76561198012345678", ("steam64", STEAM64)),
        ("   https://steamcommunity.com/id/s1mple/  ", ("vanity", "s1mple")),
        ("https://STEAMCOMMUNITY.com/ID/s1mple?l=english", ("vanity", "s1mple")),
    ],
)
def test_parse_steam_url_accepts(text, expected):
    assert parse_steam_url(text) == SteamProfileRef(*expected)


@pytest.mark.parametrize(
    "text",
    [
        "https://faceit.com/en/players/s1mple",
        "https://steamcommunity.com/profiles/abc",
        "https://steamcommunity.com/profiles/123",
        "",
        "https://steamcommunity.com/",
        "https://evilsteamcommunity.com/id/x",
        "ftp://steamcommunity.com/id/x",
    ],
)
def test_parse_steam_url_rejects(text):
    with pytest.raises(ValueError):
        parse_steam_url(text)


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


class FakeSession:
    """Plays back Steam's answers: each known code maps to the next one."""

    def __init__(self, chain, status_code=200):
        self.chain = chain
        self.status_code = status_code
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params)
        if self.status_code != 200:
            return FakeResponse(self.status_code)
        next_code = self.chain.get(params["knowncode"])
        if next_code is None:
            return FakeResponse(202, {"result": {"nextcode": "n/a"}})
        return FakeResponse(200, {"result": {"nextcode": next_code}})


def test_iter_share_codes_walks_until_no_newer_match():
    session = FakeSession({CODES[0]: CODES[1], CODES[1]: CODES[2], CODES[2]: CODES[3]})
    assert list(iter_share_codes("key", STEAM64, AUTH_CODE, CODES[0], session=session)) == CODES[1:]
    assert session.calls[0]["steamidkey"] == AUTH_CODE


def test_iter_share_codes_respects_limit():
    session = FakeSession({CODES[0]: CODES[1], CODES[1]: CODES[2], CODES[2]: CODES[3]})
    assert list(iter_share_codes("key", STEAM64, AUTH_CODE, CODES[0], limit=2, session=session)) == CODES[1:3]


def test_no_newer_match_returns_none():
    assert get_next_share_code("key", STEAM64, AUTH_CODE, CODES[0], session=FakeSession({})) is None


@pytest.mark.parametrize("status", [403, 412, 429, 500])
def test_steam_errors_raise(status):
    with pytest.raises(SteamAPIError):
        get_next_share_code("key", STEAM64, AUTH_CODE, CODES[0], session=FakeSession({}, status))


def test_bad_inputs_rejected_before_calling_steam():
    session = FakeSession({})
    with pytest.raises(ValueError):
        get_next_share_code("key", "123", AUTH_CODE, CODES[0], session=session)
    with pytest.raises(ValueError):
        get_next_share_code("key", STEAM64, "not-a-code", CODES[0], session=session)
    with pytest.raises(ValueError):
        get_next_share_code("key", STEAM64, AUTH_CODE, "CSGO-bad", session=session)
    assert session.calls == []
