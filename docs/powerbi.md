# Building the Getleanpeek Power BI dashboard

A step-by-step build of a three-page Power BI report on the `analytics` star schema. It takes about 45 minutes. Everything that needs code is already done: the tables, a read-only login, and every measure below.

What you'll have at the end:

1. **Player overview:** KPI cards, avoidable deaths match by match, and how a player compares with the pool.
2. **Where deaths happen:** callouts, sides and a scatter of every player in the pool.
3. **Economy and clutches:** force-or-save calls and clutch results.

## 1. Get the data ready

In PowerShell, from the project folder:

```powershell
docker compose up -d                                          # the local database
.venv\Scripts\python -m cs2_insights.analytics --powerbi-login  # rebuild the tables, refresh the Power BI login
```

The second command rebuilds every `analytics` table from the stored matches. It also gives the `powerbi` login a new password, saved in `.env` as `POWERBI_PASSWORD`. Open `.env` to copy it. The login can read the `analytics` schema and nothing else.

## 2. Connect

1. Open Power BI Desktop → **Get data** → **PostgreSQL database**.
2. Server: `localhost:5432`. Database: `decision_tracker`. Data connectivity mode: **Import**.
3. When asked for credentials, pick the **Database** tab. User name `powerbi`, password from `.env`.
4. In the Navigator, tick these and click **Transform Data**:
   `analytics.dim_match`, `analytics.dim_player`, `analytics.fact_player_match`, `analytics.fact_death`, `analytics.fact_clutch`, `analytics.fact_opening`, `analytics.fact_buy_call`.
5. In Power Query, select `analytics dim_player`, right-click the **name** column → **Remove**. The report then only has stand-in names (`stand_in`, for example "Player 417"), so screenshots are safe to post.
6. Rename the queries to drop the `analytics ` prefix (double-click each one), so they read `dim_match`, `fact_death` and so on. The measures below use those names.
7. **Close & Apply.**

## 3. Model

Open **Model view**. Power BI may create some relationships itself; make the list match this one, all **one-to-many**, **single** direction, from the dimension to the fact:

| From (one) | To (many) |
|---|---|
| `dim_player[steamid]` | `fact_player_match[steamid]`, `fact_death[steamid]`, `fact_clutch[steamid]`, `fact_opening[steamid]` |
| `dim_match[match_id]` | `fact_player_match[match_id]`, `fact_death[match_id]`, `fact_clutch[match_id]`, `fact_opening[match_id]`, `fact_buy_call[match_id]` |

`fact_buy_call` is per team, not per player, so it only joins to `dim_match`. That's a star schema: filters flow from the dimensions into the facts.

Then:

- Hide every `steamid` and `match_id` column in the facts (right-click → **Hide in report view**). Report builders should filter through the dimensions.
- Select `dim_match[match_order]` and set **Summarization** to **Don't summarize**, so it works as an axis.

## 4. Measures

**Home → Enter data**, name the table `_Measures`, load it, and delete its one column once the first measure is in. Then **New measure** for each of these. Set the format shown in brackets (**Measure tools → Format**).

```DAX
Matches = DISTINCTCOUNT ( fact_player_match[match_id] )                    -- whole number
Rounds Played = SUM ( fact_player_match[rounds] )                          -- whole number
Win Rate =                                                                  -- percentage
    DIVIDE (
        CALCULATE ( COUNTROWS ( fact_player_match ), fact_player_match[won] = TRUE () ),
        COUNTROWS ( fact_player_match )
    )
Deaths = SUM ( fact_player_match[deaths] )                                 -- whole number
Avoidable Deaths = SUM ( fact_player_match[avoidable_deaths] )             -- whole number
Avoidable Share = DIVIDE ( [Avoidable Deaths], [Deaths] )                  -- percentage
Avoidable per 12 Rounds = DIVIDE ( [Avoidable Deaths], [Rounds Played] ) * 12   -- decimal, 1 place
Traded Share = DIVIDE ( SUM ( fact_player_match[traded_deaths] ), [Deaths] )    -- percentage
Coverage Score = AVERAGE ( fact_player_match[coverage_score] )             -- percentage, 1 place
Opening Win Rate =                                                          -- percentage
    DIVIDE ( SUM ( fact_player_match[opening_wins] ), SUM ( fact_player_match[opening_duels] ) )
Clutch Win Rate =                                                           -- percentage
    DIVIDE ( SUM ( fact_player_match[clutches_won] ), SUM ( fact_player_match[clutches] ) )
Buy Call Accuracy =                                                         -- percentage
    DIVIDE ( SUM ( fact_player_match[buy_calls_right] ), SUM ( fact_player_match[buy_calls] ) )
Rounds Lost to Mistakes =                                                   -- decimal, 1 place
    SUM ( fact_player_match[rounds_lost_avoidable] ) + SUM ( fact_player_match[rounds_lost_calls] )
```

Comparing with the pool. `REMOVEFILTERS` ignores the player slicer, so this is every player in the stored matches:

```DAX
Pool Avoidable Share = CALCULATE ( [Avoidable Share], REMOVEFILTERS ( dim_player ) )   -- percentage
Avoidable vs Pool = [Avoidable Share] - [Pool Avoidable Share]                       -- percentage, +0.0%;-0.0%
```

A trend line that smooths out one bad match: the player's last 3 matches up to each point:

