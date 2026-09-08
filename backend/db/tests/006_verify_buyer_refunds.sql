DO $$
DECLARE violations BIGINT;
BEGIN
 SELECT count(*) INTO violations FROM refunds f JOIN payment_attempts a ON a.id=f.payment_attempt_id
 JOIN orders o ON o.id=f.order_id JOIN reservations r ON r.id=o.reservation_id
 WHERE f.currency<>a.currency OR f.amount<>o.total_amount OR
 (f.source='BUYER' AND (a.accepted_at IS NULL OR a.status<>'SUCCEEDED' OR
   (f.status IN ('PROCESSING','FAILED') AND (o.status<>'PAID' OR r.status<>'CONFIRMED')) OR
   (f.status='SUCCEEDED' AND (o.status<>'CANCELLED' OR r.status<>'CANCELLED' OR
     o.refunded_at IS DISTINCT FROM f.refunded_at OR f.provider_terminal_at IS DISTINCT FROM f.refunded_at))));
 IF violations<>0 THEN RAISE EXCEPTION 'Phase12 refund invariant violations=%',violations; END IF;
 -- Successful historical refunds do not constrain current inventory: resale is legal.
 RAISE NOTICE 'Phase12 refund verifier violation_count=0';
END $$;
