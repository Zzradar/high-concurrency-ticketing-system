BEGIN;

CREATE TABLE checkout_sessions (
    id                              TEXT PRIMARY KEY,
    user_id                         TEXT NOT NULL REFERENCES app_users(id),
    session_id                      TEXT NOT NULL REFERENCES sessions(id),
    status                          TEXT NOT NULL,
    active_confirm_idempotency_key  TEXT,
    reservation_id                  TEXT UNIQUE,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT checkout_sessions_status_check
        CHECK (status IN ('SELECTING', 'SUBMITTING', 'RESERVED', 'ABANDONED')),
    CONSTRAINT checkout_sessions_confirm_key_length_check
        CHECK (
            active_confirm_idempotency_key IS NULL
            OR char_length(active_confirm_idempotency_key) BETWEEN 1 AND 128
        ),
    CONSTRAINT checkout_sessions_state_shape_check CHECK (
        (status = 'SELECTING'
            AND active_confirm_idempotency_key IS NULL
            AND reservation_id IS NULL)
        OR (status = 'SUBMITTING'
            AND active_confirm_idempotency_key IS NOT NULL
            AND reservation_id IS NULL)
        OR (status = 'RESERVED'
            AND active_confirm_idempotency_key IS NOT NULL
            AND reservation_id IS NOT NULL)
        OR (status = 'ABANDONED'
            AND active_confirm_idempotency_key IS NULL
            AND reservation_id IS NULL)
    ),
    CONSTRAINT checkout_sessions_reservation_user_fk
        FOREIGN KEY (reservation_id, user_id)
        REFERENCES reservations(id, user_id),
    CONSTRAINT checkout_sessions_reservation_session_fk
        FOREIGN KEY (reservation_id, session_id)
        REFERENCES reservations(id, session_id),
    CONSTRAINT checkout_sessions_id_session_unique UNIQUE (id, session_id)
);

CREATE INDEX checkout_sessions_user_session_status_idx
    ON checkout_sessions(user_id, session_id, status, created_at DESC);
CREATE INDEX checkout_sessions_submitting_idx
    ON checkout_sessions(updated_at, id)
    WHERE status = 'SUBMITTING';

CREATE TABLE checkout_session_seats (
    checkout_session_id  TEXT NOT NULL,
    session_id           TEXT NOT NULL,
    session_seat_id      TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (checkout_session_id, session_seat_id),
    CONSTRAINT checkout_session_seats_session_fk
        FOREIGN KEY (checkout_session_id, session_id)
        REFERENCES checkout_sessions(id, session_id)
        ON DELETE CASCADE,
    CONSTRAINT checkout_session_seats_inventory_fk
        FOREIGN KEY (session_seat_id, session_id)
        REFERENCES session_seats(id, session_id)
);

CREATE INDEX checkout_session_seats_inventory_idx
    ON checkout_session_seats(session_seat_id);

COMMIT;
