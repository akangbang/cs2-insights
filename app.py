"""Halftime: upload a CS2 demo, get an economy report.

Run with: streamlit run app.py
"""

import dataclasses
import hashlib
import os
import tempfile
from datetime import datetime
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from cs2_insights import db
from cs2_insights.demo import ParsedDemo, parse_demo
from cs2_insights import fights
from cs2_insights.demo import TICK_RATE
from cs2_insights.fights import FightModel, fit_fight_model, opening_duels
from cs2_insights.grade import CLOSE, GOOD_CALL, SHOULD_FORCE, SHOULD_SAVE
from cs2_insights.habits import MIN_MATCHES, build_habits, checklist
from cs2_insights.ingest import DEMO_SUFFIXES, ingest, plain_demo
from cs2_insights.progress import FOCUS, RECENT_MATCHES, history, match_numbers
from cs2_insights.rates import equipment_slope
from cs2_insights.utility import UNUSED_WORTH_MENTION
from cs2_insights.report import (
    CLUTCH_FIXES,
    clutch_reasons,
    BUY_LABELS,
    DEATH_FIXES,
    DEATH_GROUPS,
    Report,
    build_report,
    call_detail,
    clock,
    cover_reasons,
    death_reasons,
    match_story,
    place_label,
    players_in,
    pooled_rates,
)

ROOT = Path(__file__).resolve().parent
REPLAYS = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\replays")
# Screenshot mode for the README: show stand-in names instead of real players' Steam names.
HIDE_NAMES = os.getenv("HALFTIME_HIDE_NAMES") == "1"
WATCH_LEAD_SECONDS = 5  # "watch" jumps to a few seconds before the moment
DISCLAIMER = (
    "Halftime is not affiliated with or endorsed by Valve Corporation. "
    "Counter-Strike and CS2 are trademarks of Valve Corporation."
)

# Validated with the dataviz palette checker (light and dark): team = slot 1 blue, opponent = slot 2 orange.
# Status colours (good / serious / critical) always come with an icon or label; neutral is for "not yours".
COLORS = {
    "light": {
        "Your team": "#2a78d6", "Opponent": "#eb6834", "good": "#0ca30c", "serious": "#ec835a", "critical": "#d03b3b",
        "aqua": "#1baf7a", "neutral": "#8a8984", "band": "#e4e3df", "text": "#0b0b0b", "on_fill": "#0b0b0b", "surface": "#ffffff",
    },
    "dark": {
        "Your team": "#3987e5", "Opponent": "#d95926", "good": "#0ca30c", "serious": "#ec835a", "critical": "#d03b3b",
        "aqua": "#199e70", "neutral": "#8a8984", "band": "#383835", "text": "#f0efec", "on_fill": "#0b0b0b", "surface": "#0e1117",
    },
}
DEATH_GROUP_ORDER = ["Traded", "Avoidable", "Teammates didn't trade", "Lost a duel"]


def map_label(name: str | None) -> str:
    return (name or "Unknown map").removeprefix("de_").replace("_", " ").title()


# ---------- data loading ----------


@st.cache_resource(show_spinner=False)
def database():
    """A shared connection, or None when PostgreSQL isn't running (the app still works)."""
    try:
        conn = db.connect()
        db.init_schema(conn)
        return conn
    except Exception:
        return None


@st.cache_data(show_spinner="Parsing demo…", max_entries=8)
def parse_cached(path: str, cache_key: str) -> ParsedDemo:
    """cache_key changes when the file does, so edits are re-parsed."""
    with plain_demo(Path(path)) as demo:
        return parse_demo(demo, match_id=_match_id_for(Path(path), cache_key))


def _match_id_for(path: Path, cache_key: str) -> str | None:
    # Valve file names carry the match ID; anything else gets a stable ID from its contents.
    return None if path.name.startswith("match730_") else f"upload_{cache_key[:16]}"


def parse_upload(upload) -> ParsedDemo:
    data = upload.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / upload.name
        path.write_bytes(data)
        return parse_cached(str(path), digest)


def save_and_pool(parsed: ParsedDemo) -> tuple[pd.DataFrame, float, FightModel]:
    """Store the match (so it joins the pool); return pooled win rates, the equipment slope and
    the fight model, all from every other match."""
    conn = database()
    if conn is None:
        return pooled_rates(parsed.team_rounds), equipment_slope(parsed.team_rounds), FightModel()
    try:
        db.load_parsed(conn, parsed)
        match_id = parsed.match.iloc[0]["match_id"]
        pool = db.pool_team_rounds(conn, exclude_match_id=match_id)
        fight_pool = db.pool_fights(conn, exclude_match_id=match_id)
        conn.commit()  # end the read transaction so this long-lived connection never holds locks
        return pooled_rates(pool), equipment_slope(pool), fit_fight_model(*fight_pool)
    except Exception:
        conn.rollback()
        return pooled_rates(parsed.team_rounds), equipment_slope(parsed.team_rounds), FightModel()


def hide_names(parsed: ParsedDemo) -> ParsedDemo:
    """In screenshot mode, replace each player's name with a stand-in that stays the same across matches."""
    if not HIDE_NAMES:
        return parsed
    stand_in = parsed.player_rounds["steamid"].map(lambda sid: f"Player {int(hashlib.sha1(sid.encode()).hexdigest(), 16) % 900 + 100}")
    return dataclasses.replace(parsed, player_rounds=parsed.player_rounds.assign(name=stand_in))


