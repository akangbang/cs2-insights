# Decision Log

## 2026-10-13 — Build the Decision Tracker
Context: The original plan (FACEIT match insights) was rewritten as "CS2 Decision Tracker: Proposal" (Oct 6, 2026).
Options: Keep the FACEIT insights tool, or switch to the proposal.
Choice + why: Switch. Grading decisions as win probability added or cost is a clearer difference from Leetify and csstats, and a $5/month membership gives it a business model.
Revisit if: Real players don't find the buy grader useful, or a major tracker already presents decisions this way.

## 2026-10-13 — Valve share codes as the core data source
Context: The insights need round-by-round demo data that a paid product can rely on.
Options: FACEIT only, Valve share codes, uploaded .dem files, Leetify.
Choice + why: Valve share codes as the core source, uploaded .dem files as the fallback, FACEIT and Leetify as optional sources. Every source loads into the same rounds table with a `source` column, so each can be switched off per tier if its terms rule out paid use. Supersedes "FACEIT only for v1".
Revisit if: Valve keeps demos for less time than expected (proposal says roughly a month, to verify), or the demo bot hits Steam rate limits or terms problems.

## 2026-10-13 — PostgreSQL star schema with insights as SQL views
Context: The web app, Power BI reports and Excel calculator all need the same numbers.
Options: Parquet files with DuckDB, PostgreSQL.
Choice + why: PostgreSQL with a star schema (matches, rounds, players, kills, economy) and each insight as a view. One source of truth for every output, and it shows data modelling and advanced SQL. Supersedes "Parquet for parsed tables".
Revisit if: Tick-level data gets too large for PostgreSQL on a small budget.

## 2026-10-13 — Live win-probability regression feeding an economy chain
Context: The buy grader needs to score a decision by its effect on the half or match, not just the current round.
Options: Conditional win rates, logistic regression, economy chain (Markov model), gradient boosting with matching.
Choice + why: A logistic regression scored every second of a round (starting from the map's CT win rate) gives round win probability, and an economy chain solved backwards turns that into half or match win chance. Both explain well to users. Conditional win rates are built first as a sanity check. Gradient boosting is more accurate but harder to explain.
Revisit if: Calibration on held-out matches is poor.

## 2026-10-13 — Power BI and Excel for reports, a small web app for members
Context: Need internal analysis, public showcase reports and a member-facing product.
Options: Power BI, Tableau, a custom web app.
Choice + why: Power BI (more common in analyst job postings, and this is a Windows machine) and an Excel "force or save?" calculator. Members use a FastAPI or Streamlit app, because embedding Power BI for thousands of paying users is expensive.
Revisit if: Development moves to a Mac (then Tableau).

## 2026-10-13 — Host on AWS (RDS and EC2)
Context: The proposal doesn't say where things run, and AWS skills are a job-hunting goal.
Options: Local only, a managed host (Render, Railway), AWS.
Choice + why: AWS. PostgreSQL on RDS, the demo bot and parser on EC2. Puts AWS on the resume next to the proposal's stack. S3 for raw .dem files to decide later.
Revisit if: AWS cost is too high before there are paying members.

## 2026-10-16 — Demo bot in Node, raw demos deleted after parsing
**Superseded 2026-10-27** by "Drop the demo bot; players bring their own demos" (bot breaks Steam SSA 4.C). Deleting raw demos after parsing still applies.
Context: Valve demo URLs come only from the CS2 game coordinator, which needs a logged-in Steam client. Valve keeps demos about 30 days (Leetify, Feb 2024; no official figure).
Options: Python Steam libraries (unmaintained for CS2), Node `steam-user` + `globaloffensive` (maintained, CS2 support), user uploads only.
Choice + why: A small Node script asks the game coordinator for each share code's demo URL; Python handles the queue, download, parsing and loading. A dedicated bot Steam account logs in once and saves a refresh token. Fetch runs at least daily so nothing expires first. Downloaded demos are deleted after parsing (about 200-400 MB each); the parsed rows are what we keep.
Revisit if: Valve restricts the bot account or rate limits it, or we need to re-parse old demos for new features (then keep raw files on S3).

## 2026-10-27 — Drop the demo bot; players bring their own demos
Context: The Steam Subscriber Agreement (4.C) bans "scripts, bots, macros, or other non-human-controlled systems" and (2.G(iii)) commercial use of accounts. Competitors run bots anyway, but that is tolerance, not permission, and legal risk must stay low.
Options: Ship the bot like Leetify and csstats; players upload their own demos; FACEIT's official Downloads API.
Choice + why: Players provide their own demos (upload now, a local helper later, ideally parsing on their machine), plus FACEIT's Downloads API once approved. Share code linking stays only as an official-API reminder of which matches are ready. Removes the bot ToS risk, demo storage costs and most server load. Supersedes "Demo bot in Node" and the core-source part of "Valve share codes as the core data source".
Revisit if: Valve publishes an approved way to fetch matchmaking demos, or upload friction blocks growth.

## 2026-10-27 — Revenue-first plan and legal setup
Context: Need revenue soon without legal exposure.
Choice + why: Ship a free upload-and-report web app first, then shareable cards, then the buy grader, then Pro at $5/month. Form an LLC before taking payments; sell through a merchant of record (Paddle or Lemon Squeezy) so global sales tax, VAT and chargebacks are handled. Brand name without Valve trademarks, with a "not affiliated with Valve" disclaimer.
Revisit if: Users won't upload demos, or the free report doesn't get traction.

---

## Superseded

## 2026-09-23 — FACEIT only for v1
**Superseded 2026-10-13** by "Valve share codes as the core data source".
Context: Need a reliable source of match demos for any player who pastes a Steam link.
Options: Valve matchmaking demos, FACEIT demos, both.
Choice + why: FACEIT only. Matchmaking demos require each user's game authentication code, which adds friction and an auth flow before anyone sees value. FACEIT exposes match history through its Data API.
Revisit if: FACEIT demo access turns out to need a Downloads API approval we can't get (open risk, verify in Phase 0), or users ask for matchmaking support.

## 2026-09-23 — Parquet for parsed tables
**Superseded 2026-10-13** by "PostgreSQL star schema with insights as SQL views".
Context: Each demo produces round, economy, and per-player tables that feed SQL and the model.
Options: CSV, Parquet, a database.
Choice + why: Parquet. Columnar and compressed, so files are much smaller than CSV, column types are preserved, and both DuckDB (local) and Athena (AWS) query it directly.
Revisit if: We need frequent row-level updates, which Parquet handles poorly.

## 2026-09-23 — Last 10 matches per player, 3 insights per match
**Partly superseded 2026-10-13:** last 10 matches is now the Free tier; Pro gets full history and every insight.
Context: Demo download and parsing are the slowest and most expensive steps.
Options: All history, last 20, last 10.
Choice + why: Last 10. Keeps per-user parse time and API calls bounded, and is enough to show patterns. 3 insights per match keeps output focused on what to change. Results are cached by match ID so shared matches are parsed once.
Revisit if: Parse cost per match turns out to be low, or users want longer-term trends.
