CREATE TABLE IF NOT EXISTS traces (
    request_id        TEXT        NOT NULL,
    timestamp          TIMESTAMPTZ NOT NULL,
    outcome             TEXT        NOT NULL,
    branch              TEXT,
    latency_ms          FLOAT,
    factors             JSONB,
    injected_fault_id   TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_traces_timestamp_branch
    ON traces (timestamp, branch);

CREATE TABLE IF NOT EXISTS fault_scenarios (
    scenario_id        TEXT        PRIMARY KEY,
    fault_type          TEXT        NOT NULL,
    injected_at          TIMESTAMPTZ NOT NULL,
    affected_factor      TEXT        NOT NULL,
    affected_value       TEXT        NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS diagnoses (
    id                  SERIAL      PRIMARY KEY,
    scenario_id          TEXT        REFERENCES fault_scenarios(scenario_id),
    window_start          TIMESTAMPTZ NOT NULL,
    window_end             TIMESTAMPTZ NOT NULL,
    hypotheses              JSONB       NOT NULL,
    top1_correct             BOOLEAN,
    top3_correct              BOOLEAN,
    diagnosed_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
