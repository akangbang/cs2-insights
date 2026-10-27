"""Turn a parsed match into a player's economy report.

Each round's buy is compared with how often that buy-versus-buy matchup wins across every
match in the pool, and every force-or-save decision is graded by simulating both choices
(see grade.py), so a player sees which calls cost their team rounds.
"""

from dataclasses import dataclass, field

import pandas as pd

from cs2_insights.demo import ParsedDemo
from cs2_insights.grade import CLOSE, FORCE, GOOD_CALL, SHOULD_FORCE, SHOULD_SAVE, grade_decisions
from cs2_insights.rates import DEFAULT_EQUIPMENT_SLOPE, expected_win_rate, pooled_rates  # noqa: F401  (re-exported)

UPSET_BELOW = 0.40
FAVOURED_ABOVE = 0.60
# A split buy: at least one player bought a rifle-level loadout while two or more saved.
SPLIT_BUYER_MIN = 3_500
SPLIT_SAVER_MAX = 1_500
# Upset moments need this many pooled rounds behind the matchup, or they're mostly noise.
UPSET_MIN_SAMPLE = 20
# A wrong call is only worth a moment when it cost at least this many expected rounds.
COSTLY_CALL = 0.25

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
    calls: pd.DataFrame = field(default_factory=pd.DataFrame)  # grade.grade_decisions() for your team
    moments: list[Moment] = field(default_factory=list)


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


def build_report(parsed: ParsedDemo, steamid: str, pool: pd.DataFrame, slope: float = DEFAULT_EQUIPMENT_SLOPE) -> Report:
    """Economy report for the team `steamid` played on.

    `pool` comes from pooled_rates(); `slope` from rates.equipment_slope() on the same pool.
    """
    me = parsed.player_rounds[parsed.player_rounds["steamid"] == steamid]
    if me.empty:
        raise ValueError("That player isn't in this match.")
    my_team = me["team"].mode().iat[0]
    their_team = "B" if my_team == "A" else "A"

    teams = parsed.team_rounds.set_index(["round", "team"])
    split = split_buy_rounds(parsed.player_rounds, my_team)
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
    calls = grade_decisions(parsed.team_rounds, my_team, slope)
    rounds = rounds.merge(calls[["round", "grade", "cost"]].rename(columns={"grade": "call", "cost": "call_cost"}), on="round", how="left")
    rounds["call"] = rounds["call"].fillna("")
    rounds["call_cost"] = rounds["call_cost"].fillna(0.0)

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
        "calls": len(calls),
        "calls_right": int((calls["grade"] == GOOD_CALL).sum()),
        "calls_close": int((calls["grade"] == CLOSE).sum()),
        "calls_wrong": int(calls["grade"].isin([SHOULD_FORCE, SHOULD_SAVE]).sum()),
        "rounds_lost_to_calls": round(float(calls["cost"].sum()), 1),
    }

    return Report(
        summary=summary,
        rounds=rounds,
        buy_summary=buy_summary,
        players=_player_table(parsed.player_rounds, my_team, split),
        calls=calls,
        moments=_moments(rounds, calls),
    )


def split_buy_rounds(player_rounds: pd.DataFrame, team: str) -> set[int]:
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


def call_detail(call: pd.Series) -> str:
    """One decision explained: what you did, what the other choice wins, and why."""
    label = BUY_LABELS.get
    did = "forced" if call["made"] == FORCE else "saved"
    span = f"round {call['round']}" if call["rounds_counted"] == 1 else f"rounds {call['round']}–{call['round'] + call['rounds_counted'] - 1}"
    text = (
        f"You {did} with ${call['money_each']:,} each against their {label(call['their_buy']).lower()}. "
        f"Over {span}, forcing wins about {call['force_wins']:.1f} rounds and saving about {call['save_wins']:.1f}. "
    )
    if call["rounds_counted"] == 1:
        return text + "Money resets after this round, so anything you save is wasted."
    if call["grade"] == SHOULD_FORCE or (call["grade"] == GOOD_CALL and call["made"] == FORCE):
        return text + (
            f"A force wins this round {call['force_now']:.0%} of the time against their buy, an eco only "
            f"{call['save_now']:.0%}, and a win leaves them short of money next round."
        )
    return text + (
        f"Forcing wins this round only {call['force_now']:.0%} of the time and leaves you broke; "
        "saving sets up a full buy next round."
    )


def _moments(rounds: pd.DataFrame, calls: pd.DataFrame) -> list[Moment]:
    """The few rounds worth talking about, most important first."""
    moments = []
    label = BUY_LABELS.get

    # Wrong buy calls first: these are the decisions a team can actually change.
    wrong = calls[calls["grade"].isin([SHOULD_FORCE, SHOULD_SAVE]) & (calls["cost"] >= COSTLY_CALL)]
    for call in wrong.sort_values("cost", ascending=False).head(2).itertuples(index=False):
        call = pd.Series(call._asdict())
        moments.append(
            Moment(int(call["round"]), "bad", f"Round {call['round']}: {call['grade'].lower()}", call_detail(call)
                   + f" Cost: about {call['cost']:.1f} rounds.")
        )
    good = calls[calls["grade"] == GOOD_CALL]
    if len(good):
        edge = (good["force_wins"] - good["save_wins"]).abs()
        call = good.loc[edge.idxmax()]
        moments.append(Moment(int(call["round"]), "good", f"Round {call['round']}: right call to {call['made']}", call_detail(call)))

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
                f"You won {split_rounds['won'].sum()} of {len(split_rounds)}."
                + (" Buy together or save together: a half-bought team loses the round and the money." if len(lost) else ""),
            )
        )

    reliable = rounds[rounds["sample"] >= UPSET_MIN_SAMPLE]
    upsets = reliable[reliable["verdict"] == UPSET_WIN].sort_values("expected")
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
    return moments
