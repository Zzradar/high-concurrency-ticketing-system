BEGIN;

ALTER TABLE reservations
    ADD COLUMN idempotency_key TEXT;

ALTER TABLE reservations
    ADD CONSTRAINT reservations_idempotency_key_length_check
    CHECK (
        idempotency_key IS NULL
        OR char_length(idempotency_key) BETWEEN 1 AND 128
    );

ALTER TABLE reservations
    ADD CONSTRAINT reservations_user_idempotency_unique
    UNIQUE (user_id, idempotency_key);

COMMIT;
