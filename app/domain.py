"""Accounting validation shared by the web app and the Windows connector."""
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

KINDS = ('Sales', 'Purchase', 'Receipt', 'Payment')
PAISA = Decimal('0.01')

def business_today():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()

class ValidationError(ValueError):
    pass

def number(value, label, positive=False):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) > Decimal('1000000000'):
            raise ValidationError(f'{label}: enter a valid number')
        if result < 0 or (positive and result <= 0):
            raise ValidationError(f'{label}: enter a positive number')
        return result
    except (InvalidOperation, TypeError) as exc:
        raise ValidationError(f'{label}: enter a valid number') from exc

def money(value):
    return number(value, 'Amount').quantize(PAISA, rounding=ROUND_HALF_UP)

def text(value, label, maximum=200, required=True):
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise ValidationError(f'{label}: invalid text')
    value = value.strip()
    if required and not value:
        raise ValidationError(f'{label} is required')
    if any(ord(char) < 32 and char not in '\n\t' for char in value):
        raise ValidationError(f'{label}: unsupported characters')
    return value

def normalize_draft(payload):
    if not isinstance(payload, dict):
        raise ValidationError('Invalid voucher')
    kind = payload.get('kind')
    if kind not in KINDS:
        raise ValidationError('Choose a supported voucher type')
    try:
        day = date.fromisoformat(payload.get('date', ''))
    except (ValueError, TypeError):
        raise ValidationError('Choose a valid date') from None
    if day > business_today():
        raise ValidationError('Future-dated entries are not enabled')
    result = dict(kind=kind, date=day.isoformat(),
                  party=text(payload.get('party'), 'Party ledger'),
                  narration=text(payload.get('narration', ''), 'Notes', 2000, False),
                  reference=text(payload.get('reference', ''), 'Reference', 100, False))
    if kind in ('Receipt', 'Payment'):
        ledger = text(payload.get('cash_bank'), 'Cash or bank ledger')
        if ledger.strip().casefold() == result['party'].casefold():
            raise ValidationError('Party and cash/bank ledgers must differ')
        amount = number(payload.get('amount'), 'Amount', True)
        if amount != amount.quantize(PAISA):
            raise ValidationError('Amount can have at most two decimal places')
        result.update(cash_bank=ledger, amount=str(amount.quantize(PAISA)), total=str(amount.quantize(PAISA)), items=[], taxes=[])
        allocations = payload.get('allocations', [])
        if not isinstance(allocations, list) or len(allocations) > 100:
            raise ValidationError('Invalid bill allocations')
        result['allocations'] = []
        for item in allocations:
            if not isinstance(item, dict):
                raise ValidationError('Invalid bill allocation')
            allocated = number(item.get('amount'), 'Bill amount', True)
            if allocated != allocated.quantize(PAISA):
                raise ValidationError('Bill amount can have at most two decimal places')
            result['allocations'].append(dict(reference=text(item.get('reference'), 'Bill reference', 100), amount=str(allocated)))
        if allocations and sum(Decimal(a['amount']) for a in result['allocations']) != amount:
            raise ValidationError('Bill allocations must equal the voucher amount')
    else:
        result['account_ledger'] = text(payload.get('account_ledger'), 'Sales or purchase ledger')
        if kind == 'Purchase' and not result['reference']:
            raise ValidationError('Supplier invoice number is required')
        rows = payload.get('items')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise ValidationError('Add between 1 and 100 items')
        result['items'] = []
        subtotal = Decimal('0')
        for row in rows:
            if not isinstance(row, dict):
                raise ValidationError('Invalid item')
            qty = number(row.get('qty'), 'Quantity', True)
            rate = number(row.get('rate'), 'Rate', True)
            discount = number(row.get('discount', 0), 'Discount')
            if discount > 100:
                raise ValidationError('Discount cannot exceed 100%')
            amount = (qty * rate * (1 - discount / 100)).quantize(PAISA, rounding=ROUND_HALF_UP)
            if amount <= 0:
                raise ValidationError('Item amount must be positive')
            subtotal += amount
            result['items'].append(dict(name=text(row.get('name'), 'Stock item'), unit=text(row.get('unit'), 'Unit', 40),
                                        qty=str(qty), rate=str(rate), discount=str(discount), amount=str(amount)))
        taxes = payload.get('taxes', [])
        if not isinstance(taxes, list) or len(taxes) > 3:
            raise ValidationError('Invalid tax lines')
        result['taxes'] = []
        labels = set()
        for tax in taxes:
            if not isinstance(tax, dict) or tax.get('type') not in ('CGST', 'SGST', 'IGST'):
                raise ValidationError('Choose CGST, SGST or IGST')
            label = tax['type']
            if label in labels:
                raise ValidationError('Duplicate tax type')
            labels.add(label)
            percent = number(tax.get('percent'), 'Tax rate', True)
            if percent > 100:
                raise ValidationError('Invalid tax rate')
            amount = (subtotal * percent / 100).quantize(PAISA, rounding=ROUND_HALF_UP)
            result['taxes'].append(dict(type=label, ledger=text(tax.get('ledger'), 'Tax ledger'), percent=str(percent), amount=str(amount)))
        if 'IGST' in labels and len(labels) > 1:
            raise ValidationError('IGST cannot be combined with CGST/SGST')
        if ('CGST' in labels) != ('SGST' in labels):
            raise ValidationError('Add both CGST and SGST')
        if 'CGST' in labels and len({Decimal(t['percent']) for t in result['taxes']}) != 1:
            raise ValidationError('CGST and SGST rates must match')
        result['subtotal'] = str(subtotal)
        result['total'] = str(subtotal + sum(Decimal(t['amount']) for t in result['taxes']))
    number(result['total'], 'Voucher total', True)
    printed = payload.get('printed_total', '')
    if printed not in ('', None):
        expected = number(printed, 'Printed bill total', True).quantize(PAISA)
        if expected != Decimal(result['total']):
            raise ValidationError('Entry total does not match the printed bill total. Check items, discounts and taxes.')
        result['printed_total'] = str(expected)
    document = payload.get('document_id', '')
    if document and not re.fullmatch(r'[0-9a-f]{32}', str(document)):
        raise ValidationError('Invalid bill attachment')
    result['document_id'] = document
    return result

