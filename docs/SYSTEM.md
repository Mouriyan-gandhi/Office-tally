# How the deployed system works

## Roles

| Component | Responsibility |
| --- | --- |
| Phone | Sign in; prepare/review entries; photograph bills; view reports/status |
| Render Python backend | Authorization, accounting validation, OCR, job queue API |
| Supabase Auth | Verify the one configured admin's identity and password |
| Supabase PostgreSQL | Durable drafts, pending jobs, synced masters, audit and reports |
| Supabase private Storage | Original bill images and PDFs |
| Windows connector | Export from and import into local Tally over XML/HTTP |
| TallyPrime Silver | Accounting source of truth |

## Purchase bill OCR

1. The signed-in phone uploads a JPG, PNG or PDF to POST /api/upload. The body is
   size-limited and the file signature is checked. The app enforces admin permission
   and CSRF validation before storing the file.
2. The cloud backend saves the original in the private office-invoices bucket. Only
   an authorized app request can download it; the browser gets no storage admin key.
3. The backend creates a disposable temporary file. Poppler converts up to the first
   three PDF pages to images when applicable.
4. Tesseract reads the image text in the Render container. The total work budget is
   approximately 45 seconds; individual render/OCR commands have timeouts. Missing
   tools, an unreadable bill or a timeout return a manual-entry fallback.
5. Conservative text rules suggest invoice reference, an ISO-formatted date, GSTIN
   text, simple item rows, printed total, and visible CGST/SGST/IGST rates.
6. Exact normalized item-name matches use the last synced Tally stock masters. Unknown
   supplier/item mappings stay visible for manual selection. No arbitrary layout is
   guaranteed, and this does not perform authoritative GSTIN registration checks.
7. You review/correct the proposed purchase draft against the original. The backend
   recomputes amounts with decimal arithmetic. The entry must match a supplied printed
   total; a mismatch blocks the draft until corrected.
8. OCR alone never creates a voucher. Only a separate owner approval queues posting.

This is on-demand document processing after upload, not live video recognition and
not an instant-response guarantee. Speed depends on the bill, network and hosting.
Invoices are processed inside your hosted backend, without Gemini or another external
AI service. Complex tables, mixed GST rates and poor photos still require manual work.

## Voucher posting

1. Save a sales, purchase, receipt or payment draft. No Tally import happens yet.
2. The owner reviews and approves it. The app checks the draft version, company,
   masters, account groups, amounts and recent sync. Duplicate submitted supplier
   references are blocked.
3. PostgreSQL records a single posting job per draft. A transaction-scoped advisory
   lock serializes changes across app instances, preventing concurrent job claims.
4. The Windows connector initiates an outbound HTTPS request about every 20 seconds.
   It authenticates with a device pairing token, not a Supabase admin key.
5. The server leases one approved job. The worker validates its company and fields
   again against fresh Tally masters.
6. Before any import, the worker durably records the job in its local SQLite journal.
   It builds allowlisted voucher XML and posts it to 127.0.0.1:9000 on Windows.
7. The worker accepts success only when Tally confirms one creation with no errors,
   exceptions or other alterations. It sends the result to the hosted backend.
8. The phone refreshes pending statuses every five seconds while the app is visible.
   A queued voucher is not labelled saved before confirmation.
9. A timeout, partial response or expired lease becomes Check in Tally. It is never
   automatically imported again. The operator must inspect Tally before replacement.

Receipt/payment workflows record accounting vouchers; they do not transfer bank funds.
Stock and balances shown on the phone are timestamped snapshots refreshed by the worker,
not direct browser connections to Tally. An office laptop that is offline/asleep cannot
perform new imports or fresh exports, though the hosted app can retain drafts.

## Read-only reports

The app accepts only predefined report names and date parameters, never caller-supplied
TDL, SQL or raw XML. Read requests use a separate queue that works with writes disabled.
Tally exports are preserved as original fields until actual company layouts are mapped.
The chatbot uses approved deterministic intents and reports its data scope/freshness.

## Verification boundary

Local HTTP, Auth/storage protocol and production transport tests are separate from
PostgreSQL integration tests and the simulated Tally round trip. None of these tests
read or write the user's real company. Real Tally 7.1 mappings must be validated on
Windows before production voucher entry.
