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

## Setup (Windows, PowerShell)
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd bot; npm install; cd ..
copy .env.example .env      # then fill in the keys
docker compose up -d        # local PostgreSQL
python -m pytest            # everything should pass
```

## Usage
```powershell
# Load demo files you already have (.dem, .dem.bz2, .dem.gz, .dem.zst; files or folders)
python -m cs2_insights.ingest "C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgoeplays"

# Link a player's Valve match history (auth code defaults to STEAM_AUTH_CODE in .env)
python -m cs2_insights.link add https://steamcommunity.com/id/<name> CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx

# One-time bot login (needs BOT_STEAM_USERNAME / BOT_STEAM_PASSWORD; asks for the Steam Guard code)
node bot/fetch_demo_urls.js --login

# Queue new matches for every linked player, then download and load them. Run at least daily.
python -m cs2_insights.fetch --sync
```
