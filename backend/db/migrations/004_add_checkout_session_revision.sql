BEGIN;

ALTER TABLE checkout_sessions
    ADD COLUMN revision BIGINT NOT NULL DEFAULT 0,
    ADD CONSTRAINT checkout_sessions_revision_nonnegative_check
        CHECK (revision >= 0);

COMMIT;
