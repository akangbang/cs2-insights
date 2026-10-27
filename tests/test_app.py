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
    assert [t.label for t in app.tabs] == ["💀 Your deaths", "🤝 Covering teammates", "💰 Buy calls", "📈 Economy"]
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
