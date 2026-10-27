"""Turn a parsed match into a player's economy report.

Each round's buy is compared with how often that buy-versus-buy matchup wins across every
match in the pool, so a player sees which rounds they won against the odds and which
decisions set their team back.
"""

from dataclasses import dataclass, field

import pandas as pd

from cs2_insights.demo import ParsedDemo

# Pooled win rates are shrunk toward the buy type's overall rate by this many rounds,
# so a matchup seen only a few times doesn't swing to 0% or 100%.
SMOOTHING_ROUNDS = 10
UPSET_BELOW = 0.40
FAVOURED_ABOVE = 0.60
# A split buy: at least one player bought a rifle-level loadout while two or more saved.
SPLIT_BUYER_MIN = 3_500
SPLIT_SAVER_MAX = 1_500

BUY_LABELS = {"pistol": "Pistol", "eco": "Eco", "force": "Force", "full": "Full buy"}


@dataclass
class Moment:
    round: int
    kind: str  # "good" or "bad"
    title: str
    detail: str


@dataclass
class Report:
    summary: dict
    rounds: pd.DataFrame
    buy_summary: pd.DataFrame
    players: pd.DataFrame
    moments: list[Moment] = field(default_factory=list)


def pooled_rates(team_rounds: pd.DataFrame) -> pd.DataFrame:
    """Win counts per (buy_type, opponent_buy_type) from team-round rows of many matches."""
    opponents = team_rounds[["match_id", "round", "team", "buy_type"]].rename(
        columns={"team": "opp_team", "buy_type": "opponent_buy_type"}
    )
    paired = team_rounds.merge(opponents, on=["match_id", "round"])
    paired = paired[paired["team"] != paired["opp_team"]]
    return (
        paired.groupby(["buy_type", "opponent_buy_type"])
        .agg(rounds=("won", "size"), wins=("won", "sum"))
        .reset_index()
    )


def expected_win_rate(pool: pd.DataFrame, buy: str, opponent_buy: str) -> tuple[float, int]:
    """Smoothed pooled win rate for a matchup, and how many rounds it's based on."""
    by_buy = pool[pool["buy_type"] == buy]
    prior = by_buy["wins"].sum() / by_buy["rounds"].sum() if by_buy["rounds"].sum() else 0.5
    match = pool[(pool["buy_type"] == buy) & (pool["opponent_buy_type"] == opponent_buy)]
    wins, rounds = (int(match["wins"].iat[0]), int(match["rounds"].iat[0])) if not match.empty else (0, 0)
    return (wins + SMOOTHING_ROUNDS * prior) / (rounds + SMOOTHING_ROUNDS), rounds


def players_in(parsed: ParsedDemo) -> pd.DataFrame:
    """One row per player: steamid, name, team. Used to ask "which one are you?"."""
    last = parsed.player_rounds.sort_values("round").drop_duplicates("steamid", keep="last")
    return last[["steamid", "name", "team"]].sort_values(["team", "name"]).reset_index(drop=True)


UPSET_WIN = "Upset win"  # won a matchup that usually loses
UPSET_LOSS = "Upset loss"  # lost a matchup that usually wins


def _verdict(won: bool, expected: float) -> str:
    if won and expected < UPSET_BELOW:
        return UPSET_WIN
    if not won and expected > FAVOURED_ABOVE:
        return UPSET_LOSS
    return "Expected win" if won else "Expected loss"


def build_report(parsed: ParsedDemo, steamid: str, pool: pd.DataFrame) -> Report:
    """Economy report for the team `steamid` played on. `pool` comes from pooled_rates()."""
    me = parsed.player_rounds[parsed.player_rounds["steamid"] == steamid]
    if me.empty:
        raise ValueError("That player isn't in this match.")
    my_team = me["team"].mode().iat[0]
    their_team = "B" if my_team == "A" else "A"

    teams = parsed.team_rounds.set_index(["round", "team"])
    split = _split_buy_rounds(parsed.player_rounds, my_team)
    rows = []
    for number in sorted(parsed.team_rounds["round"].unique()):
        mine, theirs = teams.loc[(number, my_team)], teams.loc[(number, their_team)]
        expected, sample = expected_win_rate(pool, mine["buy_type"], theirs["buy_type"])
        rows.append(
            {
                "round": int(number),
                "side": mine["side"],
                "score": f"{mine['score']}-{mine['opponent_score']}",
                "your_buy": mine["buy_type"],
                "their_buy": theirs["buy_type"],
                "your_equip": int(mine["equip_value"]),
                "their_equip": int(theirs["equip_value"]),
                "your_bank": int(mine["bank"]),
                "won": bool(mine["won"]),
                "expected": round(expected, 3),
                "sample": sample,
                "split_buy": number in split,
            }
        )
    rounds = pd.DataFrame(rows)
    rounds["verdict"] = [_verdict(w, e) for w, e in zip(rounds["won"], rounds["expected"])]

    buy_summary = (
        rounds.groupby("your_buy")
        .agg(rounds=("won", "size"), wins=("won", "sum"), expected=("expected", "mean"))
        .reset_index()
    )
    buy_summary["win_rate"] = buy_summary["wins"] / buy_summary["rounds"]
    buy_summary["vs_expected"] = buy_summary["wins"] - (buy_summary["expected"] * buy_summary["rounds"])
    order = list(BUY_LABELS)
    buy_summary = buy_summary.sort_values("your_buy", key=lambda s: s.map(order.index)).reset_index(drop=True)

    match = parsed.match.iloc[0]
    my_score = int(match["team_a_score"] if my_team == "A" else match["team_b_score"])
    their_score = int(match["team_b_score"] if my_team == "A" else match["team_a_score"])
    summary = {
        "map": match["map"],
        "your_score": my_score,
        "their_score": their_score,
        "result": "Win" if my_score > their_score else "Loss" if my_score < their_score else "Draw",
        "name": me["name"].iat[-1],
        "rounds": len(rounds),
        "upsets_won": int((rounds["verdict"] == UPSET_WIN).sum()),
        "favoured_lost": int((rounds["verdict"] == UPSET_LOSS).sum()),
        "expected_wins": round(float(rounds["expected"].sum()), 1),
        "pool_rounds": int(pool["rounds"].sum()) // 2,
    }

    return Report(
        summary=summary,
        rounds=rounds,
        buy_summary=buy_summary,
        players=_player_table(parsed.player_rounds, my_team, split),
        moments=_moments(rounds),
    )


