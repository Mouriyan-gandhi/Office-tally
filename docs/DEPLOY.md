# Render + Supabase deployment

This release includes the cloud backend. It has not been deployed to your Supabase or
Render account by the coding agent. Do not use previously exposed secret/service-role
keys. Replace/revoke them using Supabase's compromised-key instructions first.

## 1. Set up Supabase

1. Open the Upkar Agency Supabase project.
2. In SQL Editor, run `supabase/migrations/202611070001_office.sql` from this release.
   It creates an `office` schema with private tables, a restricted backend role, RLS,
   indexes and the private `office-invoices` bucket. It does not import Tally data.
3. In Authentication → Users, create the one admin email/password user and confirm
   its email. Keep the password private. No application user password goes in SQL.
4. Turn off Allow new users to sign up and Allow anonymous sign-ins.
5. In Connect, copy the Session pooler PostgreSQL connection URI. Substitute the DB
   password, URL-encoding reserved characters if required. Use the provided host;
   do not infer it from the region. The app requires an encrypted DB connection.

## 2. Deploy on Render

Use the latest tested `main` branch of Mouriyan-gandhi/Office-tally.
The supplied `render.yaml` is a Blueprint for a Docker web service, initially using
Render's Free instance for a pilot. Its availability, sleep and resource limits apply.
For daily accounting use, review an appropriate always-on plan and backup arrangement.
Do not assume production reliability from a free test deployment.

In Render, create a Blueprint from the repository and review the service/plan before
creating it. Or create a Web Service with Docker runtime and health path `/healthz`.
The Docker image includes Python, Tesseract and Poppler. It does not include secrets,
local SQLite databases, invoice files or your Windows connector credentials.

Set these values privately in the Render environment:

| Variable | Value |
| --- | --- |
| OFFICE_BACKEND | supabase |
| SUPABASE_URL | Your Supabase project HTTPS URL |
| SUPABASE_PUBLISHABLE_KEY | Current new-format publishable key |
| SUPABASE_SECRET_KEY | A new, unexposed sb_secret key |
| DATABASE_URL | Session pooler URI with the database password |
| SUPABASE_STORAGE_BUCKET | office-invoices |
| OFFICE_OWNER_EMAIL | Exact email of the single confirmed admin |
| OFFICE_CONNECTOR_TOKEN | A new random token of at least 32 characters |
| OFFICE_SECURE_COOKIE | YES |
| OFFICE_ENABLE_POSTING | NO for the first connection |

The Blueprint can generate OFFICE_CONNECTOR_TOKEN and prompts for private values.
RENDER_EXTERNAL_URL supplies the public HTTPS origin automatically. If deploying
elsewhere or using a custom origin, also set OFFICE_PUBLIC_URL to that HTTPS origin.
Never put passwords, secret keys or complete DB connection strings in chat or Git.

## 3. Check the hosted app

1. Wait for deployment and its `/healthz` check to succeed.
2. Open the HTTPS site on your phone. Only the configured admin may sign in.
3. The cloud app opens the Tally workspace; empty fields are expected before sync.
4. Confirm that signed-out visitors cannot access `/api/state?mode=live` or invoices.
5. A private bucket check runs at startup. A public invoice bucket stops deployment.

Auth uses Supabase to verify the password/confirmed identity. The application keeps
an opaque, HttpOnly, Secure, SameSite session cookie for up to eight hours and stores
only the session ID's hash in PostgreSQL. It re-checks that the approved Supabase admin
has not been banned/deleted. Auth JWTs and passwords are not returned to frontend JS.
There is no public signup route. To revoke app sessions directly, an authorized database
administrator can run `DELETE FROM office.sessions;` in the project SQL Editor.

## 4. Connect Windows

1. Install Python 3.11+ on the PC where TallyPrime Silver 7.1 runs.
2. Download/extract this release. Keep Upkar Agency loaded in Tally.
3. Keep Tally's confirmed settings: Both mode, port 9000.
4. Open http://localhost:9000 on Windows to check the server, then in the repository:

```bat
py -m connector.read_company --company "Upkar Agency"
```

5. Double-click `scripts/start-windows.cmd`. Enter the Render HTTPS address, the
   OFFICE_CONNECTOR_TOKEN from Render, and port 9000. The token input is hidden.
6. The token is protected by Windows DPAPI under the signed-in Windows account.
   The connector starts with voucher writes disabled and syncs masters every 20 seconds.
