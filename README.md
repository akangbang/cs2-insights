# CS2 Insights

Paste your Steam profile link, get concrete insights from your last 10 FACEIT matches.

Most stat sites describe what happened. This tool scores your **buy decisions**: a calibrated round win-probability model estimates whether a force-buy, save, or full buy was the right call given the economy and round state.

## How it works
Steam URL → Steam64 ID → FACEIT player → recent matches → demo files → parsed round, economy, and per-player tables (Parquet) → win-probability model → 3 insights per match.

## Stack
Python, DuckDB/SQL, scikit-learn, Streamlit, AWS (S3, Glue/Athena, Lambda, Fargate), Power BI.

## Status
Pre-alpha, Phase 0: validating the data chain by hand.

## Setup
1. Copy `.env.example` to `.env` and add your FACEIT and Steam API keys.
2. More to come.
