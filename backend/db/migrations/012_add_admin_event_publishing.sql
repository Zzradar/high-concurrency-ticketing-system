BEGIN;

ALTER TABLE app_users ADD COLUMN role TEXT NOT NULL DEFAULT 'CUSTOMER';
ALTER TABLE app_users ADD CONSTRAINT app_users_role_check CHECK (role IN ('CUSTOMER', 'ADMIN'));

CREATE TABLE venue_zones (
    id TEXT PRIMARY KEY,
    venue_id TEXT NOT NULL REFERENCES venues(id),
    code TEXT NOT NULL CHECK (btrim(code) <> ''),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    sort_order INTEGER NOT NULL CHECK (sort_order >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (venue_id, code),
    UNIQUE (venue_id, name),
    UNIQUE (venue_id, sort_order),
    UNIQUE (id, venue_id)
);

-- Length-prefixed venue identity makes legacy IDs injective, without hash collisions.
-- Order uses the actual first (row_no, seat_no) pair in each Zone, then its name.
WITH first_seats AS (
    SELECT DISTINCT ON (venue_id, zone) venue_id, zone, row_no, seat_no
    FROM seats ORDER BY venue_id, zone, row_no, seat_no
), ordered AS (
    SELECT *, row_number() OVER (PARTITION BY venue_id ORDER BY row_no, seat_no, zone) - 1 AS position
    FROM first_seats
)
INSERT INTO venue_zones (id, venue_id, code, name, sort_order)
SELECT 'VZ-LEGACY-' || length(venue_id)::text || ':' || venue_id || ':' || zone,
       venue_id, 'LEGACY_' || position::text, zone, position::integer
FROM ordered;

ALTER TABLE seats ADD COLUMN zone_id TEXT;
UPDATE seats s SET zone_id = z.id FROM venue_zones z
WHERE z.venue_id = s.venue_id AND z.name = s.zone;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM seats WHERE zone_id IS NULL) THEN
        RAISE EXCEPTION 'Every legacy seat must map to exactly one venue Zone';
    END IF;
END $$;
ALTER TABLE seats ALTER COLUMN zone_id SET NOT NULL;
ALTER TABLE seats ADD CONSTRAINT seats_zone_venue_fk
    FOREIGN KEY (zone_id, venue_id) REFERENCES venue_zones(id, venue_id);
ALTER TABLE seats DROP CONSTRAINT seats_venue_position_unique;
ALTER TABLE seats DROP CONSTRAINT seats_venue_label_unique;
ALTER TABLE seats ADD CONSTRAINT seats_venue_zone_position_unique UNIQUE (venue_id, zone_id, row_no, seat_no);
ALTER TABLE seats ADD CONSTRAINT seats_venue_zone_label_unique UNIQUE (venue_id, zone_id, seat_label);
DROP INDEX seats_venue_row_number_idx;
CREATE INDEX seats_venue_zone_row_number_idx ON seats(venue_id, zone_id, row_no, seat_no);
ALTER TABLE seats DROP COLUMN zone;

ALTER TABLE events DROP CONSTRAINT events_status_check;
ALTER TABLE events ADD CONSTRAINT events_status_check CHECK (status IN ('DRAFT', 'ON_SALE', 'COMING_SOON'));
ALTER TABLE sessions DROP CONSTRAINT sessions_status_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_status_check CHECK (status IN ('DRAFT', 'ON_SALE', 'SOLD_OUT'));
ALTER TABLE events ADD COLUMN published_at TIMESTAMPTZ;
ALTER TABLE events ADD COLUMN published_by TEXT REFERENCES app_users(id);

CREATE TABLE session_zone_prices (
    session_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    venue_id TEXT NOT NULL,
    price BIGINT NOT NULL CHECK (price > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, zone_id),
    FOREIGN KEY (session_id, venue_id) REFERENCES sessions(id, venue_id) ON DELETE CASCADE,
    FOREIGN KEY (zone_id, venue_id) REFERENCES venue_zones(id, venue_id) ON DELETE CASCADE
);

COMMIT;