7. Keep its window open. Optional startup-task installation is described in WINDOWS.md.

No Supabase admin/database keys go on Windows. Never forward or publicly tunnel Tally's
port. The phone and the connector communicate through the hosted app over HTTPS.

## 5. Validate real data before live imports

Confirm the company, customer/supplier names, stock units/quantities, debit/credit signs
and last-sync timestamp against Tally. Request read-only financial reports and compare
them. Actual Tally 7.1 report field mapping and company-specific accounting features
still need validation; simulated connector tests do not substitute for this.

For write tests, use a separate test company in an isolated test build/configuration
before live imports. The current release pins Upkar Agency to prevent arbitrary company
switching. Do not point a test voucher at live accounts simply to check connectivity.
Only after test-company validation and confirmation of GST/inventory/bill allocations
should posting be activated at both ends. See WINDOWS.md for the activation switches.

## What happens to data

PostgreSQL holds drafts, jobs, audit records, sessions, synced masters and reports.
Supabase private Storage holds original bills. Render uses temporary files only for
OCR. The Windows import journal is local and survives worker restarts. The Mac is for
development and does not need to stay on after deployment.

OCR processing currently runs in Render, not on the office laptop. Thus invoices are
uploaded to your configured cloud hosting/storage. No external generative-AI API is
used. Review host/storage retention and backups for your business records.

Official references:
- https://supabase.com/docs/guides/security/rotate-leaked-api-keys
- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://supabase.com/docs/guides/storage/buckets/fundamentals
- https://render.com/docs/blueprint-spec
- https://render.com/docs/free

## Read-only voucher history update (migration 2)

The `cloud-backend` branch now includes a rolling voucher-history cache. Before
updating the Windows connector, run `supabase/migrations/202611070002_history.sql`
in Supabase SQL Editor. It adds one private RLS-protected table; no existing data is
removed. Without migration 2 the hosted app and master sync continue to work, while
history is unavailable.

Deploy the updated branch on Render, then replace the Windows source files with
the latest branch ZIP and restart `scripts/start-windows.cmd`. Keep the same Windows
user: pairing credentials are outside the source folder, protected by DPAPI. Stop
the old connector first so two workers do not run simultaneously. Posting stays off.

The worker reads one monthly period per cycle, beginning with the company's
`BooksFrom` date. Previously unattempted periods run first; successfully fetched
periods become eligible for reconciliation after one hour. A complete sweep may
therefore take longer than an hour for a large company. This is rolling, eventual
history, not a transactionally consistent company-wide backup. An edit or deletion
appears after that affected period is successfully read again. Dates through today
are included; future-dated vouchers are excluded. A failed read retains the old
period and exposes the failure/freshness in the ledger dialog.

Each successful period atomically replaces its old vouchers (including an empty
collection), preventing append duplicates and removing deleted entries. Missing
collection containers, invalid identities/amounts and oversized exports fail closed.
Each period currently has a 16 MiB XML / 5,000 voucher limit. Oversized periods need
smaller partition support before they can sync; they are never silently truncated.

Ledger dialogs show cached date ranges and their timestamps. They display debit
and credit movements from active, nonoptional voucher ledger allocations. They do
not infer opening/running balances from the current master closing balance. The
latest 1,000 matching vouchers are displayed/exported with an explicit limit notice.
App-recorded entries remain a separate section to avoid double-counting posted jobs.
The real Tally 7.1 collection request still requires verification on the office PC;
local exported XML compatibility is not proof of a live request's correctness.

## Additional approved administrators

Create each user's confirmed email/password account in Supabase Authentication →
Users (or invite them and finish password setup using a configured redirect flow).
Keep public signup disabled. Add OFFICE_ADMIN_EMAILS to Render with comma-separated
approved email addresses and deploy. OFFICE_OWNER_EMAIL remains the original owner
and is always included. Up to ten total approved addresses are accepted; each has
full owner access, including approval/posting. No passwords belong in environment
variables or SQL. Remove an address from OFFICE_ADMIN_EMAILS and redeploy to revoke
its next request; banning/deleting the Supabase account also revokes access.

Multi-company operation is not enabled: all queues, drafts and caches currently
belong to one pinned company. Do not change company constants to repurpose the same
database. A second company needs a separate isolated deployment/database and connector,
or a reviewed multi-company schema and company-specific access controls.
