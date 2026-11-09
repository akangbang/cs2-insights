"""Replay a decision: what each option a player had was worth, from the models Getleanpeek already tests.

These are estimates of each option's value, not a prediction of what would have happened. For a
death, a demo can't show whether you'd have survived by playing differently, so "stayed alive" is
labelled a best case. The measured option next to it is the same death with a teammate close enough
to trade, at the rate deaths like that get traded across the pool.
"""

from dataclasses import dataclass, replace

import pandas as pd

from cs2_insights import fights
from cs2_insights.fights import FightModel
from cs2_insights.grade import CLOSE_CALL, FORCE

WIN, ROUNDS = "win", "rounds"  # what an option's value measures: round win chance, or expected rounds


@dataclass(frozen=True)
class Option:
    label: str
    value: float
    taken: bool = False
    best_case: bool = False


@dataclass(frozen=True)
class Replay:
    question: str
    unit: str
    axis: str
    options: tuple[Option, ...]
    takeaway: str
    note: str
    disputes_verdict: bool = False  # the numbers lean against the verdict on the card


def _compare(options: tuple[Option, ...], close: float, span: str) -> str:
    """One sentence on a two-option choice measured in rounds."""
    taken = next(o for o in options if o.taken)
    other = next(o for o in options if not o.taken)
    gap = other.value - taken.value
    if abs(gap) < close:
        return f"Too close to call: the two options are within {abs(gap):.2f} rounds of each other {span}."
    if gap > 0:
        return f"**{other.label}** comes out about **{gap:.2f} rounds** ahead {span}."
    return f"What you did was the better option, by about **{-gap:.2f} rounds** {span}."


def call_replay(call: pd.Series) -> Replay:
    """Force or save: expected rounds won from each, over the rounds the grader played forward."""
    first, counted = int(call["round"]), int(call["rounds_counted"])
    span = f"in round {first}" if counted == 1 else f"over rounds {first}–{first + counted - 1}"
    forced = call["made"] == FORCE
    options = (Option("Force", float(call["force_wins"]), taken=forced), Option("Save", float(call["save_wins"]), taken=not forced))
    return Replay(
        "Force or save?", ROUNDS, f"Rounds your team is expected to win {span}", options, _compare(options, CLOSE_CALL, span),
        f"This round alone, a force wins about {call['force_now']:.0%} against their buy and a save about {call['save_now']:.0%}. "
        "Later rounds play out both teams' money under CS2's rules.",
    )


def _fight_or_save(question: str, fight_label: str, save_label: str, p: float, q: float, save_value: float, fought: bool) -> Replay:
    """Fighting wins the round with chance p and keeps the gun if it does; saving keeps it for sure, with the team's chance at q."""
    options = (Option(fight_label, p * (1 + save_value), taken=fought), Option(save_label, q + save_value, taken=not fought))
    return Replay(
        question, ROUNDS, "Expected rounds: this one, plus what the gun is worth later", options,
        _compare(options, fights.CLUTCH_MARGIN, "counting this round and later buys"),
        f"Your team's chance to win this round was about {p:.0%} with you fighting and {q:.0%} with you hiding. "
        f"Keeping your gear was worth about {save_value:.2f} rounds in later buys.",
    )


def clutch_replay(clutch: pd.Series) -> Replay | None:
    """Fight or save when you were last alive. None for a won clutch, or when saving was worth nothing (money was about to reset)."""
    if clutch["outcome"] == "Won" or not clutch["save_rounds"]:
        return None
    return _fight_or_save("Fight or save?", "Fight", "Save the gun", float(clutch["win_chance"]), 0.0, float(clutch["save_value"]),
                          clutch["outcome"] != "Saved")


def death_replay(death: pd.Series, model: FightModel, close_trade_rate: float) -> Replay | None:
    """The options behind an avoidable death. None for deaths that weren't the player's decision."""
    label = death["label"]
    happened = float(death["win_before"] - death["cost"])
    if label == fights.SHOULD_SAVE:
        if not death["save_rounds"]:
            return None
        replay = _fight_or_save("Keep fighting or keep your gun?", "Keep fighting", "Hide and keep the gun", float(death["win_before"]), happened,
                                float(death["save_value"]), True)
        fight, hide = replay.options
        if fight.value - hide.value < fights.CLUTCH_MARGIN:
            return replay
        return replace(replay, disputes_verdict=True,
                       takeaway=replay.takeaway + " \"Lost round\" is a rule of thumb, and here the numbers lean the other way: your gear wasn't worth much in later buys.")
    if label not in (fights.REPEEK, fights.ALONE):
        return None
    alive = float(death["win_before"])
    team, enemies, plant = int(death["team_alive"]), int(death["enemies_alive"]), int(death["plant"])
    if label == fights.REPEEK:
        question, did, lived = "Re-peek or move?", "Re-peeked and died", "Moved and stayed alive (best case)"
    else:
        question, did, lived = "Push now or wait?", "Pushed alone and died", "Waited and stayed alive (best case)"
    options = [Option(did, happened, taken=True)]
    takeaway = ""
    if team >= 2:  # somebody has to be left to trade you
        after_trade = float(model.win_chance(team - 1, enemies - 1, plant)[0])
        traded = close_trade_rate * after_trade + (1 - close_trade_rate) * happened
        options.append(Option("Same death, teammate close enough to trade", traded))
        takeaway = f"A teammate close enough to trade was worth about **+{(traded - happened) * 100:.0f} points** of round win chance. "
    options.append(Option(lived, alive, best_case=True))
    takeaway += f"Staying alive was worth up to **+{(alive - happened) * 100:.0f} points**."
    note = "Best case assumes you'd have lived, which a demo can't show."
    if team >= 2:
        note += f" The trade option uses how often deaths with a teammate within 300 units get traded across the pool ({close_trade_rate:.0%})."
    return Replay(question, WIN, "Your team's chance to win the round", tuple(options), takeaway, note)