def require_masters(draft, snapshot):
    ledgers = {row['name']: row for row in snapshot.get('ledgers', [])}
    required = [draft['party']]
    required += [draft['cash_bank']] if draft['kind'] in ('Receipt', 'Payment') else [draft['account_ledger']] + [t['ledger'] for t in draft['taxes']]
    for name in required:
        if name not in ledgers:
            raise ValidationError(f'Ledger not found in the latest Tally sync: {name}')
    party_group = ledgers[draft['party']].get('group')
    party_groups = {'Sales':{'Sundry Debtors','Cash-in-Hand','Bank Accounts'}, 'Purchase':{'Sundry Creditors','Cash-in-Hand','Bank Accounts'}, 'Receipt':{'Sundry Debtors'}, 'Payment':{'Sundry Creditors'}}
    if party_group not in party_groups[draft['kind']]:
        raise ValidationError('The party ledger group does not match this workflow')
    if draft['kind'] in ('Receipt','Payment'):
        if ledgers[draft['cash_bank']].get('group') not in ('Cash-in-Hand','Bank Accounts'):
            raise ValidationError('Choose a cash or bank ledger for this entry')
    else:
        expected_group = 'Sales Accounts' if draft['kind'] == 'Sales' else 'Purchase Accounts'
        if ledgers[draft['account_ledger']].get('group') != expected_group:
            raise ValidationError('Choose the correct sales or purchase ledger')
        if len({draft['party'],draft['account_ledger'],*[t['ledger'] for t in draft['taxes']]}) != 2+len(draft['taxes']):
            raise ValidationError('Party, account and tax ledgers must be distinct')
        for tax in draft['taxes']:
            if ledgers[tax['ledger']].get('group') != 'Duties & Taxes':
                raise ValidationError('Choose an existing Duties & Taxes ledger')
    if ledgers[draft['party']].get('billwise') and draft['kind'] in ('Sales','Purchase') and not draft['reference']:
        raise ValidationError('This party uses bill-wise accounting; add an invoice reference')
    # Bill-wise and advanced inventory must not silently lose accounting detail.
    if ledgers[draft['party']].get('billwise') and draft['kind'] in ('Receipt', 'Payment') and not draft['allocations']:
        raise ValidationError('This party uses bill-wise accounting; allocate the amount to bills first')
    stock = {row['name']: row for row in snapshot.get('stock', [])}
    for item in draft['items']:
        master = stock.get(item['name'])
        if not master or master.get('unit') != item['unit']:
            raise ValidationError(f'Check the stock item and unit: {item["name"]}')
        if master.get('batchwise') or master.get('godown_required'):
            raise ValidationError('Batch/godown inventory needs additional mapping before posting')
