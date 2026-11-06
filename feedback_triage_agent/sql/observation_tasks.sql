-- Idempotent setup only: no deletion or rewriting of existing tasks.
CREATE TABLE IF NOT EXISTS fta_observation_tasks (
    namespace TEXT NOT NULL,
    task_id TEXT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    state JSONB NOT NULL CHECK (jsonb_typeof(state) = 'object'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (namespace, task_id)
);

