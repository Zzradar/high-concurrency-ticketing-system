BEGIN;

-- The migration runs in the explicitly selected installation schema, as 001-015 do.
-- Resolve the existing helper OID once at installation. Its permanent references
-- are embedded as quoted identifiers, never resolved from a later caller's path.
DO $install$
DECLARE
    target_schema pg_catalog.name;
BEGIN
    SELECT n.nspname INTO STRICT target_schema
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
      WHERE p.oid='bump_session_layout_revisions(pg_catalog.text[])'::pg_catalog.regprocedure;
    EXECUTE pg_catalog.format($definition$
CREATE OR REPLACE FUNCTION %1$I.bump_session_layout_revisions(affected pg_catalog.text[])
RETURNS pg_catalog.void LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $body$
BEGIN
    IF coalesce(pg_catalog.cardinality(affected),0)=0 THEN RETURN; END IF;
    PERFORM session_id FROM %1$I.session_layout_revisions
      WHERE session_id=ANY(affected) ORDER BY session_id FOR UPDATE;
    UPDATE %1$I.session_layout_revisions SET revision=revision+1
      WHERE session_id=ANY(affected);
END $body$;
$definition$,target_schema);
END $install$;

CREATE OR REPLACE FUNCTION maintain_session_layout_identity() RETURNS pg_catalog.trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        EXECUTE pg_catalog.format($sql$INSERT INTO %1$I.session_layout_revisions AS target_revision(session_id,revision)
          SELECT id,1 FROM new_rows ORDER BY id
          ON CONFLICT(session_id) DO UPDATE
          SET revision=target_revision.revision+1$sql$, TG_TABLE_SCHEMA);
    ELSIF TG_OP = 'UPDATE' THEN
        -- No hall/time/status invalidation: these are not in the Layout body.
        EXECUTE pg_catalog.format($sql$INSERT INTO %1$I.session_layout_revisions AS target_revision(session_id,revision)
          SELECT n.id,1 FROM new_rows n LEFT JOIN old_rows o ON o.id=n.id
          WHERE o.id IS NULL ORDER BY n.id
          ON CONFLICT(session_id) DO UPDATE
          SET revision=target_revision.revision+1$sql$, TG_TABLE_SCHEMA);
        EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(
          SELECT n.id FROM new_rows n JOIN old_rows o ON o.id=n.id
          WHERE (n.venue_id,n.event_id,n.created_at)
             IS DISTINCT FROM (o.venue_id,o.event_id,o.created_at)))$sql$, TG_TABLE_SCHEMA);
    ELSE
        EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(SELECT id FROM old_rows))$sql$, TG_TABLE_SCHEMA);
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION maintain_layout_session_seats() RETURNS pg_catalog.trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(
          WITH changed AS (
            (SELECT id,session_id,seat_id,venue_id,price FROM new_rows EXCEPT SELECT id,session_id,seat_id,venue_id,price FROM old_rows)
            UNION
            (SELECT id,session_id,seat_id,venue_id,price FROM old_rows EXCEPT SELECT id,session_id,seat_id,venue_id,price FROM new_rows)
          ) SELECT DISTINCT session_id FROM changed))$sql$, TG_TABLE_SCHEMA);
    ELSIF TG_OP = 'INSERT' THEN
        EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,session_id,seat_id,venue_id,price FROM new_rows) SELECT DISTINCT session_id FROM changed))$sql$, TG_TABLE_SCHEMA);
    ELSE
        EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,session_id,seat_id,venue_id,price FROM old_rows) SELECT DISTINCT session_id FROM changed))$sql$, TG_TABLE_SCHEMA);
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION maintain_layout_seats() RETURNS pg_catalog.trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(
          WITH changed AS (
            (SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM new_rows EXCEPT SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM old_rows)
            UNION
            (SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM old_rows EXCEPT SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM new_rows)
          ) SELECT DISTINCT i.session_id FROM %1$I.session_seats i JOIN changed c ON c.id=i.seat_id))$sql$, TG_TABLE_SCHEMA);
    ELSIF TG_OP = 'INSERT' THEN
        EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM new_rows) SELECT DISTINCT i.session_id FROM %1$I.session_seats i JOIN changed c ON c.id=i.seat_id))$sql$, TG_TABLE_SCHEMA);
    ELSE
        EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,venue_id,zone_id,seat_label,row_no,seat_no FROM old_rows) SELECT DISTINCT i.session_id FROM %1$I.session_seats i JOIN changed c ON c.id=i.seat_id))$sql$, TG_TABLE_SCHEMA);
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION maintain_layout_venue_zones() RETURNS pg_catalog.trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(
          WITH changed AS (
            (SELECT id,venue_id,name,sort_order FROM new_rows EXCEPT SELECT id,venue_id,name,sort_order FROM old_rows)
            UNION
            (SELECT id,venue_id,name,sort_order FROM old_rows EXCEPT SELECT id,venue_id,name,sort_order FROM new_rows)
          ) SELECT DISTINCT i.session_id FROM %1$I.session_seats i JOIN %1$I.seats s ON s.id=i.seat_id JOIN changed c ON c.id=s.zone_id AND c.venue_id=s.venue_id))$sql$, TG_TABLE_SCHEMA);
    ELSIF TG_OP = 'INSERT' THEN
        EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,venue_id,name,sort_order FROM new_rows) SELECT DISTINCT i.session_id FROM %1$I.session_seats i JOIN %1$I.seats s ON s.id=i.seat_id JOIN changed c ON c.id=s.zone_id AND c.venue_id=s.venue_id))$sql$, TG_TABLE_SCHEMA);
    ELSE
        EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(
          WITH changed AS (SELECT id,venue_id,name,sort_order FROM old_rows) SELECT DISTINCT i.session_id FROM %1$I.session_seats i JOIN %1$I.seats s ON s.id=i.seat_id JOIN changed c ON c.id=s.zone_id AND c.venue_id=s.venue_id))$sql$, TG_TABLE_SCHEMA);
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION maintain_layout_inventory_truncate() RETURNS pg_catalog.trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
    EXECUTE pg_catalog.format($sql$SELECT %1$I.bump_session_layout_revisions(ARRAY(SELECT DISTINCT session_id FROM %1$I.session_seats))$sql$, TG_TABLE_SCHEMA);
    RETURN NULL;
END $$;

COMMIT;
