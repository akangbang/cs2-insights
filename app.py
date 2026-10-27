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
from cs2_insights.grade import CLOSE, GOOD_CALL
from cs2_insights.habits import MIN_MATCHES, build_habits
from cs2_insights.ingest import DEMO_SUFFIXES, ingest, plain_demo
from cs2_insights.rates import equipment_slope
from cs2_insights.report import BUY_LABELS, Report, build_report, clock, place_label, players_in, pooled_rates

ROOT = Path(__file__).resolve().parent
REPLAYS = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\replays")
WATCH_LEAD_SECONDS = 5  # "watch" jumps to a few seconds before the moment
DISCLAIMER = (
    "Halftime is not affiliated with or endorsed by Valve Corporation. "
    "Counter-Strike and CS2 are trademarks of Valve Corporation."
)

# Validated with the dataviz palette checker (light and dark): team = slot 1 blue, opponent = slot 2 orange.
COLORS = {
    "light": {"Your team": "#2a78d6", "Opponent": "#eb6834", "good": "#0ca30c", "critical": "#d03b3b", "surface": "#ffffff"},
    "dark": {"Your team": "#3987e5", "Opponent": "#d95926", "good": "#0ca30c", "critical": "#d03b3b", "surface": "#0e1117"},
}


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
    mode = "dark" if getattr(st.context.theme, "type", "light") == "dark" else "light"

    st.header(f"{map_label(s['map'])} · {s['result']} {s['your_score']}–{s['their_score']}")
    over = s["your_score"] - s["expected_wins"]
    cols = st.columns(4)
    cols[0].metric("Rounds won", s["your_score"], f"{over:+.1f} vs expected", delta_color="normal")
    cols[1].metric("Expected from your buys", s["expected_wins"])
    cols[2].metric(
        "Buy calls right", f"{s['calls_right']}/{s['calls']}",
        help="Rounds where your team could force or save, and Halftime's simulation agrees with what you did. "
        "Close calls count as neither right nor wrong.",
    )
    cols[3].metric(
        "Rounds lost to buy calls", s["rounds_lost_to_calls"],
        help="Expected rounds the wrong force-or-save calls cost, compared with the other choice.",
    )
    if s.get("fights_parsed"):
        c = s["coverage"]
        cols = st.columns(4)
        cols[0].metric("Deaths traded", f"{s['traded_deaths']}/{s['deaths']}",
                       help=f"A teammate killed your killer within {fights.TRADE_SECONDS} seconds.")
        cols[1].metric("Avoidable deaths", s["avoidable_deaths"],
                       help="Re-peeks after a kill, pushes with nobody close enough to trade, and deaths with gear in rounds already lost.")
        cols[2].metric("Rounds lost to avoidable deaths", s["rounds_lost_to_avoidable"],
                       help="How much these deaths dropped your team's chance to win their rounds, added up.")
        cols[3].metric("Coverage grade", c["grade"] or "–",
                       help="How well you were set up to trade teammates who died near you: close to the killer and aiming at him. "
                       "Graded against every player in Halftime's pool.")
    st.caption(
        f"Expected wins add up how often each of your buy matchups wins across {s['pool_rounds']:,} rounds "
        "in Halftime's match pool. Buy calls are graded by playing both choices forward a few rounds with CS2's "
        "money rules. Deaths and coverage are judged from where everyone stood and aimed. Early beta: the pool is "
        "still small, so treat these as rough."
    )

    st.subheader("Key moments")
    if not report.moments:
        st.write("A clean economy game: no traps, split buys or big swings.")
    for moment in report.moments:
        icon = "✅" if moment.kind == "good" else "⚠️"
        with st.container(border=True):
            st.markdown(f"{icon} **{moment.title}**  \n{moment.detail}")

    if len(report.deaths):
        st.subheader("Your deaths")
        render_deaths(report)
    if s.get("fights_parsed"):
        st.subheader("Covering your teammates")
        render_coverage(report)

    if len(report.calls):
        st.subheader("Every buy call")
        render_calls(report.calls)

    st.subheader("Economy, round by round")
    st.altair_chart(economy_chart(report, mode), width="stretch")

    table = report.rounds.assign(
        expected=(report.rounds["expected"] * 100).round(),
        your_buy=report.rounds["your_buy"].map(BUY_LABELS),
        their_buy=report.rounds["their_buy"].map(BUY_LABELS),
        result=report.rounds["won"].map({True: "Won", False: "Lost"}),
        split_buy=report.rounds["split_buy"].map({True: "Yes", False: ""}),
    )[["round", "side", "score", "your_buy", "their_buy", "your_equip", "their_equip", "expected", "result", "verdict", "split_buy"]]
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "round": "Round",
            "side": "Side",
            "score": "Score before",
            "your_buy": "Your buy",
            "their_buy": "Their buy",
            "your_equip": st.column_config.NumberColumn("Your equipment", format="$%d"),
            "their_equip": st.column_config.NumberColumn("Their equipment", format="$%d"),
            "expected": st.column_config.ProgressColumn("Matchup win rate", format="%d%%", min_value=0, max_value=100),
            "result": "Result",
            "verdict": "Verdict",
            "split_buy": "Split buy",
        },
    )

    left, right = st.columns(2)
    with left:
        st.subheader("By buy type")
        buys = report.buy_summary.assign(
            your_buy=report.buy_summary["your_buy"].map(BUY_LABELS),
            win_rate=(report.buy_summary["win_rate"] * 100).round(),
            expected=(report.buy_summary["expected"] * 100).round(),
        )
        st.dataframe(
            buys[["your_buy", "rounds", "wins", "win_rate", "expected", "vs_expected"]],
            hide_index=True,
            width="stretch",
            column_config={
                "your_buy": "Buy",
                "rounds": "Rounds",
                "wins": "Won",
                "win_rate": st.column_config.NumberColumn("Win rate", format="%d%%"),
                "expected": st.column_config.NumberColumn("Expected", format="%d%%"),
                "vs_expected": st.column_config.NumberColumn("Rounds vs expected", format="%+.1f"),
            },
        )
    with right:
        st.subheader("Your team's spending")
        st.dataframe(
            report.players[["name", "avg_equip", "avg_unspent", "split_buys"]],
            hide_index=True,
            width="stretch",
            column_config={
                "name": "Player",
                "avg_equip": st.column_config.NumberColumn("Avg equipment", format="$%d"),
                "avg_unspent": st.column_config.NumberColumn("Avg money left", format="$%d"),
                "split_buys": st.column_config.NumberColumn("Bought in split buys"),
            },
        )


