"""Narrow, validated voucher XML builders. No raw XML comes from the phone."""
import xml.etree.ElementTree as ET
from decimal import Decimal
from app.domain import normalize_draft


def build(draft, company, identifier):
    if company != 'Upkar Agency':
        raise ValueError('Unexpected company')
    draft = normalize_draft(draft)
    root = ET.Element('ENVELOPE')
    def put(parent, tag, value):
        ET.SubElement(parent, tag).text = str(value)
    put(ET.SubElement(root, 'HEADER'), 'TALLYREQUEST', 'Import Data')
    data = ET.SubElement(ET.SubElement(root, 'BODY'), 'IMPORTDATA')
    desc = ET.SubElement(data, 'REQUESTDESC')
    put(desc, 'REPORTNAME', 'Vouchers')
    put(ET.SubElement(desc, 'STATICVARIABLES'), 'SVCURRENTCOMPANY', company)
    message = ET.SubElement(ET.SubElement(data, 'REQUESTDATA'), 'TALLYMESSAGE')
    kind = draft['kind']
    view = 'Invoice Voucher View' if kind in ('Sales', 'Purchase') else 'Accounting Voucher View'
    voucher = ET.SubElement(message, 'VOUCHER', VCHTYPE=kind, ACTION='Create', OBJVIEW=view, REMOTEID=identifier)
    for tag, value in [('DATE', draft['date'].replace('-', '')), ('VOUCHERTYPENAME', kind),
                       ('PERSISTEDVIEW', view), ('PARTYLEDGERNAME', draft['party']),
                       ('NARRATION', draft['narration']), ('REFERENCE', draft['reference']),
                       ('ISINVOICE', 'Yes' if draft['items'] else 'No')]:
        put(voucher, tag, value)
    total = Decimal(draft['total'])
    # Native Tally amounts use a negative sign for debits.
    party_amount = -total if kind in ('Sales', 'Payment') else total
    def ledger(parent, name, amount):
        entry = ET.SubElement(parent, 'ALLLEDGERENTRIES.LIST')
        put(entry, 'LEDGERNAME', name)
        put(entry, 'ISDEEMEDPOSITIVE', 'Yes' if amount < 0 else 'No')
        put(entry, 'AMOUNT', format(amount, '.2f'))
        return entry
    party = ledger(voucher, draft['party'], party_amount)
    put(party, 'ISPARTYLEDGER', 'Yes')
    if draft.get('allocations'):
        for bill in draft['allocations']:
            entry = ET.SubElement(party, 'BILLALLOCATIONS.LIST')
            put(entry, 'NAME', bill['reference'])
            put(entry, 'BILLTYPE', 'Agst Ref')
            put(entry, 'AMOUNT', format(Decimal(bill['amount']) * (-1 if party_amount < 0 else 1), '.2f'))
    elif draft['reference'] and draft['items']:
        entry = ET.SubElement(party, 'BILLALLOCATIONS.LIST')
        put(entry, 'NAME', draft['reference'])
        put(entry, 'BILLTYPE', 'New Ref')
        put(entry, 'AMOUNT', format(party_amount, '.2f'))
    if not draft['items']:
        ledger(voucher, draft['cash_bank'], -party_amount)
    else:
        sign = Decimal('1') if kind == 'Sales' else Decimal('-1')
        for item in draft['items']:
            entry = ET.SubElement(voucher, 'ALLINVENTORYENTRIES.LIST')
            for tag, value in [('STOCKITEMNAME', item['name']), ('ISDEEMEDPOSITIVE', 'Yes' if sign < 0 else 'No'),
                               ('RATE', item['rate'] + '/' + item['unit']), ('DISCOUNT', item['discount']),
                               ('ACTUALQTY', item['qty'] + ' ' + item['unit']), ('BILLEDQTY', item['qty'] + ' ' + item['unit']),
                               ('AMOUNT', format(sign * Decimal(item['amount']), '.2f'))]:
                put(entry, tag, value)
            allocation = ET.SubElement(entry, 'ACCOUNTINGALLOCATIONS.LIST')
            put(allocation, 'LEDGERNAME', draft['account_ledger'])
            put(allocation, 'ISDEEMEDPOSITIVE', 'Yes' if sign < 0 else 'No')
            put(allocation, 'AMOUNT', format(sign * Decimal(item['amount']), '.2f'))
        for tax in draft['taxes']:
            ledger(voucher, tax['ledger'], sign * Decimal(tax['amount']))
    return ET.tostring(root, encoding='utf-8')
