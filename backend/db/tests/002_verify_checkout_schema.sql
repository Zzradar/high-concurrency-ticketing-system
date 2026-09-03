BEGIN;

INSERT INTO app_users (id, display_name, username, password_hash, status)
VALUES (
    'U-CHECKOUT-SCHEMA-TEST', 'Checkout schema verification',
    'checkout-schema-test', '!disabled', 'DISABLED'
);

INSERT INTO checkout_sessions (id, user_id, session_id, status)
VALUES (
    'CHK-SCHEMA-TEST',
    'U-CHECKOUT-SCHEMA-TEST',
    'ses-concert-1001',
    'SELECTING'
);

DO $$
DECLARE
    current_revision BIGINT;
BEGIN
    SELECT revision INTO current_revision
    FROM checkout_sessions
    WHERE id = 'CHK-SCHEMA-TEST';
    IF current_revision <> 0 THEN
        RAISE EXCEPTION 'checkout revision default was not zero';
    END IF;

    BEGIN
        UPDATE checkout_sessions SET revision = -1
        WHERE id = 'CHK-SCHEMA-TEST';
        RAISE EXCEPTION 'negative checkout revision was accepted';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;
END;
$$;

INSERT INTO checkout_session_seats (
    checkout_session_id, session_id, session_seat_id
)
VALUES (
    'CHK-SCHEMA-TEST',
    'ses-concert-1001',
    'ses-concert-1001-A01'
);

DO $$
BEGIN
    BEGIN
        INSERT INTO checkout_sessions (
            id, user_id, session_id, status
        )
        VALUES (
            'CHK-SCHEMA-INVALID-STATE',
            'U-CHECKOUT-SCHEMA-TEST',
            'ses-concert-1001',
            'SUBMITTING'
        );
        RAISE EXCEPTION 'SUBMITTING without a confirm key was accepted';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO checkout_session_seats (
            checkout_session_id, session_id, session_seat_id
        )
        VALUES (
            'CHK-SCHEMA-TEST',
            'ses-concert-1001',
            'ses-concert-1001-A01'
        );
        RAISE EXCEPTION 'duplicate checkout session seat was accepted';
    EXCEPTION
        WHEN unique_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO checkout_session_seats (
            checkout_session_id, session_id, session_seat_id
        )
        VALUES (
            'CHK-SCHEMA-TEST',
            'ses-concert-1001',
            'ses-concert-1002-A01'
        );
        RAISE EXCEPTION 'a seat from another Session was accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN NULL;
    END;
END;
$$;

ROLLBACK;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM app_users WHERE id = 'U-CHECKOUT-SCHEMA-TEST'
    ) THEN
        RAISE EXCEPTION 'checkout schema verification leaked test data';
    END IF;

    RAISE NOTICE 'Checkout schema verified: state shape, unique membership, and Session ownership';
END;
$$;
