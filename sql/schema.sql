-- Star schema for parsed demos. Safe to run repeatedly.

CREATE TABLE IF NOT EXISTS players (
    steamid      text PRIMARY KEY,
    last_name    text,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS matches (
    match_id       text PRIMARY KEY,
    source         text NOT NULL CHECK (source IN ('valve', 'upload', 'faceit', 'leetify')),
    map            text,
    server         text,
    patch_version  text,
    rounds         integer NOT NULL,
    team_a_score   integer NOT NULL,
    team_b_score   integer NOT NULL,
    demo_file      text,
    parser_version integer NOT NULL DEFAULT 1,
    parsed_at      timestamptz NOT NULL DEFAULT now()
);
-- Databases created before parser versions existed.
ALTER TABLE matches ADD COLUMN IF NOT EXISTS parser_version integer NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS rounds (
    match_id         text NOT NULL REFERENCES matches ON DELETE CASCADE,
    round            integer NOT NULL,
    freeze_end_tick  integer NOT NULL,
    end_tick         integer NOT NULL,
    winner_side      text NOT NULL CHECK (winner_side IN ('CT', 'T')),
    reason           text,
    PRIMARY KEY (match_id, round)
);

CREATE TABLE IF NOT EXISTS team_rounds (
    match_id           text NOT NULL,
    round              integer NOT NULL,
    team               text NOT NULL CHECK (team IN ('A', 'B')),
    side               text NOT NULL CHECK (side IN ('CT', 'T')),
    players            integer NOT NULL,
    equip_value        integer NOT NULL,
    bank               integer NOT NULL,
    start_equip_value  integer NOT NULL,
    cash_spent         integer NOT NULL,
    won                boolean NOT NULL,
    score              integer NOT NULL,
    opponent_score     integer NOT NULL,
    buy_type           text NOT NULL CHECK (buy_type IN ('pistol', 'eco', 'force', 'full')),
    PRIMARY KEY (match_id, round, team),
    FOREIGN KEY (match_id, round) REFERENCES rounds ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS player_rounds (
    match_id           text NOT NULL,
    round              integer NOT NULL,
    steamid            text NOT NULL REFERENCES players,
    team               text NOT NULL CHECK (team IN ('A', 'B')),
    side               text NOT NULL CHECK (side IN ('CT', 'T')),
    balance            integer NOT NULL,
    equip_value        integer NOT NULL,
    start_equip_value  integer NOT NULL,
    cash_spent         integer NOT NULL,
    armor              integer NOT NULL,
    has_helmet         boolean NOT NULL,
    has_defuser        boolean NOT NULL,
    PRIMARY KEY (match_id, round, steamid),
    FOREIGN KEY (match_id, round) REFERENCES rounds ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS player_rounds_steamid ON player_rounds (steamid);

-- Every death during live play, with what's needed to judge it (demo.parse_fights).
CREATE TABLE IF NOT EXISTS deaths (
    match_id       text NOT NULL,
    round          integer NOT NULL,
    tick           integer NOT NULL,
    round_seconds  real NOT NULL,
    victim         text NOT NULL,
    killer         text,
    victim_team    text NOT NULL CHECK (victim_team IN ('A', 'B')),
    killer_team    text CHECK (killer_team IN ('A', 'B')),
    weapon         text,
    headshot       boolean NOT NULL,
    victim_place   text,
    killer_place   text,
    victim_equip   integer NOT NULL,
    victim_blind   boolean NOT NULL,
    victim_speed   real,
    victim_x       real,
    victim_y       real,
    killer_x       real,
    killer_y       real,
    team_alive     integer NOT NULL,
    enemies_alive  integer NOT NULL,
    bomb_planted   boolean NOT NULL,
    traded_by      text,
    trade_seconds  real,
    PRIMARY KEY (match_id, tick, victim),
    FOREIGN KEY (match_id, round) REFERENCES rounds ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS deaths_victim ON deaths (victim);
-- Added with parser version 3.
ALTER TABLE deaths ADD COLUMN IF NOT EXISTS plant_seconds real;
ALTER TABLE deaths ADD COLUMN IF NOT EXISTS unused_utility integer NOT NULL DEFAULT 0;

-- Where each living teammate of the victim stood and aimed at the moment of a death.
CREATE TABLE IF NOT EXISTS trade_chances (
    match_id            text NOT NULL,
    round               integer NOT NULL,
    tick                integer NOT NULL,
    victim              text NOT NULL,
    mate                text NOT NULL,
    distance_to_killer  real NOT NULL,
    distance_to_victim  real,
    aim_angle           real NOT NULL,
    mate_x              real,
    mate_y              real,
    mate_yaw            real,
    PRIMARY KEY (match_id, tick, victim, mate),
    FOREIGN KEY (match_id, tick, victim) REFERENCES deaths ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS trade_chances_mate ON trade_chances (mate);

-- Grenades and flashes per player per round (demo.parse_utility).
CREATE TABLE IF NOT EXISTS player_utility (
    match_id             text NOT NULL,
    round                integer NOT NULL,
    steamid              text NOT NULL,
    flashes              integer NOT NULL,
    smokes               integer NOT NULL,
    hes                  integer NOT NULL,
    molotovs             integer NOT NULL,
    enemies_blinded      integer NOT NULL,
    enemy_blind_seconds  real NOT NULL,
    teammates_blinded    integer NOT NULL,
    utility_damage       integer NOT NULL,
    PRIMARY KEY (match_id, round, steamid),
    FOREIGN KEY (match_id, round) REFERENCES rounds ON DELETE CASCADE
);

-- Every flash that blinded someone for a second or more.
CREATE TABLE IF NOT EXISTS blinds (
    match_id  text NOT NULL,
    round     integer NOT NULL,
    tick      integer NOT NULL,
    thrower   text NOT NULL,
    blinded   text NOT NULL,
    seconds   real NOT NULL,
    teammate  boolean NOT NULL,
    PRIMARY KEY (match_id, tick, thrower, blinded),
    FOREIGN KEY (match_id, round) REFERENCES rounds ON DELETE CASCADE
);

-- Product usage: what gets used, for the business dashboards. No names, IPs or device details.
CREATE TABLE IF NOT EXISTS app_events (
    event_id    bigserial PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    session_id  text NOT NULL,   -- random per browser session
    event       text NOT NULL,   -- e.g. report_viewed
    steamid     text,            -- the player being reviewed, when there is one
    match_id    text,
    detail      text
);
CREATE INDEX IF NOT EXISTS app_events_event ON app_events (event, occurred_at);
-- The logged-in account (a hash) in hosted mode; 'local' on your own PC.
ALTER TABLE app_events ADD COLUMN IF NOT EXISTS user_id text;

-- Which user added which match, for hosted mode. No foreign key on purpose: re-parsing a match
-- deletes and re-inserts it, and that must not cost its owners their access.
CREATE TABLE IF NOT EXISTS user_matches (
    user_id   text NOT NULL,
    match_id  text NOT NULL,
    added_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, match_id)
);

-- App settings that should survive restarts, e.g. which player "me" is.
CREATE TABLE IF NOT EXISTS settings (
    key    text PRIMARY KEY,
    value  text NOT NULL
);

-- Players who linked their Valve match history.
CREATE TABLE IF NOT EXISTS linked_accounts (
    steamid          text PRIMARY KEY,
    auth_code        text NOT NULL,
    last_share_code  text NOT NULL,
    linked_at        timestamptz NOT NULL DEFAULT now(),
    last_synced_at   timestamptz
);

-- Every share code found, and how far its demo has got.
CREATE TABLE IF NOT EXISTS share_codes (
    share_code   text PRIMARY KEY,
    match_id     text NOT NULL,
    outcome_id   text NOT NULL,
    tv_port      integer NOT NULL,
    steamid      text NOT NULL,
    status       text NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'fetched', 'parsed', 'failed', 'expired')),
    demo_url     text,
    error        text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS share_codes_status ON share_codes (status);

-- Option 1 from the proposal: plain conditional win rates by buy matchup, the sanity check
-- for the win-probability model.
CREATE OR REPLACE VIEW v_buy_matchup_win_rates AS
SELECT
    t.buy_type,
    o.buy_type        AS opponent_buy_type,
    t.side,
    count(*)          AS rounds,
    round(avg(t.won::int), 3) AS win_rate
FROM team_rounds t
JOIN team_rounds o
  ON o.match_id = t.match_id AND o.round = t.round AND o.team <> t.team
GROUP BY t.buy_type, o.buy_type, t.side;
