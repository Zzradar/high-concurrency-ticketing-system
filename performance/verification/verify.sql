-- Phase 10A authoritative cross-table invariant checks.
-- This file is intentionally read-only and scopes business facts by perf users
-- or perf inventory so the Demo seed cannot affect a performance verdict.

WITH checks AS (
    SELECT 'effective_seat_overlap' AS check_name, count(*)::BIGINT AS violation_count
    FROM (
        SELECT item.session_seat_id
        FROM reservation_session_seats AS item
        JOIN reservations AS reservation ON reservation.id = item.reservation_id
        WHERE item.session_seat_id LIKE 'perf-ss-%'
          AND reservation.status IN ('ACTIVE', 'CONFIRMED')
        GROUP BY item.session_seat_id
        HAVING count(*) > 1
    ) AS violation

    UNION ALL
    SELECT 'active_reservation_seat_mismatch', count(*)
    FROM reservations AS reservation
    WHERE reservation.user_id LIKE 'perf-user-%'
      AND reservation.status = 'ACTIVE'
      AND (
          NOT EXISTS (
              SELECT 1 FROM reservation_session_seats AS item
              WHERE item.reservation_id = reservation.id
          )
          OR EXISTS (
              SELECT 1
              FROM reservation_session_seats AS item
              JOIN session_seats AS seat ON seat.id = item.session_seat_id
              WHERE item.reservation_id = reservation.id
                AND (seat.status <> 'HELD'
                     OR seat.current_reservation_id IS DISTINCT FROM reservation.id)
          )
          OR (SELECT count(*) FROM orders AS ticket_order
              WHERE ticket_order.reservation_id = reservation.id
                AND ticket_order.status = 'PENDING_PAYMENT') <> 1
      )

    UNION ALL
    SELECT 'held_seat_owner_mismatch', count(*)
    FROM session_seats AS seat
    WHERE seat.id LIKE 'perf-ss-%'
      AND seat.status = 'HELD'
      AND NOT EXISTS (
          SELECT 1
          FROM reservations AS reservation
          JOIN reservation_session_seats AS item
            ON item.reservation_id = reservation.id
           AND item.session_seat_id = seat.id
          JOIN orders AS ticket_order
            ON ticket_order.reservation_id = reservation.id
          WHERE reservation.id = seat.current_reservation_id
            AND reservation.status = 'ACTIVE'
            AND ticket_order.status = 'PENDING_PAYMENT'
      )

    UNION ALL
    SELECT 'confirmed_state_mismatch', count(*)
    FROM reservations AS reservation
    WHERE reservation.user_id LIKE 'perf-user-%'
      AND reservation.status = 'CONFIRMED'
      AND (
          NOT EXISTS (
              SELECT 1 FROM orders AS ticket_order
              WHERE ticket_order.reservation_id = reservation.id
                AND ticket_order.status = 'PAID'
          )
          OR NOT EXISTS (
              SELECT 1 FROM reservation_session_seats AS item
              WHERE item.reservation_id = reservation.id
          )
          OR EXISTS (
              SELECT 1
              FROM reservation_session_seats AS item
              JOIN session_seats AS seat ON seat.id = item.session_seat_id
              WHERE item.reservation_id = reservation.id
                AND (seat.status <> 'SOLD' OR seat.current_reservation_id IS NOT NULL)
          )
      )

    UNION ALL
    SELECT 'sold_state_mismatch', count(*)
    FROM session_seats AS seat
    WHERE seat.id LIKE 'perf-ss-%'
      AND seat.status = 'SOLD'
      AND NOT EXISTS (
          SELECT 1
          FROM reservation_session_seats AS item
          JOIN reservations AS reservation ON reservation.id = item.reservation_id
          JOIN orders AS ticket_order ON ticket_order.reservation_id = reservation.id
          WHERE item.session_seat_id = seat.id
            AND reservation.status = 'CONFIRMED'
            AND ticket_order.status = 'PAID'
      )

    UNION ALL
    SELECT 'order_reservation_status_mismatch', count(*)
    FROM orders AS ticket_order
    JOIN reservations AS reservation ON reservation.id = ticket_order.reservation_id
    WHERE ticket_order.user_id LIKE 'perf-user-%'
      AND NOT (
          (ticket_order.status = 'PENDING_PAYMENT' AND reservation.status = 'ACTIVE')
          OR (ticket_order.status = 'PAID' AND reservation.status = 'CONFIRMED')
          OR (ticket_order.status = 'CANCELLED' AND reservation.status = 'CANCELLED')
          OR (ticket_order.status = 'EXPIRED' AND reservation.status = 'EXPIRED')
      )

    UNION ALL
    SELECT 'order_paid_at_mismatch', count(*)
    FROM orders AS ticket_order
    WHERE ticket_order.user_id LIKE 'perf-user-%'
      AND ((ticket_order.status = 'PAID' AND ticket_order.paid_at IS NULL)
           OR (ticket_order.status <> 'PAID' AND ticket_order.paid_at IS NOT NULL))

    UNION ALL
    SELECT 'order_amount_mismatch', count(*)
    FROM orders AS ticket_order
    WHERE ticket_order.user_id LIKE 'perf-user-%'
      AND ticket_order.total_amount IS DISTINCT FROM (
          SELECT sum(item.reserved_price)
          FROM reservation_session_seats AS item
          WHERE item.reservation_id = ticket_order.reservation_id
      )

    UNION ALL
    SELECT 'terminal_reservation_still_holds', count(*)
    FROM reservations AS reservation
    WHERE reservation.user_id LIKE 'perf-user-%'
      AND reservation.status IN ('CANCELLED', 'EXPIRED')
      AND EXISTS (
          SELECT 1 FROM session_seats AS seat
          WHERE seat.current_reservation_id = reservation.id
      )

    UNION ALL
    SELECT 'accepted_payment_mismatch', count(*)
    FROM payment_attempts AS attempt
    JOIN orders AS ticket_order ON ticket_order.id = attempt.order_id
    JOIN reservations AS reservation ON reservation.id = ticket_order.reservation_id
    WHERE ticket_order.user_id LIKE 'perf-user-%'
      AND attempt.status = 'SUCCEEDED'
      AND attempt.accepted_at IS NOT NULL
      AND (ticket_order.status <> 'PAID' OR reservation.status <> 'CONFIRMED')

    UNION ALL
    SELECT 'unaccepted_success_refund_mismatch', count(*)
    FROM payment_attempts AS attempt
    JOIN orders AS ticket_order ON ticket_order.id = attempt.order_id
    WHERE ticket_order.user_id LIKE 'perf-user-%'
      AND attempt.status = 'SUCCEEDED'
      AND attempt.accepted_at IS NULL
      AND (SELECT count(*) FROM refunds AS refund
           WHERE refund.payment_attempt_id = attempt.id) <> 1

    UNION ALL
    SELECT 'multiple_processing_attempts', count(*)
    FROM (
        SELECT attempt.order_id
        FROM payment_attempts AS attempt
        JOIN orders AS ticket_order ON ticket_order.id = attempt.order_id
        WHERE ticket_order.user_id LIKE 'perf-user-%'
          AND attempt.status = 'PROCESSING'
        GROUP BY attempt.order_id
        HAVING count(*) > 1
    ) AS violation

    UNION ALL
    SELECT 'multiple_refunds', count(*)
    FROM (
        SELECT refund.payment_attempt_id
        FROM refunds AS refund
        JOIN orders AS ticket_order ON ticket_order.id = refund.order_id
        WHERE ticket_order.user_id LIKE 'perf-user-%'
        GROUP BY refund.payment_attempt_id
        HAVING count(*) > 1
    ) AS violation

    UNION ALL
    SELECT 'refund_order_or_amount_mismatch', count(*)
    FROM refunds AS refund
    JOIN payment_attempts AS attempt ON attempt.id = refund.payment_attempt_id
    JOIN orders AS ticket_order ON ticket_order.id = attempt.order_id
    WHERE ticket_order.user_id LIKE 'perf-user-%'
      AND (refund.order_id <> attempt.order_id
           OR refund.amount <> ticket_order.total_amount)
)
SELECT check_name, violation_count
FROM checks
ORDER BY check_name;
