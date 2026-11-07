# Development plan and confirmed requirements

## Confirmed

Upkar Agency (exact spelling), TallyPrime Silver 7.1, Windows office laptop with
inventory and accounting. HTTP server on port 9000 works locally. Development happens
on a separate MacBook. User wants a business-owner-friendly mobile interface, minimal
running cost, local OCR, a chatbot without generative AI, and optional WhatsApp.
User reports having a Tally backup and permits connecting to the existing company.

## Built locally

Private owner workspace, isolated demo, four draft workflows, stock/ledger search,
server-side accounting validation, local OCR suggestions and attachments, approved
query intents, reports/CSV/print, outbound Windows connector, approval queue and import
journal. No live company data has been read or written during development.

## Validation and delivery stages

1. Local unit/HTTP tests and desktop/mobile browser checks using fictional data.
2. Share local preview and source package for review. Do not request company credentials.
3. When user is ready, validate XML exports and imports on Windows, first using a test
   company for writes. Compare stock, balances, bill references, taxes and numbering.
4. Confirm company-specific GST/inventory/voucher mappings, then complete polished
   financial report layouts from actual export fixtures. Add advanced features only
   after matching the real Tally setup.
5. Choose commercially suitable hosting after checking current terms and budget.
   Configure persistent backend storage, HTTPS, private auth, backups, a production
   process server and a reachable outbound connector endpoint. The local preview is
   not a substitute for this phone/cloud deployment.
6. Activate live posting only after validation; owner review remains mandatory.
7. Optional official WhatsApp Cloud API delivery after recipient/consent/template setup.

## Deferred configuration — do not interrupt the build to ask

Number of users/roles, custom GST ledgers, godowns/batches, bill-wise settings, custom
voucher types and numbering, hosting budget and desired WhatsApp integration. These
are needed for deployment/accounting validation, not for the isolated local build.
