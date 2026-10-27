"""Patterns across many matches: the economy habits that cost a player's team the most rounds.

One match can't show a habit; ten can. Every force-or-save decision is graded (grade.py)
and grouped by situation, split buys are compared with what the team's equipment should
win, money left unspent when it's about to reset is totalled, and avoidable deaths and
teammate coverage (fights.py) are compared with every player in the pool.
"""

from dataclasses import dataclass, field

import pandas as pd

from cs2_insights import fights
from cs2_insights.demo import ParsedDemo
from cs2_insights.fights import FightModel, coverage, judge_deaths, setup_scores
from cs2_insights.grade import GOOD_CALL, SAVE, SHOULD_FORCE, SHOULD_SAVE, economy_states, grade_decisions
from cs2_insights.rates import DEFAULT_EQUIPMENT_SLOPE, equipment_win_rate
from cs2_insights.report import SPLIT_BUYER_MIN, split_buy_rounds

# Fewer matches than this and patterns are too thin to call habits.
MIN_MATCHES = 3
# Money left in your pocket on the last round of a half above this is worth flagging.
WASTED_MONEY_MIN = 1_000
GERUND = {"save": "saving", "force": "forcing"}
# Your traded-death rate must beat the pool's by this much to count as a strength.
TRADED_MARGIN = 0.03
# An avoidable-death habit needs at least this many examples.
MIN_DEATHS_FOR_HABIT = 2
DEATH_HABITS = {
    fights.REPEEK: (
        "You re-peek after getting a kill",
        "{n} times in {m} matches you got a kill, peeked the same spot again and died ({per:.1f} per match). "
        "After a kill, reposition or fall back so a teammate can trade.",
    ),
    fights.ALONE: (
        "You push without support",
        "{n} times in {m} matches you died pushing with no teammate close enough to trade ({per:.1f} per match). "
        "Wait for a teammate to follow before you clear the next angle.",
    ),
    fights.SHOULD_SAVE: (
        "You die with your gun in rounds that are already lost",
        "{n} times in {m} matches your team was under {lost:.0%} to win and you died with $3,000+ of gear "
        "(${gear:,} in total). Hide and save it: next round starts from that money.",
    ),
}


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
    deaths: pd.DataFrame = field(default_factory=pd.DataFrame)  # your judged deaths, with match_id
    coverage: pd.DataFrame = field(default_factory=pd.DataFrame)  # teammate deaths near you, with match_id
    fight_matches: int = 0  # matches with death data
    coverage_grade: str | None = None
    fixes: list[Habit] = field(default_factory=list)
    strengths: list[Habit] = field(default_factory=list)


def _situation(call: pd.Series, first_rounds: set[int]) -> str:
    if call["rounds_counted"] == 1:
        return "last round"
    if call["round"] - 1 in first_rounds:
        return "after a lost pistol" if call["lost_previous"] else "after a won pistol"
    return "mid-half"


def build_habits(matches: list[ParsedDemo], steamid: str, slope: float = DEFAULT_EQUIPMENT_SLOPE,
                 fight_model: FightModel | None = None) -> Habits:
    """Habits for `steamid` across `matches` (only the matches they played are used).

    All `matches` (not only the player's) set the pool averages deaths and coverage are compared with.
    """
    model = fight_model or FightModel()
    calls, splits, wasted, name, played = [], [], [], None, 0
    my_deaths, my_cover, pool_deaths, pool_chances = [], [], [], []
    for parsed in matches:
        if len(parsed.deaths):
            pool_deaths.append(parsed.deaths)
            pool_chances.append(parsed.trade_chances.assign(match_id=parsed.match.iloc[0]["match_id"]))
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

        if len(parsed.deaths):
            judged = judge_deaths(parsed.deaths, parsed.trade_chances, parsed.team_rounds, model)
            tags = {"match_id": match["match_id"], "map": match["map"]}
            my_deaths.append(judged[judged["victim"] == steamid].assign(**tags))
            my_cover.append(coverage(judged, parsed.trade_chances, steamid, model).assign(**tags))

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
    if my_deaths:
        habits.deaths = pd.concat(my_deaths, ignore_index=True)
        habits.coverage = pd.concat(my_cover, ignore_index=True)
        habits.fight_matches = len(my_deaths)
        if len(habits.coverage) >= fights.MIN_COVERAGE_CHANCES:
            habits.coverage_grade = model.grade(float(habits.coverage["chance"].mean()))
    if played < MIN_MATCHES:
        return habits
    if habits.fight_matches:
        _fight_habits(habits, pd.concat(pool_deaths, ignore_index=True), pd.concat(pool_chances, ignore_index=True), model)

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


