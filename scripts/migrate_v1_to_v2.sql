-- LuigiBot: v1 -> v2 schema migration (Postgres).
--
-- Run this ONCE as the table owner (or a superuser). The bot's runtime DB
-- user typically only has DML privileges and cannot ALTER / CREATE INDEX,
-- which is why the bot itself refuses to migrate in that environment.
--
-- Usage (from a container/host that can reach the Postgres server):
--   psql -h <pg_host> -U <owner_role> -d luigi_todo -f scripts/migrate_v1_to_v2.sql
--
-- Non-destructive; wrapped in a transaction and idempotent. If any statement
-- fails the whole thing rolls back. Safe to re-run.

BEGIN;

-- 1. Add the uuid column to the four whole-table-rewrite tables. IF NOT EXISTS
--    means re-running after a partial success is safe.
ALTER TABLE tasks            ADD COLUMN IF NOT EXISTS uuid TEXT;
ALTER TABLE recurring_tasks  ADD COLUMN IF NOT EXISTS uuid TEXT;
ALTER TABLE discipline_list  ADD COLUMN IF NOT EXISTS uuid TEXT;
ALTER TABLE follow_up_tasks  ADD COLUMN IF NOT EXISTS uuid TEXT;

-- 2. Backfill any NULL uuids. gen_random_uuid() is built into Postgres 13+;
--    on older versions run `CREATE EXTENSION IF NOT EXISTS pgcrypto;` first.
UPDATE tasks            SET uuid = gen_random_uuid()::text WHERE uuid IS NULL;
UPDATE recurring_tasks  SET uuid = gen_random_uuid()::text WHERE uuid IS NULL;
UPDATE discipline_list  SET uuid = gen_random_uuid()::text WHERE uuid IS NULL;
UPDATE follow_up_tasks  SET uuid = gen_random_uuid()::text WHERE uuid IS NULL;

-- 3. Unique indexes so the GUI (and any other external client) can rely on
--    uuid as a stable primary key.
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_uuid            ON tasks(uuid);
CREATE UNIQUE INDEX IF NOT EXISTS idx_recurring_tasks_uuid  ON recurring_tasks(uuid);
CREATE UNIQUE INDEX IF NOT EXISTS idx_discipline_list_uuid  ON discipline_list(uuid);
CREATE UNIQUE INDEX IF NOT EXISTS idx_follow_up_tasks_uuid  ON follow_up_tasks(uuid);

-- 4. Bump schema_version so the bot's init_db() skips the auto-migration.
UPDATE schema_version SET version = 2;
-- If schema_version was somehow empty, seed it.
INSERT INTO schema_version (version)
SELECT 2 WHERE NOT EXISTS (SELECT 1 FROM schema_version);

COMMIT;

-- Verification (run separately after COMMIT):
--   SELECT version FROM schema_version;
--   SELECT
--     (SELECT COUNT(*) FROM tasks            WHERE uuid IS NULL) AS tasks_null,
--     (SELECT COUNT(*) FROM recurring_tasks  WHERE uuid IS NULL) AS recurring_null,
--     (SELECT COUNT(*) FROM discipline_list  WHERE uuid IS NULL) AS discipline_null,
--     (SELECT COUNT(*) FROM follow_up_tasks  WHERE uuid IS NULL) AS follow_null;
-- All four counts must be 0.
