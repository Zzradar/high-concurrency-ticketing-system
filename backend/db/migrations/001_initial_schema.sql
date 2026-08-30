BEGIN;

CREATE TABLE venues (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    city        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE app_users (
    id            TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE events (
    id                TEXT PRIMARY KEY,
    primary_venue_id  TEXT NOT NULL REFERENCES venues(id),
    name              TEXT NOT NULL,
    description       TEXT NOT NULL,
    status            TEXT NOT NULL,
    category          TEXT NOT NULL,
    cover_url         TEXT NOT NULL,
    date_range        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT events_status_check
        CHECK (status IN ('ON_SALE', 'COMING_SOON'))
);

CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,
    event_id    TEXT NOT NULL REFERENCES events(id),
    venue_id    TEXT NOT NULL REFERENCES venues(id),
    hall_name   TEXT NOT NULL,
    start_time  TIMESTAMPTZ NOT NULL,
    gate_time   TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT sessions_status_check
        CHECK (status IN ('ON_SALE', 'SOLD_OUT')),
    CONSTRAINT sessions_gate_before_start_check
        CHECK (gate_time < start_time),
    CONSTRAINT sessions_id_venue_unique UNIQUE (id, venue_id)
);

CREATE INDEX sessions_event_start_idx ON sessions(event_id, start_time);

CREATE TABLE seats (
    id          TEXT PRIMARY KEY,
    venue_id    TEXT NOT NULL REFERENCES venues(id),
    row_no      TEXT NOT NULL,
    seat_no     INTEGER NOT NULL,
    seat_label  TEXT NOT NULL,
    zone        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT seats_number_positive_check CHECK (seat_no > 0),
    CONSTRAINT seats_venue_position_unique UNIQUE (venue_id, row_no, seat_no),
    CONSTRAINT seats_venue_label_unique UNIQUE (venue_id, seat_label),
    CONSTRAINT seats_id_venue_unique UNIQUE (id, venue_id)
);

CREATE INDEX seats_venue_row_number_idx ON seats(venue_id, row_no, seat_no);

CREATE TABLE reservations (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES app_users(id),
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    status      TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT reservations_status_check
        CHECK (status IN ('ACTIVE', 'CONFIRMED', 'CANCELLED', 'EXPIRED')),
    CONSTRAINT reservations_expiry_check CHECK (expires_at > created_at),
    CONSTRAINT reservations_id_session_unique UNIQUE (id, session_id),
    CONSTRAINT reservations_id_user_unique UNIQUE (id, user_id)
);

CREATE INDEX reservations_user_created_idx
    ON reservations(user_id, created_at DESC);
CREATE INDEX reservations_active_expiry_idx
    ON reservations(expires_at)
    WHERE status = 'ACTIVE';

CREATE TABLE session_seats (
    id                      TEXT PRIMARY KEY,
    session_id              TEXT NOT NULL,
    seat_id                 TEXT NOT NULL,
    venue_id                TEXT NOT NULL,
    status                  TEXT NOT NULL,
    price                   BIGINT NOT NULL,
    current_reservation_id  TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT session_seats_session_venue_fk
        FOREIGN KEY (session_id, venue_id)
        REFERENCES sessions(id, venue_id),
    CONSTRAINT session_seats_seat_venue_fk
        FOREIGN KEY (seat_id, venue_id)
        REFERENCES seats(id, venue_id),
    CONSTRAINT session_seats_current_reservation_fk
        FOREIGN KEY (current_reservation_id, session_id)
        REFERENCES reservations(id, session_id),
    CONSTRAINT session_seats_status_check
        CHECK (status IN ('AVAILABLE', 'HELD', 'SOLD')),
    CONSTRAINT session_seats_price_nonnegative_check CHECK (price >= 0),
    CONSTRAINT session_seats_hold_pointer_check CHECK (
        (status = 'AVAILABLE' AND current_reservation_id IS NULL)
        OR (status = 'HELD' AND current_reservation_id IS NOT NULL)
        OR status = 'SOLD'
    ),
    CONSTRAINT session_seats_session_seat_unique UNIQUE (session_id, seat_id),
    CONSTRAINT session_seats_id_session_unique UNIQUE (id, session_id)
);

CREATE INDEX session_seats_session_status_idx
    ON session_seats(session_id, status);
CREATE INDEX session_seats_current_reservation_idx
    ON session_seats(current_reservation_id)
    WHERE current_reservation_id IS NOT NULL;

CREATE TABLE reservation_session_seats (
    reservation_id  TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    session_seat_id TEXT NOT NULL,
    reserved_price  BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (reservation_id, session_seat_id),
    CONSTRAINT reservation_session_seats_reservation_fk
        FOREIGN KEY (reservation_id, session_id)
        REFERENCES reservations(id, session_id),
    CONSTRAINT reservation_session_seats_session_seat_fk
        FOREIGN KEY (session_seat_id, session_id)
        REFERENCES session_seats(id, session_id),
    CONSTRAINT reservation_session_seats_price_nonnegative_check
        CHECK (reserved_price >= 0)
);

CREATE INDEX reservation_session_seats_seat_idx
    ON reservation_session_seats(session_seat_id);

CREATE TABLE orders (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    reservation_id  TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL,
    total_amount    BIGINT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    paid_at         TIMESTAMPTZ,
    CONSTRAINT orders_user_fk
        FOREIGN KEY (user_id) REFERENCES app_users(id),
    CONSTRAINT orders_reservation_user_fk
        FOREIGN KEY (reservation_id, user_id)
        REFERENCES reservations(id, user_id),
    CONSTRAINT orders_status_check
        CHECK (status IN ('PENDING_PAYMENT', 'PAID', 'CANCELLED', 'EXPIRED')),
    CONSTRAINT orders_amount_nonnegative_check CHECK (total_amount >= 0),
    CONSTRAINT orders_expiry_check CHECK (expires_at > created_at),
    CONSTRAINT orders_paid_at_check CHECK (
        (status = 'PAID' AND paid_at IS NOT NULL)
        OR (status <> 'PAID' AND paid_at IS NULL)
    )
);

CREATE INDEX orders_user_created_idx ON orders(user_id, created_at DESC);
CREATE INDEX orders_pending_expiry_idx
    ON orders(expires_at)
    WHERE status = 'PENDING_PAYMENT';

COMMIT;
