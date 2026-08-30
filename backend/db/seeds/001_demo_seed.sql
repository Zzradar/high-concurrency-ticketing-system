BEGIN;

INSERT INTO venues (id, name, city) VALUES
    ('venue-shanghai-stadium', '上海体育场', '上海'),
    ('venue-pudong-sports-center', '浦东体育中心', '上海');

INSERT INTO app_users (id, display_name) VALUES
    ('U-1001', 'Demo 用户'),
    ('U-SEED-HOLDER', 'Seed 占座用户');

INSERT INTO events (
    id, primary_venue_id, name, description, status,
    category, cover_url, date_range
) VALUES
    (
        'evt-concert-2026',
        'venue-shanghai-stadium',
        '星海回响 · 2026 巡演',
        '沉浸式环形舞台与全景声现场，和三万名观众一起点亮这个夜晚。',
        'ON_SALE',
        '演唱会',
        '/images/concert-cover.png',
        '2026.10.01 — 10.03'
    ),
    (
        'evt-basketball-finals',
        'venue-pudong-sports-center',
        '城市巅峰 · 篮球总决赛',
        '年度冠军之夜，见证最后一球落下前的每一次攻防与呐喊。',
        'ON_SALE',
        '体育赛事',
        '/images/basketball-cover.png',
        '2026.11.08 — 11.09'
    );

INSERT INTO sessions (
    id, event_id, venue_id, hall_name, start_time, gate_time, status
) VALUES
    ('ses-concert-1001', 'evt-concert-2026', 'venue-shanghai-stadium', '主场馆',
     '2026-10-01 19:30:00+08', '2026-10-01 17:30:00+08', 'ON_SALE'),
    ('ses-concert-1002', 'evt-concert-2026', 'venue-shanghai-stadium', '主场馆',
     '2026-10-02 19:30:00+08', '2026-10-02 17:30:00+08', 'ON_SALE'),
    ('ses-concert-1003', 'evt-concert-2026', 'venue-shanghai-stadium', '主场馆',
     '2026-10-03 19:30:00+08', '2026-10-03 17:30:00+08', 'ON_SALE'),
    ('ses-basketball-2001', 'evt-basketball-finals', 'venue-pudong-sports-center', '一号馆',
     '2026-11-08 18:30:00+08', '2026-11-08 17:00:00+08', 'ON_SALE'),
    ('ses-basketball-2002', 'evt-basketball-finals', 'venue-pudong-sports-center', '一号馆',
     '2026-11-09 19:00:00+08', '2026-11-09 17:30:00+08', 'ON_SALE');

WITH seat_layout AS (
    SELECT
        venue.id AS venue_id,
        row_data.row_no,
        number_data.seat_no,
        row_data.row_no || LPAD(number_data.seat_no::TEXT, 2, '0') AS seat_label,
        CASE
            WHEN row_data.row_no IN ('A', 'B') THEN '星光区'
            WHEN row_data.row_no IN ('C', 'D') THEN '看台 A 区'
            ELSE '看台 B 区'
        END AS zone
    FROM venues AS venue
    CROSS JOIN (VALUES ('A'), ('B'), ('C'), ('D'), ('E'), ('F')) AS row_data(row_no)
    CROSS JOIN generate_series(1, 10) AS number_data(seat_no)
)
INSERT INTO seats (id, venue_id, row_no, seat_no, seat_label, zone)
SELECT
    'seat-' || venue_id || '-' || seat_label,
    venue_id,
    row_no,
    seat_no,
    seat_label,
    zone
FROM seat_layout;

INSERT INTO reservations (id, user_id, session_id, status, expires_at, created_at)
SELECT
    'RSV-SEED-HELD-' || session.id,
    'U-SEED-HOLDER',
    session.id,
    'ACTIVE',
    CURRENT_TIMESTAMP + INTERVAL '10 years',
    CURRENT_TIMESTAMP
FROM sessions AS session
UNION ALL
SELECT
    'RSV-SEED-SOLD-' || session.id,
    'U-SEED-HOLDER',
    session.id,
    'CONFIRMED',
    CURRENT_TIMESTAMP + INTERVAL '15 minutes',
    CURRENT_TIMESTAMP
FROM sessions AS session;

INSERT INTO session_seats (
    id, session_id, seat_id, venue_id, status, price, current_reservation_id
)
SELECT
    session.id || '-' || seat.seat_label,
    session.id,
    seat.id,
    session.venue_id,
    CASE
        WHEN seat.seat_label IN ('A03', 'B07', 'D04', 'F09') THEN 'HELD'
        WHEN seat.seat_label IN ('A08', 'C05', 'C06', 'E02', 'E03') THEN 'SOLD'
        ELSE 'AVAILABLE'
    END,
    CASE
        WHEN session.id LIKE 'ses-basketball-%' THEN
            CASE
                WHEN seat.row_no IN ('A', 'B') THEN 88000
                WHEN seat.row_no IN ('C', 'D') THEN 58000
                ELSE 38000
            END
        ELSE
            CASE
                WHEN seat.row_no IN ('A', 'B') THEN 128000
                WHEN seat.row_no IN ('C', 'D') THEN 88000
                ELSE 58000
            END
    END,
    CASE
        WHEN seat.seat_label IN ('A03', 'B07', 'D04', 'F09')
            THEN 'RSV-SEED-HELD-' || session.id
        ELSE NULL
    END
FROM sessions AS session
JOIN seats AS seat ON seat.venue_id = session.venue_id;

INSERT INTO reservation_session_seats (
    reservation_id, session_id, session_seat_id, reserved_price
)
SELECT
    CASE
        WHEN session_seat.status = 'HELD'
            THEN 'RSV-SEED-HELD-' || session_seat.session_id
        ELSE 'RSV-SEED-SOLD-' || session_seat.session_id
    END,
    session_seat.session_id,
    session_seat.id,
    session_seat.price
FROM session_seats AS session_seat
WHERE session_seat.status IN ('HELD', 'SOLD');

INSERT INTO orders (
    id, user_id, reservation_id, status, total_amount,
    expires_at, created_at, paid_at
)
SELECT
    'TKT-SEED-HELD-' || reservation.session_id,
    reservation.user_id,
    reservation.id,
    'PENDING_PAYMENT',
    SUM(item.reserved_price),
    reservation.expires_at,
    reservation.created_at,
    NULL
FROM reservations AS reservation
JOIN reservation_session_seats AS item ON item.reservation_id = reservation.id
WHERE reservation.status = 'ACTIVE'
GROUP BY reservation.id, reservation.session_id, reservation.user_id,
         reservation.expires_at, reservation.created_at
UNION ALL
SELECT
    'TKT-SEED-SOLD-' || reservation.session_id,
    reservation.user_id,
    reservation.id,
    'PAID',
    SUM(item.reserved_price),
    reservation.expires_at,
    reservation.created_at,
    reservation.created_at
FROM reservations AS reservation
JOIN reservation_session_seats AS item ON item.reservation_id = reservation.id
WHERE reservation.status = 'CONFIRMED'
GROUP BY reservation.id, reservation.session_id, reservation.user_id,
         reservation.expires_at, reservation.created_at;

COMMIT;
