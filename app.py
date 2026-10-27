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
from cs2_insights.ingest import DEMO_SUFFIXES, plain_demo
from cs2_insights.report import BUY_LABELS, Report, build_report, players_in, pooled_rates

ROOT = Path(__file__).resolve().parent
REPLAYS = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\replays")
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


def save_and_pool(parsed: ParsedDemo) -> pd.DataFrame:
    """Store the match (so it joins the pool) and return pooled win rates from every other match."""
    conn = database()
    if conn is None:
        return pooled_rates(parsed.team_rounds)
    try:
        db.load_parsed(conn, parsed)
        pool = db.pool_team_rounds(conn, exclude_match_id=parsed.match.iloc[0]["match_id"])
        conn.commit()  # end the read transaction so this long-lived connection never holds locks
        return pooled_rates(pool)
    except Exception:
        conn.rollback()
        return pooled_rates(parsed.team_rounds)


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
    cols[2].metric("Upset wins", s["upsets_won"], help="Rounds you won with a buy matchup that usually loses.")
    cols[3].metric("Upset losses", s["favoured_lost"], help="Rounds you lost with a buy matchup that usually wins.")
    st.caption(
        f"Expected wins add up how often each of your buy matchups wins across {s['pool_rounds']:,} rounds "
        "in Halftime's match pool. Early beta: the pool is still small, so treat these as rough."
    )

    st.subheader("Key moments")
    if not report.moments:
        st.write("A clean economy game: no traps, split buys or big swings.")
    for moment in report.moments:
        icon = "✅" if moment.kind == "good" else "⚠️"
        with st.container(border=True):
            st.markdown(f"{icon} **{moment.title}**  \n{moment.detail}")

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


# ---------- pages ----------


def report_page() -> None:
    st.title("Halftime")
    st.write("Your CS2 economy, graded. Pick a match and see which buys won you rounds and which ones cost you.")

    with st.sidebar:
        st.markdown("### Choose a match")
        source = st.radio("Demo source", ["My CS2 replays", "Upload a demo"], label_visibility="collapsed")

    parsed = None
    if source == "My CS2 replays":
        folder = Path(st.sidebar.text_input("CS2 replays folder", str(REPLAYS)))
        demos = sorted(folder.glob("*.dem"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []
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

    pool = save_and_pool(parsed)
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

    render_report(build_report(parsed, names[picked], pool))


def markdown_page(file: str):
    def page() -> None:
        st.markdown((ROOT / "legal" / file).read_text(encoding="utf-8"))

    page.__name__ = file.replace(".", "_")
    return page


st.set_page_config(page_title="Halftime", page_icon="⏱️", layout="wide")
navigation = st.navigation(
    [
        st.Page(report_page, title="Match report", icon="📊", default=True),
        st.Page(markdown_page("privacy.md"), title="Privacy", icon="🔒", url_path="privacy"),
        st.Page(markdown_page("terms.md"), title="Terms", icon="📄", url_path="terms"),
    ]
)
navigation.run()
st.divider()
st.caption(DISCLAIMER)
