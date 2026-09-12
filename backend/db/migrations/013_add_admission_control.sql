BEGIN;

-- Missing rows deliberately mean OFF; no historical event receives a capacity.
CREATE TABLE event_admission_policies (
    event_id TEXT PRIMARY KEY REFERENCES events(id),
    mode TEXT NOT NULL DEFAULT 'OFF' CHECK (mode IN ('OFF','OBSERVE','ENFORCED','PAUSED')),
    prequeue_seconds INTEGER NOT NULL CHECK (prequeue_seconds BETWEEN 0 AND 86400),
    max_active_users INTEGER NOT NULL CHECK (max_active_users BETWEEN 1 AND 1000000),
    admission_rate_per_second INTEGER NOT NULL CHECK (admission_rate_per_second BETWEEN 1 AND 100000),
    lease_seconds INTEGER NOT NULL CHECK (lease_seconds BETWEEN 10 AND 3600),
    policy_version BIGINT NOT NULL CHECK (policy_version BETWEEN 1 AND 9007199254740991),
    queue_generation TEXT NOT NULL CHECK (queue_generation ~ '^[a-f0-9]{32}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT NOT NULL REFERENCES app_users(id)
);
CREATE TABLE admission_policy_audit (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id),
    administrator_id TEXT NOT NULL REFERENCES app_users(id),
    action TEXT NOT NULL CHECK (action IN ('CREATE','UPDATE','RESET_GENERATION')),
    old_version BIGINT NOT NULL CHECK (old_version >= 0),
    new_version BIGINT NOT NULL CHECK (new_version = old_version + 1),
    old_policy JSONB NOT NULL CHECK (jsonb_typeof(old_policy) = 'object'),
    new_policy JSONB NOT NULL CHECK (jsonb_typeof(new_policy) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(event_id, new_version)
);
COMMIT;
