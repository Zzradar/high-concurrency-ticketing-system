BEGIN;

ALTER TABLE session_seats
    ADD COLUMN formal_version BIGINT NOT NULL DEFAULT 0,
    ADD CONSTRAINT session_seats_formal_version_nonnegative CHECK (formal_version >= 0);

-- Deliberately no FK: queued projection events must not change inventory deletion semantics.
CREATE TABLE seat_availability_outbox (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    session_seat_id TEXT NOT NULL,
    formal_status TEXT NOT NULL CHECK (formal_status IN ('AVAILABLE', 'HELD', 'SOLD')),
    formal_version BIGINT NOT NULL CHECK (formal_version >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_token TEXT,
    lease_until TIMESTAMPTZ,
    CONSTRAINT seat_availability_outbox_seat_version_unique UNIQUE (session_seat_id, formal_version),
    CONSTRAINT seat_availability_outbox_lease_pair CHECK ((lease_token IS NULL) = (lease_until IS NULL))
);
CREATE INDEX seat_availability_outbox_unleased_idx ON seat_availability_outbox(id) WHERE lease_until IS NULL;
CREATE INDEX seat_availability_outbox_expired_lease_idx ON seat_availability_outbox(lease_until, id) WHERE lease_until IS NOT NULL;

CREATE FUNCTION advance_seat_formal_version() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.formal_version := OLD.formal_version + 1;
    RETURN NEW;
END;
$$;
CREATE TRIGGER session_seats_advance_formal_version
    BEFORE UPDATE OF status ON session_seats
    FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION advance_seat_formal_version();

CREATE FUNCTION enqueue_seat_availability_change() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO seat_availability_outbox(session_id, session_seat_id, formal_status, formal_version)
    VALUES (NEW.session_id, NEW.id, NEW.status, NEW.formal_version);
    RETURN NEW;
END;
$$;
CREATE TRIGGER session_seats_enqueue_availability
    AFTER UPDATE OF status ON session_seats
    FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION enqueue_seat_availability_change();

COMMIT;
