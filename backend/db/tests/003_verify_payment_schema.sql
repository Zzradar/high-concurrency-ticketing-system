BEGIN;

INSERT INTO payment_attempts (
    id, order_id, status, started_at, processing_deadline,
    scheduled_complete_at
)
VALUES (
    'PAY-SCHEMA-TEST',
    'TKT-SEED-HELD-ses-concert-1001',
    'PROCESSING',
    clock_timestamp(),
    clock_timestamp() + INTERVAL '10 seconds',
    clock_timestamp() + INTERVAL '2 seconds'
);

DO $$
BEGIN
    BEGIN
        INSERT INTO payment_attempts (
            id, order_id, status, started_at, processing_deadline,
            scheduled_complete_at
        )
        SELECT 'PAY-SCHEMA-DUPLICATE', order_id, 'PROCESSING',
               started_at, processing_deadline, scheduled_complete_at
        FROM payment_attempts WHERE id = 'PAY-SCHEMA-TEST';
        RAISE EXCEPTION 'a second PROCESSING attempt was accepted';
    EXCEPTION
        WHEN unique_violation THEN NULL;
    END;

    BEGIN
        UPDATE payment_attempts
        SET accepted_at = clock_timestamp()
        WHERE id = 'PAY-SCHEMA-TEST';
        RAISE EXCEPTION 'PROCESSING attempt accepted_at was allowed';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;
END;
$$;

UPDATE payment_attempts
SET status = 'SUCCEEDED',
    completed_at = clock_timestamp(),
    accepted_at = NULL
WHERE id = 'PAY-SCHEMA-TEST';

INSERT INTO refunds (
    id, payment_attempt_id, order_id, amount, reason, refunded_at
)
VALUES (
    'RFD-SCHEMA-TEST',
    'PAY-SCHEMA-TEST',
    'TKT-SEED-HELD-ses-concert-1001',
    256000,
    'PAYMENT_NOT_ACCEPTED',
    clock_timestamp()
);

INSERT INTO user_notifications (
    id, user_id, order_id, type, title, message, dedupe_key
)
VALUES (
    'NTF-SCHEMA-TEST',
    'U-SEED-HOLDER',
    'TKT-SEED-HELD-ses-concert-1001',
    'AUTO_REFUND_COMPLETED',
    '测试通知',
    '测试退款通知',
    'schema-test-refund'
);

DO $$
BEGIN
    BEGIN
        INSERT INTO refunds (
            id, payment_attempt_id, order_id, amount, reason, refunded_at
        ) VALUES (
            'RFD-SCHEMA-DUPLICATE', 'PAY-SCHEMA-TEST',
            'TKT-SEED-HELD-ses-concert-1001', 256000,
            'PAYMENT_NOT_ACCEPTED', clock_timestamp()
        );
        RAISE EXCEPTION 'duplicate attempt refund was accepted';
    EXCEPTION
        WHEN unique_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO user_notifications (
            id, user_id, order_id, type, title, message, dedupe_key
        ) VALUES (
            'NTF-SCHEMA-DUPLICATE', 'U-SEED-HOLDER',
            'TKT-SEED-HELD-ses-concert-1001', 'AUTO_REFUND_COMPLETED',
            '测试通知', '测试退款通知', 'schema-test-refund'
        );
        RAISE EXCEPTION 'duplicate notification dedupe key was accepted';
    EXCEPTION
        WHEN unique_violation THEN NULL;
    END;
END;
$$;

ROLLBACK;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM payment_attempts WHERE id = 'PAY-SCHEMA-TEST') THEN
        RAISE EXCEPTION 'payment schema verification leaked test data';
    END IF;
    RAISE NOTICE 'Payment lifecycle schema verified';
END;
$$;
