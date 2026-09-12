BEGIN;
ALTER TABLE events ADD COLUMN sales_starts_at TIMESTAMPTZ,
                   ADD COLUMN sales_ends_at TIMESTAMPTZ;
UPDATE events AS event SET sales_ends_at=COALESCE(
    (SELECT MAX(session.start_time) FROM sessions AS session WHERE session.event_id=event.id),
    event.created_at + INTERVAL '1 second');
UPDATE events SET sales_starts_at=LEAST(created_at,sales_ends_at-INTERVAL '1 second');
ALTER TABLE events ADD CONSTRAINT events_sales_window_check CHECK(sales_starts_at<sales_ends_at),
                   ALTER COLUMN sales_starts_at SET NOT NULL,
                   ALTER COLUMN sales_ends_at SET NOT NULL;
COMMIT;
