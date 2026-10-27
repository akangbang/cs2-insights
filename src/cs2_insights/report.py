"""Turn a parsed match into a player's economy report.

Each round's buy is compared with how often that buy-versus-buy matchup wins across every
match in the pool, every force-or-save decision is graded by simulating both choices
(see grade.py), and every death and teammate death is judged (see fights.py), so a player
sees which calls and which fights cost their team rounds.
"""

import re
from dataclasses import dataclass, field

import pandas as pd

from cs2_insights.demo import ParsedDemo
from cs2_insights import fights
from cs2_insights.fights import FightModel, coverage, coverage_summary, judge_deaths
from cs2_insights.grade import CLOSE, FORCE, GOOD_CALL, SHOULD_FORCE, SHOULD_SAVE, grade_decisions
from cs2_insights.rates import DEFAULT_EQUIPMENT_SLOPE, expected_win_rate, pooled_rates  # noqa: F401  (re-exported)

UPSET_BELOW = 0.40
FAVOURED_ABOVE = 0.60
# A split buy: at least one player bought a rifle-level loadout while two or more saved.
SPLIT_BUYER_MIN = 3_500
SPLIT_SAVER_MAX = 1_500
# Upset moments need this many pooled rounds behind the matchup, or they're mostly noise.
UPSET_MIN_SAMPLE = 20
# A wrong call or avoidable death is only worth a moment when it cost at least this many rounds.
COSTLY_CALL = 0.25
COSTLY_DEATH = 0.10
MOMENTS_BAD = 3
MOMENTS_MAX = 4

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
    deaths: pd.DataFrame = field(default_factory=pd.DataFrame)  # fights.judge_deaths() rows where you died
    coverage: pd.DataFrame = field(default_factory=pd.DataFrame)  # fights.coverage(): teammate deaths near you
    trade_chances: pd.DataFrame = field(default_factory=pd.DataFrame)  # where everyone stood at each death
    names: dict = field(default_factory=dict)  # steamid -> name, everyone in the match
    fight_model: FightModel = field(default_factory=FightModel)  # the models the fight numbers came from
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


