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
    parsed_at      timestamptz NOT NULL DEFAULT now()
);

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
