"""Duo report: how two players on the same team back each other up across their shared matches.

Everything comes from rounds they actually played together on one team. "Trades" use the same
2-second rule as the rest of the app, and "expected" is what players in those spots usually get
from the pool's trade model.
"""

from dataclasses import dataclass, field

import pandas as pd

from cs2_insights import fights, spacing
from cs2_insights.demo import TICK_RATE, ParsedDemo
from cs2_insights.fights import FightModel
from cs2_insights.utility import review_team_flashes

MIN_MATCHES = 2  # one match together says little
MIN_CHANCES = 3  # in-range moments before comparing trades with what's expected
TRADE_GAP = 0.5  # trades above or below expected before it's worth a note
FAR_APART = 600  # units: typical distance beyond which nobody can trade
FLASHES_PER_MATCH = 1.0


@dataclass
class Support:
    """One player backing up the other."""

    alive: int = 0  # the other died while this player was alive
    in_range: int = 0
    set_up: int = 0  # in range and aiming at the killer
    traded: int = 0
    expected: float = 0.0
    flashed_them: int = 0
    died_blind: int = 0
    kills_set_up: int = 0  # this player's flash blinded an enemy the other then killed


@dataclass
class Note:
    title: str
    detail: str
    kind: str  # "fix" or "keep"


@dataclass
class Duo:
    matches: int
    rounds: int
    win_rate: float
    solo_rounds: int
    solo_win_rate: float | None
    you: Support  # you backing them up
    them: Support  # them backing you up
    median_distance: float | None
    close_share: float | None
    notes: list[Note] = field(default_factory=list)


def _teams(match: ParsedDemo, steamid: str) -> pd.Series:
    rows = match.player_rounds[match.player_rounds["steamid"] == steamid]
    return rows.set_index("round")["team"]


def _together(match: ParsedDemo, me: str, mate: str) -> set[int]:
    """Rounds these two played on the same team."""
    mine, theirs = _teams(match, me), _teams(match, mate)
    return {int(r) for r in mine.index.intersection(theirs.index) if mine[r] == theirs[r]}


def partners(matches: list[ParsedDemo], me: str) -> pd.DataFrame:
    """Everyone who played on `me`'s team, most shared matches first."""
    columns = ["steamid", "name", "matches", "rounds"]
    rows = []
    for match in matches:
        table = match.player_rounds
        mine = table[table["steamid"] == me][["round", "team"]]
        mates = table.merge(mine, on=["round", "team"])
        mates = mates[mates["steamid"] != me]
        rows.extend({"steamid": s, "name": g["name"].iat[-1], "rounds": len(g)} for s, g in mates.groupby("steamid"))
    if not rows:
        return pd.DataFrame(columns=columns)
    out = pd.DataFrame(rows).groupby("steamid").agg(name=("name", "last"), matches=("rounds", "size"), rounds=("rounds", "sum")).reset_index()
    return out.sort_values(["matches", "rounds"], ascending=False).reset_index(drop=True)[columns]


def _in_rounds(frame: pd.DataFrame, rounds: set[int]) -> pd.DataFrame:
    return frame[frame["round"].isin(rounds)] if len(frame) else frame


def _add_trades(support: Support, chances: pd.DataFrame, deaths: pd.DataFrame, helper: str, victim: str, model: FightModel) -> None:
    """The moments `victim` died while `helper` was alive."""
    if chances.empty:
        return
    moments = chances[(chances["victim"] == victim) & (chances["mate"] == helper)]
    if moments.empty:
        return
    in_range = moments["distance_to_killer"] <= fights.TRADE_RANGE
    support.alive += len(moments)
    support.in_range += int(in_range.sum())
    support.set_up += int((in_range & (moments["aim_angle"] <= fights.FACING_ANGLE)).sum())
    support.expected += float(model.trade_chance(moments["distance_to_killer"], moments["aim_angle"]).sum())
    quick = deaths[(deaths["victim"] == victim) & (deaths["traded_by"] == helper) & deaths["trade_seconds"].le(fights.TRADE_SECONDS)]
    support.traded += len(quick)


def _add_flashes(support: Support, blinds: pd.DataFrame, deaths: pd.DataFrame, thrower: str, target: str) -> None:
    if blinds.empty:
        return
    review = review_team_flashes(blinds, deaths, thrower)
    on_them = review[review["blinded"] == target]
    support.flashed_them += len(on_them)
    support.died_blind += int(on_them["died_blind"].astype(bool).sum())
    enemies = blinds[(blinds["thrower"] == thrower) & ~blinds["teammate"].astype(bool)]
    if deaths.empty or enemies.empty:
        return
    kills = deaths[deaths["killer"] == target]
    for flash in enemies.itertuples():
        window = kills[(kills["victim"] == flash.blinded) & kills["tick"].between(flash.tick, flash.tick + flash.seconds * TICK_RATE)]
        support.kills_set_up += int(len(window) > 0)


