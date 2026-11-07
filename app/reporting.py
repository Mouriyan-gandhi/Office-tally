"""Allowlisted report requests, with explicit periods and no caller-defined TDL."""
from datetime import date
import xml.etree.ElementTree as ET
from app.domain import ValidationError

REPORTS = {
    'daybook': 'Day Book', 'sales': 'Sales Register', 'purchases': 'Purchase Register',
    'ledger': 'Ledger Vouchers', 'receivables': 'Bills Receivable', 'payables': 'Bills Payable',
    'trial': 'Trial Balance', 'profit': 'Profit and Loss', 'balance': 'Balance Sheet', 'stock': 'Stock Summary',
}


def parameters(data):
    if data.get('report') not in REPORTS:
        raise ValidationError('Unsupported report')
    try:
        start, end = date.fromisoformat(data.get('from', '')), date.fromisoformat(data.get('to', ''))
    except (ValueError, TypeError):
        raise ValidationError('Choose valid report dates') from None
    if start > end or (end-start).days > 366*5:
        raise ValidationError('Choose a period of at most five years with the start before the end')
    ledger = data.get('ledger', '')
    if not isinstance(ledger, str) or len(ledger) > 200:
        raise ValidationError('Invalid ledger')
    if data['report'] == 'ledger' and not ledger.strip():
        raise ValidationError('Choose a ledger')
    return {'report': data['report'], 'from': start.isoformat(), 'to': end.isoformat(), 'ledger': ledger.strip()}


def request_xml(params, company):
    params = parameters(params)
    root = ET.Element('ENVELOPE')
    ET.SubElement(ET.SubElement(root, 'HEADER'), 'TALLYREQUEST').text = 'Export Data'
    desc = ET.SubElement(ET.SubElement(ET.SubElement(root, 'BODY'), 'EXPORTDATA'), 'REQUESTDESC')
    ET.SubElement(desc, 'REPORTNAME').text = REPORTS[params['report']]
    variables = ET.SubElement(desc, 'STATICVARIABLES')
    values = {'SVCURRENTCOMPANY': company, 'SVEXPORTFORMAT': '$$SysName:XML',
              'SVFROMDATE': params['from'].replace('-', ''), 'SVTODATE': params['to'].replace('-', ''), 'EXPLODEFLAG': 'Yes'}
    if params['report'] == 'ledger':
        values['LEDGERNAME'] = params['ledger']
    for tag, value in values.items():
        ET.SubElement(variables, tag).text = value
    return ET.tostring(root, encoding='utf-8')


def flatten(root, maximum=20000):
    rows = []
    def walk(node, path):
        path = path + '/' + node.tag
        if len(rows) >= maximum:
            return
        if not len(node) and node.text and node.text.strip():
            rows.append({'field': path, 'value': node.text.strip()[:2000]})
        for child in node:
            walk(child, path)
    walk(root, '')
    return {'rows': rows, 'truncated': len(rows) >= maximum,
            'note': 'Original report fields exported by Tally. No totals have been inferred or recalculated.'}
