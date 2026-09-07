BEGIN;

ALTER TABLE payment_attempts
    ALTER COLUMN scheduled_complete_at DROP NOT NULL,
    DROP CONSTRAINT payment_attempts_schedule_check,
    ADD COLUMN provider TEXT NOT NULL DEFAULT 'simulation',
    ADD COLUMN provider_payment_id TEXT,
    ADD COLUMN provider_status TEXT,
    ADD COLUMN provider_last_sync_at TIMESTAMPTZ,
    ADD COLUMN provider_terminal_at TIMESTAMPTZ,
    ADD COLUMN provider_retry_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN next_reconcile_at TIMESTAMPTZ,
    ADD CONSTRAINT payment_attempts_schedule_check CHECK (
        scheduled_complete_at IS NULL OR scheduled_complete_at >= started_at
    ),
    ADD CONSTRAINT payment_attempts_provider_retry_check CHECK (provider_retry_count >= 0),
    ADD CONSTRAINT payment_attempts_provider_terminal_check CHECK (
        provider_terminal_at IS NULL OR status IN ('SUCCEEDED', 'FAILED')
    );

CREATE UNIQUE INDEX payment_attempts_provider_payment_unique_idx
    ON payment_attempts(provider, provider_payment_id)
    WHERE provider_payment_id IS NOT NULL;
CREATE INDEX payment_attempts_reconcile_due_idx
    ON payment_attempts(next_reconcile_at)
    WHERE provider <> 'simulation'
      AND provider_terminal_at IS NULL
      AND status IN ('PROCESSING', 'TIMED_OUT');

UPDATE payment_attempts
SET provider_terminal_at = COALESCE(completed_at, timed_out_at, created_at),
    provider_status = lower(status)
WHERE status IN ('SUCCEEDED', 'FAILED');

ALTER TABLE refunds
    ALTER COLUMN refunded_at DROP NOT NULL,
    ADD COLUMN source TEXT NOT NULL DEFAULT 'SYSTEM',
    ADD COLUMN status TEXT NOT NULL DEFAULT 'SUCCEEDED',
    ADD COLUMN provider TEXT NOT NULL DEFAULT 'simulation',
    ADD COLUMN provider_refund_id TEXT,
    ADD COLUMN provider_status TEXT,
    ADD COLUMN failed_at TIMESTAMPTZ,
    ADD COLUMN failure_reason TEXT,
    ADD COLUMN provider_last_sync_at TIMESTAMPTZ,
    ADD COLUMN provider_terminal_at TIMESTAMPTZ,
    ADD COLUMN provider_retry_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN next_reconcile_at TIMESTAMPTZ,
    ADD CONSTRAINT refunds_source_check CHECK (source IN ('SYSTEM', 'BUYER')),
    ADD CONSTRAINT refunds_status_check CHECK (status IN ('PROCESSING', 'SUCCEEDED', 'FAILED')),
    ADD CONSTRAINT refunds_provider_retry_check CHECK (provider_retry_count >= 0),
    ADD CONSTRAINT refunds_state_shape_check CHECK (
        (status = 'PROCESSING' AND refunded_at IS NULL AND failed_at IS NULL)
        OR (status = 'SUCCEEDED' AND refunded_at IS NOT NULL AND failed_at IS NULL)
        OR (status = 'FAILED' AND refunded_at IS NULL AND failed_at IS NOT NULL
            AND failure_reason IS NOT NULL)
    ),
    ADD CONSTRAINT refunds_provider_terminal_check CHECK (
        provider_terminal_at IS NULL OR status IN ('SUCCEEDED', 'FAILED')
    );

CREATE UNIQUE INDEX refunds_provider_refund_unique_idx
    ON refunds(provider, provider_refund_id)
    WHERE provider_refund_id IS NOT NULL;
CREATE INDEX refunds_reconcile_due_idx
    ON refunds(next_reconcile_at)
    WHERE status = 'PROCESSING' AND provider_terminal_at IS NULL;

UPDATE refunds
SET provider_terminal_at = refunded_at,
    provider_status = 'succeeded'
WHERE status = 'SUCCEEDED';

CREATE TABLE payment_provider_events (
    id                  TEXT PRIMARY KEY,
    provider            TEXT NOT NULL,
    provider_event_id   TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    object_kind         TEXT NOT NULL,
    provider_object_id  TEXT,
    local_reference_id  TEXT,
    status              TEXT NOT NULL DEFAULT 'PENDING',
    received_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    processed_at        TIMESTAMPTZ,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    next_retry_at       TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_error          TEXT,
    payload_sha256      TEXT NOT NULL,
    CONSTRAINT payment_provider_events_provider_event_unique
        UNIQUE (provider, provider_event_id),
    CONSTRAINT payment_provider_events_kind_check
        CHECK (object_kind IN ('PAYMENT', 'REFUND')),
    CONSTRAINT payment_provider_events_status_check
        CHECK (status IN ('PENDING', 'PROCESSED', 'FAILED')),
    CONSTRAINT payment_provider_events_retry_check CHECK (retry_count >= 0),
    CONSTRAINT payment_provider_events_state_shape_check CHECK (
        (status = 'PENDING' AND processed_at IS NULL)
        OR (status = 'PROCESSED' AND processed_at IS NOT NULL AND last_error IS NULL)
        OR (status = 'FAILED' AND processed_at IS NOT NULL AND last_error IS NOT NULL)
    ),
    CONSTRAINT payment_provider_events_payload_hash_check
        CHECK (payload_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX payment_provider_events_pending_idx
    ON payment_provider_events(status, next_retry_at)
    WHERE status = 'PENDING';

ALTER TABLE user_notifications
    DROP CONSTRAINT user_notifications_type_check,
    ADD CONSTRAINT user_notifications_type_check CHECK (type IN (
        'ORDER_CREATED',
        'PAYMENT_SUCCEEDED',
        'ORDER_CANCELLED',
        'ORDER_EXPIRED',
        'AUTO_REFUND_COMPLETED',
        'AUTO_REFUND_FAILED'
    ));

COMMIT;
