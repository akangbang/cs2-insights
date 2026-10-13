# CLAUDE.md

## Project
CS2 Decision Tracker (working name; repo is still `cs2-insights`). A CS2 tracker that grades players' decisions, not just their aim: it parses round-level demo data and tells players what each choice (force vs. save, retake vs. save, peek vs. hold) did to their win probability. Existing sites (Leetify, csstats, FACEIT stats) report what happened; this answers "what should I have done?". Source of truth: the proposal "CS2 Decision Tracker: Proposal" (Oct 6, 2026).

Data sources, all ending in the same rounds table with a `source` column, each switchable per tier:
- Core: Valve match share codes. Player gives one share code + match history auth code; Steam Web API returns every later code; a Steam game client bot fetches each demo.
- Fallback: user-uploaded .dem files (no approval needed, covers older and FACEIT matches).
- Optional: FACEIT Data API + Downloads API; Leetify public API.

Parser: demoparser2. Model: one live round win-probability logistic regression (map CT-win baseline + alive, HP, equipment, utility, time, bomb, bomb x time), feeding an economy chain (Markov model, solved backwards) that scores each buy by half/match win chance. Conditional win rates are built first as a sanity check. Buy labels from team equipment value: eco < $5,000, force/half $5,000-$20,000, full > $20,000 (to tune).

Stack: Python (ETL, demoparser2, pandas, scikit-learn) -> PostgreSQL (star schema: matches, rounds, players, kills, economy; insights as SQL views) -> Power BI reports, Excel "force or save?" calculator, member web app (FastAPI or Streamlit). Every output reads the same SQL views. Hosting on AWS: PostgreSQL on RDS, demo bot and parsing on EC2 (S3 for raw .dem files is an option to decide later).

Membership: Free (last 10 matches, standard stats, one teaser insight per match), Pro $5/month or $40/year (full history, all insights, buy grader every round, weekly "three things to fix"), Team $15/month for 5. Payments via Stripe. Growth via shareable "your worst buy this week" cards.

Build phases:
1. Data foundation: share code linking, demo-fetching bot, demoparser2 loading rounds into PostgreSQL, .dem upload fallback. Apply for the FACEIT Downloads API on day one.
2. Win-probability model and buy grader: train on a few thousand parsed matches, validate, first Power BI report on force-buy outcomes.
3. Remaining insights (tilt, trades, utility, predictability, duo synergy as SQL views) and the Excel calculator.
4. Member web app: link share code, see insights, Stripe checkout for Pro.
5. More sources and growth: FACEIT and Leetify connectors, shareable cards, Team tier.

## Goals
1. Ship: launch as a real product players pay for to improve their game. This is the priority.
2. Portfolio: the stack (Python, SQL, Power BI, Excel, ML, AWS) still shows on a resume, but learning by hand is no longer a goal.

## How to work with me
- Claude writes the code (switched 2026-10-13; I'm no longer coding by hand to learn). Build in small working pieces, test each one, and tell me briefly what was built and what you need from me (keys, files, decisions).
- Keep product thinking in view: differentiation vs. Leetify/csstats/Scope.gg (scoring decisions as win probability added or cost), validate insights with real players before building the model, demo parsing cost at scale, Steam/FACEIT/Leetify API terms for paid use.
- Open risks to verify early in Phase 1: how long Valve keeps demos (proposal says roughly a month); demo bot on a Steam account needs care with rate limits and Steam terms; FACEIT Downloads API approval takes about 30 days; whether FACEIT/Leetify terms allow paid use.
- Small, frequent commits with clear imperative messages. Claude may commit locally; never push unless I ask.
- Terminal is Windows PowerShell 5.1: no `&&`, use `;` or separate lines.

## Status
- 2026-09-23: Repo created, git identity configured. Filled .gitignore, .env.example, README.md, decisions.md. First commit pushed to https://github.com/akangbang/cs2-insights. `gh` CLI not installed.
- 2026-09-23: Project setup done: .venv (Python 3.12), requirements.txt (requests, python-dotenv, pytest; write with `Set-Content -Encoding ascii`, not `>`), src/cs2_insights/steam.py + tests/test_steam.py. Pushed.
- 2026-10-01: parse_steam_url() written in steam.py (by Claude, at my request; uncommitted). Turns a Steam profile link into Steam64 or a vanity name. Less central now that share codes are the core input; may still serve Steam64 lookups for FACEIT/Leetify.
- 2026-10-13: AWS kept as hosting (RDS + EC2), added on top of the proposal. Created a FACEIT developer account and Data API key, stored in .env as FACEIT_API_KEY (.gitignore now also covers `.env.*` except `.env.example`). Applied for the FACEIT Downloads API on 2026-10-13 (about 30 days; expect a reply around mid-November).
- 2026-10-13: Plan switched to the Decision Tracker proposal (above). Earlier FACEIT-only/Parquet/DuckDB/AWS plan superseded; see decisions.md. Next: Phase 1. Get a Steam Web API key, verify Valve demo retention. Open: keep CLAUDE.md in git or local only (undecided).
- 2026-10-13: Built sharecode.py (decode/encode, verified against a published code), Steam match history walker in steam.py (tested with a fake Steam server, not yet live), demo.py (demoparser2 -> match, rounds, team_rounds, player_rounds DataFrames; ~1s per demo). STEAM_API_KEY and STEAM_AUTH_CODE are in .env. 11 of my own demos (Mar-Aug 2026, 180-390 MB each) are in CS2's replays folder and all parse. Buy cut-offs need tuning: a $5,700 T round-2 buy counts as "force". Next: live test of the walker (needs a share code from Steam's "Access to your match history" page), PostgreSQL in Docker + loader, then research the demo-fetching bot.