def _fight_habits(habits: Habits, pool_deaths: pd.DataFrame, pool_chances: pd.DataFrame, model: FightModel) -> None:
    """Avoidable deaths and coverage, compared with every player in the pool."""
    m, deaths, cover = habits.fight_matches, habits.deaths, habits.coverage
    for label, (title, template) in DEATH_HABITS.items():
        group = deaths[deaths["label"] == label]
        if len(group) >= MIN_DEATHS_FOR_HABIT:
            detail = template.format(n=len(group), m=m, per=len(group) / m, lost=fights.LOST_CAUSE, gear=int(group["victim_equip"].sum()))
            habits.fixes.append(Habit(title, detail + f" These deaths cost about {group['cost'].sum():.1f} rounds.", group["cost"].sum() / m))

    if len(cover) >= fights.MIN_COVERAGE_CHANCES:
        pool_score = float(setup_scores(pool_chances, model).mean()) if len(pool_chances) else 0.0
        score = float(cover["chance"].mean())
        in_range = cover["distance_to_killer"] <= fights.TRADE_RANGE
        set_up = in_range & (cover["aim_angle"] <= fights.FACING_ANGLE)
        trades = int((cover["verdict"] == fights.COVER_TRADED).sum())
        detail = (
            f"{len(cover)} teammate deaths happened near you in {m} matches. You were close enough to trade {int(in_range.sum())} times "
            f"and aiming at the fight in {int(set_up.sum())} of those. You traded {trades}; players in the pool would trade "
            f"about {cover['chance'].sum():.1f} from your spots."
        )
        if habits.coverage_grade in ("D", "F"):
            facing_away = int((cover["verdict"] == fights.COVER_FACING_AWAY).sum())
            tip = (" Most of the gap is where you aim: when a teammate takes a fight near you, aim where his killer will be."
                   if facing_away >= in_range.sum() / 2 else
                   " Most of the gap is distance: play close enough to your teammates (under 900 units) to trade them.")
            cost = max(pool_score - score, 0) * len(cover) * float(cover["cost"].mean()) / m
            habits.fixes.append(Habit(f"You're rarely set up to trade teammates (coverage {habits.coverage_grade})", detail + tip, cost))
        elif habits.coverage_grade in ("A", "B"):
            habits.strengths.append(Habit(f"You cover your teammates well (coverage {habits.coverage_grade})", detail, 0.0, "good"))

    traded = deaths["label"] == fights.TRADED
    pool_traded = pool_deaths["trade_seconds"].le(fights.TRADE_SECONDS).mean() if len(pool_deaths) else 0.0
    if len(deaths) and traded.mean() >= pool_traded + TRADED_MARGIN:
        habits.strengths.append(Habit(
            f"{int(traded.sum())} of your {len(deaths)} deaths were traded",
            f"That's {traded.mean():.0%}; across the pool it's {pool_traded:.0%}. You fight where teammates can back you up.",
            0.0, "good",
        ))
    habits.fixes.sort(key=lambda h: h.cost, reverse=True)


def _why(made: str, situation: str) -> str:
    if made == SAVE and situation == "after a lost pistol":
        return "The pistol winners usually buy SMGs and armour, not rifles, so a force of your own is close to even and a win breaks their economy."
    if made == SAVE and situation == "last round":
        return "Nothing you save on the last round of a half carries over."
    if made == SAVE:
        return "Their buy was weak enough that your force had a real chance, and saving didn't buy you much next round."
    return "Their full buy beats a force most of the time, and losing it leaves you broke for the next round too."