def build_report(
    parsed: ParsedDemo, steamid: str, pool: pd.DataFrame, slope: float = DEFAULT_EQUIPMENT_SLOPE,
    fight_model: FightModel | None = None,
) -> Report:
    """Economy and fight report for `steamid` and the team they played on.

    `pool` comes from pooled_rates(); `slope` from rates.equipment_slope() and `fight_model`
    from fights.fit_fight_model() on the same pool.
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

    model = fight_model or FightModel()
    names = parsed.player_rounds.drop_duplicates("steamid", keep="last").set_index("steamid")["name"].to_dict()
    judged = judge_deaths(parsed.deaths, parsed.trade_chances, parsed.team_rounds, model) if len(parsed.deaths) else pd.DataFrame()
    my_deaths = judged[judged["victim"] == steamid].reset_index(drop=True) if len(judged) else judged
    cover = coverage(judged, parsed.trade_chances, steamid, model) if len(parsed.trade_chances) else pd.DataFrame()
    avoidable = my_deaths[my_deaths["label"].isin(fights.AVOIDABLE)] if len(my_deaths) else my_deaths
    summary.update(
        {
            "fights_parsed": bool(len(judged)),
            "deaths": len(my_deaths),
            "traded_deaths": int((my_deaths["label"] == fights.TRADED).sum()) if len(my_deaths) else 0,
            "avoidable_deaths": len(avoidable),
            "rounds_lost_to_avoidable": round(float(avoidable["cost"].sum()), 1) if len(avoidable) else 0.0,
            "coverage": coverage_summary(cover, model),
        }
    )

    return Report(
        summary=summary,
        rounds=rounds,
        buy_summary=buy_summary,
        players=_player_table(parsed.player_rounds, my_team, split),
        calls=calls,
        deaths=my_deaths,
        coverage=cover,
        trade_chances=parsed.trade_chances,
        names=names,
        fight_model=model,
        moments=_moments(rounds, calls, my_deaths, cover, names),
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


def place_label(place) -> str:
    """CS2 callout names ("TopofMid", "BombsiteA") as words ("Top of Mid", "Bombsite A")."""
    if not isinstance(place, str) or not place:
        return "somewhere"
    words = re.sub(r"of(?=[A-Z])", " of ", place)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", words).replace("  ", " ").strip()


def clock(seconds) -> str:
    """Time since the round went live, as m:ss."""
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


# What each verdict means in one line, and what to do next time.
DEATH_GROUPS = {
    fights.TRADED: "Traded",
    fights.REPEEK: "Avoidable",
    fights.SHOULD_SAVE: "Avoidable",
    fights.ALONE: "Avoidable",
    fights.NOT_TRADED: "Teammates didn't trade",
    fights.DUEL: "Lost a duel",
    fights.OTHER: "Other",
}
DEATH_FIXES = {
    fights.REPEEK: "After a kill, move: fall back or swing a different angle. The enemy now knows exactly where you are.",
    fights.ALONE: "Wait a second until a teammate is close enough to trade (under 900 units) before you clear the next angle.",
    fights.SHOULD_SAVE: "When the round is this lopsided, hide and keep the gun: it's money you start the next round with.",
    fights.NOT_TRADED: "Not on you. Call where you're fighting so teammates know to swing with you.",
}


def death_reasons(death: pd.Series, chances: pd.DataFrame, names: dict) -> list[str]:
    """The facts behind a death's verdict, each a short sentence with the numbers from the demo."""
    label = death["label"]
    reasons = []
    if label == fights.TRADED:
        reasons.append(f"{names.get(death['traded_by'], 'A teammate')} killed your killer {death['trade_seconds']:.1f}s later.")
        if death["moving"]:
            reasons.append("You were moving into the fight: an entry or angle clear that got traded is doing the job.")
        return reasons
    if label == fights.REPEEK:
        reasons.append(f"You got a kill from {place_label(death['victim_place'])} {death['repeek_gap']:.1f}s earlier.")
        reasons.append("You peeked the same spot again instead of moving, and the next enemy was ready for it.")
    elif label == fights.SHOULD_SAVE:
        planted = " with the bomb planted" if death["bomb_planted"] else ""
        reasons.append(f"It was {int(death['team_alive'])} vs {int(death['enemies_alive'])}{planted}: "
                       f"your team had a {death['win_before']:.0%} chance to win the round.")
        reasons.append(f"You were holding ${int(death['victim_equip']):,} of gear, lost with the fight.")
    elif label == fights.ALONE:
        reasons.append(f"You were moving at {death['victim_speed']:.0f} units/s: pushing or clearing an angle.")
        if pd.notna(death["closest_mate"]):
            reasons.append(f"Your nearest teammate was {death['closest_mate']:,.0f} units from your killer. "
                           f"Trades almost only happen within {fights.TRADE_RANGE:,}.")
        else:
            reasons.append("No teammate was anywhere near the fight.")
    mates = chances[(chances["tick"] == death["tick"]) & (chances["victim"] == death["victim"])] if len(chances) else chances
    if label in (fights.NOT_TRADED, fights.DUEL, fights.REPEEK) and len(mates):
        for mate in mates[mates["distance_to_killer"] <= fights.TRADE_RANGE].sort_values("distance_to_killer").itertuples():
            reasons.append(f"{names.get(mate.mate, 'A teammate')} was {mate.distance_to_killer:,.0f} units from your killer, "
                           f"aiming {mate.aim_angle:.0f}° away from him, and didn't trade.")
        if label == fights.DUEL and not (mates["distance_to_killer"] <= fights.TRADE_RANGE).any():
            if death["moving"]:
                reasons.append("You were moving into the fight and lost it; no teammate was close enough to trade.")
            elif death["side"] == "CT":
                reasons.append("You were holding an angle alone, which is normal on CT; nobody could have traded.")
            else:
                reasons.append("You were holding an angle with no teammate close enough to trade.")
    if death["victim_blind"]:
        reasons.append("You were flashed when you died.")
    return reasons


