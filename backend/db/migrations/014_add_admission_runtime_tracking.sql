BEGIN;
-- Runtime initialization is durable: missing Redis after this marker means a reset,
-- rather than permission to recreate the same qualification namespace.
CREATE TABLE admission_runtime_generations (
 event_id TEXT PRIMARY KEY REFERENCES events(id),
 generation TEXT NOT NULL CHECK (generation ~ '^[a-f0-9]{32}$'),
 initialized_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE admission_policy_audit ALTER COLUMN administrator_id DROP NOT NULL;
ALTER TABLE admission_policy_audit ADD COLUMN actor_kind TEXT NOT NULL DEFAULT 'ADMIN'
 CHECK (actor_kind IN ('ADMIN','SYSTEM'));
ALTER TABLE admission_policy_audit ADD CONSTRAINT admission_audit_actor_check
 CHECK ((actor_kind='ADMIN' AND administrator_id IS NOT NULL) OR
        (actor_kind='SYSTEM' AND administrator_id IS NULL AND action='RESET_GENERATION'));
COMMIT;
