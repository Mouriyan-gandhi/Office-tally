"""Native Tally invoice requests reuse the private read-request queue and document store."""
import base64
import hmac
import json
from pathlib import Path
import secrets
import time
from app import cloud,store
from app.domain import ValidationError


def available(db):
    return not cloud.enabled() or bool(db.execute('SELECT version FROM schema_migrations WHERE version=3').fetchone())

def target(db,data):
    if data.get('draft_id'):
        row=db.execute("SELECT d.*,j.id AS job_id FROM drafts d JOIN jobs j ON j.draft_id=d.id WHERE d.id=? AND d.mode='live' AND d.status='posted'",(data['draft_id'],)).fetchone()
        if not row:raise ValidationError('A confirmed posted voucher is required for an invoice')
        draft=json.loads(row['payload'])
        result={'key':row['job_id'],'kind':draft['kind'],'date':draft['date'],'party':draft['party'],
                'number':draft.get('voucher_number',''),'reference':draft.get('reference',''),'total':draft['total'],'source':'posted_app'}
    else:
        result=None
        for period in db.execute('SELECT payload,updated FROM history_periods ORDER BY updated DESC'):
            if not period['updated']:continue
            voucher=next((v for v in json.loads(period['payload']) if v['id']==data.get('voucher_id')),None)
            if voucher:
                if voucher['cancelled'] or voucher['optional']:raise ValidationError('Cancelled/optional vouchers do not have final invoices')
                result={'key':voucher['id'],'kind':voucher['kind'],'date':voucher['date'],'party':voucher.get('party','')};break
        if result is None:raise ValidationError('Voucher is not in synced Tally history')
    if result['kind'] not in ('Sales','Purchase'):raise ValidationError('Native invoice export currently supports Sales and Purchase types')
    return result


def request(db,data,actor):
    if not available(db):raise ValidationError('Run the native invoice database update (migration 3) before requesting PDFs')
    params=target(db,data)
    # Reuse a pending or ready request; explicit refresh creates a new PDF version.
    if not data.get('refresh'):
        for row in db.execute("SELECT * FROM report_requests WHERE report='invoice' ORDER BY created DESC LIMIT 1000"):
            if json.loads(row['params'])==params and row['status'] in ('queued','reading','ready'):
                return {'id':row['id'],'status':row['status']}
    count=db.execute("SELECT COUNT(*) FROM report_requests WHERE report='invoice' AND status IN ('queued','reading')").fetchone()[0]
    if count>=30:raise ValidationError('Wait for pending invoice exports to finish')
    identifier=secrets.token_hex(16);now=time.time()
    db.execute('INSERT INTO report_requests VALUES(?,?,?,?,?,?,?,?)',(identifier,'invoice',json.dumps(params),'queued',None,None,now,now))
    store.audit(db,actor,'native_invoice_requested',identifier)
    return {'id':identifier,'status':'queued'}


def status(db,identifier):
    row=db.execute("SELECT * FROM report_requests WHERE id=? AND report='invoice'",(identifier,)).fetchone()
    if not row:raise ValidationError('Invoice request not found')
    result=json.loads(row['result']) if row['result'] else {}
    return {'id':row['id'],'status':row['status'],'updated':row['updated'],**result}


def poll(db):
    if not available(db):return None
    db.execute("UPDATE report_requests SET status='queued',lease=NULL WHERE report='invoice' AND status='reading' AND updated<?",(time.time()-180,))
    row=db.execute("SELECT * FROM report_requests WHERE report='invoice' AND status='queued' ORDER BY created LIMIT 1").fetchone()
    if not row:return None
    lease=secrets.token_urlsafe(32)
    db.execute("UPDATE report_requests SET status='reading',lease=?,updated=? WHERE id=?",(lease,time.time(),row['id']))
    return {'id':row['id'],'lease':lease,'target':json.loads(row['params'])}


def receive(data):
    class AlreadyCompleted(Exception):pass
    def check(db):
        row=db.execute("SELECT * FROM report_requests WHERE report='invoice' AND id=?",(data.get('id'),)).fetchone()
        if not row or not row['lease'] or not hmac.compare_digest(row['lease'],str(data.get('lease',''))):raise PermissionError('Invalid invoice lease')
        return row
    with store.transaction() as db:
        row=check(db)
        if row['status'] in ('ready','failed'):return {'ok':True}
        if data.get('error'):
            result={'rows':[],'error':'Tally could not export this native PDF. Run the read-only invoice export check on Windows; no substitute invoice was generated.'}
            db.execute("UPDATE report_requests SET status='failed',result=?,updated=? WHERE id=?",(json.dumps(result),time.time(),row['id']))
            return {'ok':True}
    try:raw=base64.b64decode(data.get('pdf',''),validate=True)
    except (ValueError,TypeError):raise ValidationError('Invalid invoice PDF') from None
    if not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-2048:] or len(raw)>8*1024*1024:raise ValidationError('Native invoice must be a complete PDF under 8 MB')
    identifier=secrets.token_hex(16);key=f'upkar-agency/native/{identifier}.pdf'
    if cloud.enabled():cloud.put_file(key,raw,'application/pdf')
    else:
        folder=store.DATA/'native-invoices';folder.mkdir(parents=True,exist_ok=True)
        path=folder/(identifier+'.pdf');path.write_bytes(raw);key=str(path)
    try:
        with store.transaction() as db:
            row=check(db)
            if row['status'] in ('ready','failed'):raise AlreadyCompleted()
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',(identifier,'live','Tally-invoice.pdf','application/pdf',key,time.time()))
            result={'rows':[],'document_id':identifier,'filename':'Tally-invoice.pdf','note':'Original PDF returned by Tally, using its native print layout.'}
            db.execute("UPDATE report_requests SET status='ready',result=?,updated=? WHERE id=?",(json.dumps(result),time.time(),data['id']))
            store.audit(db,'connector','native_invoice_received',identifier)
    except AlreadyCompleted:
        if cloud.enabled():cloud.delete_file(key)
        else:Path(key).unlink(missing_ok=True)
        return {'ok':True}
    except Exception:
        if cloud.enabled():cloud.delete_file(key)
        else:Path(key).unlink(missing_ok=True)
        raise
    return {'ok':True}
