"""Apply explicitly fictional demo entries so the practice workspace is interactive."""
from decimal import Decimal
import json
import time
from app.store import snapshot


def apply(db, draft):
    snap = snapshot(db, 'demo')
    ledgers = {row['name']: row for row in snap['ledgers']}
    stock = {row['name']: row for row in snap['stock']}
    amount = Decimal(draft['total'])
    # Public view uses debit-positive balances, unlike native Tally XML signs.
    direction = 1 if draft['kind'] in ('Sales', 'Payment') else -1
    party = ledgers.get(draft['party'])
    if party:
        party['balance'] = str(Decimal(party.get('balance') or '0') + amount * direction)
    if draft['kind'] in ('Receipt', 'Payment'):
        bank = ledgers.get(draft['cash_bank'])
        if bank:
            bank['balance'] = str(Decimal(bank.get('balance') or '0') - amount * direction)
    else:
        for item in draft['items']:
            master = stock.get(item['name'])
            if master:
                quantity = Decimal(master.get('quantity') or '0') + Decimal(item['qty']) * (-1 if draft['kind'] == 'Sales' else 1)
                master['quantity'] = str(quantity)
                master['value'] = str((quantity * Decimal(master.get('rate') or '0')).quantize(Decimal('.01')))
    snap.pop('synced_at', None)
    db.execute('UPDATE snapshots SET payload=?,updated=? WHERE mode=?', (json.dumps(snap), time.time(), 'demo'))
