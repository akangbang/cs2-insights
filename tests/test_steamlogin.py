from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from cs2_insights.steamlogin import ENDPOINT, NS, login_url, verify

APP = "https://getleanpeek.example/"
STEAM_ID = "76561198000000001"


def _reply(**overrides):
    params = {
        "openid.ns": NS, "openid.mode": "id_res", "openid.op_endpoint": ENDPOINT,
        "openid.claimed_id": f"https://steamcommunity.com/openid/id/{STEAM_ID}",
        "openid.identity": f"https://steamcommunity.com/openid/id/{STEAM_ID}",
        "openid.return_to": APP, "openid.response_nonce": "2026-11-10T00:00:00Zabc", "openid.assoc_handle": "1234567890",
        "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle", "openid.sig": "c2ln",
    }
    params.update(overrides)
    return {k: v for k, v in params.items() if v is not None}


def _steam(answer="ns:http://specs.openid.net/auth/2.0\nis_valid:true\n", status=200):
    sent = []

    def post(url, data, timeout):
        sent.append((url, data))
        return SimpleNamespace(text=answer, status_code=status)
    return post, sent


def test_login_url_sends_the_player_to_steam_and_back_here():
    url = urlparse(login_url(APP))
    query = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == ENDPOINT
    assert query["openid.return_to"] == [APP] and query["openid.realm"] == [APP] and query["openid.mode"] == ["checkid_setup"]


def test_a_reply_steam_confirms_gives_the_steam_id():
    post, sent = _steam()
    assert verify(_reply(), APP, post) == STEAM_ID
    url, data = sent[0]
    assert url == ENDPOINT and data["openid.mode"] == "check_authentication" and data["openid.sig"] == "c2ln"


def test_a_reply_steam_rejects_signs_nobody_in():
    post, _ = _steam("ns:http://specs.openid.net/auth/2.0\nis_valid:false\n")
    assert verify(_reply(), APP, post) is None


@pytest.mark.parametrize("change", [
    {"openid.return_to": "https://evil.example/"},
    {"openid.op_endpoint": "https://evil.example/openid/login"},
    {"openid.claimed_id": "https://evil.example/openid/id/76561198000000001"},
    {"openid.identity": "https://steamcommunity.com/openid/id/76561198000000002"},
    {"openid.mode": "cancel"},
    {"openid.signed": "signed,op_endpoint,return_to"},
    {"openid.claimed_id": None},
])
def test_tampered_replies_are_rejected_before_asking_steam(change):
    post, sent = _steam()
    assert verify(_reply(**change), APP, post) is None
    assert not sent


def test_steam_being_unreachable_signs_nobody_in():
    def post(url, data, timeout):
        raise requests.ConnectionError("down")
    assert verify(_reply(), APP, post) is None
    bad, _ = _steam(status=500)
    assert verify(_reply(), APP, bad) is None
