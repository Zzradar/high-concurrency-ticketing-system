DO $$
DECLARE
    violation_count BIGINT;
BEGIN
    SELECT SUM(count) INTO violation_count FROM (
        SELECT COUNT(*) AS count FROM (
            SELECT provider, provider_payment_id FROM payment_attempts
            WHERE provider_payment_id IS NOT NULL GROUP BY provider, provider_payment_id HAVING COUNT(*) > 1
        ) duplicate_payment
        UNION ALL SELECT COUNT(*) FROM (
            SELECT provider, provider_refund_id FROM refunds
            WHERE provider_refund_id IS NOT NULL GROUP BY provider, provider_refund_id HAVING COUNT(*) > 1
        ) duplicate_refund
        UNION ALL SELECT COUNT(*) FROM refunds WHERE status = 'PROCESSING' AND (refunded_at IS NOT NULL OR failed_at IS NOT NULL)
        UNION ALL SELECT COUNT(*) FROM refunds WHERE status = 'SUCCEEDED' AND refunded_at IS NULL
        UNION ALL SELECT COUNT(*) FROM refunds WHERE status = 'FAILED' AND (failed_at IS NULL OR failure_reason IS NULL)
        UNION ALL SELECT COUNT(*) FROM refunds AS refund JOIN orders AS ticket_order ON ticket_order.id = refund.order_id
                         WHERE refund.source = 'SYSTEM' AND refund.amount <> ticket_order.total_amount
        UNION ALL SELECT COUNT(*) FROM (
            SELECT payment_attempt_id FROM refunds GROUP BY payment_attempt_id HAVING COUNT(*) > 1
        ) duplicate_attempt_refund
        UNION ALL SELECT COUNT(*) FROM refunds AS refund JOIN payment_attempts AS attempt ON attempt.id = refund.payment_attempt_id
                         WHERE refund.source = 'SYSTEM' AND attempt.accepted_at IS NOT NULL
        UNION ALL SELECT COUNT(*) FROM payment_attempts AS attempt
                         WHERE attempt.status = 'SUCCEEDED' AND attempt.accepted_at IS NULL
                           AND NOT EXISTS (SELECT 1 FROM refunds WHERE payment_attempt_id = attempt.id)
        UNION ALL SELECT COUNT(*) FROM (
            SELECT provider, provider_event_id FROM payment_provider_events
            GROUP BY provider, provider_event_id HAVING COUNT(*) > 1
        ) duplicate_event
        UNION ALL SELECT COUNT(*) FROM payment_attempts
                         WHERE status IN ('SUCCEEDED','FAILED') AND provider_terminal_at IS NULL
        UNION ALL SELECT COUNT(*) FROM refunds
                         WHERE status IN ('SUCCEEDED','FAILED') AND provider_terminal_at IS NULL
        UNION ALL SELECT COUNT(*) FROM payment_attempts
                         WHERE status IN ('PROCESSING','TIMED_OUT')
                           AND (provider_terminal_at IS NOT NULL OR provider_status IN ('succeeded','canceled'))
        UNION ALL SELECT COUNT(*) FROM refunds
                         WHERE status = 'PROCESSING' AND provider_terminal_at IS NOT NULL
    ) checks;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION 'Phase11 payment provider invariant violation_count=%', violation_count;
    END IF;
    RAISE NOTICE 'Phase11 payment provider verifier violation_count=0';
END;
$$;