def replay_demos(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.dem"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []


def add_all_replays(demos: list[Path]) -> int:
    """Load every replay that isn't stored yet, so habits and win rates use all of them."""
    conn = database()
    added = 0
    progress = st.progress(0.0, text="Adding replays…")
    for i, path in enumerate(demos, start=1):
        try:
            added += ingest(path, conn).startswith("loaded")
        except Exception:
            conn.rollback()
        progress.progress(i / len(demos), text=f"Adding replays… {i}/{len(demos)}")
    progress.empty()
    return added


# ---------- report rendering ----------


def economy_chart(report: Report, mode: str) -> alt.Chart:
    palette = COLORS[mode]
    rounds = report.rounds
    long = pd.concat(
        [
            rounds.assign(team="Your team", equip=rounds["your_equip"]),
            rounds.assign(team="Opponent", equip=rounds["their_equip"]),
        ]
    )
    long["Your buy"] = long["your_buy"].map(BUY_LABELS)
    long["Their buy"] = long["their_buy"].map(BUY_LABELS)
    long["Result"] = long["won"].map({True: "Won", False: "Lost"})
    long["Matchup win rate"] = long["expected"]
    tooltip = [
        alt.Tooltip("round:O", title="Round"),
        alt.Tooltip("team:N", title="Team"),
        alt.Tooltip("equip:Q", title="Equipment", format="$,.0f"),
        "Your buy:N",
        "Their buy:N",
        alt.Tooltip("Matchup win rate:Q", format=".0%"),
        "Result:N",
        alt.Tooltip("verdict:N", title="Verdict"),
    ]
    color = alt.Color(
        "team:N",
        scale=alt.Scale(domain=["Your team", "Opponent"], range=[palette["Your team"], palette["Opponent"]]),
        legend=alt.Legend(title=None, orient="top"),
    )
    x = alt.X("round:O", title="Round", axis=alt.Axis(labelAngle=0))
    base = alt.Chart(long).encode(x=x, y=alt.Y("equip:Q", title="Team equipment value ($)", axis=alt.Axis(format="$,.0f")), color=color)
    lines = base.mark_line(strokeWidth=2)
    points = base.mark_point(size=70, filled=True, stroke=palette["surface"], strokeWidth=2).encode(tooltip=tooltip)

    result = rounds.assign(Result=rounds["won"].map({True: "W", False: "L"}))
    strip = (
        alt.Chart(result)
        .mark_text(fontSize=13, fontWeight="bold")
        .encode(
            x=alt.X("round:O", title=None, axis=alt.Axis(labels=False, ticks=False, domain=False)),
            text="Result:N",
            color=alt.Color(
                "Result:N",
                scale=alt.Scale(domain=["W", "L"], range=[palette["good"], palette["critical"]]),
                legend=None,
            ),
            tooltip=[alt.Tooltip("round:O", title="Round"), alt.Tooltip("verdict:N", title="Verdict")],
        )
        .properties(height=24)
    )
    return alt.vconcat((lines + points).properties(height=320), strip, spacing=4).resolve_scale(color="independent")


def render_report(report: Report, past: pd.DataFrame | None = None, current: dict | None = None) -> None:
    s = report.summary
    mode = theme_mode()
    past = past if past is not None else pd.DataFrame()

    st.header(f"{map_label(s['map'])} · {s['result']} {s['your_score']}–{s['their_score']}")
    st.caption(f"Reviewing **{s['name']}** · {s['rounds']} rounds")
    st.markdown(match_story(report))
    if current:
        render_focus_banner(current, past, current["match_id"])
    render_scorecards(report, past, current["match_id"] if current else None)
    render_timeline(report, mode)

    st.subheader("Top moments")
    if not report.moments:
        st.write("A clean game: no costly calls, avoidable deaths or big swings.")
    for moment in report.moments:
        icon = "✅" if moment.kind == "good" else "⚠️"
        with st.container(border=True):
            st.markdown(f"{icon} **{moment.title}**  \n{moment.detail}")

    # Three groups, each with its own sub-tabs, so the page doesn't open on a wall of six choices.
    fights_tab, teamplay_tab, economy_tab = st.tabs(["⚔️ Fights", "🤝 Teamplay", "💰 Economy"])
    with fights_tab:
        deaths_tab, clutch_tab = st.tabs(["💀 Your deaths", "🎯 Clutches & openings"])
        with deaths_tab:
            render_deaths(report, mode)
        with clutch_tab:
            render_clutches(report)
    with teamplay_tab:
        cover_tab, utility_tab = st.tabs(["🤝 Covering teammates", "🧨 Utility"])
        with cover_tab:
            render_coverage(report, mode)
        with utility_tab:
            render_utility(report, mode)
    with economy_tab:
        calls_tab, rounds_tab = st.tabs(["💰 Buy calls", "📈 Round by round"])
        with calls_tab:
            render_buy_calls(report)
        with rounds_tab:
            render_economy(report, mode)
    st.caption(
        f"Win chances come from Halftime's pool of {s['pool_rounds']:,} rounds. Buy calls are graded by playing both "
        "choices forward a few rounds with CS2's money rules; deaths and coverage from where everyone stood and aimed. "
        "Early beta: the pool is still small, so treat the numbers as a guide."
    )


TIMELINE_PRIORITY = ["⚠️", "💰", "🏆", "💀"]


def timeline_data(report: Report) -> pd.DataFrame:
    """One row per round: result plus icons for what happened to you in it."""
    deaths = report.deaths
    avoidable = set(deaths.loc[deaths["label"].isin(fights.AVOIDABLE), "round"]) if len(deaths) else set()
    died = set(deaths["round"]) if len(deaths) else set()
    calls = report.calls
    wrong = set(calls.loc[calls["grade"].isin([SHOULD_FORCE, SHOULD_SAVE]), "round"]) if len(calls) else set()
    clutches_won = set(report.clutches.loc[report.clutches["outcome"] == "Won", "round"]) if len(report.clutches) else set()
    rows = []
    for r in report.rounds.itertuples():
        icons, notes = [], []
        if r.round in avoidable:
            icons.append("⚠️")
            notes.append(deaths.loc[(deaths["round"] == r.round) & deaths["label"].isin(fights.AVOIDABLE), "label"].iat[0])
        elif r.round in died:
            icons.append("💀")
            notes.append(deaths.loc[deaths["round"] == r.round, "label"].iat[0])
        if r.round in wrong:
            icons.append("💰")
            notes.append(calls.loc[calls["round"] == r.round, "grade"].iat[0])
        if r.round in clutches_won:
            icons.append("🏆")
            notes.append("Won a clutch")
        # One icon per tile so they fit on a phone; the tooltip lists everything.
        icon = min(icons, key=TIMELINE_PRIORITY.index) if icons else ""
        rows.append({"round": int(r.round), "result": "Won" if r.won else "Lost", "icons": icon,
                     "notes": "; ".join(notes) or "Nothing to flag"})
    return pd.DataFrame(rows)


def timeline_chart(data: pd.DataFrame, mode: str) -> alt.Chart:
    """One row of tiles per half (12 rounds, then overtime) so tiles stay wide enough on a phone."""
    palette = COLORS[mode]
    data = data.assign(
        half=[("1st half" if r <= 12 else "2nd half" if r <= 24 else "Overtime") for r in data["round"]],
        slot=[(r - 1) % 12 + 1 if r <= 24 else r - 24 for r in data["round"]],
    )
    halves = [h for h in ("1st half", "2nd half", "Overtime") if h in set(data["half"])]
    pick = alt.selection_point(name="pick", fields=["round"], on="click", empty=False)
    x = alt.X("slot:O", title=None, axis=None, scale=alt.Scale(domain=list(range(1, 13))))
    y = alt.Y("half:N", title=None, sort=halves, axis=alt.Axis(ticks=False, domain=False, labelPadding=6))
    tiles = alt.Chart(data).mark_rect(stroke=palette["surface"], strokeWidth=2, cornerRadius=4, cursor="pointer").encode(
        x=x, y=y,
        color=alt.Color("result:N", title=None, scale=alt.Scale(domain=["Won", "Lost"], range=[palette["good"], palette["critical"]]),
                        legend=None),  # explained in the caption
        opacity=alt.condition(pick, alt.value(1.0), alt.value(0.8)),
        tooltip=[alt.Tooltip("round:O", title="Round"), alt.Tooltip("result:N", title="Result"), alt.Tooltip("notes:N", title="What happened")],
    ).add_params(pick)
    icons = alt.Chart(data).mark_text(fontSize=14, baseline="middle", dy=-5).encode(x=x, y=y, text="icons:N")
    numbers = alt.Chart(data).mark_text(fontSize=9, baseline="middle", dy=11, color=palette["on_fill"]).encode(x=x, y=y, text="round:O")
    return alt.layer(tiles, icons, numbers).properties(height=alt.Step(40))


def render_timeline(report: Report, mode: str) -> None:
    data = timeline_data(report)
    st.markdown("#### Round by round")
    event = st.altair_chart(timeline_chart(data, mode), width="stretch", on_select="rerun", key="timeline")
    st.caption("Green = round won, red = round lost · ⚠️ avoidable death · 💰 wrong buy call · 🏆 clutch won · 💀 other death "
               "(the most important one shows; hover for all). Click a round to see what happened.")
    picked = (event.selection.get("pick") or [{}])[0].get("round") if event and event.selection else None
    if picked is not None:
        render_round(report, int(picked))


def render_round(report: Report, number: int) -> None:
    """Everything that happened to you in one round, in one card."""
    r = report.rounds.set_index("round").loc[number]
    with st.container(border=True):
        st.markdown(f"**Round {number} · {'✅ Won' if r['won'] else '❌ Lost'}** · score before {r['score']} · {r['side']} · "
                    f"your {BUY_LABELS[r['your_buy']].lower()} (\\${r['your_equip']:,}) vs their {BUY_LABELS[r['their_buy']].lower()} (\\${r['their_equip']:,})")
        # (Two "$" in one markdown line would render as a maths formula, hence the escapes.)
        calls = report.calls[report.calls["round"] == number] if len(report.calls) else report.calls
        for _, call in calls.iterrows():
            st.markdown(f"💰 **Buy call: {call['grade']}.** {call_detail(call)}")
        openings = report.openings[report.openings["round"] == number] if len(report.openings) else report.openings
        for o in openings.itertuples():
            st.markdown(f"🚪 **Opening duel {'won' if o.won else 'lost'}** at {place_label(o.place)} ({o.weapon}).")
        flashes = report.team_flashes[report.team_flashes["round"] == number] if len(report.team_flashes) else report.team_flashes
        for f in flashes.itertuples():
            st.markdown(f"🧨 Your flash blinded **{report.names.get(f.blinded, 'a teammate')}** for {f.seconds:.1f}s.")
        clutch = report.clutches[report.clutches["round"] == number] if len(report.clutches) else report.clutches
        for _, c in clutch.iterrows():
            st.markdown(f"{CLUTCH_ICONS[c['verdict']]} **1v{int(c['enemies'])}: {c['verdict']}.** " + " ".join(clutch_reasons(c)))
        deaths = report.deaths[report.deaths["round"] == number] if len(report.deaths) else report.deaths
        if deaths.empty:
            st.markdown("🛡️ You survived the round.")
        for _, death in deaths.iterrows():
            death_card(death, report)


def theme_mode() -> str:
    return "dark" if getattr(st.context.theme, "type", "light") == "dark" else "light"


def render_scorecards(report: Report, past: pd.DataFrame, match_id: str | None) -> None:
    """Four headline numbers; the arrows compare with your own last few matches."""
    s = report.summary
    over = s["your_score"] - s["expected_wins"]
    others = past[past["match_id"] != match_id].tail(RECENT_MATCHES) if len(past) else past
    average = others.mean(numeric_only=True) if len(others) else pd.Series(dtype=float)
    vs = f"vs your last {len(others)}"

    def change(value, column, scale=1.0, unit=""):
        if column not in average or pd.isna(average[column]) or value is None:
            return None
        return f"{(value - average[column]) * scale:+.1f}{unit} {vs}"

    cards = st.columns(4)
    with cards[0].container(border=True):
        st.metric("Rounds won", s["your_score"], f"{over:+.1f} vs your buys", delta_color="normal")
        st.caption(f"Your team's buys usually win about {s['expected_wins']:.0f} of these {s['rounds']} rounds.")
    with cards[1].container(border=True):
        if s.get("fights_parsed"):
            st.metric("Avoidable deaths", f"{s['avoidable_deaths']} of {s['deaths']}", change(s["avoidable_deaths"], "avoidable"),
                      delta_color="inverse",
                      help="Deaths a different decision would likely have prevented. The Your deaths tab shows why for each one.")
            kinds = report.deaths[report.deaths["label"].isin(fights.AVOIDABLE)]["label"].value_counts()
            st.caption(" · ".join(f"{n} {SHORT_LABELS[label]}" for label, n in kinds.items()) or "None. Clean fights.")
        else:
            st.metric("Avoidable deaths", "–")
            st.caption("Re-add this demo to see your deaths.")
    with cards[2].container(border=True):
        c = s.get("coverage") or {}
        rate = c["set_up"] / c["chances"] if c.get("chances") else None
        st.metric("Coverage", c.get("grade") or "–", change(rate, "set_up_rate", 100, " pts in position"),
                  help="How often you were in position to trade teammates who died near you. The Covering teammates tab shows how it's worked out.")
        st.caption(f"In position to trade {c.get('set_up', 0)} of {c.get('chances', 0)} times · traded {c.get('trades', 0)}"
                   if c.get("chances") else "No teammate died near you.")
    with cards[3].container(border=True):
        st.metric("Buy calls right", f"{s['calls_right']} of {s['calls']}", change(s["calls_wrong"], "wrong_calls", unit=" wrong"),
                  delta_color="inverse",
                  help="Rounds your team could force or save, where Halftime's simulation agrees with what you did.")
        st.caption(f"Wrong calls cost about {s['rounds_lost_to_calls']:.1f} rounds." if s["calls_wrong"] else "No costly calls.")


SHORT_LABELS = {fights.REPEEK: "re-peek", fights.ALONE: "pushed alone", fights.SHOULD_SAVE: "lost gear in a lost round"}
DEATH_ICONS = {"Traded": "✅", "Avoidable": "⚠️", "Teammates didn't trade": "🤝", "Lost a duel": "⚔️", "Other": "•"}


def watch_command(tick: int) -> str:
    return f"demo_gototick {max(int(tick) - WATCH_LEAD_SECONDS * TICK_RATE, 0)}"


WATCH_HELP = "Open the demo in CS2, then paste this into the console (~) to jump to 5 seconds before the moment."


def watch_hint(tick: int) -> None:
    """One compact row: a label with the how-to on hover, and the command with a copy button."""
    label, command = st.columns([1, 3], vertical_alignment="center")
    label.caption("▶ Watch in CS2", help=WATCH_HELP)
    command.code(watch_command(tick), language=None)


def death_breakdown_chart(deaths: pd.DataFrame, mode: str) -> alt.Chart:
    palette = COLORS[mode]
    groups = deaths["label"].map(DEATH_GROUPS)
    counts = groups[groups != "Other"].value_counts().reindex(DEATH_GROUP_ORDER).fillna(0).astype(int).reset_index()
    counts.columns = ["group", "deaths"]
    counts["label"] = [f"{g} · {n}" for g, n in zip(counts["group"], counts["deaths"])]
    counts["order"] = range(len(counts))
    colors = [palette["good"], palette["critical"], palette["serious"], palette["neutral"]]
    color = alt.Color("label:N", title=None,
                      scale=alt.Scale(domain=counts["label"].tolist(), range=colors),
                      legend=alt.Legend(orient="top", direction="horizontal", symbolSize=160, labelFontSize=13))
    bars = (
        alt.Chart(counts[counts["deaths"] > 0])
        .mark_bar(height=34, stroke=palette["surface"], strokeWidth=2, cornerRadius=4)
        .encode(
            x=alt.X("deaths:Q", stack="zero", axis=None), order="order:Q", color=color,
            tooltip=[alt.Tooltip("group:N", title="Verdict"), alt.Tooltip("deaths:Q", title="Deaths")],
        )
    )
    # Streamlit drops a lone stacked bar with no y; as a one-layer chart it renders.
    return alt.layer(bars).properties(height=70)


def render_deaths(report: Report, mode: str) -> None:
    deaths = report.deaths
    if not report.summary.get("fights_parsed"):
        st.info("This demo was stored before deaths were tracked. Re-add it (Your habits → Add all replays) to see them.")
        return
    if deaths.empty:
        st.success("You didn't die once. Nothing to review here.")
        return
    st.altair_chart(death_breakdown_chart(deaths, mode), width="stretch")
    st.markdown(
        "**Avoidable** means a different decision would likely have saved you: peeking a spot again right after a "
        "kill, pushing with no teammate close enough to trade, or fighting for a round that was already lost while "
        "holding expensive gear. A death that gets **traded** within 2 seconds is fine, even as the first one in."
    )
    groups = deaths["label"].map(DEATH_GROUPS)
    avoidable = deaths[groups == "Avoidable"].sort_values("cost", ascending=False)
    for _, death in avoidable.iterrows():
        death_card(death, report)
    others = deaths[groups != "Avoidable"].sort_values("tick")
    if len(others):
        with st.expander(f"Your other {len(others)} deaths: traded, not your call, or a fair fight"):
            for _, death in others.iterrows():
                death_card(death, report)


def death_card(death: pd.Series, report: Report) -> None:
    group = DEATH_GROUPS.get(death["label"], "Other")
    before, after = death["win_before"], death["win_before"] - death["cost"]
    with st.container(border=True):
        text, picture = st.columns([3, 2])
        with text:
            st.markdown(f"{DEATH_ICONS[group]} **Round {death['round']} · {clock(death['round_seconds'])} · "
                        f"{place_label(death['victim_place'])}** — {death['label']}")
            reasons = death_reasons(death, report.trade_chances, report.names)
            if reasons:
                st.markdown("\n".join(f"- {reason}" for reason in reasons))
            if group != "Traded":
                st.markdown(f"**Impact:** your team's chance to win the round went from **{before:.0%} → {after:.0%}**.")
            if death["label"] in DEATH_FIXES:
                st.markdown(f"**Next time:** {DEATH_FIXES[death['label']]}")
            watch_hint(death["tick"])
        with picture:
            render_moment_map(death, report)


COVER_GROUPS = ["You traded", "In position", "Facing away", "Too far"]


def cover_group(row: pd.Series) -> str:
    if row["verdict"] == fights.COVER_TRADED:
        return "You traded"
    if row["distance_to_killer"] > fights.TRADE_RANGE:
        return "Too far"
    return "In position" if row["aim_angle"] <= fights.FACING_ANGLE else "Facing away"


def coverage_chart(cover: pd.DataFrame, names: dict, mode: str) -> alt.Chart:
    """Every teammate death near you: your distance to the killer against how far off your aim was."""
    palette = COLORS[mode]
    max_x = 2_500
    dots = pd.DataFrame(
        {
            "distance": cover["distance_to_killer"].clip(upper=max_x),
            "aim": cover["aim_angle"],
            "group": cover.apply(cover_group, axis=1),
            "round": cover["round"],
            "time": cover["round_seconds"].map(clock),
            "teammate": cover["victim"].map(lambda v: names.get(v, "")),
            "where": cover["victim_place"].map(place_label),
            "chance": cover["chance"],
            "verdict": cover["verdict"],
        }
    )
    x = alt.X("distance:Q", title="Your distance to the killer (units)", scale=alt.Scale(domain=[0, max_x]))
    y_scale = alt.Scale(domain=[0, 180], type="sqrt")
    y = alt.Y("aim:Q", title="How far your aim was off the killer (°)", scale=y_scale, axis=alt.Axis(values=[0, 10, 35, 90, 180]))
    zone = alt.Chart(pd.DataFrame({"x": [0], "x2": [fights.TRADE_RANGE], "y": [0], "y2": [fights.FACING_ANGLE]})).mark_rect(
        color=palette["good"], opacity=0.14, stroke=palette["good"], strokeDash=[4, 3], strokeWidth=1.5
    ).encode(x=alt.X("x:Q", scale=alt.Scale(domain=[0, max_x])), x2="x2:Q", y=alt.Y("y:Q", scale=y_scale), y2="y2:Q")
    zone_label = alt.Chart(pd.DataFrame({"x": [10], "y": [2]})).mark_text(
        text="Trade zone", align="left", baseline="bottom", fontWeight="bold", fontSize=12, color=palette["good"]
    ).encode(x=alt.X("x:Q", scale=alt.Scale(domain=[0, max_x])), y=alt.Y("y:Q", scale=y_scale))
    points = alt.Chart(dots).mark_point(size=170, filled=True, opacity=0.9, stroke=palette["surface"], strokeWidth=1.5).encode(
        x=x, y=y,
        color=alt.Color("group:N", title=None, scale=alt.Scale(
            domain=COVER_GROUPS, range=[palette["good"], palette["Your team"], palette["critical"], palette["neutral"]]),
            legend=alt.Legend(orient="top", direction="horizontal")),
        shape=alt.Shape("group:N", title=None, scale=alt.Scale(domain=COVER_GROUPS, range=["circle", "triangle-up", "diamond", "square"])),
        tooltip=[
            alt.Tooltip("round:O", title="Round"), alt.Tooltip("time:N", title="Time"),
            alt.Tooltip("teammate:N", title="Teammate who died"), alt.Tooltip("where:N", title="Where"),
            alt.Tooltip("distance:Q", title="Your distance", format=",.0f"), alt.Tooltip("aim:Q", title="Aim off (°)", format=".0f"),
            alt.Tooltip("chance:Q", title="Trade chance", format=".0%"), alt.Tooltip("verdict:N", title="Verdict"),
        ],
    )
    return (zone + zone_label + points).properties(height=340)


def grade_scale_chart(score: float, grade: str, cuts: tuple, mode: str) -> alt.Chart:
    """The five grade bands with your score marked, so a letter grade shows how close the next one is."""
    palette = COLORS[mode]
    top = max(cuts[-1] * 1.5, score * 1.15)
    edges = [0.0, *cuts, top]
    bands = pd.DataFrame({"grade": list(fights.GRADES), "start": edges[:-1], "end": edges[1:]})
    bands["mid"] = (bands["start"] + bands["end"]) / 2
    bands["yours"] = bands["grade"] == grade
    x_scale = alt.Scale(domain=[0, top])
    rects = alt.Chart(bands).mark_rect(stroke=palette["surface"], strokeWidth=2, cornerRadius=4).encode(
        x=alt.X("start:Q", scale=x_scale, axis=None), x2="end:Q", y=alt.value(24), y2=alt.value(58),
        color=alt.Color("yours:N", scale=alt.Scale(domain=[True, False], range=[palette["Your team"], palette["band"]]), legend=None),
        tooltip=[alt.Tooltip("grade:N", title="Grade"), alt.Tooltip("start:Q", title="From", format=".1%"), alt.Tooltip("end:Q", title="To", format=".1%")],
    )
    letters = alt.Chart(bands).mark_text(fontWeight="bold", fontSize=14, color=palette["text"]).encode(
        x=alt.X("mid:Q", scale=x_scale), y=alt.value(41), text="grade:N")
    marker = alt.Chart(pd.DataFrame({"score": [score], "label": [f"You: {score:.1%}"]}))
    rule = marker.mark_rule(color=palette["text"], strokeWidth=2).encode(x=alt.X("score:Q", scale=x_scale), y=alt.value(18), y2=alt.value(62))
    you = marker.mark_text(fontWeight="bold", color=palette["text"], baseline="bottom").encode(
        x=alt.X("score:Q", scale=x_scale), y=alt.value(15), text="label:N")
    return (rects + letters + rule + you).properties(height=64)


def render_coverage(report: Report, mode: str) -> None:
    c = report.summary.get("coverage") or {}
    cover, names = report.coverage, report.names
    if not report.summary.get("fights_parsed"):
        st.info("This demo was stored before positions were tracked. Re-add it (Your habits → Add all replays) to see coverage.")
        return
    if not c.get("chances"):
        st.write("No teammate died near you this match, so there's nothing to grade.")
        return

    left, right = st.columns([1, 2])
    with left:
        st.metric("Coverage grade", c["grade"] or "–")
        cuts = report.fight_model.setup_cuts
        st.caption(f"Each time a teammate died near you, you had on average a **{c['score']:.1%}** chance to trade him, "
                   f"from where you stood and aimed. The middle of the pool is about {(cuts[1] + cuts[2]) / 2:.1%}.")
    with right:
        if c["grade"]:
            st.altair_chart(grade_scale_chart(c["score"], c["grade"], report.fight_model.setup_cuts, mode), width="stretch")
        st.markdown(
            "**How it's graded.** For every teammate who died within 1,600 units of you, Halftime checks two things "
            f"at the moment he died: how far you were from his killer, and how far your crosshair was from the killer. "
            f"Players trade 40%+ of the time when close and aiming at the killer, and almost never when over "
            f"{fights.TRADE_RANGE:,} units away or facing elsewhere."
        )

    st.markdown("#### Every teammate death near you")
    st.altair_chart(coverage_chart(cover, names, mode), width="stretch")
    counts = cover.apply(cover_group, axis=1).value_counts()
    icons = {"You traded": "✅", "In position": "🎯", "Facing away": "⚠️", "Too far": "📏"}
    st.markdown(" · ".join(f"{icons[g]} **{counts.get(g, 0)}** {g.lower()}" for g in COVER_GROUPS))
    st.caption("Each dot is one teammate death. Dots in the green box are where trades happen; the further a dot sits "
               "from it, the less chance you had.")

    good_col, bad_col = st.columns(2)
    with good_col:
        st.markdown("#### ✅ Repeat this")
        good = cover[cover["verdict"] == fights.COVER_TRADED].sort_values("trade_seconds")
        if good.empty:
            good = cover[cover.apply(cover_group, axis=1) == "In position"].sort_values("chance", ascending=False)
        if good.empty:
            st.write("No trades or set-ups this match.")
        for _, row in good.head(2).iterrows():
            cover_card(row, report)
    with bad_col:
        st.markdown("#### ⚠️ Fix this")
        bad = cover[cover["verdict"] == fights.COVER_FACING_AWAY].sort_values("lost", ascending=False)
        far = cover[cover["verdict"] == fights.COVER_TOO_FAR].sort_values("cost", ascending=False)
        if bad.empty and far.empty:
            st.write("Nothing to fix: you were in position every time.")
        for _, row in pd.concat([bad.head(2), far.head(2 - min(len(bad), 2))]).iterrows():
            cover_card(row, report)
        if len(far):
            st.caption(f"You were too far to trade {len(far)} times (on average {far['distance_to_killer'].mean():,.0f} units "
                       f"from the killer). Playing within {fights.TRADE_RANGE:,} units of a teammate lets you trade him.")

    with st.expander("Full table"):
        st.dataframe(
            pd.DataFrame({
                "round": cover["round"], "time": cover["round_seconds"].map(clock),
                "teammate": cover["victim"].map(lambda v: names.get(v, "")), "where": cover["victim_place"].map(place_label),
                "distance": cover["distance_to_killer"].round(), "aim": cover["aim_angle"].round(),
                "chance": (cover["chance"] * 100).round(), "verdict": cover["verdict"], "watch": cover["tick"].map(watch_command),
            }),
            hide_index=True, width="stretch",
            column_config={
                "round": "Round", "time": "Time", "teammate": "Teammate who died", "where": "Where",
                "distance": st.column_config.NumberColumn("Your distance to killer", format="%d"),
                "aim": st.column_config.NumberColumn("Your aim off", format="%d°"),
                "chance": st.column_config.NumberColumn("Trade chance", format="%d%%"), "verdict": "Verdict", "watch": "Watch",
            },
        )


def cover_card(row: pd.Series, report: Report) -> None:
    names = report.names
    icon = "✅" if row["verdict"] in (fights.COVER_TRADED, fights.COVER_SET_UP) else "⚠️"
    with st.container(border=True):
        st.markdown(f"{icon} **Round {row['round']} · {clock(row['round_seconds'])}** — "
                    f"{names.get(row['victim'], 'A teammate')} died at {place_label(row['victim_place'])}")
        st.markdown("\n".join(f"- {reason}" for reason in cover_reasons(row, names)))
        if row["verdict"] == fights.COVER_FACING_AWAY:
            st.markdown("**Next time:** when a teammate is fighting near you, aim where his killer will appear.")
        elif row["verdict"] == fights.COVER_TOO_FAR:
            st.markdown(f"**Next time:** stay within {fights.TRADE_RANGE:,} units of a teammate taking a fight.")
        death = report.all_deaths[(report.all_deaths["tick"] == row["tick"]) & (report.all_deaths["victim"] == row["victim"])]
        if len(death):
            render_moment_map(death.iloc[0], report)
        watch_hint(row["tick"])


def render_buy_calls(report: Report) -> None:
    calls = report.calls
    if calls.empty:
        st.write("Your team never had a force-or-save decision this match: every buy round was a clear full buy or a forced eco.")
        return
    st.markdown(
        "A **buy call** is a round where your team could afford a force but not a full buy. Halftime plays both "
        "choices forward up to four rounds with CS2's money rules and checks which wins more."
    )
    wrong = calls[calls["grade"].isin([SHOULD_FORCE, SHOULD_SAVE])].sort_values("cost", ascending=False)
    for _, call in wrong.iterrows():
        with st.container(border=True):
            st.markdown(f"⚠️ **Round {call['round']}** — {call['grade']}  \n{call_detail(call)}")
    right = calls[calls["grade"] == GOOD_CALL]
    if len(right):
        st.markdown(f"✅ **{len(right)} right call{'s' if len(right) != 1 else ''}:** rounds "
                    f"{', '.join(map(str, right['round']))}.")
    with st.expander("Every buy call"):
        render_calls(calls)


def render_economy(report: Report, mode: str) -> None:
    st.altair_chart(economy_chart(report, mode), width="stretch")
    with st.expander("Round by round"):
        table = report.rounds.assign(
            expected=(report.rounds["expected"] * 100).round(),
            your_buy=report.rounds["your_buy"].map(BUY_LABELS),
            their_buy=report.rounds["their_buy"].map(BUY_LABELS),
            result=report.rounds["won"].map({True: "Won", False: "Lost"}),
            split_buy=report.rounds["split_buy"].map({True: "Yes", False: ""}),
        )[["round", "side", "score", "your_buy", "their_buy", "your_equip", "their_equip", "expected", "result", "verdict", "split_buy"]]
        st.dataframe(
            table, hide_index=True, width="stretch",
            column_config={
                "round": "Round", "side": "Side", "score": "Score before", "your_buy": "Your buy", "their_buy": "Their buy",
                "your_equip": st.column_config.NumberColumn("Your equipment", format="$%d"),
                "their_equip": st.column_config.NumberColumn("Their equipment", format="$%d"),
                "expected": st.column_config.ProgressColumn("Matchup win rate", format="%d%%", min_value=0, max_value=100),
                "result": "Result", "verdict": "Verdict", "split_buy": "Split buy",
            },
        )
    with st.expander("By buy type and team spending"):
        buys = report.buy_summary.assign(
            your_buy=report.buy_summary["your_buy"].map(BUY_LABELS),
            win_rate=(report.buy_summary["win_rate"] * 100).round(),
            expected=(report.buy_summary["expected"] * 100).round(),
        )
        st.dataframe(
            buys[["your_buy", "rounds", "wins", "win_rate", "expected", "vs_expected"]], hide_index=True, width="stretch",
            column_config={
                "your_buy": "Buy", "rounds": "Rounds", "wins": "Won",
                "win_rate": st.column_config.NumberColumn("Win rate", format="%d%%"),
                "expected": st.column_config.NumberColumn("Expected", format="%d%%"),
                "vs_expected": st.column_config.NumberColumn("Rounds vs expected", format="%+.1f"),
            },
        )
        st.dataframe(
            report.players[["name", "avg_equip", "avg_unspent", "split_buys"]], hide_index=True, width="stretch",
            column_config={
                "name": "Player",
                "avg_equip": st.column_config.NumberColumn("Avg equipment", format="$%d"),
                "avg_unspent": st.column_config.NumberColumn("Avg money left", format="$%d"),
                "split_buys": st.column_config.NumberColumn("Bought in split buys"),
            },
        )


def render_calls(calls: pd.DataFrame, with_match: bool = False) -> None:
    table = calls.assign(
        made=calls["made"].str.title(),
        their_buy=calls["their_buy"].map(BUY_LABELS),
        cost=[f"{c:.2f}" if c > 0 else "" for c in calls["cost"]],
    )
    columns = (["map"] if with_match else []) + [
        "round", "money_each", "their_buy", "made", "force_wins", "save_wins", "rounds_counted", "grade", "cost",
    ]
    if with_match:
        table["map"] = table["map"].map(map_label)
    st.dataframe(
        table[columns],
        hide_index=True,
        width="stretch",
        column_config={
            "map": "Map",
            "round": "Round",
            "money_each": st.column_config.NumberColumn("Money each", format="$%d", help="Money plus carried gear, per player."),
            "their_buy": "Their buy",
            "made": "You",
            "force_wins": st.column_config.NumberColumn("Wins if force", format="%.1f", help="Expected rounds won over the rounds counted."),
            "save_wins": st.column_config.NumberColumn("Wins if save", format="%.1f", help="Expected rounds won over the rounds counted."),
            "rounds_counted": st.column_config.NumberColumn("Rounds counted", help="This round plus up to 3 after it, stopping at half-time."),
            "grade": "Verdict",
            "cost": "Rounds lost",
        },
    )


MOMENT_ROLES = ["You", "Teammate", "Teammate who died", "Killer"]
AIM_RAY = 400  # units: how long the aim lines on a moment map are


def moment_map(death: pd.Series, chances: pd.DataFrame, names: dict, me: str, mode: str) -> alt.Chart | None:
    """Top-down positions at the moment of a death: who stood where and where they aimed. No walls (no map images)."""
    palette = COLORS[mode]
    if any(pd.isna(death.get(k)) for k in ("victim_x", "victim_y", "killer_x", "killer_y")):
        return None
    rows = [
        {"role": "You" if death["victim"] == me else "Teammate who died", "x": death["victim_x"], "y": death["victim_y"],
         "yaw": None, "label": "You (died)" if death["victim"] == me else names.get(death["victim"], "Teammate")},
        {"role": "Killer", "x": death["killer_x"], "y": death["killer_y"], "yaw": None, "label": names.get(death["killer"], "Killer")},
    ]
    if len(chances):
        for c in chances[(chances["tick"] == death["tick"]) & (chances["victim"] == death["victim"])].itertuples():
            if pd.notna(c.mate_x):
                rows.append({"role": "You" if c.mate == me else "Teammate", "x": c.mate_x, "y": c.mate_y, "yaw": c.mate_yaw,
                             "label": "You" if c.mate == me else names.get(c.mate, "Teammate")})
    points = pd.DataFrame(rows)
    aims = points[points["yaw"].notna()].copy()
    aims["x2"] = aims["x"] + AIM_RAY * np.cos(np.radians(aims["yaw"].astype(float)))
    aims["y2"] = aims["y"] + AIM_RAY * np.sin(np.radians(aims["yaw"].astype(float)))

    xs = pd.concat([points["x"], aims["x2"]]).astype(float)
    ys = pd.concat([points["y"], aims["y2"]]).astype(float)
    half = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2 + 250
    cx, cy = (xs.max() + xs.min()) / 2, (ys.max() + ys.min()) / 2
    x_scale, y_scale = alt.Scale(domain=[cx - half, cx + half]), alt.Scale(domain=[cy - half, cy + half])
    color = alt.Color("role:N", title=None, scale=alt.Scale(
        domain=MOMENT_ROLES, range=[palette["Your team"], palette["neutral"], palette["critical"], palette["Opponent"]]),
        legend=None)  # explained once in the caption under the map
    fight = alt.Chart(pd.DataFrame([{"x": death["killer_x"], "y": death["killer_y"], "x2": death["victim_x"], "y2": death["victim_y"]}])).mark_rule(
        strokeDash=[5, 4], strokeWidth=1.5, color=palette["text"], opacity=0.6
    ).encode(x=alt.X("x:Q", scale=x_scale, axis=None), y=alt.Y("y:Q", scale=y_scale, axis=None), x2="x2:Q", y2="y2:Q")
    layers = [fight]
    if len(aims):
        layers.append(alt.Chart(aims).mark_rule(strokeWidth=2, opacity=0.8).encode(
            x=alt.X("x:Q", scale=x_scale), y=alt.Y("y:Q", scale=y_scale), x2="x2:Q", y2="y2:Q", color=color))
    layers.append(alt.Chart(points).mark_point(filled=True, size=150, stroke=palette["surface"], strokeWidth=1.5, opacity=1).encode(
        x=alt.X("x:Q", scale=x_scale), y=alt.Y("y:Q", scale=y_scale), color=color,
        shape=alt.Shape("role:N", scale=alt.Scale(domain=MOMENT_ROLES, range=["circle", "circle", "diamond", "triangle-up"]), legend=None),
        tooltip=[alt.Tooltip("label:N", title="Player"), alt.Tooltip("role:N", title="Role")]))
    # Name only the people the moment is about; other teammates show their name on hover.
    labelled = points[points["role"] != "Teammate"]
    layers.append(alt.Chart(labelled).mark_text(align="left", dx=9, dy=-7, fontSize=11, color=palette["text"]).encode(
        x=alt.X("x:Q", scale=x_scale), y=alt.Y("y:Q", scale=y_scale), text="label:N"))
    return alt.layer(*layers).properties(width=230, height=230).configure_view(stroke=palette["band"])


def render_moment_map(death: pd.Series, report: Report) -> None:
    chart = moment_map(death, report.trade_chances, report.names, report.steamid, theme_mode())
    if chart is not None:
        st.altair_chart(chart, width="content")
        st.caption("Blue = you · grey = teammates (lines show where they aimed) · red ◆ = teammate who died · "
                   "orange ▲ = killer · dashed line = the fight. Seen from above; walls aren't drawn.")


def render_utility(report: Report, mode: str) -> None:
    u = report.utility
    if not u:
        st.info("This demo was stored before utility was tracked. Re-add it (Your habits → Add all replays) to see it.")
        return
    palette = COLORS[mode]
    cols = st.columns(4)
    with cols[0].container(border=True):
        st.metric("Grenades thrown", u["grenades"], f"{u['grenades'] - u['match_grenades']:+.0f} vs match average")
        st.caption(f"{u['thrown']['flashes']} flashes · {u['thrown']['smokes']} smokes · {u['thrown']['hes']} HEs · {u['thrown']['molotovs']} molotovs")
    with cols[1].container(border=True):
        st.metric("Enemies flashed", u["enemies_blinded"], help="Blinded for at least a second.")
        st.caption(f"{u['per_flash']:.1f} enemies per flash (match average {u['match_per_flash']:.1f}), "
                   f"{u['enemy_blind_seconds']:.0f}s of blindness in total.")
    with cols[2].container(border=True):
        st.metric("Teammates flashed", u["teammates_blinded"], f"{u['teammates_blinded'] - u['match_teammates_blinded']:+.1f} vs match average",
                  delta_color="inverse", help="Your flashes that blinded a teammate for at least a second.")
        st.caption("Every one is a teammate who can't shoot back for a moment.")
    with cols[3].container(border=True):
        st.metric("Grenade damage", u["utility_damage"], f"{u['utility_damage'] - u['match_utility_damage']:+.0f} vs match average")
        st.caption("HE and molotov damage to enemies.")

    flashes = report.team_flashes
    left, right = st.columns(2)
    with left:
        st.markdown("#### ⚠️ Flashes that blinded your team")
        if flashes.empty:
            st.write("None. Clean flashes.")
        for f in flashes.itertuples():
            st.markdown(f"- Round {f.round}: blinded **{report.names.get(f.blinded, 'a teammate')}** for {f.seconds:.1f}s · `{watch_command(f.tick)}`")
        if len(flashes):
            st.caption("Next time: say \"flashing\" before you throw, and throw over your teammate's head, not past his face.")
    with right:
        st.markdown("#### 💸 Died holding grenades")
        unused = report.deaths[report.deaths["unused_utility"] >= UNUSED_WORTH_MENTION] if len(report.deaths) and "unused_utility" in report.deaths else pd.DataFrame()
        if unused.empty:
            st.write("You used your utility before your fights.")
        for d in unused.itertuples():
            st.markdown(f"- Round {d.round} · {clock(d.round_seconds)} · {place_label(d.victim_place)}: died with **${d.unused_utility:,}** of grenades unused")
        if len(unused):
            st.caption(f"${int(unused['unused_utility'].sum()):,} of grenades in total. Throw a flash or molotov before taking the fight, "
                       "or drop them to a teammate.")


CLUTCH_ICONS = {
    fights.CLUTCH_WON: "🏆", fights.CLUTCH_PLAYED: "✅", fights.CLUTCH_SAVED: "✅",
    fights.CLUTCH_SHOULD_SAVE: "⚠️", fights.CLUTCH_SHOULD_PLAY: "⚠️", fights.CLUTCH_CLOSE: "➖",
}


def render_clutches(report: Report) -> None:
    clutch = report.clutches
    st.markdown("#### Clutches: you, alone")
    st.caption("Every round where you were your team's last player alive, and whether fighting or saving was right. "
               "A saved gun keeps paying off in later buys, so its value counts the rest of the half (up to 4 rounds). "
               "Fighting is right when your chance to win beats that, since winning keeps the gun too.")
    if clutch.empty:
        st.write("You were never your team's last player alive this match.")
    else:
        won = int((clutch["outcome"] == "Won").sum())
        wrong = int(clutch["verdict"].isin([fights.CLUTCH_SHOULD_SAVE, fights.CLUTCH_SHOULD_PLAY]).sum())
        st.markdown(f"**{won}** of **{len(clutch)}** clutches won · **{wrong}** fight-or-save mistakes")
        for _, c in clutch.iterrows():
            with st.container(border=True):
                st.markdown(f"{CLUTCH_ICONS[c['verdict']]} **Round {c['round']} · 1v{int(c['enemies'])}** — {c['verdict']}")
                st.markdown("\n".join(f"- {reason}" for reason in clutch_reasons(c)))
                if c["verdict"] in CLUTCH_FIXES:
                    st.markdown(f"**Next time:** {CLUTCH_FIXES[c['verdict']]}")
                watch_hint(c["tick"])

    st.markdown("#### Opening duels")
    od = report.openings
    if od.empty:
        st.write("You weren't in the first fight of any round.")
        return
    st.markdown(f"You were in the first fight of **{len(od)}** rounds and won **{int(od['won'].sum())}**. "
                "Winning the opening duel puts your team 5v4; losing it puts you 4v5.")
    st.dataframe(
        pd.DataFrame({"round": od["round"], "side": od["side"], "where": od["place"].map(place_label),
                      "result": od["won"].map({True: "✅ Won", False: "❌ Lost"}), "weapon": od["weapon"]}),
        hide_index=True, width="stretch",
        column_config={"round": "Round", "side": "Side", "where": "Where you were", "result": "Result", "weapon": "Weapon used"},
    )


def openings_chart(od: pd.DataFrame, mode: str) -> alt.Chart:
    palette = COLORS[mode]
    counts = (od.assign(where=od["place"].map(place_label), result=od["won"].map({True: "Won", False: "Lost"}))
              .groupby(["where", "result"]).size().reset_index(name="duels"))
    order = counts.groupby("where")["duels"].sum().sort_values(ascending=False).index.tolist()
    counts["stack"] = counts["result"].map({"Won": 0, "Lost": 1})
    bars = alt.Chart(counts).mark_bar(stroke=palette["surface"], strokeWidth=2).encode(
        y=alt.Y("where:N", title=None, sort=order, axis=alt.Axis(labelOverlap=False, labelLimit=200)),
        x=alt.X("duels:Q", title="Opening duels", stack="zero", axis=alt.Axis(tickMinStep=1)),
        color=alt.Color("result:N", title=None, scale=alt.Scale(domain=["Won", "Lost"], range=[palette["good"], palette["critical"]]),
                        legend=alt.Legend(orient="top", direction="horizontal")),
        order="stack:Q",
        tooltip=[alt.Tooltip("where:N", title="Where"), alt.Tooltip("result:N", title="Result"), alt.Tooltip("duels:Q", title="Duels")],
    )
    # One-layer chart: Streamlit drops some single-mark bar charts.
    return alt.layer(bars.properties(height=alt.Step(30)))


# ---------- progress ----------


@st.cache_data(show_spinner="Loading your past matches…", max_entries=16)
def player_history(steamid: str, model: FightModel, slope: float, stamp: int) -> pd.DataFrame:
    """Match-by-match numbers for a player from the database. `stamp` changes when matches are added."""
    conn = database()
    if conn is None:
        return pd.DataFrame()
    try:
        matches = db.load_matches(conn, steamid=steamid)
        conn.commit()
    except Exception:
        conn.rollback()
        return pd.DataFrame()
    return history(matches, steamid, model, slope)


def history_stamp() -> int:
    conn = database()
    if conn is None:
        return 0
    try:
        stamp = conn.execute("SELECT count(*), coalesce(max(parsed_at)::text, '') FROM matches").fetchone()
        conn.commit()
        return hash(stamp)
    except Exception:
        conn.rollback()
        return 0


def saved_setting(key: str) -> str | None:
    conn = database()
    if conn is None:
        return None
    try:
        return db.get_setting(conn, key)
    except Exception:
        conn.rollback()
        return None


def save_setting(key: str, value: str) -> None:
    conn = database()
    if conn is not None:
        db.set_setting(conn, key, value)


def format_focus(value, column: str) -> str:
    if value is None or pd.isna(value):
        return "–"
    return f"{value:.0%}" if column == "set_up_rate" else f"{value:.1f}" if isinstance(value, float) else str(value)


def render_focus_banner(current: dict, past: pd.DataFrame, exclude: str) -> None:
    key = saved_setting("focus")
    if key not in FOCUS or not current:
        return
    label, column, lower_is_better = FOCUS[key]
    others = past[past["match_id"] != exclude].tail(RECENT_MATCHES) if len(past) else past
    value = current.get(column)
    if value is None or others.empty or column not in others:
        st.info(f"🎯 Your focus: **{label}**. This match: {format_focus(value, column)}.")
        return
    average = others[column].mean()
    better = (value < average) if lower_is_better else (value > average)
    verdict = "✅ better than" if better else "⚠️ worse than" if value != average else "level with"
    st.info(f"🎯 Your focus: **{label}**. This match: **{format_focus(value, column)}**, {verdict} your last "
            f"{len(others)} matches ({format_focus(average, column)}).")


def focus_chart(past: pd.DataFrame, column: str, mode: str) -> alt.Chart:
    palette = COLORS[mode]
    data = past[["match_id", "map", column]].dropna().reset_index(drop=True)
    data["match"] = [f"{i}. {map_label(m)}" for i, m in enumerate(data["map"], start=1)]
    average = float(data[column].mean())
    fmt = ".0%" if column == "set_up_rate" else ".0f"
    bars = alt.Chart(data).mark_bar(color=palette["Your team"], cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=alt.X("match:N", title=None, sort=data["match"].tolist(), axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f"{column}:Q", title=None, axis=alt.Axis(format=fmt, tickMinStep=1 if fmt == ".0f" else None)),
        tooltip=[alt.Tooltip("match:N", title="Match"), alt.Tooltip(f"{column}:Q", title="Value", format=".2f" if fmt == ".0f" else fmt)],
    )
    rule = alt.Chart(pd.DataFrame({"avg": [average], "label": [f"Your average: {format_focus(average, column)}"]}))
    line = rule.mark_rule(color=palette["text"], strokeDash=[5, 4]).encode(y="avg:Q")
    text = rule.mark_text(align="right", dy=-6, x="width", color=palette["text"], fontSize=11).encode(y="avg:Q", text="label:N")
    return (bars + line + text).properties(height=240)


GUIDE_STEPS = [
    ("📥", "Get a match",
     "In CS2 open **Watch → Your Matches** and press **Download** on a match. Halftime finds it in your replays folder "
     "automatically. On FACEIT, download the demo from the match room and use **Upload a demo** in the sidebar."),
    ("🗂️", "Pick it", "Choose the match in the sidebar. The newest download is at the top."),
    ("🙋", "Pick yourself", "Choose your name, then press **This is me** so Halftime opens on you from then on."),
    ("🎯", "Learn one thing", "Every death, buy, grenade and clutch is judged with the reasons. Pick one habit to work on in "
     "**Your habits** and watch it change match by match."),
]


def render_guide() -> None:
    """How to get started: in full until you've saved yourself with "This is me", then tucked away."""
    def steps() -> None:
        cols = st.columns(len(GUIDE_STEPS))
        for col, (icon, title, text) in zip(cols, GUIDE_STEPS):
            with col.container(border=True):
                st.markdown(f"### {icon}\n**{title}**")
                st.caption(text)

    if saved_setting("me"):
        with st.expander("How Halftime works"):
            steps()
    else:
        st.markdown("#### Get your first report in four steps")
        steps()


# ---------- pages ----------


def report_page() -> None:
    st.title("Halftime")
    st.write("Your CS2 decisions, graded: your buys, your deaths, and how well you cover your teammates.")

    with st.sidebar:
        st.markdown("### Choose a match")
        source = st.radio("Demo source", ["My CS2 replays", "Upload a demo"], label_visibility="collapsed")

    parsed = None
    if source == "My CS2 replays":
        folder = Path(st.sidebar.text_input("CS2 replays folder", str(REPLAYS), key="replays_folder"))
        demos = replay_demos(folder)
        if not demos:
            st.info("No demos found yet. Download a match in CS2 (step 1 below), then refresh this page.")
            render_guide()
            return
        labels = {
            f"{datetime.fromtimestamp(p.stat().st_mtime):%b %d, %Y %H:%M} · {p.stat().st_size / 1e6:.0f} MB": p
            for p in demos
        }
        choice = st.sidebar.selectbox("Match", list(labels))
        path = labels[choice]
        parsed = parse_cached(str(path), f"{path.stat().st_mtime_ns}-{path.stat().st_size}")
    else:
        upload = st.sidebar.file_uploader(
            "Demo file", type=[s.lstrip(".").split(".")[-1] for s in DEMO_SUFFIXES],
            help="A .dem from CS2 (Watch → Your Matches → Download) or FACEIT (.dem.gz / .dem.zst).",
        )
        st.sidebar.caption("By uploading you agree to the Terms and Privacy policy (see the pages in the menu).")
        if upload is None:
            st.info("Upload a demo in the sidebar to get your report.")
            render_guide()
            return
        try:
            parsed = parse_upload(upload)
        except Exception as error:
            st.error(
                "Couldn't read that demo. It may not be a CS2 demo, or the download may be incomplete. "
                "Try downloading the match again (CS2: Watch → Your Matches → Download)."
            )
            st.caption(f"Details: {type(error).__name__}: {error}")
            return

    pool, slope, fight_model = save_and_pool(parsed)
    parsed = hide_names(parsed)
    if database() is None:
        st.warning(
            "The match database isn't running, so win rates come from this match only. "
            "Start it with `docker compose up -d` for pooled win rates."
        )

    # Ask who to review whenever nobody already picked is in this demo; never guess.
    match = parsed.match.iloc[0]
    scores = {"A": int(match["team_a_score"]), "B": int(match["team_b_score"])}
    players = players_in(parsed)
    names = {f"{row.name}  ·  Team {row.team} ({scores[row.team]} rounds won)": row.steamid for row in players.itertuples()}
    options = list(names)
    # A fixed key keeps the widget stable across reruns; preselect the last player reviewed if they're in this demo.
    if st.session_state.get("review_player") not in options:
        remembered = st.session_state.get("steamid") or saved_setting("me")
        st.session_state["review_player"] = next((label for label in options if names[label] == remembered), None)
    picked = st.selectbox(
        "Which player do you want to review?", options, key="review_player",
        placeholder=f"Choose one of the {len(options)} players in this match",
    )
    if picked is None:
        st.info(f"Pick a player above to see their report for {map_label(match['map'])} ({scores['A']}–{scores['B']}).")
        render_guide()
        return
    steamid = names[picked]
    st.session_state["steamid"] = steamid
    if database() is not None and saved_setting("me") != steamid:
        if st.button(f"⭐ This is me: always open my reports as {picked.split('  ·  ')[0]}"):
            save_setting("me", steamid)
            st.toast("Saved. Halftime will pick you automatically from now on.")

    past = player_history(steamid, fight_model, slope, history_stamp())
    current = match_numbers(parsed, steamid, fight_model, slope)
    render_report(build_report(parsed, steamid, pool, slope, fight_model), past, current)


def habits_page() -> None:
    st.title("Your habits")
    st.write("Patterns across all your stored matches: the habits that cost your team the most rounds, and how they change match to match.")
    conn = database()
    if conn is None:
        st.warning("Habits need the match database. Start it with `docker compose up -d`, then refresh.")
        return

    demos = replay_demos(Path(st.session_state.get("replays_folder", str(REPLAYS))))
    if demos and st.sidebar.button(f"Add all {len(demos)} replays", help="Parses every replay in your CS2 folder that isn't stored yet."):
        added = add_all_replays(demos)
        st.sidebar.success(f"Added {added} new match{'es' if added != 1 else ''}.")

    try:
        matches = [hide_names(m) for m in db.load_matches(conn)]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if not matches:
        st.info("No matches stored yet. Open a report on the Match report page, or add all your replays from the sidebar.")
        return

    pool = pd.concat([m.team_rounds for m in matches], ignore_index=True)
    counts = pd.concat([m.player_rounds.drop_duplicates("steamid")[["steamid", "name"]] for m in matches])
    counts = counts.groupby("steamid").agg(name=("name", "last"), matches=("name", "size")).sort_values("matches", ascending=False)
    labels = {
        f"{row['name']}  ({row['matches']} match{'es' if row['matches'] != 1 else ''})": sid for sid, row in counts.iterrows()
    }
    options = list(labels)
    remembered = st.session_state.get("steamid") or saved_setting("me")
    default = next((i for i, label in enumerate(options) if labels[label] == remembered), 0)
    picked = st.sidebar.selectbox("Which player are you?", options, index=default)
    st.session_state["steamid"] = labels[picked]

    with_fights = [m for m in matches if len(m.deaths)]
    fight_model = (
        fit_fight_model(
            pd.concat([m.deaths for m in with_fights], ignore_index=True),
            pd.concat([m.trade_chances for m in with_fights], ignore_index=True),
            pool,
        )
        if with_fights else FightModel()
    )
    habits = build_habits(matches, labels[picked], equipment_slope(pool), fight_model)
    mode = theme_mode()
    st.header(f"{habits.name} · {habits.matches} match{'es' if habits.matches != 1 else ''}")
    outdated = len(matches) - len(with_fights)
    if outdated:
        st.caption(f"{outdated} stored match{'es were' if outdated != 1 else ' was'} parsed before deaths were tracked; "
                   "re-add your replays from the sidebar to include them.")
    render_habit_scorecards(habits)
    render_checklist(habits)
    render_focus(matches, labels[picked], fight_model, equipment_slope(pool), mode)

    if habits.matches < MIN_MATCHES:
        st.info(f"Habits need at least {MIN_MATCHES} of your matches; you have {habits.matches}. Add more replays from the sidebar.")
        return

    st.subheader("Fix these first")
    st.caption("Ranked by how many rounds each habit costs you per match.")
    if not habits.fixes:
        st.write("No costly habits found. Nice.")
    for number, habit in enumerate(habits.fixes[:3], start=1):
        with st.container(border=True):
            impact = f"  \n**Costs you about {habit.cost:.2f} rounds per match.**" if habit.cost > 0 else ""
            st.markdown(f"**#{number} · {habit.title}**  \n{habit.detail}{impact}")
    if len(habits.fixes) > 3:
        with st.expander(f"{len(habits.fixes) - 3} smaller habits"):
            for habit in habits.fixes[3:]:
                st.markdown(f"- **{habit.title}.** {habit.detail}")
    if habits.strengths:
        st.subheader("Keep doing this")
        for habit in habits.strengths:
            with st.container(border=True):
                st.markdown(f"✅ **{habit.title}**  \n{habit.detail}")

    names = {}
    for m in matches:
        names.update(m.player_rounds.drop_duplicates("steamid", keep="last").set_index("steamid")["name"].to_dict())
    tabs = st.tabs(["📉 Avoidable deaths by match", "🤝 Coverage across matches", "🚪 Opening duels by callout", "💰 Every buy call"])
    with tabs[0]:
        if habits.fight_matches:
            st.altair_chart(avoidable_trend_chart(habits.deaths, matches, mode), width="stretch")
            st.caption("Oldest match on the left. Fewer bars on the right means the habit is fading.")
        else:
            st.write("No death data yet: re-add your replays from the sidebar.")
    with tabs[1]:
        if len(habits.coverage):
            st.altair_chart(coverage_chart(habits.coverage, names, mode), width="stretch")
            st.caption(f"Every teammate death near you across {habits.fight_matches} matches. Dots in the green box are "
                       "where trades happen: close to the killer and aiming at him.")
        else:
            st.write("No teammate died near you in these matches.")
    with tabs[2]:
        render_habit_openings(matches, labels[picked], mode)
    with tabs[3]:
        if len(habits.calls):
            render_calls(habits.calls.sort_values("cost", ascending=False), with_match=True)


def render_checklist(habits) -> None:
    """Your top habits as a short list to keep in mind (or open on a second screen) next match."""
    items = checklist(habits)
    focus = FOCUS.get(saved_setting("focus") or "")
    if not items and not focus:
        return
    with st.container(border=True):
        st.markdown("#### 📋 Before your next match")
        if focus:
            st.markdown(f"🎯 **This week's focus: {focus[0].lower()}.**")
        for i, item in enumerate(items):
            st.checkbox(item, key=f"checklist_{i}")
        text = "Halftime: before your next match\n" + (f"Focus: {focus[0]}\n" if focus else "") + "".join(f"[ ] {i}\n" for i in items)
        st.download_button("Save as a text file", text, file_name="halftime-checklist.txt", mime="text/plain",
                           help="Keep it open on a second screen while you play.")


def render_focus(matches: list, steamid: str, model: FightModel, slope: float, mode: str) -> None:
    """Pick one habit to work on; see it match by match against your average."""
    st.subheader("🎯 Your focus")
    keys = list(FOCUS)
    saved = saved_setting("focus")
    choice = st.selectbox(
        "Pick one habit to work on this week", keys, index=keys.index(saved) if saved in keys else None,
        format_func=lambda k: FOCUS[k][0], placeholder="Choose a habit to track",
    )
    if choice is None:
        st.caption("Working on one thing at a time is how habits change. Your choice shows on every match report.")
        return
    if choice != saved and database() is not None:
        save_setting("focus", choice)
    label, column, lower_is_better = FOCUS[choice]
    past = history(matches, steamid, model, slope)
    if past.empty or column not in past or past[column].dropna().empty:
        st.write("No data for this habit yet. Re-add your replays from the sidebar.")
        return
    st.altair_chart(focus_chart(past, column, mode), width="stretch")
    direction = "Lower" if lower_is_better else "Higher"
    st.caption(f"{label}, match by match, oldest on the left. {direction} is better; the dashed line is your average.")


def render_habit_openings(matches: list, steamid: str, mode: str) -> None:
    """Where you take the first fight of a round, per map, and how often you win it."""
    duels = [opening_duels(m.deaths, m.team_rounds, steamid).assign(map=map_label(m.match.iloc[0]["map"]))
             for m in matches if len(m.deaths)]
    duels = pd.concat(duels, ignore_index=True) if duels else pd.DataFrame()
    if duels.empty:
        st.write("No opening duels yet.")
        return
    maps = duels["map"].value_counts()
    chosen = st.selectbox("Map", maps.index.tolist(), format_func=lambda m: f"{m} ({maps[m]} opening duels)")
    on_map = duels[duels["map"] == chosen]
    st.markdown(f"On {chosen} you took the first fight **{len(on_map)}** times and won **{int(on_map['won'].sum())}** "
                f"({on_map['won'].mean():.0%}).")
    st.altair_chart(openings_chart(on_map, mode), width="stretch")
    spots = on_map.groupby("place")["won"].agg(["size", "sum"])
    spots = spots[spots["size"] >= 2]
    if len(spots):
        rate = spots["sum"] / spots["size"]
        best, worst = rate.idxmax(), rate.idxmin()
        notes = []
        if rate[best] >= 0.5:
            notes.append(f"✅ Your best spot: **{place_label(best)}** (won {int(spots.at[best, 'sum'])} of {int(spots.at[best, 'size'])}).")
        if rate[worst] < 0.5 and worst != best:
            notes.append(f"⚠️ Rethink **{place_label(worst)}**: you lost {int(spots.at[worst, 'size'] - spots.at[worst, 'sum'])} "
                         f"of {int(spots.at[worst, 'size'])} first fights there. Try another angle or wait for a teammate.")
        st.markdown("  \n".join(notes))
    st.caption("A callout needs a few duels before it means much; spots with only one duel aren't called out.")


def render_habit_scorecards(habits) -> None:
    cards = st.columns(4)
    deaths, calls = habits.deaths, habits.calls
    with cards[0].container(border=True):
        if habits.fight_matches:
            avoidable = deaths[deaths["label"].isin(fights.AVOIDABLE)]
            st.metric("Avoidable deaths", f"{len(avoidable) / habits.fight_matches:.1f}")
            kinds = avoidable["label"].value_counts()
            st.caption("per match. " + (" · ".join(f"{n} {SHORT_LABELS[label]}" for label, n in kinds.items()) or "None. Clean fights."))
        else:
            st.metric("Avoidable deaths", "–")
    with cards[1].container(border=True):
        cover = habits.coverage
        st.metric("Coverage", habits.coverage_grade or "–",
                  help="How well you're set up to trade teammates who die near you, against every player in the pool.")
        if len(cover):
            set_up = ((cover["distance_to_killer"] <= fights.TRADE_RANGE) & (cover["aim_angle"] <= fights.FACING_ANGLE)).sum()
            st.caption(f"In position to trade {int(set_up)} of {len(cover)} times")
    with cards[2].container(border=True):
        if habits.fight_matches:
            traded = int((deaths["label"] == fights.TRADED).sum())
            st.metric("Deaths traded", f"{traded} of {len(deaths)}")
            st.caption(f"{traded / max(len(deaths), 1):.0%} of your deaths got traded within {fights.TRADE_SECONDS}s.")
        else:
            st.metric("Deaths traded", "–")
    with cards[3].container(border=True):
        right = int((calls["grade"] == GOOD_CALL).sum()) if len(calls) else 0
        st.metric("Buy calls right", f"{right} of {len(calls)}")
        if len(calls):
            st.caption(f"Wrong calls cost about {calls['cost'].sum() / habits.matches:.2f} rounds per match.")


def avoidable_trend_chart(deaths: pd.DataFrame, matches: list, mode: str) -> alt.Chart:
    """Avoidable deaths per match, oldest to newest, split by kind."""
    palette = COLORS[mode]
    order = [m.match.iloc[0]["match_id"] for m in sorted(matches, key=lambda m: m.match.iloc[0]["match_id"])]
    maps = {m.match.iloc[0]["match_id"]: map_label(m.match.iloc[0]["map"]) for m in matches}
    played = [mid for mid in order if mid in set(deaths["match_id"])]
    labels = {mid: f"{i}. {maps[mid]}" for i, mid in enumerate(played, start=1)}
    kinds = [fights.REPEEK, fights.ALONE, fights.SHOULD_SAVE]
    avoidable = deaths[deaths["label"].isin(kinds)]
    counts = (avoidable.groupby(["match_id", "label"]).size().reindex(
        pd.MultiIndex.from_product([played, kinds], names=["match_id", "label"]), fill_value=0).reset_index(name="deaths"))
    counts["match"] = counts["match_id"].map(labels)
    counts["kind"] = counts["label"].map(lambda k: SHORT_LABELS[k].capitalize())
    kind_names = [SHORT_LABELS[k].capitalize() for k in kinds]
    return (
        alt.Chart(counts[counts["deaths"] > 0])
        .mark_bar(stroke=palette["surface"], strokeWidth=2, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("match:N", title=None, sort=[labels[mid] for mid in played], axis=alt.Axis(labelAngle=0)),
            y=alt.Y("deaths:Q", title="Avoidable deaths", axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("kind:N", title=None, scale=alt.Scale(domain=kind_names, range=[palette["Your team"], palette["Opponent"], palette["aqua"]]),
                            legend=alt.Legend(orient="top", direction="horizontal")),
            order=alt.Order("kind:N"),
            tooltip=[alt.Tooltip("match:N", title="Match"), alt.Tooltip("kind:N", title="Kind"), alt.Tooltip("deaths:Q", title="Deaths")],
        )
        .properties(height=280)
    )


def markdown_page(file: str):
    def page() -> None:
        st.markdown((ROOT / "legal" / file).read_text(encoding="utf-8"))

    page.__name__ = file.replace(".", "_")
    return page


st.set_page_config(page_title="Halftime", page_icon="⏱️", layout="wide")
navigation = st.navigation(
    [
        st.Page(report_page, title="Match report", icon="📊", default=True),
        st.Page(habits_page, title="Your habits", icon="🎯", url_path="habits"),
        st.Page(markdown_page("privacy.md"), title="Privacy", icon="🔒", url_path="privacy"),
        st.Page(markdown_page("terms.md"), title="Terms", icon="📄", url_path="terms"),
    ]
)
navigation.run()
st.divider()
st.caption(DISCLAIMER)
