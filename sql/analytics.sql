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
