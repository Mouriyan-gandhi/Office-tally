"""Dependency-free local pilot server. Bind only to loopback; cloud rollout is separate."""
import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sqlite3
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from app import store, cloud
from app.assistant import answer
from app.demo import seed
from app.domain import ValidationError, normalize_draft, require_masters
from app.ocr import extract
from app.reporting import REPORTS, parameters
from app import history

WEB = store.ROOT / 'web'
from app.company import COMPANY
MAX_BODY = 12 * 1024 * 1024
SESSION_AGE = 8 * 3600
DEVICE_TOKEN = os.environ.get('OFFICE_CONNECTOR_TOKEN', '')
LIVE_WRITES = os.environ.get('OFFICE_ENABLE_POSTING') == 'YES'
ATTEMPTS = {}
PREVIEW = False

class ForbiddenError(PermissionError):
    pass


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return salt + ':' + value


def check_password(password, encoded):
    salt, _ = encoded.split(':', 1)
    return hmac.compare_digest(password_hash(password, salt), encoded)


def session_id(token):
    return hashlib.sha256(token.encode()).hexdigest() if cloud.enabled() else token


def init_user(email, password):
    if cloud.enabled():
        raise ValueError('Create the admin in Supabase Authentication, then set OFFICE_OWNER_EMAIL on the host')
    if '@' not in email or len(email) > 200:
        raise ValueError('Enter a valid owner email address')
    if len(password) < 12:
        raise ValueError('Choose a password with at least 12 characters')
    with store.transaction() as db:
        if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            raise ValueError('An owner already exists; initialization is not a password reset')
        db.execute('INSERT INTO users VALUES(?,?,?,?)', (secrets.token_hex(16), email.lower(), password_hash(password), 'owner'))


