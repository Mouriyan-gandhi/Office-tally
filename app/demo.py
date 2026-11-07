"""Explicitly fictional data; never mixed with the Tally snapshot."""
import json
import time
import uuid
from datetime import date, timedelta
from app.domain import business_today
from app.store import audit

def seed(db, actor):
    if db.execute("SELECT 1 FROM snapshots WHERE mode='demo'").fetchone():
        return
    today = business_today()
    ledgers = [
        {'name': 'Asha Retail · Demo', 'group': 'Sundry Debtors', 'balance': '28400.00', 'billwise': False},
        {'name': 'City Stores · Demo', 'group': 'Sundry Debtors', 'balance': '12600.00', 'billwise': False},
        {'name': 'Premier Supply · Demo', 'group': 'Sundry Creditors', 'balance': '-18750.00', 'billwise': False},
        {'name': 'Cash', 'group': 'Cash-in-Hand', 'balance': '8500.00', 'billwise': False},
        {'name': 'Current Account · Demo', 'group': 'Bank Accounts', 'balance': '72000.00', 'billwise': False},
        {'name': 'Sales', 'group': 'Sales Accounts', 'balance': '0'},
        {'name': 'Purchase', 'group': 'Purchase Accounts', 'balance': '0'},
        *[{'name': t, 'group': 'Duties & Taxes', 'balance': '0'} for t in ['CGST', 'SGST', 'IGST']],
    ]
    stock = [
        {'name': 'Classic Backpack · Demo', 'unit': 'pcs', 'quantity': '48', 'rate': '450', 'value': '21600', 'batchwise': False},
        {'name': 'Travel Duffel · Demo', 'unit': 'pcs', 'quantity': '22', 'rate': '720', 'value': '15840', 'batchwise': False},
        {'name': 'Everyday Tote · Demo', 'unit': 'pcs', 'quantity': '6', 'rate': '250', 'value': '1500', 'batchwise': False},
        {'name': 'Cabin Trolley · Demo', 'unit': 'pcs', 'quantity': '14', 'rate': '1850', 'value': '25900', 'batchwise': False},
    ]
    snap = {'company': 'Upkar Agency', 'ledgers': ledgers, 'stock': stock, 'source': 'Fictional demo data'}
    now = time.time()
    db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?)', ('demo', json.dumps(snap), now))
    if not db.execute("SELECT 1 FROM drafts WHERE mode='demo' LIMIT 1").fetchone():
        for index, (kind, party, amount) in enumerate([('Sales', ledgers[0]['name'], '5310.00'), ('Receipt', ledgers[1]['name'], '4200.00'), ('Purchase', ledgers[2]['name'], '10620.00')]):
            payload = {'kind': kind, 'party': party, 'date': (today-timedelta(days=index)).isoformat(), 'total': amount, 'reference': f'DEMO-{100+index}', 'narration': 'Fictional sample entry', 'items': [], 'taxes': [], 'cash_bank': 'Cash', 'allocations': []}
            db.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?)', (uuid.uuid4().hex, 'demo', json.dumps(payload), 'demo_saved', 1, now-index*86400, now, actor))
    audit(db, actor, 'demo_enabled', 'demo')
