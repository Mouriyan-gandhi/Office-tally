"""Deterministic accounting intents. No LLM, generated SQL or guessed figures."""
from datetime import date, timedelta
from decimal import Decimal
import re
from app.domain import business_today


def decimal(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except Exception:
        return None


def period(question):
    today = business_today()
    explicit = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', question)
    if 'between' in question and len(explicit) == 2:
        try:
            start, end = (date.fromisoformat(value) for value in explicit)
            return (start, end) if start <= end else None
        except ValueError:
            return None
    keys = [key for key in ['today','yesterday','this month','last month','this week','last week'] if key in question]
    if len(keys) != 1:
        return None
    key = keys[0]
    if key == 'today': return today, today
    if key == 'yesterday': return today-timedelta(days=1), today-timedelta(days=1)
    if key == 'this month': return today.replace(day=1), today
    if key == 'last month':
        end = today.replace(day=1)-timedelta(days=1)
        return end.replace(day=1), end
    monday = today-timedelta(days=today.weekday())
    return (monday,today) if key == 'this week' else (monday-timedelta(days=7),monday-timedelta(days=1))


def answer(question, snapshot, vouchers):
    q = question.strip().casefold()
    if not q or len(q) > 300:
        return {'message':'Ask a question of up to 300 characters.'}
    result = {'source':snapshot.get('source','Tally master snapshot'),'synced_at':snapshot.get('synced_at'),
              'scope':'Synced masters and app-recorded vouchers only. Balances are snapshots, not invoice ageing.'}
    if re.search(r'\b(predict|prediction|forecast|next year|next month|tomorrow)\b',q):
        return result | {'message':'I could not match an approved historical query. Forecasts and predictions are not supported.'}
    for pattern, name in [(r'profit|p\s*&\s*l','profit'),(r'balance sheet','balance'),(r'trial balance','trial'),(r'day\s*book','daybook')]:
        if re.search(pattern,q):
            report = snapshot.get('available_reports',{}).get(name)
            if report:
                return result | {'message':f'Tally report: {report["title"]} ({report["from"]} to {report["to"]})', 'rows':report['rows'], 'columns':['field','value'], 'synced_at':report['updated'], 'source':'Tally report export', 'scope':'Original Tally field values; no totals inferred.'}
            return result | {'message':'Request this report from the office connector in Reports → Tally reports. It will be available here after the export completes.','action':'tally-reports'}
    if not snapshot.get('synced_at'):
        return result | {'message':'No data has been synced in this workspace yet. Connect the office laptop or explore the fictional demo.'}
    ledgers, stock = snapshot.get('ledgers',[]), snapshot.get('stock',[])
    if re.search(r'\bsales\b|\bpurchases?\b',q):
        dates = period(q)
        if not dates:
            return result | {'message':'Specify today, yesterday, this/last week, this/last month, or between two YYYY-MM-DD dates. Only app-recorded entries are available.'}
        if re.search(r'\b(top|highest|lowest|above|over|below|under|by item|by customer)\b',q):
            return result | {'message':'That sales/purchase filter is not supported. Open the register, or ask for a total for a supported period.'}
        start,end = dates
        kind = 'Sales' if 'sales' in q else 'Purchase'
        rows = [v for v in vouchers if v['kind']==kind and start.isoformat()<=v['date']<=end.isoformat() and v['status'] in ('posted','demo_saved')]
        matches = [l for l in ledgers if l['name'].casefold().replace(' · demo','') in q]
        if len(matches)>1:
            return result | {'message':'More than one party matches. Use one full ledger name.'}
        if matches:
            rows = [v for v in rows if v['party']==matches[0]['name']]
        total = sum((Decimal(v['total']) for v in rows),Decimal(0))
        return result | {'message':f'{kind} recorded through this app: ₹{total:,.2f} ({start} to {end})','rows':rows,'columns':['date','party','total']}
    if re.search(r'\b(yesterday|last month|last week|tomorrow|between|since|before|after)\b|\d{4}-\d{2}-\d{2}',q):
        return result | {'message':'Only the latest synced master balances and stock are available here. Request a dated Tally report for historical figures.','action':'tally-reports'}
    candidates = [row for row in ledgers+stock if row['name'].casefold().replace(' · demo','') in q]
    if len(candidates)>1:
        return result | {'message':'More than one name matches. Ask using one full ledger or item name.'}
    if len(candidates)==1 and not any(w in q for w in ['customers owe','receivable','payable','low stock']):
        row = candidates[0]
        return result | {'message':row['name']+' — latest synced record','rows':[row], 'columns':['name','quantity','unit'] if 'unit' in row else ['name','group','balance']}
    if re.search(r'\b(low stock|stock low)\b',q):
        rows = [s for s in stock if decimal(s.get('quantity','')) is not None and decimal(s['quantity'])<=10]
        return result | {'message':'Items with 10 units or fewer','rows':rows,'columns':['name','quantity','unit']}
    if any(w in q for w in ['receivable','customers owe','collect from','payable','owe suppliers','outstanding']):
        creditors = any(w in q for w in ['payable','owe suppliers','supplier'])
        group = 'Sundry Creditors' if creditors else 'Sundry Debtors'
        rows = [r for r in ledgers if r.get('group')==group]
        if any(decimal(r.get('balance','')) is None for r in rows):
            return result | {'message':'Some balances are unavailable. Review the ledger rows.','rows':rows,'columns':['name','balance']}
        def due(row): return max(decimal(row['balance'])*(-1 if creditors else 1),Decimal(0))
        threshold = re.search(r'\b(above|over|more than|below|under|less than)\s*(?:rs\.?\s*|₹\s*)?([\d,]+(?:\.\d+)?)',q)
        if threshold:
            value = Decimal(threshold.group(2).replace(',',''))
            above = threshold.group(1) in ('above','over','more than')
            rows = [r for r in rows if due(r)>value] if above else [r for r in rows if due(r)<value]
        elif re.search(r'\b(above|over|below|under)\b',q):
            return result | {'message':'Use a numeric amount, for example “Customer outstanding above 50000”.'}
        if 'highest' in q:
            rows = sorted(rows,key=due,reverse=True)[:1]
        total = sum((due(r) for r in rows),Decimal(0))
        return result | {'message':('Supplier balances to pay' if creditors else 'Customer balances to collect')+f': ₹{total:,.2f}','rows':rows,'columns':['name','balance']}
    if 'cash' in q or 'bank' in q:
        group = 'Bank Accounts' if 'bank' in q else 'Cash-in-Hand'
        return result | {'message':group+' — synced balances','rows':[r for r in ledgers if r.get('group')==group],'columns':['name','balance']}
    return result | {'message':'I could not match an approved query. Try “Customers owe”, “Supplier payables”, “Low stock”, “Cash balance”, or “Sales today”. You can also include an exact ledger or item name.'}
