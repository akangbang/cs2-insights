-- Star schema for Power BI, rebuilt by `python -m cs2_insights.analytics` (analytics.refresh).
-- The numbers come from the same Python logic as the app (fights.py, grade.py), so they always match it.
-- Safe to run repeatedly.

CREATE SCHEMA IF NOT EXISTS analytics;

-- Dimensions
CREATE TABLE IF NOT EXISTS analytics.dim_player (
    steamid  text PRIMARY KEY,
    name     text,
    matches  integer NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_match (
    match_id      text PRIMARY KEY,
    match_order   integer NOT NULL,  -- 1 = oldest stored match (Valve match IDs increase over time)
    map           text,
    rounds        integer NOT NULL,
    team_a_score  integer NOT NULL,
    team_b_score  integer NOT NULL,
    source        text,
    parsed_at     timestamptz
);

-- One row per player per match: the scorecard numbers.
CREATE TABLE IF NOT EXISTS analytics.fact_player_match (
    match_id               text NOT NULL,
    steamid                text NOT NULL,
    team                   text NOT NULL,
    won                    boolean NOT NULL,
    rounds                 integer NOT NULL,
    deaths                 integer,
    traded_deaths          integer,
    avoidable_deaths       integer,
    repeeks                integer,
    pushed_alone           integer,
    lost_gear              integer,
    rounds_lost_avoidable  real,
    coverage_chances       integer,
    coverage_set_up        integer,
    coverage_trades        integer,
    coverage_score         real,
    coverage_grade         text,
    grenades               integer,
    flashes                integer,
    enemies_flashed        integer,
    teammates_flashed      integer,
    utility_damage         integer,
    unused_utility_deaths  integer,
    clutches               integer,
    clutches_won           integer,
    clutch_mistakes        integer,
    opening_duels          integer,
    opening_wins           integer,
    buy_calls              integer,
    buy_calls_right        integer,
    buy_calls_wrong        integer,
    rounds_lost_calls      real,
    PRIMARY KEY (match_id, steamid)
);

-- Detail facts
CREATE TABLE IF NOT EXISTS analytics.fact_death (
    match_id     text NOT NULL,
    round        integer NOT NULL,
    tick         integer NOT NULL,
    steamid      text NOT NULL,   -- the player who died
    killer       text,
    side         text,
    place        text,
    verdict      text NOT NULL,   -- e.g. "Re-peeked after a kill"
    verdict_group text NOT NULL,  -- Traded / Avoidable / Teammates didn't trade / Lost a duel / Other
    cost         real NOT NULL,   -- drop in the team's round win chance
    PRIMARY KEY (match_id, tick, steamid)
);

CREATE TABLE IF NOT EXISTS analytics.fact_clutch (
    match_id    text NOT NULL,
    round       integer NOT NULL,
    steamid     text NOT NULL,
    side        text,
    enemies     integer NOT NULL,
    outcome     text NOT NULL,    -- Won / Died / Saved
    gear        integer NOT NULL,
    win_chance  real NOT NULL,
    save_value  real NOT NULL,
    verdict     text NOT NULL,
    PRIMARY KEY (match_id, round, steamid)
);

CREATE TABLE IF NOT EXISTS analytics.fact_opening (
    match_id  text NOT NULL,
    round     integer NOT NULL,
    steamid   text NOT NULL,
    won       boolean NOT NULL,
    place     text,
    side      text,
    weapon    text,
    PRIMARY KEY (match_id, round, steamid)
);

CREATE TABLE IF NOT EXISTS analytics.fact_buy_call (
    match_id    text NOT NULL,
    round       integer NOT NULL,
    team        text NOT NULL,
    made        text NOT NULL,    -- force / save
    money_each  integer NOT NULL,
    their_buy   text,
    grade       text NOT NULL,
    cost        real NOT NULL,
    PRIMARY KEY (match_id, round, team)
);

-- Business metrics: views over app_events (product usage), so they're always current.

CREATE OR REPLACE VIEW analytics.v_usage_daily AS
SELECT
    occurred_at::date                                      AS day,
    count(DISTINCT session_id)                             AS sessions,
    count(*) FILTER (WHERE event = 'report_viewed')        AS reports_viewed,
    count(DISTINCT steamid) FILTER (WHERE event = 'report_viewed') AS players_reviewed,
    count(*) FILTER (WHERE event = 'demo_uploaded')        AS demos_uploaded,
    coalesce(sum(detail::int) FILTER (WHERE event = 'replays_added'), 0) AS replays_added,
    count(*) FILTER (WHERE event = 'habits_viewed')        AS habits_views,
    count(DISTINCT user_id) FILTER (WHERE user_id <> 'local') AS active_accounts
FROM app_events
GROUP BY 1;

-- How far sessions get: opened the app -> viewed a report -> opened habits -> saved themselves.
CREATE OR REPLACE VIEW analytics.v_funnel AS
WITH s AS (
    SELECT session_id,
           bool_or(event = 'report_viewed') AS viewed_report,
           bool_or(event = 'habits_viewed') AS viewed_habits,
           bool_or(event = 'player_saved')  AS saved_player
    FROM app_events GROUP BY session_id
)
SELECT 1 AS step, 'Opened the app' AS stage, count(*) AS sessions FROM s
UNION ALL SELECT 2, 'Viewed a report', count(*) FILTER (WHERE viewed_report) FROM s
UNION ALL SELECT 3, 'Opened Your habits', count(*) FILTER (WHERE viewed_report AND viewed_habits) FROM s
UNION ALL SELECT 4, 'Saved themselves ("This is me")', count(*) FILTER (WHERE viewed_report AND saved_player) FROM s;

-- Which features get used, and by how many sessions.
CREATE OR REPLACE VIEW analytics.v_feature_use AS
SELECT event, count(*) AS uses, count(DISTINCT session_id) AS sessions, max(occurred_at) AS last_used
FROM app_events
GROUP BY event;

-- Weekly retention: people grouped by the week they first viewed a report, and how many came back each week after.
-- A person is their account when hosted, and the reviewed player on a local copy with no accounts.
CREATE OR REPLACE VIEW analytics.v_retention_weekly AS
WITH seen AS (
    SELECT DISTINCT
        CASE WHEN user_id IS NULL OR user_id = 'local' THEN steamid ELSE user_id END AS person,
        date_trunc('week', occurred_at)::date AS week
    FROM app_events WHERE event = 'report_viewed'
), first_seen AS (
    SELECT person, min(week) AS cohort_week FROM seen WHERE person IS NOT NULL GROUP BY person
)
SELECT f.cohort_week, (s.week - f.cohort_week) / 7 AS weeks_later, count(*) AS players
FROM seen s JOIN first_seen f USING (person)
GROUP BY 1, 2;

-- Power BI logs in with a role that can read this schema and nothing else: no raw usage events,
-- no Steam auth codes. Give a login this role with: GRANT analytics_reader TO <login>;
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_reader') THEN
        CREATE ROLE analytics_reader NOLOGIN;
    END IF;
END
$$;
GRANT USAGE ON SCHEMA analytics TO analytics_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO analytics_reader;
