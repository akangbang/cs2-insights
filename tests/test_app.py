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
    assert {"Fights", "Teamplay", "Economy"} <= set(labels)
    assert {"Your deaths", "Clutches & openings", "Covering teammates", "Spacing", "Utility", "Buy calls",
            "Round by round"} <= set(labels)
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


def test_hosted_guests_can_upload_without_signing_in(monkeypatch):
    monkeypatch.setenv("HALFTIME_HOSTED", "1")
    app = AppTest.from_file("../app.py", default_timeout=120).run()
    assert not app.exception
    assert "Upload a demo" in app.info[0].value
    assert any("isn't saved" in m.value for m in app.markdown)
    assert not app.button and not app.sidebar.button  # no Sign out, and no sign-in until it's set up
    assert not app.header and not app.metric


def test_hosted_mode_offers_sign_in_once_login_is_set_up(monkeypatch):
    monkeypatch.setenv("HALFTIME_HOSTED", "1")
    app = AppTest.from_file("../app.py", default_timeout=120)
    app.secrets["auth"] = {"redirect_uri": "https://example.test/oauth2callback"}
    app.run()
    assert not app.exception
    assert [b.label for b in app.button] == ["Sign in with Google"]
    assert [b.label for b in app.get("link_button")] == ["Sign in through Steam"]
    assert "Upload a demo" in app.info[0].value  # guests can still use it
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


def test_the_app_reconnects_after_the_database_drops_its_connection():
    """A hosted database (Neon) closes idle connections when it suspends; the next page load must still work."""
    from cs2_insights import db

    try:
        admin = db.connect()
    except Exception:
        pytest.skip("PostgreSQL not running (docker compose up -d)")
    app = AppTest.from_file("../app.py", default_timeout=120).run()
    assert not app.exception
    # Close only the app's connections (other tests' connections survive), like a suspending database would.
    closed = admin.execute("SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE application_name = %s",
                           (db.APP_NAME,)).fetchone()[0]
    assert closed >= 1
    admin.close()
    app.run()
    assert not app.exception
    assert not any("database isn't running" in w.value for w in app.warning)

