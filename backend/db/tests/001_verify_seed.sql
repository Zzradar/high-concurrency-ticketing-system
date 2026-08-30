DO $$
DECLARE
    event_count INTEGER;
    session_count INTEGER;
    physical_seat_count INTEGER;
    inventory_count INTEGER;
    invalid_inventory_count INTEGER;
    invalid_reservation_item_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO event_count FROM events;
    SELECT COUNT(*) INTO session_count FROM sessions;
    SELECT COUNT(*) INTO physical_seat_count FROM seats;
    SELECT COUNT(*) INTO inventory_count FROM session_seats;

    IF event_count <> 2 THEN
        RAISE EXCEPTION 'Expected 2 events, got %', event_count;
    END IF;
    IF session_count <> 5 THEN
        RAISE EXCEPTION 'Expected 5 sessions, got %', session_count;
    END IF;
    IF physical_seat_count <> 120 THEN
        RAISE EXCEPTION 'Expected 120 physical seats, got %', physical_seat_count;
    END IF;
    IF inventory_count <> 300 THEN
        RAISE EXCEPTION 'Expected 300 session seats, got %', inventory_count;
    END IF;
    IF (SELECT COUNT(*) FROM reservations) <> 10 THEN
        RAISE EXCEPTION 'Expected 10 coherent Seed reservations';
    END IF;
    IF (SELECT COUNT(*) FROM orders) <> 10 THEN
        RAISE EXCEPTION 'Expected one Seed order per reservation';
    END IF;
    IF (SELECT COUNT(*) FROM reservation_session_seats) <> 45 THEN
        RAISE EXCEPTION 'Expected 45 held/sold reservation-seat associations';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM sessions AS session
        LEFT JOIN session_seats AS inventory ON inventory.session_id = session.id
        GROUP BY session.id
        HAVING COUNT(inventory.id) <> 60
    ) THEN
        RAISE EXCEPTION 'Every session must contain exactly 60 session seats';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM sessions AS session
        LEFT JOIN session_seats AS inventory ON inventory.session_id = session.id
        GROUP BY session.id
        HAVING COUNT(*) FILTER (WHERE inventory.status = 'AVAILABLE') <> 51
            OR COUNT(*) FILTER (WHERE inventory.status = 'HELD') <> 4
            OR COUNT(*) FILTER (WHERE inventory.status = 'SOLD') <> 5
    ) THEN
        RAISE EXCEPTION 'Unexpected AVAILABLE/HELD/SOLD distribution';
    END IF;

    SELECT COUNT(*) INTO invalid_inventory_count
    FROM session_seats AS inventory
    JOIN sessions AS session ON session.id = inventory.session_id
    JOIN seats AS seat ON seat.id = inventory.seat_id
    WHERE inventory.venue_id <> session.venue_id
       OR inventory.venue_id <> seat.venue_id;

    IF invalid_inventory_count <> 0 THEN
        RAISE EXCEPTION 'Session-seat venue integrity failed';
    END IF;

    SELECT COUNT(*) INTO invalid_reservation_item_count
    FROM reservation_session_seats AS item
    JOIN reservations AS reservation ON reservation.id = item.reservation_id
    JOIN session_seats AS inventory ON inventory.id = item.session_seat_id
    WHERE item.session_id <> reservation.session_id
       OR item.session_id <> inventory.session_id;

    IF invalid_reservation_item_count <> 0 THEN
        RAISE EXCEPTION 'Reservation item session integrity failed';
    END IF;

    RAISE NOTICE 'Seed verified: % events, % sessions, % physical seats, % inventory rows',
        event_count, session_count, physical_seat_count, inventory_count;
END
$$;
