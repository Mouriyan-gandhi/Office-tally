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
    ET.SubElement(variables, 'SVFROMDATE').text = start.strftime('%Y%m%d')
    ET.SubElement(variables, 'SVTODATE').text = end.strftime('%Y%m%d')
    collection = root.find('.//COLLECTION')
    for child in list(collection): collection.remove(child)
    ET.SubElement(collection, 'TYPE').text = 'Voucher'
    for field in ('GUID','MasterID','AlterID','Date','VoucherTypeName','VoucherNumber','Narration','IsCancelled','IsOptional','AllLedgerEntries.*'):
        ET.SubElement(collection, 'NATIVEMETHOD').text = field
    ET.SubElement(collection, 'FILTER').text = 'OfficeHistoryPeriod'
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
        if response.status != 200 or len(raw)>MAX_RESPONSE: raise ValueError('History export failed or exceeded size limit')
        return vouchers(parse_response(raw),start,end)
    finally: connection.close()
