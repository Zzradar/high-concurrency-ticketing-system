# Database-maintained Layout revision

The v1 validator missed direct PostgreSQL changes and reused a preflight tag for a later body snapshot. migration015 adds a transactional revision; 001-014 are untouched. The old price counterexample is retained and now passes against v2.

| Response or ordering field | Actual database source | Revision source |
|---|---|---|
| sessionId | sessions.id | Session INSERT/DELETE/identity UPDATE; revision tombstone |
| seats[].id, membership | session_seats.id/session_id/seat_id | Inventory INSERT/DELETE and static projection UPDATE |
| seats[].price | session_seats.price | Inventory static UPDATE |
| seats[].label | seats.seat_label | Seat static UPDATE |
| seats[].row, seats[].number | seats.row_no/seat_no | Seat static UPDATE |
| seats[].zone | venue_zones.name via seats.zone_id/venue_id | Seat relationship and Zone static UPDATE |
| array ordering | venue_zones.sort_order, seats.row_no/seat_no, session_seats.id | Same static projections |
| retained public validator identity | sessions.venue_id/created_at and events.published_at | Read alongside revision in each statement; Session identity also bumps revision |

Venue name/city, Session hall/start/gate, event text, session_zone_prices (draft configuration), inventory status/current_reservation_id/formal_version/created_at and reservations are not Layout DTO fields. They do not bump revision. A static Seat INSERT/DELETE only affects Layout if it changes referenced inventory; inventory FK/statement triggers cover membership, including TRUNCATE CASCADE. Venue/Zone/Seat composite foreign keys continue enforcing cross-Venue consistency. DRAFT visibility is still read from PostgreSQL before any conditional response.

Transition tables project only static fields, symmetric EXCEPT removes no-op rows and DISTINCT collects truly affected Sessions. Each statement updates each affected revision at most once. The helper locks revision rows in Session ID order, then increments once; empty changes return before any revision UPDATE, so dynamic stock writes execute no revision UPDATE and take no revision-row locks. Batch 5000/10000 INSERT/UPDATE tests install a fixture-only revision-write audit trigger and assert exactly one write per affected Session, including two-Session updates. No activity-level inventory lock is introduced.

Backfill is deterministic revision=1 under a transactional installation lock. New Sessions initialize at 1. Tombstones survive deletion so reusing a Session ID cannot resurrect a prior validator. Failed or explicitly rolled-back transactions roll back both body changes and revision increments. Reexecuting migration015 fails on the existing table and rolls back; it does not silently reset revisions. Application deployments must install the additive migration before starting the new binary.

Lightweight identity/revision SELECT permits 304 without full Layout SQL. A mismatch uses one SELECT with a lateral Layout join and revision/identity in the same PostgreSQL statement snapshot. Visible empty Layouts retain an identity row; missing/DRAFT have none. The service transports that snapshot tag with its DTO; the controller never attaches the earlier preflight tag to a 200. `seat-layout-v2` rejects all old v1 validators. Concurrent readers observe a committed old or new representation and its matching tag.

The revision is a cache validator, not an inventory version or ownership authority. Authorized static corrections may serialize on affected Session revision rows; high-rate inventory operations do not. PostgreSQL privileged tampering with trigger definitions or revision bookkeeping is not a content correction. No application-layer manual bump or complete-Layout hashing is used.

Historical after/ stays byte-identical and invalidated; after-v2 must be freshly collected with the original eight protocol files and pinned browser. Capability failures are retained here as CLOSED diagnostics rather than changing diagnostics/ or formal raw evidence.
