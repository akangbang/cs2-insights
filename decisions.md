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

## 2026-10-27 — Grade buys with an equipment curve and a money simulation
Context: Bucketed buy-matchup win rates (eco/force/full) made every force look right: "force" mixes $2,000 SMG buys with $3,500 rifle buys. Users need "what should I have done", not "what happened".
Choice + why: Win chance per round = sigmoid(slope × ln(your equipment / theirs)), slope fit to the pool (1.08–1.18 so far, beats buckets on log loss). Each decision plays both choices forward up to 3 more rounds (stopping at half-time or match point), both teams then using the standard policy (full buy if they average $4,500+, else save; spend all on the last round). Close calls (< 0.10 rounds) aren't graded either way.
Revisit if: The pool grows past ~100 matches (refit, check calibration by rank), or players report verdicts that feel wrong in specific situations.

## 2026-10-27 — Judge deaths and grade trade coverage, not just buys
Context: Team buy calls are small (about 0.5 rounds a match for a whole team) and solo-queue players can't act on them. Deaths cost far more, and most players don't trade or hold angles that cover teammates.
Choice + why: A death traded within 2 seconds counts as fine, including entries and angle clears. Coverage is graded from positions at each teammate death: distance to the killer and how far your aim was from him, turned into a trade chance by a model fitted on the pool. No map geometry (walls) yet, so it uses straight-line distance; the fitted chances already absorb the typical effect of walls.
Revisit if: Players report verdicts that are wrong because of walls (e.g. close but behind a wall), or a licensed source of map geometry becomes available.

## 2026-11-07 — Coach spacing; show crossfires without grading them
Context: The user asked for a crossfire and spacing coach. Measured on 13 matches (2-second trades): a death with a teammate within 150 units was traded 38% of the time, 150-300 units 26%, 600-900 units 8%, past 1,600 almost never. Deaths with a crossfire set up (a teammate in range at 45 degrees or more from the victim, seen from the killer) were traded 22% of the time, against 26% on the same line (667 deaths); same result at equal distances.
Choice + why: Grade spacing (nearest teammate when you die; habit, checklist tip, weekly focus) because the data shows a strong effect. Show crossfires as information only, with the finding explained, because teaching "crossfire more" isn't supported by this data. A crossfire's value is likely preventing the kill, which death-only data can't measure.
Revisit if: The pool grows past ~100 matches, or kills that didn't happen can be measured (e.g. duels won by the player with a crossfire behind them), so crossfire value can be tested directly.

## 2026-11-08 — Recap compares matches, not calendar weeks
Context: The user asked for a weekly recap. A demo doesn't reliably say when it was played: the stored time is when it was parsed, and uploads carry no date.
Choice + why: Compare the last matches (up to 5) with the same number before them, ordered by Valve match ID, which increases over time. Uploaded demos are left out and counted in a note, because their place in time is unknown. A change only counts when it's at least one standard error, so ordinary match-to-match swings aren't reported as progress.
Revisit if: Match dates become available (Steam match history, or FACEIT's API), which would allow a real calendar week and include uploads.

## 2026-11-08 — Replays show a best case for deaths; lost-cause verdict left as is
Context: Replaying a death needs a counterfactual, but a demo can't show that a player would have survived by playing differently. Measuring the replay on stored matches also showed that "Died with gear in a lost round" is sometimes wrong by its own numbers: of 120 such deaths that could be valued, hiding was better in 73, 21 were too close to call, and fighting on was better in 26.
Choice + why: Deaths show what happened, the same death with a teammate close enough to trade (at the pool's measured trade rate), and staying alive, labelled a best case. Where a lost-cause death's numbers favour fighting, the replay says so and the card drops its "hide next time" advice. The verdict itself is unchanged, because changing it would change avoidable-death counts and habits, which is a product decision.
Revisit if: The player decides lost-cause deaths should only count as avoidable when hiding is actually better.

## 2026-11-09 — Rename Halftime to LeanPeek
Context: halftime.gg costs about $50,000. The user wanted a learning-flavoured name containing "lean" and chose getleanpeek.com. leanpeek.com is taken; leanpeek.gg and getleanpeek.com were unregistered on 2026-11-09. Web searches found no product or trademark called LeanPeek. The closest record is LEANPEAK (serial 99633070), a pending application for vitamin supplements by Cowboy Nutrition LLC, per third-party trademark sites. Leanify was rejected: registered US software trademark (6824693), and very close to the competitor Leetify.
Choice + why: LeanPeek in everything users see. HALFTIME_ environment settings stay, because users never see them and renaming them would break existing setups and the stored-key configuration.
Revisit if: A USPTO search or a lawyer finds a conflict. Web searches are not trademark clearance.

## 2026-11-09 — Brand is Getleanpeek
Context: After the rename to LeanPeek, the user asked for the brand to match the chosen domain, getleanpeek.com.
Choice + why: Getleanpeek, with that exact capitalisation, in everything users see. The trademark notes in the LeanPeek entry above still apply.
Revisit if: A USPTO search or a lawyer finds a conflict.

## 2026-11-09 — Habit proof counts from a match ID, not a date
Context: Habit proof needs "since you picked this focus", but demos don't say when they were played.
Choice + why: When a focus is picked, the newest stored Valve match ID is saved as `focus_since`, and matches with a higher ID count as after. Nothing is claimed before 3 such matches, and a change must beat the player's normal swing, using the recap's test. On the first 6 matches, 1 of 24 trial comparisons counted as an improvement, so the card stays rare. The card carries no player name.
Revisit if: Match dates become available. A replay played before the focus but downloaded after it currently counts as after.

## 2026-11-09 — Free hosting on Streamlit Community Cloud, for testing only
Context: The user wants the app online for free. Hugging Face's docs say Docker Spaces need a paid subscription, Koyeb and Render free tiers have 512 MB, and Oracle's free server can be reclaimed when idle and needs server administration.
Choice + why: Streamlit Community Cloud with Neon's free database (DEPLOY.md). It needs no server to run. Its terms (November 2025) limit apps handling personal data to personal, non-commercial use such as evaluation, so this is for a free test only.
Revisit if: Charging money, marketing it as a business, or large demos crash the free memory limit. Next step is a Hetzner CX23.

## 2026-11-09 — Match categories from the demo itself
Context: The user wanted Premier, Competitive and FACEIT kept apart.
Choice + why: comp_rank_type 11 is Premier and 12 is Competitive, checked on 12 real demos. FACEIT is recognised from the server name, which has not been tested on a real FACEIT demo. Win-chance models still pool every category, because splitting them would leave too little data.
Revisit if: A real FACEIT demo isn't recognised, or the pool grows large enough to fit models per category.
