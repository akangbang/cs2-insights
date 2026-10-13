# CS2 Decision Tracker

A CS2 tracker that grades your decisions, not just your aim.

Most stat sites report what happened. This one answers "what should I have done?": it parses your match demos round by round and scores each choice (force vs. save, retake vs. save, peek vs. hold) by the win probability it added or cost. For example: *"Your round-2 force after a pistol loss cost 6% half win chance versus saving."*

## How it works
1. **Get the matches.** Link your Valve match history once with a share code and auth code; the tool pulls every later Premier and Competitive demo. You can also upload `.dem` files. FACEIT and Leetify are optional extra sources.
2. **Parse.** demoparser2 extracts money, equipment, positions, kills and damage for every round.
3. **Score.** A round win-probability model feeds an economy chain that rates each buy by its effect on your chance to win the half or match.
4. **Report.** Insights are SQL views in PostgreSQL, read by the web app, Power BI reports and an Excel "force or save?" calculator.

## Stack
Python (demoparser2, pandas, scikit-learn), PostgreSQL, Power BI, Excel, FastAPI or Streamlit, hosted on AWS (RDS, EC2).

## Status
Pre-alpha. Phase 1 of 5: data foundation.

## Setup
1. Copy `.env.example` to `.env` and add your keys.
2. More to come.
