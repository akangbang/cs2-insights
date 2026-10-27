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
                "start_equip_value": 1_000, "cash_spent": max(equip - 1_000, 0),
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


def test_expected_win_rate_is_smoothed_toward_a_symmetric_prior():
    # Overall win rates: force 27/90 = 0.3, full (63 + 81)/180 = 0.8, eco 9/90 = 0.1.
    rate, sample = expected_win_rate(POOL, "force", "full")
    assert sample == 90
    assert rate == pytest.approx((27 + 10 * (0.3 + 1 - 0.8) / 2) / 100)
    # An unseen matchup falls back to the prior alone.
    rate, sample = expected_win_rate(POOL, "force", "eco")
    assert sample == 0 and rate == pytest.approx((0.3 + 1 - 0.1) / 2)


def test_matchup_and_its_mirror_sum_to_one():
    # A pool built from real rounds: every round counts once for each team.
    rounds = []
    for number, (a_buy, b_buy, a_won) in enumerate(
        [("full", "eco", True), ("full", "eco", False), ("eco", "full", False), ("force", "full", True), ("pistol", "pistol", True)]
    ):
        rounds += [
            {"match_id": "m", "round": number, "team": "A", "buy_type": a_buy, "won": a_won},
            {"match_id": "m", "round": number, "team": "B", "buy_type": b_buy, "won": not a_won},
        ]
    pool = pooled_rates(pd.DataFrame(rounds))
    for buy, opponent in [("full", "eco"), ("force", "full"), ("pistol", "pistol"), ("eco", "force")]:
        total = expected_win_rate(pool, buy, opponent)[0] + expected_win_rate(pool, opponent, buy)[0]
        assert total == pytest.approx(1.0)


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
    assert "1 split buy" in titles
    assert "Round 3: best upset" in titles
    assert report.players.loc[report.players["steamid"] == ME, "split_buys"].iat[0] == 1

    # No fight data in this match: those sections stay empty instead of failing.
    assert report.summary["fights_parsed"] is False and report.summary["coverage"]["grade"] is None

    # Every graded decision shows up in the round table too.
    assert report.summary["calls"] == len(report.calls)
    assert set(report.rounds["call"]) <= {"", "Good call", "Close call", "Should have saved", "Should have forced"}


def test_report_grades_buy_calls_and_explains_them():
    # Round 2 is the match's last round: $3,200 each, and the team saves money it can never use.
    parsed = _match([
        ("pistol", 4_000, "pistol", 4_000, False, [800] * 5),
        ("eco", 4_000, "full", 22_000, False, [800] * 5),
    ])
    parsed.team_rounds.loc[parsed.team_rounds["round"] == 2, "bank"] = 12_000
    report = build_report(parsed, ME, POOL)
    assert report.summary["calls"] == 1 and report.summary["calls_wrong"] == 1
    assert report.rounds.set_index("round").at[2, "call"] == "Should have forced"
    moment = report.moments[0]
    assert moment.title == "Round 2: should have forced"
    assert "Money resets" in moment.detail


def test_players_in_and_unknown_player():
    parsed = _match([("full", 22_000, "force", 12_000, True, FULL)])
    assert set(players_in(parsed)["steamid"]) == {ME, "mate1", "mate2", "mate3", "mate4", "enemy"}
    with pytest.raises(ValueError):
        build_report(parsed, "nobody", POOL)
