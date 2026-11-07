# Office laptop connection — for the later connection stage

## Already confirmed

Windows office laptop; TallyPrime Silver 7.1; company name **Upkar Agency**;
Tally acts as Both, ODBC Yes, port **9000**. The Windows browser displayed
“TallyPrime server is running” at http://localhost:9000. That checks the server,
not company XML export/import compatibility.

## Read-only check

1. Install Python 3.11+ from python.org on Windows if it is not installed.
2. Download this repository and extract it into a normal local folder.
3. Open Tally with Upkar Agency loaded.
4. Open Command Prompt in the repository folder and run:

```bat
py -m connector.read_company --company "Upkar Agency"
```

Success reports `connected: true` and `mode: read-only`. No voucher is written.

## Pair the connector once a reachable HTTPS app is configured

The local Mac preview is deliberately isolated. `localhost` on Windows means Windows,
not the Mac. Do not enter the Mac's localhost URL as the remote app address.
A persistent app host behind HTTPS is required for access from the phone and Windows.

The app host sets a long random `OFFICE_CONNECTOR_TOKEN` (at least 32 characters).
Generate/store it locally or in hosting secret storage; never in Git or chat.
Then double-click `scripts/start-windows.cmd`. The launcher asks for the HTTPS app URL,
token (hidden input), and Tally port. The device token is encrypted using the current
Windows user's DPAPI key. The file is stored under `%LOCALAPPDATA%\OfficeTally`.
Do not copy this configuration between Windows users or machines.

The worker syncs masters and services approved report requests every 20 seconds.
Keep Tally and Upkar Agency open. No port forwarding or inbound firewall exception is
needed. A Windows Task Scheduler task can later run the launcher at user sign-in.
An installed Windows service/executable is not included in this source pilot.

## Voucher posting activation

The feature is implemented, but production posting is **off by default** pending validation.
The user has authorized building voucher entry and connecting to the existing company;
this does not cause any automatic entries.

Before real imports, compare exported sample vouchers and report fixtures from Tally 7.1,
confirm GST ledgers, voucher numbering, inventory features, bill allocation references
and the backup/restore process. Use a separate test company for the initial write tests.
This test company name must be configured consistently in a reviewed test build; the
current source intentionally pins Upkar Agency to prevent accidental company switching.

After validation:

- On the app host, set `OFFICE_ENABLE_POSTING=YES`.
- In the Windows local connector configuration, change `allow_writes` to `true`.
- Restart both processes. An owner must still approve each draft in the app.

A token can be revoked by changing it on the app host and re-pairing the office device.
No plain-text cloud credentials or Tally passwords are required by the application.

## Uncertain import result

A lost response does not mean an import failed. The worker records an import marker
before sending XML. An expired job becomes **Check in Tally**, never an automatic retry.
Inspect the actual company and import log. If a voucher exists, keep it and reconcile
the app record; do not create a replacement. A dedicated reconciliation UI is still a
production follow-up; no “retry anyway” button is provided.

## Optional startup at Windows sign-in

After pairing and validating read-only sync, the provided
`scripts/install-startup-task.ps1` can register a scheduled task for the same signed-in
Windows user. It uses that user's DPAPI key, not a system service account, and stores
no Windows password. Review/run it locally; it has not been exercised on the actual
office laptop. Keep the extracted repository in a permanent folder so the task's
working directory does not change.

## Isolated acceptance setup for writes

Use a restored backup copy named exactly **Upkar Agency TEST**. Restore into a
separate data location; confirm the original company remains intact. Do not rename
the only live company to run this test. Keep the production connector running from
its existing folder if needed; it remains read-only and targets Upkar Agency.

Download the write-update release into another folder and double-click
`scripts/test-windows-writes.cmd`. This opens only a loopback web server on port
8767. It uses a separate local SQLite database and journal under
`%LOCALAPPDATA%\OfficeTally-Test`. A random device token is held in memory; no Render
or Supabase credentials are requested. The local test password is entered privately.

In the Windows browser open http://127.0.0.1:8767, sign in, switch from Demo to Tally
workspace and verify the **TEST COMPANY** banner. Create and review Sales, Purchase,
Receipt and Payment entries using existing masters. Check the actual voucher in the
test Tally company after each confirmation: number/date, party and cash/bank signs,
item quantities, godown, sales/purchase and GST ledgers, rounding and total. For
Sales use the manual voucher number; Purchase reference is the supplier invoice
number, separate from the Tally voucher number.

Test positive/negative rounding and a reviewed taxable amount where the displayed
rate does not multiply exactly. Review the explicit override reason. Test app
approval while Tally is closed and verify it stays queued until the test company
is available again. Never force retry an uncertain import.

This is acceptance tooling, not proof of statutory GST correctness. Mixed item GST
rates, real batch tracking and complex inventory allocations remain unsupported.
Verify GST registers and outstanding balances in Tally before activating production.
Production app/device posting switches are deliberately unchanged by this setup.
