"""How sure each verdict is, in words: a level and a one-line reason.

These describe the evidence behind one verdict (how clear-cut the numbers were, how many examples
a habit has). They are rules of thumb, not statistical confidence intervals.
"""

import pandas as pd

from cs2_insights import fights

HIGH, MEDIUM, LOW = "High", "Medium", "Low"
DOTS = {HIGH: "●●●", MEDIUM: "●●○", LOW: "●○○"}

CLEAR_REPEEK_SECONDS = 2.0
FAR_FROM_TRADE = 1_500  # units from the killer; well past where trades happen, even allowing for walls
HOPELESS_ROUND = 0.08
CLUTCH_CLEAR, CLUTCH_FAIR = 0.15, 0.06  # how far the fight's value is from the save's, in rounds
CALL_CLEAR, CALL_FAIR = 0.4, 0.2  # gap between forcing and saving, in rounds
GRADE_MANY, GRADE_SOME = 15, 6  # teammate deaths near you
HABIT_MANY, HABIT_SOME = 8, 4  # examples
HABIT_MATCHES_MANY, HABIT_MATCHES_SOME = 5, 3


def describe(level: str, why: str) -> str:
    return f"{DOTS[level]} Confidence: {level.lower()}. {why}"


def death_confidence(death: pd.Series) -> tuple[str, str] | None:
    """Only avoidable deaths: the other verdicts aren't a call about what you should have done."""
    label = death["label"]
    if label == fights.REPEEK:
        if death["repeek_gap"] <= CLEAR_REPEEK_SECONDS:
            return HIGH, "You died within seconds of your kill, in the same spot."
        return MEDIUM, "A few seconds passed after your kill, so this may have been a new fight."
    if label == fights.ALONE:
        if pd.isna(death["closest_mate"]) or death["closest_mate"] >= FAR_FROM_TRADE:
            return HIGH, "Your nearest teammate was far beyond trading range."
        return MEDIUM, "Your nearest teammate wasn't far outside trading range, and walls aren't modelled."
    if label == fights.SHOULD_SAVE:
        if death["win_before"] < HOPELESS_ROUND:
            return HIGH, "The round was as good as lost."
        return MEDIUM, "A comeback was unlikely, but not impossible."
    return None


def clutch_confidence(clutch: pd.Series) -> tuple[str, str] | None:
    """Not for won clutches: the result already settled those."""
    if clutch["outcome"] == "Won":
        return None
    edge = abs(clutch["win_chance"] * (1 + clutch["save_value"]) - clutch["save_value"])
    if edge >= CLUTCH_CLEAR:
        return HIGH, "Fighting and saving weren't close."
    if edge >= CLUTCH_FAIR:
        return MEDIUM, "One choice was better, but not by much."
    return LOW, "Fighting and saving were worth about the same."


def call_confidence(call: pd.Series) -> tuple[str, str]:
    if call["rounds_counted"] == 1:
        return HIGH, "Money resets after this round, so saving couldn't pay off."
    gap = abs(call["force_wins"] - call["save_wins"])
    if gap >= CALL_CLEAR:
        return HIGH, "Forcing and saving weren't close in the simulation."
    if gap >= CALL_FAIR:
        return MEDIUM, "The simulation favours this choice, but not by much."
    return LOW, "The simulation only slightly favours this choice."


def grade_confidence(chances: int) -> tuple[str, str]:
    if chances >= GRADE_MANY:
        return HIGH, f"Based on {chances} teammate deaths near you."
    if chances >= GRADE_SOME:
        return MEDIUM, f"Based on {chances} teammate deaths near you."
    return LOW, f"Based on only {chances} teammate deaths near you."


def habit_confidence(examples: int, matches: int) -> tuple[str, str]:
    seen = f"{examples} example{'s' if examples != 1 else ''} in {matches} match{'es' if matches != 1 else ''}."
    if examples >= HABIT_MANY and matches >= HABIT_MATCHES_MANY:
        return HIGH, seen
    if examples >= HABIT_SOME and matches >= HABIT_MATCHES_SOME:
        return MEDIUM, seen
    return LOW, f"Only {seen} Could be chance so far."
