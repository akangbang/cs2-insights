"""Habit proof: has the habit you chose to work on changed since you chose it?

Demos carry no dates, so "since you chose it" is measured in match IDs: when a focus is picked, the
newest stored match ID is remembered, and only matches with a higher ID count as after. Valve IDs
increase over time; uploads have no place in that order and are left out, as in the recap.
"""

from dataclasses import dataclass
from io import BytesIO

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from cs2_insights.progress import FOCUS, RECENT_MATCHES
from cs2_insights.recap import MOVED, Change, measure_change

MIN_BEFORE = 2  # matches from before the focus needed to compare with
MIN_AFTER = 3  # one or two good matches can be luck, so no claim before this many
WAITING, NO_BASELINE, IMPROVED, SAME, WORSE = "waiting", "no baseline", "improved", "same", "worse"


@dataclass(frozen=True)
class Proof:
    status: str
    label: str
    before_matches: int
    after_matches: int
    change: Change | None = None


def _ordered(past: pd.DataFrame) -> pd.DataFrame:
    return past[past["match_id"].astype(str).str.isdigit()] if len(past) else past


def latest_match(past: pd.DataFrame) -> str | None:
    """The newest match with a known place in time: where a new focus starts counting from."""
    ordered = _ordered(past)
    return str(max(ordered["match_id"].astype(str), key=int)) if len(ordered) else None


def build_proof(past: pd.DataFrame, key: str, since: str) -> Proof:
    """Compare a focus habit before and after match ID `since`."""
    label, column, _ = FOCUS[key]
    ordered = _ordered(past)
    if len(ordered) and column in ordered:
        ordered = ordered[pd.to_numeric(ordered[column], errors="coerce").notna()]
    else:
        ordered = ordered.iloc[:0]
    start = int(since)
    is_after = ordered["match_id"].astype(str).map(lambda m: int(m) > start).astype(bool)
    before, after = ordered[~is_after].tail(RECENT_MATCHES), ordered[is_after]
    if len(after) < MIN_AFTER:
        return Proof(WAITING, label, len(before), len(after))
    if len(before) < MIN_BEFORE:
        return Proof(NO_BASELINE, label, len(before), len(after))
    change = measure_change(key, before, after)
    status = IMPROVED if change.score >= MOVED else WORSE if change.score <= -MOVED else SAME
    return Proof(status, label, len(before), len(after), change)


CARD_SIZE = (1200, 630)
CARD_BACKGROUND, CARD_ACCENT, CARD_TEXT, CARD_MUTED = "#0e1117", "#3987e5", "#fafafa", "#a3a8b4"


def _matches(n: int) -> str:
    return f"{n} match{'es' if n != 1 else ''}"


def change_words(change: Change) -> str:
    """The size of a change in plain words, e.g. "0.9 fewer per match"."""
    down = change.difference < 0
    if change.kind == "rate":
        return f"{abs(change.difference) * 100:.0f} points {'lower' if down else 'higher'}"
    return f"{abs(change.difference):.1f} {'fewer' if down else 'more'} per match"


def proof_card(proof: Proof) -> bytes:
    """A shareable PNG of an improvement. It carries no player name, so it's safe to post."""
    change = proof.change
    image = Image.new("RGB", CARD_SIZE, CARD_BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default
    left = 72
    draw.rectangle((0, 0, 14, CARD_SIZE[1]), fill=CARD_ACCENT)
    draw.text((left, 56), "Getleanpeek", font=font(38), fill=CARD_TEXT)
    draw.text((left, 150), "Habit I worked on", font=font(30), fill=CARD_MUTED)
    draw.text((left, 192), proof.label, font=font(54), fill=CARD_TEXT)

    # The default font has no arrow character, so the arrow is drawn.
    numbers, y = font(136), 288
    before = change.value(change.earlier)
    x = left
    draw.text((x, y), before, font=numbers, fill=CARD_MUTED)
    x += draw.textlength(before, font=numbers) + 42
    middle = y + 78
    draw.line((x, middle, x + 88, middle), fill=CARD_ACCENT, width=10)
    draw.polygon([(x + 118, middle), (x + 80, middle - 30), (x + 80, middle + 30)], fill=CARD_ACCENT)
    draw.text((x + 160, y), change.value(), font=numbers, fill=CARD_TEXT)

    draw.text((left, 468), change_words(change), font=font(38), fill=CARD_ACCENT)
    draw.text((left, 540), f"Last {_matches(proof.before_matches)} before choosing this habit, compared with {_matches(proof.after_matches)} since",
              font=font(28), fill=CARD_MUTED)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