def draft_row(row):
    result = json.loads(row['payload']) | {key: row[key] for key in ['id', 'status', 'version', 'created', 'updated']}
    if 'result' in row.keys():
        result['result'] = row['result']
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = 'OfficeTally'

    def log_message(self, *_):
        pass  # URLs and request bodies may contain confidential business information.

    def respond(self, status, payload, headers=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.security_headers()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def security_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def payload(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise ValidationError('Invalid request length') from None
        if not 0 < size <= MAX_BODY:
            raise ValidationError('Request is empty or too large')
        try:
            payload = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError):
            raise ValidationError('Invalid JSON request') from None
        if not isinstance(payload, dict):
            raise ValidationError('Expected a JSON object')
        return payload

    def user(self, db, mutate=False):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            token = cookie.get('office_session')
        except Exception:
            token = None
        session = db.execute('SELECT s.*,u.email,u.role FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.id=? AND s.expires>?', (session_id(token.value) if token else '', time.time())).fetchone()
        if not session:
            raise PermissionError('Sign in to continue')
        if cloud.enabled():
            if session['email'].casefold() != cloud.settings()['owner'] or session['role'] != 'owner':
                raise ForbiddenError('This account is not the approved admin')
            cloud.verify_admin(session['user_id'])
        if mutate and not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
            raise ForbiddenError('Session check failed; reload the page')
        return session

    def device(self):
        token = self.headers.get('Authorization', '')
        if len(DEVICE_TOKEN) < 32 or not hmac.compare_digest(token, 'Bearer ' + DEVICE_TOKEN):
            raise PermissionError('Connector authentication failed')

    def mode(self, payload):
        mode = payload.get('mode', 'demo')
        if PREVIEW and mode != 'demo':
            raise ValidationError('Preview is demo-only')
        if mode not in ('demo', 'live'):
            raise ValidationError('Invalid data mode')
        return mode

    def do_GET(self):
        try:
            self.get()
        except cloud.CloudError as error:
            self.respond(503, {'error': str(error)})
        except ForbiddenError as error:
            self.respond(403, {'error': str(error)})
        except PermissionError as error:
            self.respond(401, {'error': str(error)})
        except (ValidationError, ValueError) as error:
            self.respond(400, {'error': str(error)})
        except Exception:
            self.respond(500, {'error': 'The request failed. Please try again.'})

    def get(self):
        route = urlparse(self.path)
        if route.path == '/api/config':
            return self.respond(200, {'preview': PREVIEW, 'cloud': cloud.enabled(), 'single_admin': cloud.enabled()})
        if route.path == '/api/session':
            with store.transaction() as db:
                user = self.user(db)
                return self.respond(200, {'email': user['email'], 'role': user['role'], 'csrf': user['csrf'], 'company': COMPANY})
        if route.path == '/api/ledger-history':
            from urllib.parse import parse_qs
            ledger = parse_qs(route.query).get('ledger',[''])[0]
            with store.transaction() as db:
                self.user(db)
                if cloud.enabled() and not db.execute('SELECT version FROM schema_migrations WHERE version=2').fetchone():
                    return self.respond(200, {'rows':[], 'coverage':[], 'note':'History database update is not installed yet.'})
                if ledger not in {r['name'] for r in store.snapshot(db,'live')['ledgers']}:
                    raise ValidationError('Ledger not found in synced masters')
                return self.respond(200, history.statement(db,ledger))
        if route.path == '/api/reports':
            with store.transaction() as db:
                self.user(db)
                rows = []
                for row in db.execute('SELECT * FROM report_requests ORDER BY created DESC LIMIT 30'):
                    rows.append({'id': row['id'], 'report': row['report'], 'title': REPORTS[row['report']], 'params': json.loads(row['params']), 'status': row['status'], 'result': json.loads(row['result']) if row['result'] else None, 'updated': row['updated']})
                return self.respond(200, {'reports': rows})
        if route.path == '/api/state':
            from urllib.parse import parse_qs
            mode = self.mode({'mode': parse_qs(route.query).get('mode', ['demo'])[0]})
            with store.transaction() as db:
                user = self.user(db)
                snap = store.snapshot(db, mode)
                drafts = [draft_row(row) for row in db.execute('SELECT d.*,j.result FROM drafts d LEFT JOIN jobs j ON j.draft_id=d.id WHERE mode=? ORDER BY d.created DESC', (mode,))]
                logs = [dict(row) for row in db.execute('SELECT actor,action,target,at FROM audit ORDER BY id DESC LIMIT 100')]
                return self.respond(200, {'snapshot': snap, 'drafts': drafts, 'audit': logs,
                    'connector': {'configured': len(DEVICE_TOKEN) >= 32, 'posting_enabled': LIVE_WRITES,
                    'fresh': bool(snap['synced_at'] and time.time() - snap['synced_at'] < 300), 'company': COMPANY},
                    'ocr_available': bool(__import__('shutil').which('tesseract'))})
        if route.path.startswith('/api/documents/'):
            document_id = route.path.rsplit('/', 1)[-1]
            with store.transaction() as db:
                self.user(db)
                row = db.execute('SELECT * FROM documents WHERE id=?', (document_id,)).fetchone()
                if not row:
                    return self.respond(404, {'error': 'Document not found'})
                body = cloud.get_file(row['path']) if cloud.enabled() else Path(row['path']).read_bytes()
                self.send_response(200)
                self.security_headers()
                self.send_header('Content-Type', row['mime'])
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        allowed = {'/': 'index.html', '/app.js': 'app.js', '/reports.js':'reports.js', '/styles.css': 'styles.css', '/phone.css':'phone.css', '/icon.svg': 'icon.svg', '/manifest.webmanifest': 'manifest.webmanifest'}
        if route.path not in allowed:
            return self.respond(404, {'error': 'Not found'})
        path = WEB / allowed[route.path]
        body = path.read_bytes()
        self.send_response(200)
        self.security_headers()
        self.send_header('Content-Type', mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            # Reject cross-site mutations, including login; the browser must use this origin.
            origin = self.headers.get('Origin')
            host = self.headers.get('Host', '')
            if origin and origin not in ('http://' + host, 'https://' + host):
                raise ForbiddenError('Cross-site request rejected')
            self.post()
        except cloud.CloudError as error:
            self.respond(503, {'error': str(error)})
        except ForbiddenError as error:
            self.respond(403, {'error': str(error)})
        except PermissionError as error:
            self.respond(401, {'error': str(error)})
        except (ValidationError, ValueError, KeyError, TypeError) as error:
            self.respond(400, {'error': str(error) if isinstance(error, ValueError) else 'Invalid or incomplete request'})
        except sqlite3.IntegrityError:
            self.respond(409, {'error': 'This action has already been recorded. Refresh to check its status.'})
        except Exception:
            self.respond(500, {'error': 'The request failed. No success is confirmed; check the activity list before retrying.'})

    def post(self):
        path = urlparse(self.path).path
        data = self.payload()
        if path.startswith('/api/connector/'):
            if PREVIEW:
                raise PermissionError('Connectors are disabled in preview mode')
            self.device()
            return self.connector(path, data)
        if path == '/api/preview':
            if not PREVIEW:
                raise PermissionError('Preview is not available')
            with store.transaction() as db:
                user = db.execute('SELECT * FROM users LIMIT 1').fetchone()
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (token, user['id'], csrf, time.time()+SESSION_AGE))
            return self.respond(200, {'email': user['email'], 'role': user['role'], 'csrf': csrf}, {'Set-Cookie': f'office_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_AGE}'})
        if path == '/api/login':
            now = time.time()
            key = self.client_address[0]
            failures = [t for t in ATTEMPTS.get(key, []) if now - t < 300]
            if len(failures) >= 10:
                return self.respond(429, {'error': 'Too many attempts. Wait five minutes.'})
            email = str(data.get('email', '')).lower().strip()
            identity = None
            if cloud.enabled():
                try:
                    identity = cloud.sign_in(email,str(data.get('password',''))[:1000])
                except PermissionError:
                    ATTEMPTS[key] = failures + [now]
                    raise
            with store.transaction() as db:
                user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
                if identity:
                    if user is None:
                        db.execute('INSERT INTO users VALUES(?,?,?,?)',(identity['id'],identity['email'],'supabase-auth-only','owner'))
                        user = db.execute('SELECT * FROM users WHERE id=?',(identity['id'],)).fetchone()
                    if user['id'] != identity['id'] or user['role'] != 'owner':
                        raise ForbiddenError('Admin identity changed; review and revoke old app sessions before re-pairing this account')
                elif not user or not check_password(str(data.get('password', ''))[:1000], user['password']):
                    ATTEMPTS[key] = failures + [now]
                    raise PermissionError('Email or password is incorrect')
                ATTEMPTS.pop(key, None)
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.execute('DELETE FROM sessions WHERE expires<?', (now,))
                db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (session_id(token), user['id'], csrf, now + SESSION_AGE))
                store.audit(db, email, 'signed_in', 'session')
            secure = '; Secure' if cloud.enabled() or os.environ.get('OFFICE_SECURE_COOKIE') == 'YES' else ''
            return self.respond(200, {'email': email, 'role': user['role'], 'csrf': csrf}, {'Set-Cookie': f'office_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_AGE}{secure}'})
        if path == '/api/upload':
            return self.upload(data)
        with store.transaction() as db:
            user = self.user(db, mutate=True)
            actor = user['email']
            if user['role'] == 'viewer' and path not in ('/api/logout', '/api/chat', '/api/request-report'):
                raise ForbiddenError('This account has read-only access')
            if path == '/api/logout':
                db.execute('DELETE FROM sessions WHERE id=?', (user['id'],))
                secure = '; Secure' if cloud.enabled() else ''
                return self.respond(200, {'ok': True}, {'Set-Cookie': 'office_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict'+secure})
            if path == '/api/demo':
                seed(db, actor)
                return self.respond(200, {'ok': True})
            mode = self.mode(data)
            if path == '/api/request-report':
                if PREVIEW or mode != 'live':
                    raise ValidationError('Full Tally report requests require the connected Tally workspace')
                params = parameters(data)
                if params['report'] == 'ledger' and params['ledger'] not in {r['name'] for r in store.snapshot(db, 'live')['ledgers']}:
                    raise ValidationError('Ledger not found in synced masters')
                pending = db.execute("SELECT COUNT(*) FROM report_requests WHERE status IN ('queued','reading')").fetchone()[0]
                if pending >= 30:
                    raise ValidationError('Too many pending reports. Wait for the office connector to finish.')
                identifier = secrets.token_hex(16)
                db.execute('INSERT INTO report_requests VALUES(?,?,?,?,?,?,?,?)', (identifier, params['report'], json.dumps(params), 'queued', None, None, time.time(), time.time()))
                store.audit(db, actor, 'report_requested', identifier)
                return self.respond(200, {'id': identifier})
            if path == '/api/chat':
                snap = store.snapshot(db, mode)
                if mode == 'live':
                    snap['available_reports'] = {}
                    for record in db.execute("SELECT * FROM report_requests WHERE status='ready' ORDER BY updated DESC"):
                        if record['report'] not in snap['available_reports']:
                            params = json.loads(record['params'])
                            snap['available_reports'][record['report']] = {'title':REPORTS[record['report']], 'from':params['from'], 'to':params['to'], 'updated':record['updated'], 'rows':json.loads(record['result'])['rows']}
                vouchers = [draft_row(row) for row in db.execute('SELECT * FROM drafts WHERE mode=?', (mode,))]
                return self.respond(200, answer(str(data.get('question', '')), snap, vouchers))
            if path == '/api/drafts':
                payload = normalize_draft(data.get('draft'))
                if payload['document_id'] and not db.execute('SELECT 1 FROM documents WHERE id=? AND mode=?', (payload['document_id'], mode)).fetchone():
                    raise ValidationError('Bill attachment not found in this data mode')
                old = db.execute('SELECT * FROM drafts WHERE id=? AND mode=?', (str(data.get('id', '')), mode)).fetchone()
                if old and (old['status'] != 'draft' or old['version'] != data.get('version')):
                    raise ValidationError('This draft changed or was submitted. Refresh before continuing.')
                identifier = old['id'] if old else secrets.token_hex(16)
                if old:
                    db.execute('UPDATE drafts SET payload=?,updated=?,version=version+1 WHERE id=?', (json.dumps(payload), time.time(), identifier))
                else:
                    db.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?)', (identifier, mode, json.dumps(payload), 'draft', 1, time.time(), time.time(), actor))
                store.audit(db, actor, 'draft_saved', identifier)
                return self.respond(200, {'id': identifier, 'total': payload['total']})
            if path in ('/api/approve', '/api/delete'):
                row = db.execute('SELECT * FROM drafts WHERE id=? AND mode=?', (data.get('id'), mode)).fetchone()
                if not row or row['status'] != 'draft' or row['version'] != data.get('version'):
                    raise ValidationError('Draft no longer available. Refresh the page.')
                if path == '/api/delete':
                    db.execute("UPDATE drafts SET status='cancelled',version=version+1,updated=? WHERE id=?", (time.time(), row['id']))
                    store.audit(db, actor, 'draft_cancelled', row['id'])
                    return self.respond(200, {'ok': True})
                if user['role'] != 'owner':
                    raise ForbiddenError('Only an owner may approve entries')
                if data.get('confirmation') != COMPANY:
                    raise ValidationError('Confirm the exact company name before submitting')
                payload = normalize_draft(json.loads(row['payload']))
                if mode == 'demo':
                    require_masters(payload, store.snapshot(db, 'demo'))
                    from app.demo_accounting import apply
                    apply(db, payload)
                    status = 'demo_saved'
                else:
                    if not LIVE_WRITES:
                        raise ValidationError('Live posting has not been activated on the app host')
                    snap = store.snapshot(db, mode)
                    if not snap['synced_at']:
                        raise ValidationError('Connect the office laptop and refresh Tally data first')
                    require_masters(payload, snap)
                    if payload.get('voucher_number'):
                        for candidate in db.execute("SELECT payload FROM drafts WHERE mode='live' AND id<>? AND status IN ('queued','posting','posted','needs_review')",(row['id'],)):
                            other=json.loads(candidate['payload'])
                            if other['kind']==payload['kind'] and (int(other['date'][:4])-(int(other['date'][5:7])<4))==(int(payload['date'][:4])-(int(payload['date'][5:7])<4)) and other.get('voucher_number','').casefold()==payload['voucher_number'].casefold():
                                raise ValidationError('This voucher number was already submitted for this type and year')
                    if payload['kind'] == 'Purchase':
                        for candidate in db.execute("SELECT id,payload FROM drafts WHERE mode='live' AND id<>? AND status IN ('queued','posting','posted','needs_review')", (row['id'],)):
                            other = json.loads(candidate['payload'])
                            if other['kind'] == 'Purchase' and other['party'].casefold() == payload['party'].casefold() and other['reference'].casefold() == payload['reference'].casefold():
                                raise ValidationError('This supplier invoice reference was already submitted. Check for a duplicate.')
                    db.execute('INSERT INTO jobs(id,draft_id,payload,status,created) VALUES(?,?,?,?,?)', (secrets.token_hex(16), row['id'], json.dumps(payload), 'queued', time.time()))
                    status = 'queued'
                db.execute('UPDATE drafts SET status=?,updated=?,version=version+1 WHERE id=?', (status, time.time(), row['id']))
                store.audit(db, actor, 'demo_saved' if mode == 'demo' else 'posting_approved', row['id'])
                return self.respond(200, {'status': status})
            return self.respond(404, {'error': 'Not found'})

    def upload(self, data):
        if cloud.enabled():
            with store.transaction() as db:
                user = self.user(db,mutate=True)
                if user['role'] != 'owner':
                    raise ForbiddenError('Only the approved admin can upload bills')
                actor,mode = user['email'],self.mode(data)
            from app.cloud_uploads import upload
            return self.respond(200,upload(data,actor,mode))
        with store.transaction() as db:
            user = self.user(db, mutate=True)
            if user['role'] == 'viewer':
                raise ForbiddenError('This account has read-only access')
            actor = user['email']
            mode = self.mode(data)
            name = str(data.get('name', 'bill'))[:200]
            try:
                raw = base64.b64decode(data.get('content', ''), validate=True)
            except Exception:
                raise ValidationError('Invalid image upload') from None
            if not raw or len(raw) > 8 * 1024 * 1024:
                raise ValidationError('Upload a file smaller than 8 MB')
            if raw.startswith(b'\x89PNG\r\n\x1a\n'):
                mime, suffix = 'image/png', '.png'
            elif raw.startswith(b'\xff\xd8\xff'):
                mime, suffix = 'image/jpeg', '.jpg'
            elif raw.startswith(b'%PDF-'):
                mime, suffix = 'application/pdf', '.pdf'
            else:
                raise ValidationError('Upload a JPG, PNG or PDF')
            identifier = secrets.token_hex(16)
            folder = store.DATA / 'documents'
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / (identifier + suffix)
            target.write_bytes(raw)
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)', (identifier, mode, name, mime, str(target), time.time()))
            store.audit(db, actor, 'bill_uploaded', identifier)
        return self.respond(200, {'id': identifier, 'mime': mime, 'name': name, 'ocr': extract(target)})

    def connector(self, path, data):
        with store.transaction() as db:
            if path in ('/api/connector/poll-history','/api/connector/history-result'):
                if cloud.enabled() and not db.execute('SELECT version FROM schema_migrations WHERE version=2').fetchone():
                    return self.respond(200, {'period':None, 'migration_required':2})
                if path.endswith('poll-history'):
                    return self.respond(200, {'period':history.poll(db,data.get('books_from'))})
                history.accept(db,data)
                return self.respond(200, {'ok':True})
            if path == '/api/connector/poll-read':
                db.execute("UPDATE report_requests SET status='queued',lease=NULL WHERE status='reading' AND updated<?", (time.time()-180,))
                row = db.execute("SELECT * FROM report_requests WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if not row:
                    return self.respond(200, {'request': None})
                lease = secrets.token_urlsafe(32)
                db.execute("UPDATE report_requests SET status='reading',lease=?,updated=? WHERE id=?", (lease,time.time(),row['id']))
                return self.respond(200, {'request': {'id': row['id'], 'lease': lease, 'params': json.loads(row['params'])}})
            if path == '/api/connector/read-result':
                row = db.execute('SELECT * FROM report_requests WHERE id=?', (data.get('id'),)).fetchone()
                if not row or not row['lease'] or not hmac.compare_digest(row['lease'], str(data.get('lease',''))):
                    raise PermissionError('Invalid report lease')
                result = data.get('result')
                if not isinstance(result, dict) or not isinstance(result.get('rows'), list) or len(result['rows']) > 20000:
                    raise ValidationError('Invalid report result')
                for line in result['rows']:
                    if not isinstance(line, dict) or not isinstance(line.get('field'), str) or not isinstance(line.get('value'), str):
                        raise ValidationError('Invalid report field')
                db.execute('UPDATE report_requests SET status=?,result=?,updated=? WHERE id=?', ('failed' if result.get('error') else 'ready',json.dumps(result),time.time(),row['id']))
                store.audit(db, 'connector', 'report_received', row['id'])
                return self.respond(200, {'ok':True})
            if path == '/api/connector/snapshot':
                snap = data.get('snapshot')
                if not isinstance(snap, dict) or snap.get('company') != COMPANY:
                    raise ValidationError('Unexpected company')
                if not isinstance(snap.get('ledgers'), list) or not isinstance(snap.get('stock'), list):
                    raise ValidationError('Invalid master snapshot')
                if len(snap['ledgers']) > 50000 or len(snap['stock']) > 50000:
                    raise ValidationError('Snapshot too large')
                for row in snap['ledgers'] + snap['stock']:
                    if not isinstance(row, dict) or not isinstance(row.get('name'), str):
                        raise ValidationError('Invalid master')
                snap['source'] = 'TallyPrime · local connector'
                db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?)', ('live', json.dumps(snap), time.time()))
                store.audit(db, 'connector', 'masters_synced', COMPANY)
                return self.respond(200, {'ok': True})
            if path == '/api/connector/poll':
                now = time.time()
                # Never requeue an expired lease: a disconnected worker may already have posted.
                expired = db.execute("SELECT draft_id FROM jobs WHERE status='leased' AND leased_at<?", (now-180,)).fetchall()
                for row in expired:
                    db.execute("UPDATE drafts SET status='needs_review',version=version+1,updated=? WHERE id=?", (now, row['draft_id']))
                db.execute("UPDATE jobs SET status='needs_review' WHERE status='leased' AND leased_at<?", (now-180,))
                if not LIVE_WRITES:
                    return self.respond(200, {'job': None})
                job = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if not job:
                    return self.respond(200, {'job': None})
                if now-job['created'] > 86400:
                    db.execute("UPDATE jobs SET status='needs_review' WHERE id=?", (job['id'],))
                    db.execute("UPDATE drafts SET status='needs_review',version=version+1 WHERE id=?", (job['draft_id'],))
                    return self.respond(200, {'job': None})
                lease = secrets.token_urlsafe(32)
                db.execute("UPDATE jobs SET status='leased',lease=?,leased_at=? WHERE id=?", (lease, now, job['id']))
                db.execute("UPDATE drafts SET status='posting',version=version+1 WHERE id=?", (job['draft_id'],))
                return self.respond(200, {'job': {'id': job['id'], 'lease': lease, 'company': COMPANY, 'draft': json.loads(job['payload'])}})
            if path == '/api/connector/result':
                job = db.execute('SELECT * FROM jobs WHERE id=?', (data.get('id'),)).fetchone()
                if not job or not job['lease'] or not hmac.compare_digest(job['lease'], str(data.get('lease', ''))):
                    raise PermissionError('Invalid job lease')
                status = data.get('status')
                if status not in ('posted', 'rejected', 'needs_review'):
                    raise ValidationError('Invalid result status')
                if job['status'] in ('posted', 'rejected'):
                    return self.respond(200, {'ok': True})
                result = str(data.get('message', ''))[:1000]
                db.execute('UPDATE jobs SET status=?,result=? WHERE id=?', (status, result, job['id']))
                db.execute('UPDATE drafts SET status=?,updated=?,version=version+1 WHERE id=?', (status, time.time(), job['draft_id']))
                store.audit(db, 'connector', status, job['draft_id'])
                return self.respond(200, {'ok': True})
            return self.respond(404, {'error': 'Not found'})


