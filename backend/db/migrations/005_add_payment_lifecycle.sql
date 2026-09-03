BEGIN;

CREATE TABLE payment_attempts (
    id                     TEXT PRIMARY KEY,
    order_id               TEXT NOT NULL REFERENCES orders(id),
    status                 TEXT NOT NULL,
    started_at             TIMESTAMPTZ NOT NULL,
    processing_deadline    TIMESTAMPTZ NOT NULL,
    scheduled_complete_at  TIMESTAMPTZ NOT NULL,
    completed_at           TIMESTAMPTZ,
    timed_out_at           TIMESTAMPTZ,
    accepted_at            TIMESTAMPTZ,
    failure_reason         TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT payment_attempts_status_check
        CHECK (status IN ('PROCESSING', 'SUCCEEDED', 'FAILED', 'TIMED_OUT')),
    CONSTRAINT payment_attempts_deadline_check
        CHECK (processing_deadline > started_at),
    CONSTRAINT payment_attempts_schedule_check
        CHECK (scheduled_complete_at >= started_at),
    CONSTRAINT payment_attempts_state_shape_check CHECK (
        (status = 'PROCESSING'
            AND completed_at IS NULL
            AND timed_out_at IS NULL
            AND accepted_at IS NULL
            AND failure_reason IS NULL)
        OR (status = 'TIMED_OUT'
            AND completed_at IS NULL
            AND timed_out_at IS NOT NULL
            AND accepted_at IS NULL
            AND failure_reason IS NULL)
        OR (status = 'FAILED'
            AND completed_at IS NOT NULL
            AND accepted_at IS NULL
            AND failure_reason IS NOT NULL)
        OR (status = 'SUCCEEDED'
            AND completed_at IS NOT NULL
            AND failure_reason IS NULL)
    ),
    CONSTRAINT payment_attempts_accepted_status_check
        CHECK (accepted_at IS NULL OR status = 'SUCCEEDED'),
    CONSTRAINT payment_attempts_id_order_unique UNIQUE (id, order_id)
);

CREATE UNIQUE INDEX payment_attempts_one_processing_per_order_idx
    ON payment_attempts(order_id)
    WHERE status = 'PROCESSING';
CREATE INDEX payment_attempts_order_created_idx
    ON payment_attempts(order_id, created_at DESC);
CREATE INDEX payment_attempts_processing_deadline_idx
    ON payment_attempts(processing_deadline)
    WHERE status = 'PROCESSING';

CREATE TABLE refunds (
    id                  TEXT PRIMARY KEY,
    payment_attempt_id  TEXT NOT NULL UNIQUE,
    order_id            TEXT NOT NULL,
    amount              BIGINT NOT NULL,
    reason              TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    refunded_at         TIMESTAMPTZ NOT NULL,
    CONSTRAINT refunds_attempt_order_fk
        FOREIGN KEY (payment_attempt_id, order_id)
        REFERENCES payment_attempts(id, order_id),
    CONSTRAINT refunds_order_fk
        FOREIGN KEY (order_id) REFERENCES orders(id),
    CONSTRAINT refunds_amount_positive_check CHECK (amount > 0),
    CONSTRAINT refunds_reason_check CHECK (reason IN (
        'ORDER_CANCELLED_BEFORE_PAYMENT_CONFIRMATION',
        'ORDER_EXPIRED_BEFORE_PAYMENT_CONFIRMATION',
        'DUPLICATE_LATE_PAYMENT',
        'PAYMENT_NOT_ACCEPTED'
    ))
);

CREATE INDEX refunds_order_created_idx ON refunds(order_id, created_at DESC);

CREATE TABLE user_notifications (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES app_users(id),
    order_id    TEXT NOT NULL REFERENCES orders(id),
    type        TEXT NOT NULL,
    title       TEXT NOT NULL,
    message     TEXT NOT NULL,
    dedupe_key  TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at     TIMESTAMPTZ,
    CONSTRAINT user_notifications_type_check CHECK (type IN (
        'PAYMENT_SUCCEEDED',
        'ORDER_CANCELLED',
        'ORDER_EXPIRED',
        'AUTO_REFUND_COMPLETED'
    ))
);

CREATE INDEX user_notifications_user_created_idx
    ON user_notifications(user_id, created_at DESC);
CREATE INDEX user_notifications_user_read_idx
    ON user_notifications(user_id, read_at);

COMMIT;
