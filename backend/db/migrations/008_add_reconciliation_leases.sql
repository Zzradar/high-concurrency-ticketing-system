BEGIN;

-- Scheduling is not ownership. Keep all existing business CHECK constraints.
ALTER TABLE payment_attempts
    ADD COLUMN reconciliation_lease_until TIMESTAMPTZ,
    ADD COLUMN reconciliation_lease_token TEXT,
    ADD CONSTRAINT payment_attempts_lease_shape_check CHECK (
        (reconciliation_lease_until IS NULL) = (reconciliation_lease_token IS NULL)
    );
ALTER TABLE refunds
    ADD COLUMN reconciliation_lease_until TIMESTAMPTZ,
    ADD COLUMN reconciliation_lease_token TEXT,
    ADD CONSTRAINT refunds_lease_shape_check CHECK (
        (reconciliation_lease_until IS NULL) = (reconciliation_lease_token IS NULL)
    );

CREATE INDEX payment_attempts_recovery_idx ON payment_attempts(id)
    WHERE provider <> 'simulation' AND status IN ('PROCESSING', 'TIMED_OUT')
      AND (provider_status IN ('succeeded', 'canceled') OR next_reconcile_at IS NULL);

COMMIT;