def main():
    parser = argparse.ArgumentParser(description='Upkar Agency local pilot')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--preview', action='store_true', help='Isolated fictional demo; cannot connect or post to Tally')
    args = parser.parse_args()
    global PREVIEW, LIVE_WRITES, DEVICE_TOKEN
    PREVIEW = args.preview
    if PREVIEW:
        os.environ['OFFICE_BACKEND'] = 'local'
        store.DATA = store.ROOT / 'local-data' / 'preview'
        LIVE_WRITES = False
        DEVICE_TOKEN = ''
    if cloud.enabled():
        raise SystemExit('Use the production ASGI deployment for Supabase mode. See docs/DEPLOY.md.')
    store.init()
    if PREVIEW:
        with store.transaction() as db:
            if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                db.execute('INSERT INTO users VALUES(?,?,?,?)', (secrets.token_hex(16), 'preview@upkar.local', password_hash(secrets.token_urlsafe(32)), 'owner'))
            seed(db, 'preview@upkar.local')
    if args.setup:
        import getpass
        email = input('Owner email: ').strip()
        password = getpass.getpass('Choose a password (12+ characters): ')
        if password != getpass.getpass('Repeat password: '):
            raise SystemExit('Passwords do not match')
        init_user(email, password)
        print('Owner account created. Run python -m app.server to start.')
        return
    with store.transaction() as db:
        if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            raise SystemExit('First run: python -m app.server --setup')
    print(f'Upkar Agency: http://127.0.0.1:{args.port} (local pilot; Ctrl+C to stop)', flush=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
