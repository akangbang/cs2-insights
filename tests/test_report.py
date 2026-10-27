import pandas as pd
import pytest

from cs2_insights.demo import ParsedDemo
from cs2_insights.report import build_report, expected_win_rate, players_in, pooled_rates

ME = "me"


def _match(rounds):
    """rounds: list of (my_buy, my_equip, their_buy, their_equip, i_won, my_player_equips)."""
    team_rounds, player_rounds = [], []
    score = {"A": 0, "B": 0}
    for number, (my_buy, my_equip, their_buy, their_equip, won, equips) in enumerate(rounds, start=1):
        for team, buy, equip, team_won in (("A", my_buy, my_equip, won), ("B", their_buy, their_equip, not won)):
            team_rounds.append({
                "match_id": "m", "round": number, "team": team, "side": "CT" if team == "A" else "T",
                "players": 5, "equip_value": equip, "bank": 1_000, "won": team_won,
                "score": score[team], "opponent_score": score["B" if team == "A" else "A"], "buy_type": buy,
            })
        for i, equip in enumerate(equips):
            player_rounds.append({
                "match_id": "m", "round": number, "steamid": ME if i == 0 else f"mate{i}", "name": "Me" if i == 0 else f"Mate {i}",
                "team": "A", "side": "CT", "balance": 500, "equip_value": equip,
            })
        player_rounds.append({
            "match_id": "m", "round": number, "steamid": "enemy", "name": "Enemy", "team": "B", "side": "T",
            "balance": 500, "equip_value": their_equip // 5,
        })
        score["A" if won else "B"] += 1
    match = pd.DataFrame([{"match_id": "m", "map": "de_test", "team_a_score": score["A"], "team_b_score": score["B"]}])
    return ParsedDemo(match, pd.DataFrame(), pd.DataFrame(team_rounds), pd.DataFrame(player_rounds))


FULL = [4_500] * 5
POOL = pd.DataFrame(
    [
        {"buy_type": "force", "opponent_buy_type": "full", "rounds": 90, "wins": 27},
        {"buy_type": "full", "opponent_buy_type": "force", "rounds": 90, "wins": 63},
        {"buy_type": "eco", "opponent_buy_type": "full", "rounds": 90, "wins": 9},
        {"buy_type": "full", "opponent_buy_type": "eco", "rounds": 90, "wins": 81},
    ]
)


def test_expected_win_rate_is_smoothed_toward_buy_type_rate():
    rate, sample = expected_win_rate(POOL, "force", "full")
    assert sample == 90
    assert rate == pytest.approx((27 + 10 * 0.3) / 100)
    # An unseen matchup falls back to the buy type's overall rate.
    rate, sample = expected_win_rate(POOL, "force", "eco")
    assert sample == 0 and rate == pytest.approx(0.3)


def test_pooled_rates_counts_both_teams():
    parsed = _match([("full", 22_000, "force", 12_000, True, FULL)])
    pool = pooled_rates(parsed.team_rounds)
    assert set(zip(pool["buy_type"], pool["opponent_buy_type"], pool["wins"])) == {("full", "force", 1), ("force", "full", 0)}


def test_report_flags_force_trap_upset_and_split_buy():
    parsed = _match([
        ("force", 12_000, "full", 22_000, False, [3_000] * 5),  # lost force...
        ("eco", 4_000, "full", 22_000, False, [800] * 5),  # ...then eco: the force trap
        ("eco", 4_000, "full", 22_000, True, [4_000, 800, 800, 800, 800]),  # upset win with a split buy
        ("full", 22_000, "force", 12_000, False, FULL),  # lost while favoured
    ])
    report = build_report(parsed, ME, POOL)

    assert report.summary["result"] == "Loss"
    assert report.rounds["verdict"].tolist() == [
        "Expected loss", "Expected loss", "Upset win", "Upset loss",
    ]
    assert report.rounds["split_buy"].tolist() == [False, False, True, False]
    titles = [m.title for m in report.moments]
    assert titles[0] == "Round 1: the force that cost two rounds"
    assert "1 split buy" in titles
    assert "Round 3: best upset" in titles
    assert "Round 4: the one that got away" in titles
    assert report.players.loc[report.players["steamid"] == ME, "split_buys"].iat[0] == 1


def test_players_in_and_unknown_player():
    parsed = _match([("full", 22_000, "force", 12_000, True, FULL)])
    assert set(players_in(parsed)["steamid"]) == {ME, "mate1", "mate2", "mate3", "mate4", "enemy"}
    with pytest.raises(ValueError):
        build_report(parsed, "nobody", POOL)
