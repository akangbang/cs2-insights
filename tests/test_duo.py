import pandas as pd
import pytest

from cs2_insights.demo import ParsedDemo
from cs2_insights.duo import Support, build_duo, partners
from cs2_insights.fights import FightModel


def _players(rounds, a=("me", "mate", "x"), b=("e1", "e2")):
    return pd.DataFrame([{"round": r, "steamid": s, "name": s.upper(), "team": t} for r in rounds for t, group in (("A", a), ("B", b)) for s in group])


def _team_rounds(rounds, won):
    return pd.DataFrame([{"round": r, "team": t, "won": (r in won) == (t == "A")} for r in rounds for t in "AB"])


def _chance(tick, victim, mate, to_killer=300.0, aim=5.0, to_victim=250.0):
    return {"round": 1, "tick": tick, "victim": victim, "mate": mate, "distance_to_killer": to_killer, "aim_angle": aim, "distance_to_victim": to_victim}


def _death(tick, victim, killer="e1", traded_by=None, seconds=None):
    return {"round": 1, "tick": tick, "victim": victim, "killer": killer, "traded_by": traded_by, "trade_seconds": seconds}


def _blind(tick, thrower, blinded, teammate, seconds=2.0):
    return {"round": 1, "tick": tick, "thrower": thrower, "blinded": blinded, "seconds": seconds, "teammate": teammate}


def _match(chances=(), deaths=(), blinds=(), rounds=(1, 2, 3, 4), won=(1, 2, 3), **teams):
    return ParsedDemo(match=pd.DataFrame([{"match_id": "m"}]), rounds=pd.DataFrame(), team_rounds=_team_rounds(rounds, set(won)),
                      player_rounds=_players(rounds, **teams), deaths=pd.DataFrame(list(deaths)), trade_chances=pd.DataFrame(list(chances)),
                      utility=pd.DataFrame(), blinds=pd.DataFrame(list(blinds)))


def test_partners_are_teammates_with_the_most_shared_matches_first():
    table = partners([_match(), _match(a=("me", "mate", "x"), b=("e1", "e2")), _match(a=("me", "mate"), b=("x", "e1"))], "me")
    assert table["steamid"].tolist() == ["mate", "x"]
    assert table.set_index("steamid").at["mate", "matches"] == 3
    assert table.set_index("steamid").at["x", "matches"] == 2  # on the enemy team in the third match


def test_counts_win_rate_with_and_without_the_partner():
    together = _match(won=(1, 2, 3))  # 3 of 4
    apart = _match(a=("me", "x"), b=("mate", "e1"), won=(1,))  # 1 of 4, on opposite teams
    duo = build_duo([together, apart], "me", "mate", "MATE")
    assert (duo.matches, duo.rounds) == (1, 4)
    assert duo.win_rate == pytest.approx(0.75)
    assert duo.solo_rounds == 4 and duo.solo_win_rate == pytest.approx(0.25)


def test_trades_go_to_the_right_player():
    chances = [_chance(100, "mate", "me"), _chance(300, "mate", "me"), _chance(500, "me", "mate", to_killer=1_500)]
    deaths = [_death(100, "mate", traded_by="me", seconds=1.0), _death(300, "mate", traded_by="x", seconds=1.0), _death(500, "me")]
    duo = build_duo([_match(chances, deaths)], "me", "mate", "MATE")
    assert (duo.you.alive, duo.you.in_range, duo.you.traded) == (2, 2, 1)
    assert (duo.them.alive, duo.them.in_range, duo.them.traded) == (1, 0, 0)
    assert duo.you.expected > duo.them.expected


def test_a_late_trade_does_not_count():
    chances = [_chance(100, "mate", "me")]
    deaths = [_death(100, "mate", traded_by="me", seconds=3.5)]
    assert build_duo([_match(chances, deaths)], "me", "mate", "MATE").you.traded == 0


def test_rounds_on_opposite_teams_are_ignored():
    deaths = [_death(100, "mate", traded_by="me", seconds=1.0)]
    chances = [_chance(100, "mate", "me")]
    both = _match(chances, deaths, a=("me", "x"), b=("mate", "e1"))
    with pytest.raises(ValueError):
        build_duo([both], "me", "mate", "MATE")


def test_flashes_between_the_two_are_counted_with_deaths_and_kills_set_up():
    blinds = [_blind(100, "me", "mate", True), _blind(400, "me", "e1", False), _blind(700, "mate", "me", True)]
    deaths = [_death(160, "mate", killer="e2"), _death(450, "e1", killer="mate")]
    duo = build_duo([_match(blinds=blinds, deaths=deaths)], "me", "mate", "MATE")
    assert (duo.you.flashed_them, duo.you.died_blind, duo.you.kills_set_up) == (1, 1, 1)
    assert (duo.them.flashed_them, duo.them.died_blind, duo.them.kills_set_up) == (1, 0, 0)


def test_notes_call_out_distance():
    far = [_chance(t, "mate", "me", to_killer=2_000, to_victim=1_200) for t in (100, 200, 300)]
    deaths = [_death(t, "mate") for t in (100, 200, 300)]
    notes = build_duo([_match(far, deaths)], "me", "mate", "MATE").notes
    assert any(n.title == "You play far apart" and n.kind == "fix" for n in notes)


def test_notes_compare_trades_with_what_is_expected():
    close = [_chance(t, "mate", "me", to_killer=200, aim=2) for t in (100, 200, 300, 400)]
    deaths = [_death(t, "mate") for t in (100, 200, 300, 400)]
    model = FightModel()
    duo = build_duo([_match(close, deaths)], "me", "mate", "MATE", model)
    assert any(n.title == "You could trade MATE more" for n in duo.notes)


def test_few_chances_make_no_trade_note():
    close = [_chance(100, "mate", "me", to_killer=200, aim=2)]
    assert not [n for n in build_duo([_match(close, [_death(100, "mate")])], "me", "mate", "MATE").notes if "could trade" in n.title or "up well" in n.title]


def test_support_starts_empty():
    assert Support().traded == 0
