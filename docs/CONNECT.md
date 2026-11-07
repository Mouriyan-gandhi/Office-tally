# Connect the phone app to TallyPrime Silver on Windows

## How the connection works

Phone → secure hosted app → Windows connector → TallyPrime on the same Windows laptop.

The MacBook is used for development. It does not need to remain on once the app is
hosted. The phone does not connect directly to Tally's port.

Tally's official XML/HTTP interface supports exports and imports through its local
server. We use that interface through the Windows connector. Your confirmed settings
are Upkar Agency, TallyPrime Silver 7.1, Both mode, port 9000, and a successful local
server check. Actual company exports and voucher imports still need validation.

Official reference: https://help.tallysolutions.com/xml-integration/

## Step 1 — Give the app a secure address

The current http://127.0.0.1:8765 preview works only on the Mac. It is not a shareable
phone URL. Configure a persistent hosted backend and database/storage behind HTTPS,
with a production application server, backups and private user sign-in. The app must
be reachable by both the phone and the Windows laptop. This deployment is not set up yet.

Do not publish the Python development server or forward Tally's port as a shortcut.

## Step 2 — Prepare the Windows laptop

- Keep TallyPrime open with **Upkar Agency** loaded.
- Keep the confirmed Tally server configuration on port **9000**.
- Install Python 3.11+ if required.
- Download the latest Office-tally repository ZIP and extract it.

## Step 3 — Pair the connector

Double-click **scripts/start-windows.cmd** in the extracted folder. The launcher asks
for the app's HTTPS address, a connector token and Tally's local port.

The connector token is configured securely on the app host and entered locally into
the Windows launcher. Do not send it through chat. The launcher protects it with the
signed-in Windows user's encryption key. Initial pairing starts with writes disabled.

## Step 4 — Check the first sync

The connector contacts the app from Windows and reads the local Tally company. It
syncs ledgers and stock approximately every 20 seconds. Open the hosted app on the
phone, sign in, and switch to the Tally workspace. Check the company name, ledger
balances, quantities and the last-sync time against Tally.

## Step 5 — Validate and enable entries

Draft preparation works before live posting is activated. Validate the generated XML
against the company's actual ledgers, inventory, GST setup and voucher numbering.
Perform the first write tests on a separate test company before live entries.

Once that validation is complete, activate posting on both the app host and the
Windows connector. You still review and confirm each voucher on the phone. The app
shows it as saved only after Tally confirms creation. Lost/uncertain responses require
checking Tally instead of automatically repeating the import.

## Daily use

The hosted app must be running. For fresh Tally data and posting, the office laptop
must be awake, have internet, and keep Tally, Upkar Agency and the connector running.
If the laptop is offline, the app can display the last synced data with its timestamp
and keep drafts for later. After hosting, the phone web app can be added to its home
screen using the browser's home-screen option; installation and camera behavior need
checking on the actual phone.

See WINDOWS.md for technical activation and recovery details.
