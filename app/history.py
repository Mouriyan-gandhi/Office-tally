"""Private history cache: replace complete periods, never append duplicate vouchers."""
import calendar
import json
import secrets
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from app.domain import ValidationError


def periods(start, end):
    cursor = start.replace(day=1)
    while cursor <= end:
        last = cursor.replace(day=calendar.monthrange(cursor.year,cursor.month)[1])
        yield max(start,cursor).isoformat(), min(end,last).isoformat()
        cursor = last + timedelta(days=1)


def poll(db, books_from):
    try: start = date.fromisoformat(books_from)
    except (TypeError,ValueError): raise ValidationError('Tally BooksFrom date required for history sync') from None
    today = date.today()
    if start > today or start.year < 1980: raise ValidationError('Unsupported company books period')
    # History is optional until migration 2 has been applied.
    candidates = []
    cached = {row['start']:row for row in db.execute('SELECT * FROM history_periods')}
    for begin,end in periods(start,today):
        row = cached.get(begin)
        if row and row['lease'] and row['attempted'] > time.time()-180: continue
        # Completed ranges are periodically re-read to reconcile alterations/deletions.
        if row and row['updated'] and row['end_date']==end and row['updated']>time.time()-3600: continue
        candidates.append((row['attempted'] if row else 0, begin,end))
    if not candidates: return None
    _, begin,end = min(candidates)
    lease = secrets.token_urlsafe(32)
    if not db.execute('SELECT start FROM history_periods WHERE start=?',(begin,)).fetchone():
        db.execute('INSERT INTO history_periods(start,end_date,payload,updated,attempted,lease,error) VALUES(?,?,?,?,?,?,?)',(begin,end,'[]',None,time.time(),lease,''))
    else:
        db.execute('UPDATE history_periods SET lease=?,attempted=? WHERE start=?',(lease,time.time(),begin))
    return {'from':begin,'to':end,'lease':lease}


def accept(db, data):
    import hmac
    row = db.execute('SELECT * FROM history_periods WHERE start=?',(data.get('from'),)).fetchone()
    if not row or not row['lease'] or not hmac.compare_digest(row['lease'],str(data.get('lease',''))):
        raise PermissionError('Invalid history lease')
    if data.get('error'):
        db.execute('UPDATE history_periods SET lease=NULL,error=? WHERE start=?',('History export failed; existing cache retained',row['start']))
        return
    entries = data.get('vouchers')
    end = data.get('to')
    try:
        last = date.fromisoformat(end)
        first = date.fromisoformat(row['start'])
        if first>last or (last-first).days>31: raise ValueError()
    except (ValueError,TypeError): raise ValidationError('Invalid history period') from None
    if not isinstance(entries,list) or len(entries)>5000: raise ValidationError('Invalid history payload')
    seen = set()
    for v in entries:
        if not isinstance(v,dict) or not isinstance(v.get('id'),str) or not v['id'] or v['id'] in seen: raise ValidationError('Invalid voucher identity')
        seen.add(v['id'])
        if not isinstance(v.get('date'),str) or not row['start']<=v['date']<=end: raise ValidationError('Voucher outside history period')
        for field in ('kind','number','narration'):
            if not isinstance(v.get(field),str) or len(v[field])>20000: raise ValidationError('Invalid voucher field')
        if type(v.get('cancelled')) is not bool or type(v.get('optional')) is not bool: raise ValidationError('Invalid voucher status')
        if not isinstance(v.get('lines'),list) or len(v['lines'])>2000: raise ValidationError('Invalid voucher lines')
        if not v['lines'] and not (v['cancelled'] or v['optional']): raise ValidationError('Missing voucher lines')
        for line in v['lines']:
            if not isinstance(line,dict) or not isinstance(line.get('ledger'),str) or not line['ledger']: raise ValidationError('Invalid history ledger')
            try: amount=Decimal(line['amount'])
            except (InvalidOperation,KeyError,TypeError): raise ValidationError('Invalid history amount') from None
            if not amount.is_finite() or abs(amount)>Decimal('1e18'): raise ValidationError('Invalid history amount')
    db.execute('UPDATE history_periods SET end_date=?,payload=?,updated=?,lease=NULL,error=? WHERE start=?',(end,json.dumps(entries),time.time(),'',row['start']))


def statement(db, ledger):
    rows, coverage, latest = [], [], {}
    for period in db.execute('SELECT * FROM history_periods ORDER BY start'):
        coverage.append({'from':period['start'],'to':period['end_date'],'synced_at':period['updated'],'error':period['error']})
        if not period['updated']: continue
        for v in json.loads(period['payload']):
            previous = latest.get(v['id'])
            if previous is None or previous[0] < period['updated']:
                latest[v['id']] = (period['updated'],v)
    # Moving a voucher to another month must not display it twice while a
    # rolling refresh is in progress. Prefer the most recently fetched record.
    for _,v in latest.values():
            if v['cancelled'] or v['optional']: continue
            amount = sum((Decimal(line['amount']) for line in v['lines'] if line['ledger']==ledger),Decimal(0))
            if not any(line['ledger']==ledger for line in v['lines']): continue
            rows.append({'date':v['date'],'kind':v['kind'],'number':v['number'],'debit':str(max(amount,Decimal(0))),
                         'credit':str(max(-amount,Decimal(0))),'narration':v['narration'],'id':v['id']})
    rows.sort(key=lambda v:(v['date'],v['id']))
    return {'rows':rows[-1000:],'truncated':len(rows)>1000,'coverage':coverage,
            'note':'Synced Tally vouchers only. Opening balances are not included; no running balance inferred. Cancelled and optional vouchers excluded.'}
