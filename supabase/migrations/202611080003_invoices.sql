-- Native PDFs: extend the existing private read-request queue. No invoice data is imported.
BEGIN;
ALTER TABLE office.report_requests DROP CONSTRAINT IF EXISTS report_requests_report_check;
ALTER TABLE office.report_requests ADD CONSTRAINT report_requests_report_check
 CHECK (report IN ('daybook','sales','purchases','ledger','receivables','payables','trial','profit','balance','stock','invoice'));
INSERT INTO office.schema_migrations(version) VALUES(3) ON CONFLICT DO NOTHING;
COMMIT;
