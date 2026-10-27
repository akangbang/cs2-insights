# Halftime

A decision coach for CS2: it grades your decisions, not just your aim.

Most stat sites report what happened. Halftime answers "what should I have done?". It parses your match demos round by round and grades every force-or-save call by simulating both choices. For example:

> **Round 9: should have forced.** You saved with $3,110 each against their full buy. Over rounds 9–12, forcing wins about 1.4 rounds and saving about 1.1. A force wins this round 29% of the time against their buy, an eco only 9%. Cost: about 0.3 rounds.

## Features
- **Match report.** Pick one of your CS2 replays or upload a demo (`.dem`, or FACEIT's compressed `.dem.gz` / `.dem.zst`), then choose your player.
  - **Every buy call graded:** "Good call", "Close call", "Should have forced" or "Should have saved", with the rounds each wrong call cost.
  - **Rounds won vs. expected:** compares your score with what your buys would usually win.
  - **Key moments:** the costliest calls, your best call, split buys and big upsets.
  - **Economy chart and round table:** both teams' equipment, buy types and matchup win rates, round by round.
- **Your habits.** Patterns across all your stored matches, ranked by rounds lost per match. For example: *"You save after a lost pistol when you should force: 4 of your 4 saves were the wrong call."* Also flags split buys and money left unspent before half-time.
- **Add all replays.** One click loads every demo in your CS2 replays folder into the stats.
- Privacy and Terms pages; light and dark mode.

## How it works
1. **Parse.** demoparser2 reads each round's money, equipment and spending for every player.
2. **Win chance.** A curve fitted to every stored round estimates how often a team wins, given its equipment and the other team's (`rates.py`).
3. **Grade.** Each round where you could force but not full-buy is played forward up to four rounds, stopping at half-time or match point, once for forcing and once for saving. The simulation uses CS2's money rules: loss bonus, win reward and the gear you keep. The choice that wins more rounds is the right call (`grade.py`).
4. **Habits.** Graded calls from all your matches are grouped by situation (after a lost pistol, mid-half, last round of a half) (`habits.py`).

Stored matches live in PostgreSQL, and every match you open joins the pool the estimates are fitted to.

**Early beta:** the pool is small, and the model leaves out kills, players alive and utility. Treat verdicts as a guide, not gospel.

## Stack
Python (demoparser2, pandas, NumPy), PostgreSQL, Streamlit + Altair. Planned: Power BI, Excel, AWS hosting.

## Setup (Windows, PowerShell)
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
copy .env.example .env      # then fill in the keys
docker compose up -d        # local PostgreSQL (the app also runs without it, using one match only)
python -m pytest            # everything should pass
```

## Usage
```powershell
# The app: match reports and your habits
streamlit run app.py

# Load demo files you already have (.dem, .dem.bz2, .dem.gz, .dem.zst; files or folders)
python -m cs2_insights.ingest "C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\replays"

# Link a player's Valve match history to see which matches are ready to analyze
python -m cs2_insights.link add https://steamcommunity.com/id/<name> CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx
```

## Project layout
| Path | What it does |
|---|---|
| `app.py` | Streamlit app: match report, habits, legal pages |
| `src/cs2_insights/demo.py` | Demo parsing into round, team and player tables |
| `src/cs2_insights/report.py` | Per-match report and key moments |
| `src/cs2_insights/grade.py` | Force-or-save grader (money simulation) |
| `src/cs2_insights/habits.py` | Patterns across matches |
| `src/cs2_insights/rates.py` | Pooled win rates and the equipment win curve |
| `src/cs2_insights/db.py`, `ingest.py` | PostgreSQL storage and bulk loading |
| `sql/schema.sql` | Database schema |
| `legal/` | Privacy policy and terms (drafts) |

---
Not affiliated with or endorsed by Valve Corporation. Counter-Strike and CS2 are trademarks of Valve Corporation.
