BEGIN;

ALTER TABLE app_users
    ADD COLUMN username TEXT,
    ADD COLUMN password_hash TEXT,
    ADD COLUMN status TEXT;

UPDATE app_users
SET username = CASE
        WHEN id = 'U-1001' THEN 'demo'
        WHEN id = 'U-SEED-HOLDER' THEN 'seed-holder'
        ELSE 'legacy-' || md5(id)
    END,
    password_hash = CASE
        WHEN id = 'U-1001' THEN '$argon2id$v=19$m=65536,t=2,p=1$tUON0+a+tW+XPmzdPL+RoA$OCRPrfDL//acztJL8FF4AhlFnL7GN03xL4mAsYextRo'
        ELSE '!disabled'
    END,
    status = CASE WHEN id = 'U-1001' THEN 'ACTIVE' ELSE 'DISABLED' END;

ALTER TABLE app_users
    ALTER COLUMN username SET NOT NULL,
    ALTER COLUMN password_hash SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ADD CONSTRAINT app_users_username_unique UNIQUE (username),
    ADD CONSTRAINT app_users_username_length_check
        CHECK (char_length(username) BETWEEN 3 AND 64),
    ADD CONSTRAINT app_users_username_canonical_check
        CHECK (username = lower(username)),
    ADD CONSTRAINT app_users_status_check
        CHECK (status IN ('ACTIVE', 'DISABLED'));

CREATE TABLE user_sessions (
    id                   TEXT PRIMARY KEY,
    user_id              TEXT NOT NULL REFERENCES app_users(id),
    token_hash           TEXT NOT NULL UNIQUE,
    created_at           TIMESTAMPTZ NOT NULL,
    last_seen_at         TIMESTAMPTZ NOT NULL,
    idle_expires_at      TIMESTAMPTZ NOT NULL,
    absolute_expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at           TIMESTAMPTZ,
    CONSTRAINT user_sessions_token_hash_shape_check
        CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT user_sessions_idle_expiry_check
        CHECK (idle_expires_at > created_at),
    CONSTRAINT user_sessions_absolute_expiry_check
        CHECK (absolute_expires_at > created_at),
    CONSTRAINT user_sessions_expiry_order_check
        CHECK (idle_expires_at <= absolute_expires_at),
    CONSTRAINT user_sessions_last_seen_check
        CHECK (last_seen_at >= created_at),
    CONSTRAINT user_sessions_revoked_at_check
        CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

CREATE INDEX user_sessions_user_created_idx
    ON user_sessions(user_id, created_at DESC);
CREATE INDEX user_sessions_active_expiry_idx
    ON user_sessions(idle_expires_at, absolute_expires_at)
    WHERE revoked_at IS NULL;

ALTER TABLE user_notifications
    DROP CONSTRAINT user_notifications_type_check,
    ADD CONSTRAINT user_notifications_type_check CHECK (type IN (
        'ORDER_CREATED',
        'PAYMENT_SUCCEEDED',
        'ORDER_CANCELLED',
        'ORDER_EXPIRED',
        'AUTO_REFUND_COMPLETED'
    ));

COMMIT;