def _split_buy_rounds(player_rounds: pd.DataFrame, team: str) -> set[int]:
    mine = player_rounds[player_rounds["team"] == team]
    split = set()
    for number, group in mine.groupby("round"):
        buyers = (group["equip_value"] >= SPLIT_BUYER_MIN).sum()
        savers = (group["equip_value"] <= SPLIT_SAVER_MAX).sum()
        if buyers >= 1 and savers >= 2:
            split.add(int(number))
    return split


def _player_table(player_rounds: pd.DataFrame, team: str, split: set[int]) -> pd.DataFrame:
    mine = player_rounds[player_rounds["team"] == team].copy()
    mine["bought_in_split"] = mine["round"].isin(split) & (mine["equip_value"] >= SPLIT_BUYER_MIN)
    table = (
        mine.groupby(["steamid", "name"])
        .agg(
            rounds=("round", "size"),
            avg_equip=("equip_value", "mean"),
            avg_unspent=("balance", "mean"),
            split_buys=("bought_in_split", "sum"),
        )
        .reset_index()
        .sort_values("avg_equip", ascending=False)
    )
    table[["avg_equip", "avg_unspent"]] = table[["avg_equip", "avg_unspent"]].round(0).astype(int)
    return table.reset_index(drop=True)


def _moments(rounds: pd.DataFrame) -> list[Moment]:
    """The few rounds worth talking about, most important first."""
    moments = []
    by_round = rounds.set_index("round")
    label = BUY_LABELS.get

    # A lost force that left the team on an eco next round: the classic economy trap.
    for number, row in by_round.iterrows():
        nxt = by_round.loc[number + 1] if number + 1 in by_round.index else None
        if row["your_buy"] == "force" and not row["won"] and nxt is not None and nxt["your_buy"] == "eco":
            moments.append(
                Moment(
                    int(number),
                    "bad",
                    f"Round {number}: the force that cost two rounds",
                    f"You forced against their {label(row['their_buy']).lower()} "
                    f"(a matchup that wins {row['expected']:.0%} of the time), lost, "
                    f"and had to eco round {number + 1}.",
                )
            )

    split_rounds = rounds[rounds["split_buy"]]
    if len(split_rounds):
        lost = split_rounds[~split_rounds["won"]]
        moments.append(
            Moment(
                int((lost if len(lost) else split_rounds)["round"].iat[0]),
                "bad" if len(lost) else "good",
                f"{len(split_rounds)} split buy{'s' if len(split_rounds) > 1 else ''}",
                f"Some of your team bought while others saved in round"
                f"{'s' if len(split_rounds) > 1 else ''} {', '.join(map(str, split_rounds['round']))}. "
                f"You won {split_rounds['won'].sum()} of {len(split_rounds)}.",
            )
        )

    upsets = rounds[rounds["verdict"] == UPSET_WIN].sort_values("expected")
    if len(upsets):
        best = upsets.iloc[0]
        moments.append(
            Moment(
                int(best["round"]),
                "good",
                f"Round {best['round']}: best upset",
                f"Your {label(best['your_buy']).lower()} beat their {label(best['their_buy']).lower()}, "
                f"a matchup that wins only {best['expected']:.0%} of the time.",
            )
        )

    thrown = rounds[rounds["verdict"] == UPSET_LOSS].sort_values("expected", ascending=False)
    if len(thrown):
        worst = thrown.iloc[0]
        moments.append(
            Moment(
                int(worst["round"]),
                "bad",
                f"Round {worst['round']}: the one that got away",
                f"Your {label(worst['your_buy']).lower()} lost to their {label(worst['their_buy']).lower()}, "
                f"a matchup that wins {worst['expected']:.0%} of the time.",
            )
        )
    return moments
