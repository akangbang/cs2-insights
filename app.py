"""Halftime: upload a CS2 demo, get an economy report.

Run with: streamlit run app.py
"""

import hashlib
import tempfile
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from cs2_insights import db
from cs2_insights.demo import ParsedDemo, parse_demo
from cs2_insights import fights
from cs2_insights.demo import TICK_RATE
from cs2_insights.fights import FightModel, fit_fight_model
from cs2_insights.grade import CLOSE, GOOD_CALL, SHOULD_FORCE, SHOULD_SAVE
from cs2_insights.habits import MIN_MATCHES, build_habits
from cs2_insights.ingest import DEMO_SUFFIXES, ingest, plain_demo
from cs2_insights.rates import equipment_slope
from cs2_insights.report import (
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


def render_report(report: Report) -> None:
    s = report.summary
    mode = theme_mode()

    st.header(f"{map_label(s['map'])} · {s['result']} {s['your_score']}–{s['their_score']}")
    st.caption(f"Reviewing **{s['name']}** · {s['rounds']} rounds")
    st.markdown(match_story(report))
    render_scorecards(report)

    st.subheader("Top moments")
    if not report.moments:
        st.write("A clean game: no costly calls, avoidable deaths or big swings.")
    for moment in report.moments:
        icon = "✅" if moment.kind == "good" else "⚠️"
        with st.container(border=True):
            st.markdown(f"{icon} **{moment.title}**  \n{moment.detail}")

    tabs = st.tabs(["💀 Your deaths", "🤝 Covering teammates", "💰 Buy calls", "📈 Economy"])
    with tabs[0]:
        render_deaths(report, mode)
    with tabs[1]:
        render_coverage(report, mode)
    with tabs[2]:
        render_buy_calls(report)
    with tabs[3]:
        render_economy(report, mode)
    st.caption(
        f"Win chances come from Halftime's pool of {s['pool_rounds']:,} rounds. Buy calls are graded by playing both "
        "choices forward a few rounds with CS2's money rules; deaths and coverage from where everyone stood and aimed. "
        "Early beta: the pool is still small, so treat the numbers as a guide."
    )


def theme_mode() -> str:
    return "dark" if getattr(st.context.theme, "type", "light") == "dark" else "light"


def render_scorecards(report: Report) -> None:
    s = report.summary
    over = s["your_score"] - s["expected_wins"]
    cards = st.columns(4)
    with cards[0].container(border=True):
        st.metric("Rounds won", s["your_score"], f"{over:+.1f} vs your buys", delta_color="normal")
        st.caption(f"Your team's buys usually win about {s['expected_wins']:.0f} of these {s['rounds']} rounds.")
    with cards[1].container(border=True):
        if s.get("fights_parsed"):
            st.metric("Avoidable deaths", f"{s['avoidable_deaths']} of {s['deaths']}",
                      help="Deaths a different decision would likely have prevented. The Your deaths tab shows why for each one.")
            kinds = report.deaths[report.deaths["label"].isin(fights.AVOIDABLE)]["label"].value_counts()
            st.caption(" · ".join(f"{n} {SHORT_LABELS[label]}" for label, n in kinds.items()) or "None. Clean fights.")
        else:
            st.metric("Avoidable deaths", "–")
            st.caption("Re-add this demo to see your deaths.")
    with cards[2].container(border=True):
        c = s.get("coverage") or {}
        st.metric("Coverage", c.get("grade") or "–",
                  help="How often you were in position to trade teammates who died near you. The Covering teammates tab shows how it's worked out.")
        st.caption(f"In position to trade {c.get('set_up', 0)} of {c.get('chances', 0)} times · traded {c.get('trades', 0)}"
                   if c.get("chances") else "No teammate died near you.")
    with cards[3].container(border=True):
        st.metric("Buy calls right", f"{s['calls_right']} of {s['calls']}",
                  help="Rounds your team could force or save, where Halftime's simulation agrees with what you did.")
        st.caption(f"Wrong calls cost about {s['rounds_lost_to_calls']:.1f} rounds." if s["calls_wrong"] else "No costly calls.")


SHORT_LABELS = {fights.REPEEK: "re-peek", fights.ALONE: "pushed alone", fights.SHOULD_SAVE: "lost gear in a lost round"}
DEATH_ICONS = {"Traded": "✅", "Avoidable": "⚠️", "Teammates didn't trade": "🤝", "Lost a duel": "⚔️", "Other": "•"}


def watch_command(tick: int) -> str:
    return f"demo_gototick {max(int(tick) - WATCH_LEAD_SECONDS * TICK_RATE, 0)}"


def watch_hint(tick: int) -> None:
    st.caption("Watch it: open the demo in CS2 and paste this into the console (~).")
    st.code(watch_command(tick), language=None)


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
            cover_card(row, names)
    with bad_col:
        st.markdown("#### ⚠️ Fix this")
        bad = cover[cover["verdict"] == fights.COVER_FACING_AWAY].sort_values("lost", ascending=False)
        far = cover[cover["verdict"] == fights.COVER_TOO_FAR].sort_values("cost", ascending=False)
        if bad.empty and far.empty:
            st.write("Nothing to fix: you were in position every time.")
        for _, row in pd.concat([bad.head(2), far.head(2 - min(len(bad), 2))]).iterrows():
            cover_card(row, names)
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


def cover_card(row: pd.Series, names: dict) -> None:
    icon = "✅" if row["verdict"] in (fights.COVER_TRADED, fights.COVER_SET_UP) else "⚠️"
    with st.container(border=True):
        st.markdown(f"{icon} **Round {row['round']} · {clock(row['round_seconds'])}** — "
                    f"{names.get(row['victim'], 'A teammate')} died at {place_label(row['victim_place'])}")
        st.markdown("\n".join(f"- {reason}" for reason in cover_reasons(row, names)))
        if row["verdict"] == fights.COVER_FACING_AWAY:
            st.markdown("**Next time:** when a teammate is fighting near you, aim where his killer will appear.")
        elif row["verdict"] == fights.COVER_TOO_FAR:
            st.markdown(f"**Next time:** stay within {fights.TRADE_RANGE:,} units of a teammate taking a fight.")
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
            st.info(
                "No demos found. In CS2, open **Watch → Your Matches**, press **Download** on a match, "
                "then refresh this page. Or switch to **Upload a demo**."
            )
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
        remembered = st.session_state.get("steamid")
        st.session_state["review_player"] = next((label for label in options if names[label] == remembered), None)
    picked = st.selectbox(
        "Which player do you want to review?", options, key="review_player",
        placeholder=f"Choose one of the {len(options)} players in this match",
    )
    if picked is None:
        st.info(f"Pick a player above to see their report for {map_label(match['map'])} ({scores['A']}–{scores['B']}).")
        return
    st.session_state["steamid"] = names[picked]

    render_report(build_report(parsed, names[picked], pool, slope, fight_model))


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
        matches = db.load_matches(conn)
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
    remembered = st.session_state.get("steamid")
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
    tabs = st.tabs(["📉 Avoidable deaths by match", "🤝 Coverage across matches", "💰 Every buy call"])
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
        if len(habits.calls):
            render_calls(habits.calls.sort_values("cost", ascending=False), with_match=True)


def render_habit_scorecards(habits) -> None:
    cards = st.columns(4)
    deaths, calls = habits.deaths, habits.calls
    with cards[0].container(border=True):
        if habits.fight_matches:
            avoidable = deaths[deaths["label"].isin(fights.AVOIDABLE)]
            st.metric("Avoidable deaths per match", f"{len(avoidable) / habits.fight_matches:.1f}")
            kinds = avoidable["label"].value_counts()
            st.caption(" · ".join(f"{n} {SHORT_LABELS[label]}" for label, n in kinds.items()) or "None. Clean fights.")
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
