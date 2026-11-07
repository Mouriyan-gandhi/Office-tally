# Local pilot status — 7 November 2026

## Verified locally

- 48 automated checks passed, including HTTP authentication/CSRF/role checks,
  demo/live isolation, decimal totals, all four voucher XML debit/credit directions,
  bill allocations, incompatible tax rejection, duplicate approval/supplier invoice
  rejection, lease expiry, durable import idempotency, partial import uncertainty,
  report allowlisting and upload attachment scope.
- JavaScript syntax checks passed for both browser scripts.
- Browser inspection at 1440×1050 and 390×844: responsive dashboard, mobile navigation,
  receipt draft/review/confirmation, payment draft/review/confirmation, stock views,
  report navigation and report request controls.
- Actual local Tesseract read a fictional bill image with invoice DEMO-2026-001,
  10 backpacks at ₹450, CGST/SGST at 9% each and a ₹5,310 printed total. Suggested
  items/taxes populated the purchase editor. After selecting the supplier and
  approving the fictional purchase, demo stock increased from 48 to 58 units.
- A fictional receipt changed the customer's balance and cash balance as expected;
  a fictional supplier payment saved through the mobile review flow.
- No browser console errors observed during these checks.

## Implemented, still needs office validation

- Real Tally company/master exports, group ancestry resolution and balance signs.
- Receipt/payment and inventory sales/purchase import compatibility with TallyPrime 7.1.
- Tally voucher numbering, GST/statutory mappings, and bill reference allocation.
- Actual financial report XML, which is preserved as original fields pending mobile
  column mapping against real exports.
- Windows launcher and DPAPI token storage: authored on macOS, not run on Windows here.
- Windows/Linux CI matrix is configured; its remote results are not yet verified.

## Not deployed / not supported in this pilot

- Reachable HTTPS hosting and phone-to-office deployment. The local preview is Mac-only.
- An installed Windows background service or packaged executable (the source worker
  runs continuously while its launcher remains open).
- Mixed-GST-rate invoices, batch/godown allocation, custom voucher classes, credit notes,
  e-invoicing, statutory invoice PDFs and automatic WhatsApp Cloud API delivery.
- Invoice OCR for every supplier layout: conservative patterns suggest simple rows;
  unknown layouts require manual entry. PDF OCR considers only the first three pages.
- Full financial reports are not calculated from incomplete app records. They must be
  fetched from Tally and verified. Outstanding master balances are not invoice ageing.

## No live changes

The preview uses fictional data in its own SQLite database and blocks connector access.
No actual Tally company read or write was performed. Production posting is off by default,
with activation required at both the app and Windows worker, plus per-entry owner review.
