"""Runs the Streamlit app headlessly and checks the report renders."""

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_demo import LOCAL_DEMOS

pytestmark = pytest.mark.skipif(not LOCAL_DEMOS, reason="no local CS2 demos")


def test_report_renders_for_newest_replay_and_switches_player():
    app = AppTest.from_file("../app.py", default_timeout=120).run()
    assert not app.exception
    # Nobody is reviewed until a player is chosen.
    picker = app.selectbox[0]
    assert picker.label == "Which player do you want to review?" and picker.value is None
    assert not app.header
    app = picker.set_value(picker.options[0]).run()
    assert not app.exception
    assert app.header[0].value.split(" · ")[1].startswith(("Win", "Loss", "Draw"))
    assert [m.label for m in app.metric][:4] == ["Rounds won", "Avoidable deaths", "Coverage", "Buy calls right"]
    labels = [t.label for t in app.tabs]
    assert {"⚔️ Fights", "🤝 Teamplay", "💰 Economy"} <= set(labels)
    assert {"💀 Your deaths", "🎯 Clutches & openings", "🤝 Covering teammates", "📏 Spacing", "🧨 Utility", "💰 Buy calls",
            "📈 Round by round"} <= set(labels)
    assert "Coverage grade" in [m.label for m in app.metric]

    first = app.header[0].value
    players = app.selectbox[0]
    app = players.set_value(players.options[-1]).run()  # someone on the other team
    assert not app.exception
    assert app.header[0].value != first


def test_upload_mode_prompts_for_a_file():
    app = AppTest.from_file("../app.py", default_timeout=120).run()
    app = app.sidebar.radio[0].set_value("Upload a demo").run()
    assert not app.exception
    assert "Upload a demo" in app.info[0].value


def test_hosted_mode_without_a_login_shows_nothing(monkeypatch):
    monkeypatch.setenv("HALFTIME_HOSTED", "1")
    app = AppTest.from_file("../app.py", default_timeout=120).run()
    assert not app.exception
    assert "Sign-in is required" in app.info[0].value
    assert not app.selectbox and not app.header and not app.metric


def test_hosted_mode_offers_sign_in_once_login_is_set_up(monkeypatch):
    monkeypatch.setenv("HALFTIME_HOSTED", "1")
    app = AppTest.from_file("../app.py", default_timeout=120)
    app.secrets["auth"] = {"redirect_uri": "https://example.test/oauth2callback"}
    app.run()
    assert not app.exception
    assert [b.label for b in app.button] == ["Sign in with Google"]
    assert [b.label for b in app.get("link_button")] == ["Sign in through Steam"]
    assert not app.selectbox and not app.header and not app.metric


def test_a_forged_steam_reply_signs_nobody_in(monkeypatch):
    monkeypatch.setenv("HALFTIME_HOSTED", "1")
    monkeypatch.setenv("HALFTIME_PUBLIC_URL", "https://getleanpeek.example/")
    app = AppTest.from_file("../app.py", default_timeout=120)
    app.query_params["openid.mode"] = "id_res"
    app.query_params["openid.claimed_id"] = "https://steamcommunity.com/openid/id/76561198000000001"
    app.query_params["openid.return_to"] = "https://evil.example/"
    app.run()
    assert not app.exception
    assert "didn't go through" in app.error[0].value
    assert not app.selectbox and not app.metric
