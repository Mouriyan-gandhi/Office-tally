"""Read-only, date-bounded voucher collection. Never generates import XML."""
from datetime import date
from decimal import Decimal, InvalidOperation
import xml.etree.ElementTree as ET
from connector.read_company import export_request, parse_response, MAX_RESPONSE
import http.client


def request_xml(company, start, end):
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if start > end or (end-start).days > 31:
        raise ValueError('History exports require a period of at most 32 days')
    root = ET.fromstring(export_request('companies', company))
    variables = root.find('.//STATICVARIABLES')
    ET.SubElement(variables, 'SVFROMDATE', TYPE='Date').text = start.strftime('%Y%m%d')
    ET.SubElement(variables, 'SVTODATE', TYPE='Date').text = end.strftime('%Y%m%d')
    collection = root.find('.//COLLECTION')
    for child in list(collection): collection.remove(child)
    ET.SubElement(collection, 'TYPE').text = 'Voucher'
    for field in ('GUID','MasterID','AlterID','Date','VoucherTypeName','VoucherNumber','Narration','IsCancelled','IsOptional','AllLedgerEntries.*'):
        ET.SubElement(collection, 'NATIVEMETHOD').text = field
    ET.SubElement(collection, 'FILTERS').text = 'OfficeHistoryPeriod'
    system = ET.SubElement(root.find('.//TDLMESSAGE'), 'SYSTEM', TYPE='Formulae', NAME='OfficeHistoryPeriod')
    system.text = '$Date >= ##SVFromDate AND $Date <= ##SVToDate'
    return ET.tostring(root, encoding='utf-8')


def vouchers(root, start, end):
    result, seen = [], set()
    collection = root.find('.//COLLECTION')
    if collection is None:
        raise ValueError('Expected a voucher collection; history was not replaced')
    for node in collection.findall('VOUCHER'):
        day = node.findtext('DATE','')
        day = date(int(day[:4]),int(day[4:6]),int(day[6:8])).isoformat()
        if not start <= day <= end:
            raise ValueError('Tally returned vouchers outside the requested period')
        identifier = node.findtext('GUID') or node.findtext('MASTERID')
        if not identifier or identifier in seen:
            raise ValueError('Missing or duplicate voucher identity')
        seen.add(identifier)
        lines = []
        for entry in list(node):
            if entry.tag not in ('ALLLEDGERENTRIES.LIST','LEDGERENTRIES.LIST'): continue
            name, raw = entry.findtext('LEDGERNAME',''), entry.findtext('AMOUNT','')
            try: amount = -Decimal(raw.replace(',',''))
            except InvalidOperation: raise ValueError('Invalid ledger amount') from None
            if not name or not amount.is_finite(): raise ValueError('Invalid ledger entry')
            lines.append({'ledger':name,'amount':str(amount)})
        cancelled = node.findtext('ISCANCELLED','').casefold() == 'yes'
        optional = node.findtext('ISOPTIONAL','').casefold() == 'yes'
        if not lines and not (cancelled or optional):
            raise ValueError('Voucher ledger allocations were not returned')
        result.append({'id':identifier,'date':day,'kind':node.findtext('VOUCHERTYPENAME',''),
            'number':node.findtext('VOUCHERNUMBER',''),'narration':node.findtext('NARRATION',''),
            'cancelled':cancelled,'optional':optional,'lines':lines})
        if len(result)>5000: raise ValueError('History period too large; no partial history saved')
    return result


def read_period(port, company, start, end):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=45)
    try:
        connection.request('POST','/',body=request_xml(company,start,end),headers={'Content-Type':'text/xml; charset=utf-8'})
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE+1)
        if response.status != 200: raise ValueError('Tally history HTTP request failed')
        if len(raw)>MAX_RESPONSE: raise ValueError('Tally history response exceeded 16 MiB')
        return vouchers(parse_response(raw),start,end)
    finally: connection.close()


def failure_reason(error):
    """Safe local diagnostics: never print provider bodies or voucher contents."""
    import socket
    if isinstance(error, (TimeoutError, socket.timeout)):
        return 'Tally did not finish the history export within 45 seconds'
    if isinstance(error, ET.ParseError):
        return 'Tally history response was not valid XML'
    reasons = {
        'Tally history HTTP request failed': 'Tally returned an unsuccessful HTTP status for history',
        'Tally history response exceeded 16 MiB': 'History response exceeded 16 MiB; verify filtering and period size',
        'Expected a voucher collection; history was not replaced': 'Tally returned no voucher collection (request compatibility needs checking)',
        'Tally returned vouchers outside the requested period': 'Tally did not apply the requested date filter',
        'Missing or duplicate voucher identity': 'Tally returned missing or duplicate voucher IDs',
        'Voucher ledger allocations were not returned': 'Tally returned vouchers without their ledger allocations',
        'History period too large; no partial history saved': 'This month exceeds the 5000-voucher limit',
        'History export failed or exceeded size limit': 'Tally HTTP export failed or exceeded the 16 MiB limit',
        'Tally rejected the read request; check company and configuration': 'Tally rejected the history export request',
        'Invalid ledger amount': 'Tally returned an unsupported ledger amount format',
        'Invalid ledger entry': 'Tally returned an incomplete ledger allocation',
        'Unsafe XML response': 'Tally response contained a blocked XML declaration',
    }
    if type(error) is ValueError and str(error) in reasons:
        return reasons[str(error)]
    if isinstance(error, OSError):
        return 'Could not read history from the local Tally server'
    return 'History reader failed (' + type(error).__name__ + '); run the read-only history check'


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Read-only voucher history diagnostic; no cloud access or posting')
    parser.add_argument('--from', dest='start', required=True)
    parser.add_argument('--to', dest='end', required=True)
    parser.add_argument('--port',type=int,default=9000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('Invalid Tally port')
    try:
        rows = read_period(args.port, 'Upkar Agency', args.start, args.end)
        print(json.dumps({'ok':True,'vouchers':len(rows),'ledger_allocations':sum(len(v['lines']) for v in rows)}))
    except Exception as error:
        print(json.dumps({'ok':False,'reason':failure_reason(error)}))
        raise SystemExit(1) from None


if __name__ == '__main__': main()