```DAX
Avoidable per 12 Rounds (3-match avg) =                                     -- decimal, 1 place
VAR CurrentOrder = MAX ( dim_match[match_order] )
-- The selected player's matches, ignoring which match this point of the chart is
VAR PlayerMatches =
    CALCULATETABLE ( VALUES ( fact_player_match[match_id] ), REMOVEFILTERS ( dim_match[match_order] ) )
VAR PlayerOrders =
    CALCULATETABLE (
        VALUES ( dim_match[match_order] ),
        REMOVEFILTERS ( dim_match[match_order] ),
        TREATAS ( PlayerMatches, dim_match[match_id] )
    )
VAR LastThree =
    TOPN ( 3, FILTER ( PlayerOrders, dim_match[match_order] <= CurrentOrder ), dim_match[match_order], DESC )
RETURN
    IF (
        ISBLANK ( [Avoidable per 12 Rounds] ),  -- no point where the player didn't play
        BLANK (),
        CALCULATE ( [Avoidable per 12 Rounds], TREATAS ( LastThree, dim_match[match_order] ) )
    )
```

And two for the death pages:

```DAX
Death Count = COUNTROWS ( fact_death )                                     -- whole number
Win Chance Lost = SUM ( fact_death[cost] )                                 -- decimal, 1 place (rounds)
```

### Check your numbers

Before building pages, drop each measure into a **Card** with no slicers set. On the 14 matches stored on November 17, 2026, they should read:

| Measure | Value |
|---|---|
| Matches | 14 |
| Win Rate | 50.0% (every match has a winner and a loser) |
| Avoidable Share | 25.8% |
| Avoidable per 12 Rounds | 2.15 |
| Buy Call Accuracy | 55.7% |
| Clutch Win Rate | 18.8% |
| Opening Win Rate | 50.0% (every opening duel has a winner and a loser) |
| Death Count | 1,887 |

If you've stored more matches since, the numbers will differ: check them against SQL instead (`SELECT sum(avoidable_deaths)::numeric / sum(deaths) FROM analytics.fact_player_match`). A measure that disagrees usually means a missing or two-way relationship.

## 5. Pages

Use the app's colours so the report and the site look like one product: **View → Themes → Customize current theme**, and set the first two data colours to `#2a78d6` (blue) and `#eb6834` (orange).

### Page 1: Player overview

- **Slicers** across the top: `dim_player[stand_in]` (Dropdown, single select) and `dim_match[map]` (Tile).
- **Cards** (or the new **Card** visual with several values): Matches, Win Rate, Avoidable Share, Coverage Score, Buy Call Accuracy.
- **Line chart:** X `dim_match[match_order]`, Y `Avoidable per 12 Rounds` and `Avoidable per 12 Rounds (3-match avg)`. Title: "Avoidable deaths per 12 rounds, match by match".
- **Card:** Avoidable vs Pool, with conditional formatting (**Format → Callout value → fx**): font colour red when above 0, green when below.
- **Clustered bar chart:** Y `fact_death[verdict_group]`, X `Death Count`. Title: "How your deaths happen".

### Page 2: Where deaths happen

- Same player slicer (select it on page 1, **View → Sync slicers**, tick page 2).
- **Bar chart:** Y `fact_death[place]`, X `Death Count`. Filter pane: `verdict_group` is `Avoidable`; `place` **Top N** 10 by `Death Count`. Title: "Where your avoidable deaths happen".
- **Matrix:** Rows `fact_death[side]`, Columns `fact_death[verdict_group]`, Values `Death Count`. Turn on **Cell elements → Background colour** for a heat map.
- **Scatter chart** of the whole pool: Values `dim_player[stand_in]`, X `Coverage Score`, Y `Avoidable Share`, Size `Matches`. Filter: `Matches` is greater than or equal to 2. Turn **Edit interactions** off for the player slicer on this visual, so it always shows everyone. Title: "Every player: covering teammates vs avoidable deaths".

### Page 3: Economy and clutches

- **Stacked bar chart:** Y `fact_buy_call[made]`, X count of `fact_buy_call[round]`, Legend `fact_buy_call[grade]`. Title: "Force or save: how the calls graded".
- **Card:** Buy Call Accuracy and Rounds Lost to Mistakes.
- **Stacked column chart:** X `fact_clutch[enemies]`, Y count of `fact_clutch[round]`, Legend `fact_clutch[outcome]`. Title: "Clutches by how many enemies were left".
- **Card:** Clutch Win Rate and Opening Win Rate.

## 6. Save and publish

1. **File → Save as**, choose **Power BI project (\*.pbip)**, and save it as `dashboards\getleanpeek.pbip` in the project folder. If that option is missing, turn it on under **File → Options and settings → Options → Preview features → Power BI Project (.pbip) save option**, then restart Power BI.
   A project is saved as text files: the model, every measure and the report layout, readable on GitHub. The data stays in a local cache that `.gitignore` keeps out of the repo, along with *.pbix files, so no Steam IDs or names are published.
2. Export each page as an image: **File → Export → Export to PDF**, or take a screenshot of each page, and save them as `docs/screenshots/powerbi-overview.png`, `powerbi-deaths.png` and `powerbi-economy.png`.
3. Commit the `dashboards/` folder and the screenshots.

## Talking about it

- **Data model:** a star schema with two dimensions and five fact tables, rebuilt by Python (`analytics.py`) from the same functions as the app, so the dashboard and the site never disagree.
- **Security:** Power BI logs in with a role that can read the `analytics` schema only: no raw usage events, no Steam auth codes.
- **DAX:** filter context with `CALCULATE`, ignoring a slicer with `REMOVEFILTERS` to compare with the pool, and a rolling window over each player's own matches with `TOPN` and `TREATAS`.
- **Privacy:** stand-in names in the model, real names removed in Power Query, and data left out of git.
