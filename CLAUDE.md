# CLAUDE.md

## Project
CS2 FACEIT Match Insights Tool. A player pastes their Steam profile link and gets insights on their last N (start: 10) FACEIT matches. Pipeline: Steam URL -> Steam64 -> FACEIT player ID -> recent matches -> demo files -> parsed round/economy/per-player tables (awpy or demoparser2, Parquet) -> calibrated round win-probability model that scores buy decisions. Streamlit front end, AWS (S3, Glue/Athena, Lambda, Fargate/EC2) pipeline, internal Power BI dashboard. Plan phases: 0 walk the chain by hand, 1 schema, 2 batch-collect 200-400 matches, 3 SQL (DuckDB), 4 model, 5 AWS, 6a Power BI, 6b Streamlit, 7 v2.

v1 scope: FACEIT only (matchmaking demos need user auth codes), 3 insights per match, cache results by match ID.

## Goals
1. Learning: Python, SQL, AWS, ML skills for job hunting.
2. Launch as a real product players use to improve their game.

## How to work with me
- I'm learning. Mentor me: explain concepts, ask guiding questions, review my code at checkpoints. Don't write solution code unless I ask for it. Setup boilerplate (config files, commands) is fine to give directly.
- Keep product thinking in view: differentiation vs. Leetify/Scope.gg (likely angle: scoring buy decisions, not just describing them), validate insights with real FACEIT players before building the model, demo parsing cost at scale, FACEIT/Steam API terms.
- Open risk to verify in Phase 0: FACEIT demo downloads may need a separately approved Downloads API, not just a Data API key.
- I make small, frequent commits with clear imperative messages to show progress.
- Terminal is Windows PowerShell 5.1: no `&&`, use `;` or separate lines.

## Status
- 2026-09-23: Repo created, GitHub remote added, git identity configured. Created empty .gitignore, README.md, decisions.md, .env.example; first commit not made yet. Next: fill those files, first commit + push, then get FACEIT and Steam API keys and start Phase 0.
