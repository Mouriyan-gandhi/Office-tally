# Pilot security and operational boundary

- App binds to 127.0.0.1. It is intended for local pilot use, not public exposure of
  Python's development HTTP server. A production server/HTTPS deployment is still needed.
- Owner passwords are salted/scrypt-hashed. Sessions expire after eight hours and use
  HttpOnly, SameSite=Strict cookies. Set `OFFICE_SECURE_COOKIE=YES` behind HTTPS.
- CSRF tokens protect user mutations, origins are checked, and browser credentials
  cannot invoke connector endpoints. Only owners can approve voucher imports.
- One company is allowlisted. There is no arbitrary SQL, raw XML execution endpoint,
  arbitrary report name, remote Tally URL, or inbound connector listener.
- The Windows worker connects to local Tally only. Its app connection requires HTTPS
  except explicit loopback development. Redirects are refused to protect bearer tokens.
- Windows pairing encrypts the device token with DPAPI under the signed-in user's key.
  App-host credentials belong in secret storage. Rotate the device token to revoke access.
- XML is size-limited, DTD/entity declarations and UTF-16/null encodings are rejected.
  Invalid control references emitted by Tally for reserved names are removed for parsing.
- Uploads are authenticated, size-limited and signature-checked. OCR subprocesses have
  timeouts, use fixed argument lists and cannot execute uploaded shell commands.
  For public/multi-user operation add stronger file validation, malware scanning,
  process isolation/resource limits and storage quotas before deployment.
- Invoice files and SQLite data are not encrypted by the app. Use disk encryption,
  OS account permissions and an agreed retention/deletion/backup policy on the host.
- Database and attachment directories are ignored by Git. No secrets are included in
  source or release ZIPs. Stop the pilot before copying its data directory as a backup.
- Queue leasing is transactional. Each draft can produce at most one job. The device
  has a durable idempotency journal. Unknown outcomes require manual reconciliation.
- Demo data is separate, visibly labelled, and cannot be queued to Tally. The preview
  launch disables all live workspaces and connector endpoints.
- Activity logs contain actions and record IDs, not authentication headers or voucher XML.

This is not a claim of a completed independent security review or production accounting
certification. Phone/cloud access, backups and release validation remain deployment work.