def pct(value: float) -> str:
    return "under 1%" if value < 0.005 else f"{value:.0%}"


def cover_reasons(row: pd.Series, names: dict) -> list[str]:
    """Where you stood and aimed when a teammate near you died, and what came of it."""
    distance, angle = row["distance_to_killer"], row["aim_angle"]
    near = "close enough to trade" if distance <= fights.TRADE_RANGE else f"too far: trades almost only happen within {fights.TRADE_RANGE:,}"
    aim = "on him" if angle <= 10 else "close to him" if angle <= fights.FACING_ANGLE else "looking somewhere else"
    reasons = [
        f"You were {distance:,.0f} units from the killer ({near}).",
        f"Your crosshair was {angle:.0f}° off the killer ({aim}).",
        f"From that spot and aim, players trade {pct(row['chance'])} of the time.",
    ]
    if row["verdict"] == fights.COVER_TRADED:
        reasons.append(f"You traded in {row['trade_seconds']:.1f}s.")
    elif row["verdict"] == fights.COVER_OTHER_TRADED:
        reasons.append(f"{names.get(row['traded_by'], 'A teammate')} traded in {row['trade_seconds']:.1f}s.")
    elif row["verdict"] == fights.COVER_FACING_AWAY:
        reasons.append(f"Facing the fight from where you stood would have made it {row['chance_if_facing']:.0%}.")
    return reasons


def match_story(report: "Report") -> str:
    """Two sentences: how the match went and the one thing to take from it."""
    s = report.summary
    over = s["your_score"] - s["expected_wins"]
    text = (f"**{s['result']} {s['your_score']}–{s['their_score']}** on {(s['map'] or '').removeprefix('de_').title()}, "
            f"{abs(over):.1f} rounds {'more' if over >= 0 else 'fewer'} than your team's buys usually win.")
    bad = [m for m in report.moments if m.kind == "bad"]
    good = [m for m in report.moments if m.kind == "good"]
    if bad:
        text += f" Biggest thing to fix: **{bad[0].title.split(': ', 1)[-1]}** (round {bad[0].round})."
    if s.get("coverage", {}).get("grade") in ("A", "B"):
        text += f" You covered your teammates well (grade {s['coverage']['grade']})."
    elif good:
        text += f" Best moment: **{good[0].title.split(': ', 1)[-1]}** (round {good[0].round})."
    return text


def death_detail(death: pd.Series, names: dict) -> str:
    """One of your deaths explained: what happened and what to do instead."""
    place = place_label(death["victim_place"])
    before, after = death["win_before"], death["win_before"] - death["cost"]
    swing = f"Your team's chance to win the round dropped from {before:.0%} to {after:.0%}."
    label = death["label"]
    if label == fights.TRADED:
        text = f"{names.get(death['traded_by'], 'A teammate')} traded you in {death['trade_seconds']:.1f}s."
        return text + (" You were pushing, so this was an entry or angle clear that did its job." if death["moving"] else "")
    if label == fights.REPEEK:
        return (f"You got a kill at {place}, peeked the same spot again and died. {swing} "
                "After a kill, reposition or fall back so a teammate can trade.")
    if label == fights.SHOULD_SAVE:
        return (f"Your team was at {before:.0%} to win when you died at {place} with ${death['victim_equip']:,} of gear. "
                "Hiding to save it keeps that money for next round.")
    if label == fights.ALONE:
        closest = death["closest_mate"]
        gap = f"the closest was {closest:,.0f} units from your killer" if pd.notna(closest) else "none were nearby"
        return (f"You were pushing at {place} and no teammate could trade: {gap} (trades are rare past "
                f"{fights.TRADE_RANGE:,}). {swing} Wait for a teammate to follow before you clear the next angle.")
    if label == fights.NOT_TRADED:
        n = int(death["mates_in_range"])
        return (f"{n} teammate{'s were' if n > 1 else ' was'} close enough to trade you at {place} but didn't within "
                f"{fights.TRADE_SECONDS} seconds. {swing}")
    return f"You lost a fight at {place}. {swing}"


