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
        current=begin[:7]==today.isoformat()[:7]
        freshness=60 if current else 3600
        if row and row['error'] and row['attempted']>time.time()-60:continue
        if row and row['updated'] and not row['error'] and row['end_date']==end and row['updated']>time.time()-freshness: continue
        candidates.append((0 if current else 1,row['attempted'] if row else 0, begin,end))
    if not candidates: return None
    _,_, begin,end = min(candidates)
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
        for field in ('kind','number','narration','party','reference'):
            if not isinstance(v.get(field,''),str) or len(v.get(field,''))>20000: raise ValidationError('Invalid voucher field')
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


def register(db, kind, snapshot, start='', end='', offset=0, limit=200):
    """Source is Tally history, never a union with app drafts (avoids duplicates)."""
    from app.domain import business_today
    if kind not in ('Sales','Purchase'): raise ValidationError('Unsupported register')
    cached=list(db.execute('SELECT * FROM history_periods ORDER BY start'))
    books=snapshot.get('books_from','')
    if len(books)==8: books=books[:4]+'-'+books[4:6]+'-'+books[6:8]
    try:
        first=date.fromisoformat(start or books or (cached[0]['start'] if cached else business_today().isoformat()))
        last=date.fromisoformat(end or business_today().isoformat())
        offset=int(offset);limit=int(limit)
        if first>last or first.year<1980 or offset<0 or not 1<=limit<=1000: raise ValueError()
    except (TypeError,ValueError):raise ValidationError('Choose valid register dates and page') from None
    coverage=[]
    for begin,finish in periods(first,last):
        p=next((p for p in cached if p['start']<=finish and p['end_date']>=begin),None)
        coverage.append({'from':begin,'to':finish,'synced_at':p['updated'] if p else None,
                         'status':'pending' if not p or not p['updated'] else 'refresh_failed' if p['error'] else 'cached' if p['start']<=begin and p['end_date']>=finish else 'partial'})
    latest={}
    for p in cached:
        if not p['updated']:continue
        for v in json.loads(p['payload']):
            previous=latest.get(v['id'])
            if previous is None or previous[0]<p['updated']:latest[v['id']]=(p['updated'],v)
    groups={p['name']:p.get('group','') for p in snapshot.get('ledgers',[])}
    types={p['name']:p.get('parent','') for p in snapshot.get('voucher_types',[])}
    rows=[];unmapped=0
    for updated,v in latest.values():
        base=v['kind'];seen=set()
        while base not in ('Sales','Purchase') and base in types and base not in seen:
            seen.add(base);base=types[base]
        if base!=kind or v['cancelled'] or v['optional'] or not first.isoformat()<=v['date']<=last.isoformat():continue
        party=v.get('party','')
        if not party:
            choices={line['ledger'] for line in v['lines'] if groups.get(line['ledger']) in ('Sundry Debtors','Sundry Creditors','Cash-in-Hand','Bank Accounts')}
            if len(choices)==1:party=choices.pop()
        amounts=[Decimal(line['amount']) for line in v['lines'] if line['ledger']==party]
        total=str(abs(sum(amounts,Decimal(0)))) if amounts else ''
        if not amounts:unmapped+=1
        rows.append({'id':v['id'],'date':v['date'],'kind':v['kind'],'number':v['number'],'party':party,
                     'reference':v.get('reference',''),'total':total,'synced_at':updated})
    rows.sort(key=lambda v:(v['date'],v['id']),reverse=True)
    ready=[p for p in coverage if p['synced_at']]
    import hashlib
    revision=hashlib.sha256(json.dumps([(p['start'],p['end_date'],p['updated'],p['error']) for p in cached]).encode()).hexdigest()
    return {'revision':revision,'rows':rows[offset:offset+limit],'count':len(rows),'offset':offset,'limit':limit,
            'from':first.isoformat(),'to':last.isoformat(),'coverage':coverage,
            'complete':all(p['status']=='cached' for p in coverage),
            'oldest_sync':min((p['synced_at'] for p in ready),default=None),
            'unmapped_totals':unmapped,'cached_total':str(sum((Decimal(v['total']) for v in rows if v['total']!=''),Decimal(0))),
            'note':'Active, nonoptional Tally vouchers from cached periods, including app-posted vouchers after sync. Drafts, waiting entries and exceptions are excluded. Totals cover synced records; incomplete coverage is not a full register.'}
