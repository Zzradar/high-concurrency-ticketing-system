BEGIN;

INSERT INTO app_users (id, display_name, username, password_hash, status)
VALUES ('U-AUTH-SCHEMA', 'Auth schema user', 'auth-schema', '!disabled', 'DISABLED');

INSERT INTO user_sessions (
    id, user_id, token_hash, created_at, last_seen_at,
    idle_expires_at, absolute_expires_at
) VALUES
    (
        'AUTH-SCHEMA-1', 'U-AUTH-SCHEMA', repeat('a', 64),
        clock_timestamp(), clock_timestamp(),
        clock_timestamp() + INTERVAL '1 day',
        clock_timestamp() + INTERVAL '7 days'
    ),
    (
        'AUTH-SCHEMA-2', 'U-AUTH-SCHEMA', repeat('b', 64),
        clock_timestamp(), clock_timestamp(),
        clock_timestamp() + INTERVAL '1 day',
        clock_timestamp() + INTERVAL '7 days'
    );

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM user_sessions WHERE user_id = 'U-AUTH-SCHEMA') <> 2 THEN
        RAISE EXCEPTION 'multiple sessions per user were not accepted';
    END IF;

    BEGIN
        INSERT INTO user_sessions (
            id, user_id, token_hash, created_at, last_seen_at,
            idle_expires_at, absolute_expires_at
        ) VALUES (
            'AUTH-SCHEMA-BAD-HASH', 'U-AUTH-SCHEMA', 'not-a-sha256',
            clock_timestamp(), clock_timestamp(),
            clock_timestamp() + INTERVAL '1 day',
            clock_timestamp() + INTERVAL '7 days'
        );
        RAISE EXCEPTION 'invalid token hash was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO app_users (id, display_name, username, password_hash, status)
        VALUES ('U-AUTH-UPPER', 'Uppercase user', 'Not-Canonical', '!disabled', 'DISABLED');
        RAISE EXCEPTION 'non-canonical username was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO app_users (id, display_name, username, password_hash, status)
        VALUES ('U-AUTH-DUP', 'Duplicate user', 'auth-schema', '!disabled', 'DISABLED');
        RAISE EXCEPTION 'duplicate username was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
END;
$$;

INSERT INTO user_notifications (
    id, user_id, order_id, type, title, message, dedupe_key
) VALUES (
    'NTF-AUTH-SCHEMA', 'U-SEED-HOLDER',
    'TKT-SEED-HELD-ses-concert-1001', 'ORDER_CREATED',
    '订单已创建', '测试订单通知', 'auth-schema-order-created'
);

ROLLBACK;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM app_users WHERE id = 'U-AUTH-SCHEMA') THEN
        RAISE EXCEPTION 'auth schema verification leaked test data';
    END IF;
    RAISE NOTICE 'Authentication schema verified';
END;
$$;
