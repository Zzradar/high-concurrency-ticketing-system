BEGIN;
ALTER TABLE payment_attempts ADD COLUMN currency TEXT;
ALTER TABLE refunds ADD COLUMN currency TEXT;
DO $$
DECLARE legacy TEXT := current_setting('ticketing.legacy_payment_currency', true);
BEGIN
    IF EXISTS (SELECT 1 FROM payment_attempts) THEN
        IF legacy IS NULL OR legacy !~ '^[a-z]{3}$' THEN
            RAISE EXCEPTION 'Confirm historical single currency and SET ticketing.legacy_payment_currency in this session';
        END IF;
        UPDATE payment_attempts SET currency = legacy;
        UPDATE refunds r SET currency = a.currency FROM payment_attempts a
        WHERE a.id = r.payment_attempt_id AND a.order_id = r.order_id;
    END IF;
    IF EXISTS (SELECT 1 FROM payment_attempts WHERE currency IS NULL)
       OR EXISTS (SELECT 1 FROM refunds WHERE currency IS NULL) THEN
        RAISE EXCEPTION 'Historical currency mapping incomplete';
    END IF;
END $$;
ALTER TABLE payment_attempts ALTER COLUMN currency SET NOT NULL,
    ADD CONSTRAINT payment_attempts_currency_check CHECK (currency ~ '^[a-z]{3}$');
ALTER TABLE refunds ALTER COLUMN currency SET NOT NULL,
    ADD CONSTRAINT refunds_currency_check CHECK (currency ~ '^[a-z]{3}$'),
    DROP CONSTRAINT refunds_reason_check,
    ADD CONSTRAINT refunds_source_reason_check CHECK (
        (source = 'BUYER' AND reason = 'BUYER_REQUESTED') OR
        (source = 'SYSTEM' AND reason IN ('ORDER_CANCELLED_BEFORE_PAYMENT_CONFIRMATION',
         'ORDER_EXPIRED_BEFORE_PAYMENT_CONFIRMATION','DUPLICATE_LATE_PAYMENT','PAYMENT_NOT_ACCEPTED')));
CREATE UNIQUE INDEX refunds_one_buyer_per_order_idx ON refunds(order_id) WHERE source = 'BUYER';
ALTER TABLE orders ADD COLUMN refunded_at TIMESTAMPTZ,
    DROP CONSTRAINT orders_paid_at_check,
    ADD CONSTRAINT orders_paid_at_check CHECK (
        (status IN ('PENDING_PAYMENT','EXPIRED') AND paid_at IS NULL AND refunded_at IS NULL) OR
        (status = 'PAID' AND paid_at IS NOT NULL AND refunded_at IS NULL) OR
        (status = 'CANCELLED' AND ((paid_at IS NULL AND refunded_at IS NULL) OR
                                 (paid_at IS NOT NULL AND refunded_at IS NOT NULL)))),
    ADD CONSTRAINT orders_refund_time_check CHECK (refunded_at >= paid_at);
ALTER TABLE user_notifications DROP CONSTRAINT user_notifications_type_check,
    ADD CONSTRAINT user_notifications_type_check CHECK (type IN (
        'ORDER_CREATED','PAYMENT_SUCCEEDED','ORDER_CANCELLED','ORDER_EXPIRED',
        'AUTO_REFUND_COMPLETED','AUTO_REFUND_FAILED','REFUND_COMPLETED','REFUND_FAILED'));
COMMIT;
