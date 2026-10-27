"""Patterns across many matches: the economy habits that cost a player's team the most rounds.

One match can't show a habit; ten can. Every force-or-save decision is graded (grade.py)
and grouped by situation, split buys are compared with what the team's equipment should
win, and money left unspent when it's about to reset is totalled.
"""

from dataclasses import dataclass, field

import pandas as pd

from cs2_insights.demo import ParsedDemo
from cs2_insights.grade import GOOD_CALL, SAVE, SHOULD_FORCE, SHOULD_SAVE, economy_states, grade_decisions
from cs2_insights.rates import DEFAULT_EQUIPMENT_SLOPE, equipment_win_rate
from cs2_insights.report import SPLIT_BUYER_MIN, split_buy_rounds

# Fewer matches than this and patterns are too thin to call habits.
MIN_MATCHES = 3
# Money left in your pocket on the last round of a half above this is worth flagging.
WASTED_MONEY_MIN = 1_000
GERUND = {"save": "saving", "force": "forcing"}


@dataclass
class Habit:
    title: str
    detail: str
    cost: float  # expected rounds lost per match
    kind: str = "bad"  # "bad" (fix it) or "good" (keep it)


@dataclass
class Habits:
    name: str
    matches: int
    calls: pd.DataFrame  # every graded decision, with match_id and map
    fixes: list[Habit] = field(default_factory=list)
    strengths: list[Habit] = field(default_factory=list)


def _situation(call: pd.Series, first_rounds: set[int]) -> str:
    if call["rounds_counted"] == 1:
        return "last round"
    if call["round"] - 1 in first_rounds:
        return "after a lost pistol" if call["lost_previous"] else "after a won pistol"
    return "mid-half"


def build_habits(matches: list[ParsedDemo], steamid: str, slope: float = DEFAULT_EQUIPMENT_SLOPE) -> Habits:
    """Habits for `steamid` across `matches` (only the matches they played are used)."""
    calls, splits, wasted, name, played = [], [], [], None, 0
    for parsed in matches:
        me = parsed.player_rounds[parsed.player_rounds["steamid"] == steamid]
        if me.empty:
            continue
        played += 1
        name = me["name"].iat[-1]
        team = me["team"].mode().iat[0]
        match = parsed.match.iloc[0]
        mine = parsed.team_rounds[parsed.team_rounds["team"] == team].set_index("round")
        theirs = parsed.team_rounds[parsed.team_rounds["team"] != team].set_index("round")

        graded = grade_decisions(parsed.team_rounds, team, slope)
        first_rounds = set(mine.index[mine["buy_type"] == "pistol"])
        graded["lost_previous"] = [not mine["won"].get(r - 1, True) for r in graded["round"]]
        graded["situation"] = [_situation(c, first_rounds) for _, c in graded.iterrows()]
        calls.append(graded.assign(match_id=match["match_id"], map=match["map"]))

        for number in split_buy_rounds(parsed.player_rounds, team):
            you = me[me["round"] == number]
            splits.append(
                {
                    "won": bool(mine.at[number, "won"]),
                    "expected": equipment_win_rate(
                        mine.at[number, "equip_value"] / mine.at[number, "players"],
                        theirs.at[number, "equip_value"] / theirs.at[number, "players"],
                        slope,
                    ),
                    "you_bought": bool(len(you) and you["equip_value"].iat[0] >= SPLIT_BUYER_MIN),
                }
            )

        states = economy_states(parsed.team_rounds)
        # Last rounds of a half, not counting the match's final round (nothing comes after it anyway).
        last_rounds = states[
            (states["team"] == team) & (states["rounds_left_in_half"] == 0) & (states["round"] < states["round"].max())
        ]["round"]
        left = me[me["round"].isin(last_rounds)]["balance"]
        wasted.extend(left.tolist())

    if played == 0:
        raise ValueError("That player isn't in any stored match.")
    all_calls = pd.concat(calls, ignore_index=True) if calls else pd.DataFrame()
    habits = Habits(name=name, matches=played, calls=all_calls)
    if played < MIN_MATCHES:
        return habits

    # Wrong calls, grouped by what you did and when.
    wrong = all_calls[all_calls["grade"].isin([SHOULD_FORCE, SHOULD_SAVE])]
    for (made, situation), group in wrong.groupby(["made", "situation"]):
        total = all_calls[(all_calls["made"] == made) & (all_calls["situation"] == situation)]
        verb, better = ("save", "force") if made == SAVE else ("force", "save")
        habits.fixes.append(
            Habit(
                f"You {verb} {situation} when you should {better}",
                f"{len(group)} of your {len(total)} {verb}s {situation} {'was' if len(group) == 1 else 'were'} the wrong call: {GERUND[better]} "
                f"would have won about {group['cost'].sum():.1f} more rounds across {played} matches. "
                + _why(made, situation),
                group["cost"].sum() / played,
            )
        )

    if splits:
        split = pd.DataFrame(splits)
        shortfall = split["expected"].sum() - split["won"].sum()
        mine_count = int(split["you_bought"].sum())
        if shortfall > 0:
            habits.fixes.append(
                Habit(
                    "Your team splits buys",
                    f"{len(split)} split buys in {played} matches: you won {int(split['won'].sum())}, when that "
                    f"equipment should win about {split['expected'].sum():.1f}. You were the one buying in {mine_count}. "
                    "Call the buy before the round: all in or all save.",
                    shortfall / played,
                )
            )

    if wasted:
        unspent = [m for m in wasted if m >= WASTED_MONEY_MIN]
        if unspent:
            habits.fixes.append(
                Habit(
                    "You keep money that's about to reset",
                    f"On {len(unspent)} of {len(wasted)} last rounds of a half you still had ${WASTED_MONEY_MIN:,}+ "
                    f"left (${sum(unspent) / len(unspent):,.0f} on average). Money resets at half-time: buy armour, "
                    "utility or a better gun, or drop for a teammate.",
                    0.0,  # not measured in rounds; listed after the habits that are
                )
            )

    habits.fixes.sort(key=lambda h: h.cost, reverse=True)
    right = all_calls[all_calls["grade"] == GOOD_CALL]
    if len(all_calls):
        habits.strengths.append(
            Habit(
                f"{len(right)} of {len(all_calls)} buy calls were right",
                f"The rest were close calls ({int((all_calls['grade'] == 'Close call').sum())}) or wrong ({len(wrong)}).",
                0.0,
                "good",
            )
        )
    return habits


def _why(made: str, situation: str) -> str:
    if made == SAVE and situation == "after a lost pistol":
        return "The pistol winners usually buy SMGs and armour, not rifles, so a force of your own is close to even and a win breaks their economy."
    if made == SAVE and situation == "last round":
        return "Nothing you save on the last round of a half carries over."
    if made == SAVE:
        return "Their buy was weak enough that your force had a real chance, and saving didn't buy you much next round."
    return "Their full buy beats a force most of the time, and losing it leaves you broke for the next round too."
