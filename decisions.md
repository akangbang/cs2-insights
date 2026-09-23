# Decision Log

## 2026-09-23 — FACEIT only for v1
Context: Need a reliable source of match demos for any player who pastes a Steam link.
Options: Valve matchmaking demos, FACEIT demos, both.
Choice + why: FACEIT only. Matchmaking demos require each user's game authentication code, which adds friction and an auth flow before anyone sees value. FACEIT exposes match history through its Data API.
Revisit if: FACEIT demo access turns out to need a Downloads API approval we can't get (open risk, verify in Phase 0), or users ask for matchmaking support.

## 2026-09-23 — Parquet for parsed tables
Context: Each demo produces round, economy, and per-player tables that feed SQL and the model.
Options: CSV, Parquet, a database.
Choice + why: Parquet. Columnar and compressed, so files are much smaller than CSV, column types are preserved, and both DuckDB (local) and Athena (AWS) query it directly.
Revisit if: We need frequent row-level updates, which Parquet handles poorly.

## 2026-09-23 — Last 10 matches per player, 3 insights per match
Context: Demo download and parsing are the slowest and most expensive steps.
Options: All history, last 20, last 10.
Choice + why: Last 10. Keeps per-user parse time and API calls bounded, and is enough to show patterns. 3 insights per match keeps output focused on what to change. Results are cached by match ID so shared matches are parsed once.
Revisit if: Parse cost per match turns out to be low, or users want longer-term trends.
