BEGIN;

-- Install atomically with deterministic backfill; no content writer can miss a bump.
LOCK TABLE sessions, session_seats, seats, venue_zones IN ACCESS EXCLUSIVE MODE;
CREATE TABLE session_layout_revisions (
    session_id TEXT PRIMARY KEY,
    revision BIGINT NOT NULL CHECK (revision > 0)
);
-- Tombstones deliberately survive Session deletion: reusing an ID cannot reuse a tag.
INSERT INTO session_layout_revisions SELECT id, 1 FROM sessions ORDER BY id;

CREATE FUNCTION bump_session_layout_revisions(affected TEXT[]) RETURNS VOID
LANGUAGE plpgsql AS $$
BEGIN
    -- Deterministic lock order for a static correction spanning multiple Sessions.
    PERFORM session_id FROM session_layout_revisions
      WHERE session_id = ANY(affected) ORDER BY session_id FOR UPDATE;
    UPDATE session_layout_revisions SET revision = revision + 1
      WHERE session_id = ANY(affected);
END $$;

CREATE FUNCTION maintain_session_layout_identity() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO session_layout_revisions(session_id,revision)
          SELECT id,1 FROM new_rows ORDER BY id
          ON CONFLICT(session_id) DO UPDATE
          SET revision=session_layout_revisions.revision+1;
    ELSIF TG_OP = 'UPDATE' THEN
        -- No hall/time/status invalidation: these are not in the Layout body.
        INSERT INTO session_layout_revisions(session_id,revision)
          SELECT n.id,1 FROM new_rows n LEFT JOIN old_rows o ON o.id=n.id
          WHERE o.id IS NULL ORDER BY n.id
          ON CONFLICT(session_id) DO UPDATE
          SET revision=session_layout_revisions.revision+1;
        PERFORM bump_session_layout_revisions(ARRAY(
          SELECT n.id FROM new_rows n JOIN old_rows o ON o.id=n.id
          WHERE (n.venue_id,n.event_id,n.created_at)
             IS DISTINCT FROM (o.venue_id,o.event_id,o.created_at)));
    ELSE
        PERFORM bump_session_layout_revisions(ARRAY(SELECT id FROM old_rows));
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER layout_sessions_insert AFTER INSERT ON sessions
 REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_session_layout_identity();
CREATE TRIGGER layout_sessions_update AFTER UPDATE ON sessions
 REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_session_layout_identity();
CREATE TRIGGER layout_sessions_delete AFTER DELETE ON sessions
 REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_session_layout_identity();

-- Compare only the projection used by Layout, never occupancy/version/reservation fields.
CREATE FUNCTION maintain_layout_session_seats() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        PERFORM bump_session_layout_revisions(ARRAY(
          WITH changed AS (
            (SELECT id,session_id,seat_id,venue_id,price FROM new_rows EXCEPT SELECT id,session_id,seat_id,venue_id,price FROM old_rows)
            UNION
            (SELECT id,session_id,seat_id,venue_id,price FROM old_rows EXCEPT SELECT id,session_id,seat_id,venue_id,price FROM new_rows)
          ) SELECT DISTINCT session_id FROM changed));
    ELSIF TG_OP = 'INSERT' THEN
        PERFORM bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,session_id,seat_id,venue_id,price FROM new_rows) SELECT DISTINCT session_id FROM changed));
    ELSE
        PERFORM bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,session_id,seat_id,venue_id,price FROM old_rows) SELECT DISTINCT session_id FROM changed));
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER layout_session_seats_insert AFTER INSERT ON session_seats
 REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_layout_session_seats();
CREATE TRIGGER layout_session_seats_update AFTER UPDATE ON session_seats
 REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_layout_session_seats();
CREATE TRIGGER layout_session_seats_delete AFTER DELETE ON session_seats
 REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_layout_session_seats();

-- Compare only the projection used by Layout, never occupancy/version/reservation fields.
CREATE FUNCTION maintain_layout_seats() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        PERFORM bump_session_layout_revisions(ARRAY(
          WITH changed AS (
            (SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM new_rows EXCEPT SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM old_rows)
            UNION
            (SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM old_rows EXCEPT SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM new_rows)
          ) SELECT DISTINCT i.session_id FROM session_seats i JOIN changed c ON c.id=i.seat_id));
    ELSIF TG_OP = 'INSERT' THEN
        PERFORM bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM new_rows) SELECT DISTINCT i.session_id FROM session_seats i JOIN changed c ON c.id=i.seat_id));
    ELSE
        PERFORM bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM old_rows) SELECT DISTINCT i.session_id FROM session_seats i JOIN changed c ON c.id=i.seat_id));
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER layout_seats_insert AFTER INSERT ON seats
 REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_layout_seats();
CREATE TRIGGER layout_seats_update AFTER UPDATE ON seats
 REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_layout_seats();
CREATE TRIGGER layout_seats_delete AFTER DELETE ON seats
 REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_layout_seats();

-- Compare only the projection used by Layout, never occupancy/version/reservation fields.
CREATE FUNCTION maintain_layout_venue_zones() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        PERFORM bump_session_layout_revisions(ARRAY(
          WITH changed AS (
            (SELECT id,venue_id,name,sort_order FROM new_rows EXCEPT SELECT id,venue_id,name,sort_order FROM old_rows)
            UNION
            (SELECT id,venue_id,name,sort_order FROM old_rows EXCEPT SELECT id,venue_id,name,sort_order FROM new_rows)
          ) SELECT DISTINCT i.session_id FROM session_seats i JOIN seats s ON s.id=i.seat_id JOIN changed c ON c.id=s.zone_id AND c.venue_id=s.venue_id));
    ELSIF TG_OP = 'INSERT' THEN
        PERFORM bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,venue_id,name,sort_order FROM new_rows) SELECT DISTINCT i.session_id FROM session_seats i JOIN seats s ON s.id=i.seat_id JOIN changed c ON c.id=s.zone_id AND c.venue_id=s.venue_id));
    ELSE
        PERFORM bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,venue_id,name,sort_order FROM old_rows) SELECT DISTINCT i.session_id FROM session_seats i JOIN seats s ON s.id=i.seat_id JOIN changed c ON c.id=s.zone_id AND c.venue_id=s.venue_id));
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER layout_venue_zones_insert AFTER INSERT ON venue_zones
 REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_layout_venue_zones();
CREATE TRIGGER layout_venue_zones_update AFTER UPDATE ON venue_zones
 REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_layout_venue_zones();
CREATE TRIGGER layout_venue_zones_delete AFTER DELETE ON venue_zones
 REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT EXECUTE FUNCTION maintain_layout_venue_zones();

-- TRUNCATE ... CASCADE also changes the represented inventory. Capture affected
-- Sessions before rows disappear (Seat/Zone truncation cascades to this table).
CREATE FUNCTION maintain_layout_inventory_truncate() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM bump_session_layout_revisions(ARRAY(SELECT DISTINCT session_id FROM session_seats));
    RETURN NULL;
END $$;
CREATE TRIGGER layout_inventory_truncate BEFORE TRUNCATE ON session_seats
 FOR EACH STATEMENT EXECUTE FUNCTION maintain_layout_inventory_truncate();

COMMIT;
