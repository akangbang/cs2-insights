"""Turn a CS2 .dem file into round-level economy tables with demoparser2."""

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from demoparser2 import DemoParser

SIDES = {2: "T", 3: "CT"}
# Team equipment value after buying (proposal cut-offs, to tune on data).
ECO_MAX = 5_000
FORCE_MAX = 20_000
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


def buy_type(round_number: int, first_round_of_half: set[int], equip_value: float) -> str:
    if round_number in first_round_of_half:
        return "pistol"
    if equip_value < ECO_MAX:
        return "eco"
    if equip_value <= FORCE_MAX:
        return "force"
    return "full"


def parse_demo(path: str | Path) -> ParsedDemo:
    path = Path(path)
    parser = DemoParser(str(path))
    header = parser.parse_header()
    match_id = match_id_from_path(path)

    ends = parser.parse_event("round_end")
    ends = ends[ends["winner"].isin(["CT", "T"])].sort_values("tick").reset_index(drop=True)
    freeze_ends = sorted(parser.parse_event("round_freeze_end")["tick"].tolist())

    # Pair each round end with the last freeze end before it (skips warmup and restarts).
    rounds = []
    previous_end = -1
    for number, end in enumerate(ends.itertuples(), start=1):
        starts = [t for t in freeze_ends if previous_end < t < end.tick]
        if starts:
            rounds.append(
                {
                    "match_id": match_id,
                    "round": number,
                    "freeze_end_tick": starts[-1],
                    "end_tick": end.tick,
                    "winner_side": end.winner,
                    "reason": end.reason,
                }
            )
        previous_end = end.tick
    rounds = pd.DataFrame(rounds)
    if rounds.empty:
        raise ValueError(f"No completed rounds found in {path.name}.")

    players = parser.parse_ticks(PLAYER_PROPS, ticks=rounds["freeze_end_tick"].tolist())
    players = players[players["team_num"].isin(SIDES)].copy()
    players["side"] = players["team_num"].map(SIDES)
    players = players.merge(
        rounds[["round", "freeze_end_tick"]], left_on="tick", right_on="freeze_end_tick"
    )

    # Team A is whoever started on CT; players keep their team when sides swap.
    first_round = players["round"].min()
    team_a = set(players[(players["round"] == first_round) & (players["side"] == "CT")]["steamid"])
    players["team"] = players["steamid"].map(lambda s: "A" if s in team_a else "B")

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

    # Rounds where a team's side differs from the round before are the first of a half.
    a_sides = team_rounds[team_rounds["team"] == "A"].set_index("round")["side"]
    first_of_half = {a_sides.index[0]} | {
        r for prev, r in zip(a_sides.index, a_sides.index[1:]) if a_sides[prev] != a_sides[r]
    }

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
        buy_type(r, first_of_half, v) for r, v in zip(team_rounds["round"], team_rounds["equip_value"])
    ]
    team_rounds.insert(0, "match_id", match_id)
    team_rounds = team_rounds.drop(columns="winner_side")

    final = wins.sum()
    match = pd.DataFrame(
        [
            {
                "match_id": match_id,
                "source": "valve" if VALVE_DEMO_NAME.match(path.name) else "upload",
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