def watch_command(tick: int) -> str:
    return f"demo_gototick {max(int(tick) - WATCH_LEAD_SECONDS * TICK_RATE, 0)}"


WATCH_HELP = "Open the demo in CS2, then paste this into the console (~) to jump to 5 seconds before the moment."


def render_deaths(report: Report) -> None:
    d = report.deaths
    names = report.names
    table = pd.DataFrame(
        {
            "round": d["round"],
            "time": d["round_seconds"].map(clock),
            "where": d["victim_place"].map(place_label),
            "killer": d["killer"].map(lambda k: names.get(k, "")),
            "weapon": d["weapon"],
            "verdict": d["label"],
            "chance": (d["win_before"] * 100).round(),
            "cost": d["cost"].round(2),
            "traded_by": [names.get(t, "") if v == fights.TRADED else "" for t, v in zip(d["traded_by"], d["label"])],
            "watch": d["tick"].map(watch_command),
        }
    )
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "round": "Round",
            "time": st.column_config.TextColumn("Time", help="Time since the round went live."),
            "where": "Where",
            "killer": "Killed by",
            "weapon": "Weapon",
            "verdict": "Verdict",
            "chance": st.column_config.NumberColumn("Team chance before", format="%d%%"),
            "cost": st.column_config.NumberColumn("Rounds lost", format="%.2f", help="How much this death dropped your team's chance to win the round."),
            "traded_by": "Traded by",
            "watch": st.column_config.TextColumn("Watch", help=WATCH_HELP),
        },
    )


