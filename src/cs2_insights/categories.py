"""Match categories: Premier, Competitive and FACEIT are different games, so they can be viewed apart."""

import pandas as pd

from cs2_insights.demo import COMPETITIVE, FACEIT, OTHER, PREMIER, ParsedDemo

ALL = "all"
LABELS = {PREMIER: "Premier", COMPETITIVE: "Competitive", FACEIT: "FACEIT", OTHER: "Other"}


def category_of(value) -> str:
    """A stored match_type as a known category; matches parsed before categories existed are Other."""
    return value if isinstance(value, str) and value in LABELS else OTHER


def match_category(parsed: ParsedDemo) -> str:
    match = parsed.match.iloc[0]
    return category_of(match.get("match_type"))


def category_counts(matches: list[ParsedDemo]) -> dict[str, int]:
    """How many matches are in each category that has any, in display order."""
    found = pd.Series([match_category(m) for m in matches], dtype=object).value_counts().to_dict()
    return {key: int(found[key]) for key in LABELS if key in found}


def filter_matches(matches: list[ParsedDemo], category: str | None) -> list[ParsedDemo]:
    if category in (None, ALL):
        return matches
    return [m for m in matches if match_category(m) == category]
