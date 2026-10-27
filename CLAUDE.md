# CLAUDE.md

## Project
Brand: **Halftime** (target domain halftime.gg, for sale on GoDaddy; brand name must never include CS2, Counter-Strike or Valve marks). Tagline style: "Halftime: a decision coach for CS2". Repo is still `cs2-insights`. A CS2 tracker that grades players' decisions, not just their aim: it parses round-level demo data and tells players what each choice (force vs. save, retake vs. save, peek vs. hold) did to their win probability. Existing sites (Leetify, csstats, FACEIT stats) report what happened; this answers "what should I have done?". Source of truth: the proposal "CS2 Decision Tracker: Proposal" (Oct 6, 2026).

Data sources, all ending in the same rounds table with a `source` column, each switchable per tier:
- Core: players bring their own demos (they download in CS2 or FACEIT and upload; later a small local helper that watches the replays folder, ideally parsing on their machine and sending only results).
- FACEIT Downloads API once approved (applied 2026-10-13): official, no ToS problem, and FACEIT players are the most likely to pay.
- Steam Web API share code linking only as a "these matches are ready to analyze" reminder. NO demo-fetching bot (dropped 2026-10-27; see Legal guardrails).
- Optional later: Leetify public API.

Parser: demoparser2. Model: one live round win-probability logistic regression (map CT-win baseline + alive, HP, equipment, utility, time, bomb, bomb x time), feeding an economy chain (Markov model, solved backwards) that scores each buy by half/match win chance. Conditional win rates are built first as a sanity check. Buy labels from team equipment value: eco < $5,000, force/half $5,000-$20,000, full > $20,000 (to tune).

Stack: Python (ETL, demoparser2, pandas, scikit-learn) -> PostgreSQL (star schema: matches, rounds, players, kills, economy; insights as SQL views) -> Power BI reports, Excel "force or save?" calculator, member web app (FastAPI or Streamlit). Every output reads the same SQL views. Hosting on AWS: PostgreSQL on RDS, demo bot and parsing on EC2 (S3 for raw .dem files is an option to decide later).

Membership: Free (last 10 matches, standard stats, one teaser insight per match), Pro $5/month or $40/year (full history, all insights, buy grader every round, weekly "three things to fix"), Team $15/month for 5. Payments via Stripe. Growth via shareable "your worst buy this week" cards.

Build phases (revised 2026-10-27, revenue first):
1. Done: parser, PostgreSQL, ingest, share code linking (bot removed).
2. Week 1: web app: upload a demo, get a free economy report (every buy rated, win rates by buy type). Privacy policy, terms, "not affiliated with Valve" footer.
3. Week 2: shareable "worst buy" image cards, email signup, post to r/cs2, r/GlobalOffensive, FACEIT Discords.
4. Week 3: buy grader v1 on pooled uploads (target 100+ matches), then the live win-probability model and economy chain.
5. Week 4: Pro tier ($5/month or $40/year) via a merchant of record (Paddle or Lemon Squeezy), after the LLC exists.
6. Later: FACEIT import when approved, local helper app, Power BI reports, Excel calculator, Team tier, AWS hosting.

## Goals
1. Ship: launch as a real product players pay for to improve their game. This is the priority.
2. Portfolio: the stack (Python, SQL, Power BI, Excel, ML, AWS) still shows on a resume, but learning by hand is no longer a goal.