def cover_detail(row: pd.Series, names: dict) -> str:
    """A teammate death near you explained from your side: where you were and where you aimed."""
    mate = names.get(row["victim"], "A teammate")
    text = f"{mate} died at {place_label(row['victim_place'])}. You were {row['distance_to_killer']:,.0f} units from the killer"
    if row["verdict"] == fights.COVER_FACING_AWAY:
        return (f"{text} but aiming {row['aim_angle']:.0f}° away from him. Facing the fight would have given you a "
                f"{row['chance_if_facing']:.0%} chance to trade instead of {row['chance']:.0%}. When a teammate takes a "
                "fight near you, aim where his killer will be.")
    if row["verdict"] == fights.COVER_TRADED:
        return f"{text} and traded in {row['trade_seconds']:.1f}s."
    if row["verdict"] == fights.COVER_SET_UP:
        return f"{text}, aiming {row['aim_angle']:.0f}° off: set up to trade ({row['chance']:.0%} chance), but no kill."
    return f"{text}: too far to trade (trades are rare past {fights.TRADE_RANGE:,})."


def _moments(rounds: pd.DataFrame, calls: pd.DataFrame, deaths: pd.DataFrame | None = None,
             cover: pd.DataFrame | None = None, names: dict | None = None) -> list[Moment]:
    """The few moments worth talking about: the costliest mistakes first, then what went well."""
    names = names or {}
    label = BUY_LABELS.get
    bad = []  # (cost, Moment)

    wrong = calls[calls["grade"].isin([SHOULD_FORCE, SHOULD_SAVE]) & (calls["cost"] >= COSTLY_CALL)]
    for call in wrong.itertuples(index=False):
        call = pd.Series(call._asdict())
        bad.append((call["cost"], Moment(int(call["round"]), "bad", f"Round {call['round']}: {call['grade'].lower()}",
                                         call_detail(call) + f" Cost: about {call['cost']:.1f} rounds.")))
    if deaths is not None and len(deaths):
        for _, death in deaths[deaths["label"].isin(fights.AVOIDABLE) & (deaths["cost"] >= COSTLY_DEATH)].iterrows():
            bad.append((death["cost"], Moment(int(death["round"]), "bad",
                                              f"Round {death['round']}, {clock(death['round_seconds'])}: {death['label'].lower()}",
                                              death_detail(death, names))))
    if cover is not None and len(cover):
        for _, row in cover[cover["lost"] >= COSTLY_DEATH / 2].iterrows():
            bad.append((row["lost"], Moment(int(row["round"]), "bad",
                                            f"Round {row['round']}, {clock(row['round_seconds'])}: facing away when {names.get(row['victim'], 'a teammate')} died",
                                            cover_detail(row, names))))
    moments = [m for _, m in sorted(bad, key=lambda pair: pair[0], reverse=True)[:MOMENTS_BAD]]

    good = calls[calls["grade"] == GOOD_CALL]
    if len(good):
        edge = (good["force_wins"] - good["save_wins"]).abs()
        call = good.loc[edge.idxmax()]
        moments.append(Moment(int(call["round"]), "good", f"Round {call['round']}: right call to {call['made']}", call_detail(call)))
    if cover is not None and len(cover) and (cover["verdict"] == fights.COVER_TRADED).any():
        row = cover[cover["verdict"] == fights.COVER_TRADED].sort_values("trade_seconds").iloc[0]
        moments.append(Moment(int(row["round"]), "good", f"Round {row['round']}, {clock(row['round_seconds'])}: you traded {names.get(row['victim'], 'a teammate')}",
                              cover_detail(row, names)))

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
    return moments[:MOMENTS_MAX]