def _notes(duo: Duo, name: str) -> list[Note]:
    notes = []
    matches = duo.matches
    if duo.median_distance is not None:
        if duo.median_distance > FAR_APART:
            notes.append(Note("You play far apart", f"When one of you dies, the other is typically {duo.median_distance:,.0f} units away, too far to trade. "
                              f"Pick a side of the map to play together and stay within {spacing.CLOSE_ENOUGH} units.", "fix"))
        elif duo.close_share is not None and duo.close_share >= 0.3:
            notes.append(Note("You stay close enough to trade", f"{duo.close_share:.0%} of the time one of you dies, the other is within {spacing.CLOSE_ENOUGH} units.", "keep"))
    for support, who, other in ((duo.you, "You", name), (duo.them, name, "you")):
        if support.in_range >= MIN_CHANCES:
            gap = support.traded - support.expected
            if gap <= -TRADE_GAP:
                notes.append(Note(f"{who} could trade {other} more", f"{who} got {support.traded} trades from {support.in_range} chances in range; players in those spots "
                                  f"would get about {support.expected:.1f}. When one of you takes a fight, the other should aim where the killer will appear.", "fix"))
            elif gap >= TRADE_GAP:
                notes.append(Note(f"{who} back{'' if who == 'You' else 's'} {other} up well", f"{who} got {support.traded} trades from {support.in_range} chances in range, "
                                  f"more than the {support.expected:.1f} players in those spots usually get.", "keep"))
        if matches and support.flashed_them / matches >= FLASHES_PER_MATCH:
            died = f", and {support.died_blind} of those ended with a death while blind" if support.died_blind else ""
            notes.append(Note(f"{who} flash{'' if who == 'You' else 'es'} {other} too often", f"{support.flashed_them} flashes in {matches} matches blinded {other}{died}. "
                              "Call the flash before you throw it.", "fix"))
        if support.kills_set_up >= 2:
            notes.append(Note(f"{who} set{'' if who == 'You' else 's'} up {other}'s kills" if other != "you" else f"{who} sets up your kills",
                              f"{support.kills_set_up} enemies blinded by {'your' if who == 'You' else 'their'} flashes were then killed by {other}. Keep doing that.", "keep"))
    return notes


def build_duo(matches: list[ParsedDemo], me: str, mate: str, name: str, model: FightModel | None = None) -> Duo:
    """`me` and `mate` across the matches they shared; `name` is how to refer to `mate` in the notes."""
    model = model or FightModel()
    you, them = Support(), Support()
    played, together_rounds, wins, solo, solo_wins = 0, 0, 0, 0, 0
    distances = []
    for match in matches:
        rounds = _together(match, me, mate)
        mine = _teams(match, me)
        results = match.team_rounds.set_index(["round", "team"])["won"].astype(bool).to_dict()
        without = [r for r in mine.index if int(r) not in rounds]
        solo += len(without)
        solo_wins += sum(results.get((r, mine[r]), False) for r in without)
        if not rounds:
            continue
        played += 1
        together_rounds += len(rounds)
        wins += sum(results.get((r, mine[r]), False) for r in rounds)
        deaths, chances, blinds = _in_rounds(match.deaths, rounds), _in_rounds(match.trade_chances, rounds), _in_rounds(match.blinds, rounds)
        _add_trades(you, chances, deaths, me, mate, model)
        _add_trades(them, chances, deaths, mate, me, model)
        _add_flashes(you, blinds, deaths, me, mate)
        _add_flashes(them, blinds, deaths, mate, me)
        if len(chances):
            pair = chances[((chances["victim"] == me) & (chances["mate"] == mate)) | ((chances["victim"] == mate) & (chances["mate"] == me))]
            distances.extend(pair["distance_to_victim"].dropna().tolist())
    if not played:
        raise ValueError("These two players didn't share a team in any of these matches.")
    gaps = pd.Series(distances, dtype=float)
    duo = Duo(
        matches=played, rounds=together_rounds, win_rate=wins / together_rounds,
        solo_rounds=solo, solo_win_rate=solo_wins / solo if solo else None, you=you, them=them,
        median_distance=float(gaps.median()) if len(gaps) else None,
        close_share=float((gaps <= spacing.CLOSE_ENOUGH).mean()) if len(gaps) else None,
    )
    duo.notes = _notes(duo, name)
    return duo