def render_coverage(report: Report) -> None:
    c = report.summary["coverage"]
    if not c["chances"]:
        st.write("No teammate died near you this match, so there's nothing to grade.")
        return
    st.write(
        f"**{c['chances']}** teammate deaths happened near you. You were close enough to trade (within {fights.TRADE_RANGE:,} units "
        f"of the killer) **{c['in_range']}** times, and also aiming at the fight (within {fights.FACING_ANGLE}°) "
        f"**{c['set_up']}** times. You traded **{c['trades']}**; for where you stood and aimed, players in the pool "
        f"would trade about **{c['expected_trades']}**."
    )
    cover, names = report.coverage, report.names
    table = pd.DataFrame(
        {
            "round": cover["round"],
            "time": cover["round_seconds"].map(clock),
            "teammate": cover["victim"].map(lambda v: names.get(v, "")),
            "where": cover["victim_place"].map(place_label),
            "distance": cover["distance_to_killer"].round(),
            "aim": cover["aim_angle"].round(),
            "chance": (cover["chance"] * 100).round(),
            "verdict": cover["verdict"],
            "watch": cover["tick"].map(watch_command),
        }
    )
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "round": "Round",
            "time": "Time",
            "teammate": "Teammate who died",
            "where": "Where",
            "distance": st.column_config.NumberColumn("Your distance to killer", format="%d"),
            "aim": st.column_config.NumberColumn("Your aim off (°)", format="%d°", help="Degrees between where you aimed and the killer."),
            "chance": st.column_config.NumberColumn("Trade chance", format="%d%%", help="How often players in the pool trade from that distance and aim."),
            "verdict": "Verdict",
            "watch": st.column_config.TextColumn("Watch", help=WATCH_HELP),
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
    st.write("Your CS2 economy, graded. Pick a match and see which buys won you rounds and which ones cost you.")

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

    players = players_in(parsed)
    names = {f"{row.name}  (team {row.team})": row.steamid for row in players.itertuples()}
    remembered = st.session_state.get("steamid")
    options = list(names)
    default = next((i for i, label in enumerate(options) if names[label] == remembered), 0)
    picked = st.sidebar.selectbox("Which player are you?", options, index=default)
    st.session_state["steamid"] = names[picked]

    render_report(build_report(parsed, names[picked], pool, slope, fight_model))


def habits_page() -> None:
    st.title("Your habits")
    st.write("Patterns across all your stored matches: the economy habits that cost your team the most rounds.")
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
    st.header(f"{habits.name} · {habits.matches} match{'es' if habits.matches != 1 else ''}")
    calls = habits.calls
    if len(calls):
        right, close = int((calls["grade"] == GOOD_CALL).sum()), int((calls["grade"] == CLOSE).sum())
        cols = st.columns(3)
        cols[0].metric("Buy calls right", f"{right}/{len(calls)}")
        cols[1].metric("Close calls", close)
        cols[2].metric(
            "Rounds lost to buy calls", f"{calls['cost'].sum():.1f}",
            help=f"{calls['cost'].sum() / habits.matches:.2f} per match.",
        )
    if habits.fight_matches:
        deaths = habits.deaths
        avoidable = deaths["label"].isin(fights.AVOIDABLE)
        cols = st.columns(3)
        cols[0].metric("Deaths traded", f"{int((deaths['label'] == fights.TRADED).sum())}/{len(deaths)}")
        cols[1].metric("Avoidable deaths per match", f"{avoidable.sum() / habits.fight_matches:.1f}")
        cols[2].metric("Coverage grade", habits.coverage_grade or "–",
                       help="How well you're set up to trade teammates who die near you, against every player in the pool.")
    outdated = len(matches) - len(with_fights)
    if outdated:
        st.caption(f"{outdated} stored match{'es were' if outdated != 1 else ' was'} parsed before deaths were tracked; "
                   "re-add your replays from the sidebar to include them.")

    if habits.matches < MIN_MATCHES:
        st.info(f"Habits need at least {MIN_MATCHES} of your matches; you have {habits.matches}. Add more replays from the sidebar.")
        return

    st.subheader("Fix these first")
    if not habits.fixes:
        st.write("No costly habits found. Nice.")
    for habit in habits.fixes[:3]:
        with st.container(border=True):
            cost = f"  \n*About {habit.cost:.2f} rounds per match.*" if habit.cost > 0 else ""
            st.markdown(f"⚠️ **{habit.title}**  \n{habit.detail}{cost}")
    for habit in habits.fixes[3:]:
        st.markdown(f"- **{habit.title}.** {habit.detail}")
    for habit in habits.strengths:
        with st.container(border=True):
            st.markdown(f"✅ **{habit.title}**  \n{habit.detail}")

    if len(calls):
        st.subheader("Every buy call")
        render_calls(calls.sort_values("cost", ascending=False), with_match=True)


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
