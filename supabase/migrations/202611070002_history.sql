-- Run after migration 1. Private, replaceable monthly Tally voucher cache.
BEGIN;
CREATE TABLE IF NOT EXISTS office.history_periods (
 start text PRIMARY KEY, end_date text NOT NULL, payload text NOT NULL DEFAULT '[]',
 updated double precision, attempted double precision NOT NULL,
 lease text, error text NOT NULL DEFAULT ''
);
ALTER TABLE office.history_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE office.history_periods FORCE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON office.history_periods TO office_backend;
REVOKE ALL ON office.history_periods FROM PUBLIC,anon,authenticated,service_role;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='office' AND tablename='history_periods' AND policyname='backend_only') THEN
 CREATE POLICY backend_only ON office.history_periods FOR ALL TO office_backend USING(true) WITH CHECK(true);
 END IF;
END $$;
INSERT INTO office.schema_migrations(version) VALUES(2) ON CONFLICT DO NOTHING;
COMMIT;