## How to work with me
- Claude writes the code (switched 2026-10-13; I'm no longer coding by hand to learn). Build in small working pieces, test each one, and tell me briefly what was built and what you need from me (keys, files, decisions).
- Keep product thinking in view: differentiation vs. Leetify/csstats/Scope.gg (scoring decisions as win probability added or cost), validate insights with real players before building the model, demo parsing cost at scale, Steam/FACEIT/Leetify API terms for paid use.
- Legal guardrails (from reading the terms 2026-10-27; get a lawyer consult before charging):
  - No bots or automated Steam accounts: Steam Subscriber Agreement 4.C bans "scripts, bots, macros, or other non-human-controlled systems"; 2.G(iii) bans commercial use of accounts.
  - Steam Web API terms: privacy policy required, fetch a user's data only when they ask, max 100,000 calls/day, never imply Valve endorsement, Valve can revoke anytime. Paid use is ambiguous ("personal use" wording), so paid features must rest on demo analysis, not API data.
  - No "CS2"/"Counter-Strike"/Valve logos in the brand; descriptive "for CS2" is fine with a "not affiliated with Valve" disclaimer.
  - Privacy: demos hold 9 other players' Steam IDs and names. Store the minimum, honor deletion requests, encrypt auth codes. Don't redistribute demo files.
  - Business: LLC before taking money; terms of service and refund policy; merchant of record for global sales tax/VAT.
  - Still to check: FACEIT and Leetify terms for paid use; Valve demo retention (~30 days, third-party sources).
- Small, frequent commits with clear imperative messages. Claude may commit locally; never push unless I ask.
- Terminal is Windows PowerShell 5.1: no `&&`, use `;` or separate lines.

## Status
- 2026-09-23: Repo created, git identity configured. Filled .gitignore, .env.example, README.md, decisions.md. First commit pushed to https://github.com/akangbang/cs2-insights. `gh` CLI not installed.
- 2026-09-23: Project setup done: .venv (Python 3.12), requirements.txt (requests, python-dotenv, pytest; write with `Set-Content -Encoding ascii`, not `>`), src/cs2_insights/steam.py + tests/test_steam.py. Pushed.
- 2026-10-01: parse_steam_url() written in steam.py (by Claude, at my request; uncommitted). Turns a Steam profile link into Steam64 or a vanity name. Less central now that share codes are the core input; may still serve Steam64 lookups for FACEIT/Leetify.
- 2026-10-13: AWS kept as hosting (RDS + EC2), added on top of the proposal. Created a FACEIT developer account and Data API key, stored in .env as FACEIT_API_KEY (.gitignore now also covers `.env.*` except `.env.example`). Applied for the FACEIT Downloads API on 2026-10-13 (about 30 days; expect a reply around mid-November).
- 2026-10-13: Plan switched to the Decision Tracker proposal (above). Earlier FACEIT-only/Parquet/DuckDB/AWS plan superseded; see decisions.md. Next: Phase 1. Get a Steam Web API key, verify Valve demo retention. Open: keep CLAUDE.md in git or local only (undecided).
- 2026-10-13: Built sharecode.py (decode/encode, verified against a published code), Steam match history walker in steam.py (tested with a fake Steam server, not yet live), demo.py (demoparser2 -> match, rounds, team_rounds, player_rounds DataFrames; ~1s per demo). STEAM_API_KEY and STEAM_AUTH_CODE are in .env. 11 of my own demos (Mar-Aug 2026, 180-390 MB each) are in CS2's replays folder and all parse. Buy cut-offs need tuning: a $5,700 T round-2 buy counts as "force". Next: live test of the walker (needs a share code from Steam's "Access to your match history" page), PostgreSQL in Docker + loader, then research the demo-fetching bot.
- 2026-10-16: Phase 1 code complete, 58 tests passing. demo.py fixed (late joiners, overtime, round gaps). PostgreSQL 16 in Docker (docker-compose.yml, sql/schema.sql: matches, rounds, team_rounds, player_rounds, players, linked_accounts, share_codes, view v_buy_matchup_win_rates). `python -m cs2_insights.ingest` loads .dem/.bz2/.gz/.zst (my 11 demos loaded, 12s). `cs2_insights.link` links accounts and queues share codes; `cs2_insights.fetch --sync` asks the Node bot (bot/fetch_demo_urls.js, steam-user + globaloffensive) for demo URLs, downloads, parses, loads, deletes the file. Valve demo retention ~30 days (third-party sources). Not yet run live: Steam match history walk (need a share code), bot (need a bot Steam account). Auth codes are stored in plain text in linked_accounts; encrypt before real users. Kills/positions aren't parsed yet (needed for the Phase 2 live model).
- 2026-10-27: Project folder moved from OneDrive\Desktop to C:\Users\andre\Desktop\cs2-insights (the OneDrive copy is stale placeholders); .venv rebuilt there. Read the Steam Subscriber Agreement and Web API terms: the demo bot violates SSA 4.C, so removed bot/ and fetch.py (still in git history). Plan switched to players bringing their own demos; revenue-first plan above. Brand name being chosen.
- 2026-10-27: Brand chosen: Halftime. No gaming/esports product named Halftime found (quick web check, not a trademark search). halftime.gg is parked for sale on GoDaddy; price unknown. Still to do: USPTO search (classes 9 and 41), buy a domain, claim social handles.
- 2026-10-27: Week 1 app built (local, $0): `streamlit run app.py`. report.py grades every round against pooled buy-matchup win rates (smoothed), flags upsets, force traps, split buys; app has replays picker + upload, player picker, economy chart (validated palette, light/dark), round/buy/player tables, Privacy and Terms drafts (legal/*.md, contact email still a placeholder), Valve disclaimer, Streamlit telemetry off. Buy thresholds now per player: eco < $1,600, full >= $3,800. 62 tests incl. headless app tests. Pool is only my 11 matches (194 rounds).
