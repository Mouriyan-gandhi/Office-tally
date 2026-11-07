# Upkar Agency · Office

A phone-first accounting and inventory companion for **TallyPrime Silver 7.1**.
Built on the Mac; the outbound connector runs beside Tally on the Windows office laptop.

## Try it on the Mac

Python 3.11+ is the only required runtime. No npm install or cloud account is needed.

```sh
python3 -m app.server --preview
```

Open **http://127.0.0.1:8765** and choose **Explore the demo**. Or double-click
`scripts/start-preview.command` on the Mac. Preview mode uses its own local database,
blocks connector endpoints and cannot access live Tally data or post entries.

## Implemented

- Phone-first home with quick actions, thumb-sized controls and persistent bottom navigation.
- Dedicated transaction/ledger/stock cards, camera capture, stacked item forms, bottom-sheet reviews and a fixed phone review bar.
- Sales and purchase drafts with stock quantities, units, rates and discounts.
- Receipt/payment drafts with optional bill allocations.
- Single-rate CGST+SGST or IGST, server-side decimal calculations and printed-total checks.
- Explicit review/approval, status tracking, optimistic edit locking and audit trail.
- Searchable ledgers and inventory with snapshot dates and debit/credit labels.
- App registers and CSV export; printable summaries/statements that can be saved as PDF.
- Image/PDF attachments, local Tesseract OCR and conservative item/date/tax suggestions.
- Deterministic accounts assistant: balances, stock, sales/purchases by supported periods,
  exact-name lookup, numeric outstanding filters and latest fetched Tally financial reports.
- Allowlisted read requests for day book, ledger statements, outstanding bills,
  trial balance, stock, sales/purchase registers, P&L and balance sheet.
- Owner/operator/viewer roles; password hashing, HttpOnly sessions and CSRF checks.
- Outbound authenticated Windows worker, write guards, durable import journal and no
  blind retries after an uncertain import. Device token protected with Windows DPAPI.
- Manual WhatsApp text sharing; the user chooses the recipient and sends the message.

## Cloud deployment

The Supabase/PostgreSQL backend and Render Docker deployment are now implemented.
Follow [DEPLOY.md](docs/DEPLOY.md) to configure the private database, single admin,
private storage and Windows pairing. [SYSTEM.md](docs/SYSTEM.md) explains the OCR and
voucher flow. Deployment to your own accounts and actual Tally validation are separate
steps; adding credentials to chat does not deploy anything.

## Current release boundary

This is a tested-source pilot, not a completed deployment to your accounts. All demo workflows
can be exercised without Windows. Actual Tally 7.1 exports/imports must be validated
on the office laptop before live use. The local preview listens on the Mac's loopback address. Deploy the included ASGI
backend on Render for phone and Windows access; do not expose the development server.

Full Tally report exports preserve original field names and values. Their final mobile
column mappings require real export fixtures. GST invoice statutory details, mixed-rate
items, batches/godowns, custom voucher types, e-invoicing, credit notes, automatic
WhatsApp delivery are outside this pilot's supported accounting scope. Cloud deployment files are included,
but hosting and actual-company validation must still be completed.
Printable summaries are **not statutory tax invoices**. Read [STATUS.md](docs/STATUS.md)
for the precise verified/unverified split.

## Private workspace

```sh
python3 -m app.server --setup
python3 -m app.server
```

Setup prompts locally for the owner's email and password. There are no default live
credentials. To add another local account, run `python3 -m app.users --role operator`
or `--role viewer`. Only owners may approve entries. Operator accounts prepare drafts;
viewers can inspect data and ask approved read queries.

Local data lives in `local-data/` and is ignored by Git. Back it up, including documents,
with the app stopped. This is a single-company app; it is not a multi-tenant service.

## OCR

Install Tesseract from its official distribution/package manager on the **app host**.
Install Poppler for PDF rendering. Without these optional tools, original attachments
and manual purchase entry still work. PDF OCR reads only the first three pages; results
are explicitly labelled. Bills are processed locally and never sent to external AI.
For private production invoice handling, see the isolation and retention notes in
[SECURITY.md](docs/SECURITY.md).

## Windows connector

Start with the [plain-language connection guide](docs/CONNECT.md), then see [Windows setup](docs/WINDOWS.md). It uses XML over HTTP to **127.0.0.1:9000** only.
Never expose that port to the internet. The connector does not listen for incoming
connections. Cloud URL and device credentials are supplied during the later connection
stage; don't put them in chat or Git. Live writes require activation at both ends.

## Checks

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
node --check web/reports.js
```

The HTTP tests use disposable local databases and temporary local ports. Worker tests
use mocks and fixtures; none connect to your actual Tally company. GitHub Actions is
configured to run the suite on Windows and Linux with Python 3.11/3.13, but remote
workflow results must be checked after pushing.

## Official integration references

- [Tally XML integration](https://help.tallysolutions.com/xml-integration/)
- [Tally sample XML and report names](https://help.tallysolutions.com/sample-xml/)
