"""Turn a CS2 .dem file into round-level economy tables with demoparser2."""

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from demoparser2 import DemoParser

SIDES = {2: "T", 3: "CT"}
# Average equipment value per player after buying. Full buy = rifle + armor + some utility.
ECO_MAX_PER_PLAYER = 1_600
FULL_MIN_PER_PLAYER = 3_800
PLAYER_PROPS = [
    "team_num",
    "balance",
    "current_equip_value",
    "round_start_equip_value",
    "cash_spent_this_round",
    "armor_value",
    "has_helmet",
    "has_defuser",
]
VALVE_DEMO_NAME = re.compile(r"match730_(\d+)_")
# Regulation is 24 rounds (MR12); after that, overtime halves start with set money, not pistols.
REGULATION_ROUNDS = 24


@dataclass
class ParsedDemo:
    match: pd.DataFrame  # one row
    rounds: pd.DataFrame  # one row per round
    team_rounds: pd.DataFrame  # one row per team per round
    player_rounds: pd.DataFrame  # one row per player per round


def match_id_from_path(path: Path) -> str:
    """Valve demos are named match730_<match id>_...; otherwise fall back to the file name."""
    found = VALVE_DEMO_NAME.match(path.name)
    return str(int(found.group(1))) if found else path.stem


def buy_type(round_number: int, first_round_of_half: set[int], equip_value: float, players: int = 5) -> str:
    if round_number in first_round_of_half and round_number <= REGULATION_ROUNDS:
        return "pistol"
    per_player = equip_value / max(players, 1)
    if per_player < ECO_MAX_PER_PLAYER:
        return "eco"
    if per_player < FULL_MIN_PER_PLAYER:
        return "force"
    return "full"


def pair_rounds(ends: pd.DataFrame, freeze_ends: list[int]) -> list[dict]:
    """Pair each round end with the last freeze end before it (skips warmup and restarts).

    Rounds are numbered consecutively, so a round end without a freeze end doesn't leave a gap.
    """
    rounds = []
    previous_end = -1
    for end in ends.sort_values("tick").itertuples():
        starts = [t for t in freeze_ends if previous_end < t < end.tick]
        if starts:
            rounds.append(
                {
                    "round": len(rounds) + 1,
                    "freeze_end_tick": starts[-1],
                    "end_tick": end.tick,
                    "winner_side": end.winner,
                    "reason": end.reason,
                }
            )
        previous_end = end.tick
    return rounds


def assign_teams(players: pd.DataFrame) -> pd.Series:
    """Label each player-round "A" or "B", where A is the team that started on CT.

    Each round, team A's side is the side most of A's starting players are on; everyone on
    that side is A. This keeps late joiners and substitutes on the right team.
    """
    first_round = players["round"].min()
    starters = set(players[(players["round"] == first_round) & (players["side"] == "CT")]["steamid"])
    a_side = {}
    for number, group in players.groupby("round"):
        known = group[group["steamid"].isin(starters)]["side"]
        a_side[number] = known.mode().iat[0] if not known.empty else None
    # Rounds with none of A's starters fall back to the previous round's side.
    last = "CT"
    for number in sorted(a_side):
        a_side[number] = a_side[number] or last
        last = a_side[number]
    return pd.Series(
        ["A" if side == a_side[r] else "B" for r, side in zip(players["round"], players["side"])],
        index=players.index,
    )


def first_rounds_of_halves(a_sides: pd.Series) -> set[int]:
    """Rounds where team A's side differs from the round before, plus the first round."""
    rounds = list(a_sides.index)
    return {rounds[0]} | {r for prev, r in zip(rounds, rounds[1:]) if a_sides[prev] != a_sides[r]}


def parse_demo(path: str | Path, match_id: str | None = None, source: str | None = None) -> ParsedDemo:
    """Parse one demo. match_id and source default to what the file name says."""
    path = Path(path)
    parser = DemoParser(str(path))
    header = parser.parse_header()
    match_id = match_id or match_id_from_path(path)

    ends = parser.parse_event("round_end")
    ends = ends[ends["winner"].isin(["CT", "T"])]
    freeze_ends = sorted(parser.parse_event("round_freeze_end")["tick"].tolist())
    rounds = pd.DataFrame(pair_rounds(ends, freeze_ends))
    if rounds.empty:
        raise ValueError(f"No completed rounds found in {path.name}.")
    rounds.insert(0, "match_id", match_id)

    players = parser.parse_ticks(PLAYER_PROPS, ticks=rounds["freeze_end_tick"].tolist())
    players = players[players["team_num"].isin(SIDES)].copy()
    players["side"] = players["team_num"].map(SIDES)
    players = players.merge(
        rounds[["round", "freeze_end_tick"]], left_on="tick", right_on="freeze_end_tick"
    )

    players["team"] = assign_teams(players)

    player_rounds = pd.DataFrame(
        {
            "match_id": match_id,
            "round": players["round"],
            "steamid": players["steamid"].astype(str),
            "name": players["name"],
            "team": players["team"],
            "side": players["side"],
            "balance": players["balance"],
            "equip_value": players["current_equip_value"],
            "start_equip_value": players["round_start_equip_value"],
            "cash_spent": players["cash_spent_this_round"],
            "armor": players["armor_value"],
            "has_helmet": players["has_helmet"].astype(bool),
            "has_defuser": players["has_defuser"].astype(bool),
        }
    ).sort_values(["round", "team", "steamid"]).reset_index(drop=True)

    team_rounds = (
        player_rounds.groupby(["round", "team"])
        .agg(
            side=("side", lambda s: s.mode().iat[0]),
            players=("steamid", "count"),
            equip_value=("equip_value", "sum"),
            bank=("balance", "sum"),
            start_equip_value=("start_equip_value", "sum"),
            cash_spent=("cash_spent", "sum"),
        )
        .reset_index()
    )

    first_of_half = first_rounds_of_halves(team_rounds[team_rounds["team"] == "A"].set_index("round")["side"])

    team_rounds = team_rounds.merge(rounds[["round", "winner_side"]], on="round")
    team_rounds["won"] = team_rounds["side"] == team_rounds["winner_side"]
    team_rounds = team_rounds.sort_values(["round", "team"]).reset_index(drop=True)
    wins = team_rounds.pivot(index="round", columns="team", values="won").astype(int)
    score_before = wins.cumsum().shift(fill_value=0)
    team_rounds["score"] = [score_before.at[r, t] for r, t in zip(team_rounds["round"], team_rounds["team"])]
    team_rounds["opponent_score"] = [
        score_before.at[r, "B" if t == "A" else "A"] for r, t in zip(team_rounds["round"], team_rounds["team"])
    ]
    team_rounds["buy_type"] = [
        buy_type(r, first_of_half, v, n)
        for r, v, n in zip(team_rounds["round"], team_rounds["equip_value"], team_rounds["players"])
    ]
    team_rounds.insert(0, "match_id", match_id)
    team_rounds = team_rounds.drop(columns="winner_side")

    final = wins.sum()
    match = pd.DataFrame(
        [
            {
                "match_id": match_id,
                "source": source or ("valve" if VALVE_DEMO_NAME.match(path.name) else "upload"),
                "map": header.get("map_name"),
                "server": header.get("server_name"),
                "patch_version": header.get("patch_version"),
                "rounds": len(rounds),
                "team_a_score": int(final.get("A", 0)),
                "team_b_score": int(final.get("B", 0)),
                "demo_file": path.name,
            }
        ]
    )
    return ParsedDemo(match=match, rounds=rounds, team_rounds=team_rounds, player_rounds=player_rounds)
