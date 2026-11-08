"""Run on the Tally Windows PC: py -m connector.read_company --company NAME."""
import argparse
import http.client
import json
import re
import xml.etree.ElementTree as ET

MAX_RESPONSE = 16 * 1024 * 1024
COLLECTIONS = {
    'godowns': ('Godown', ('Name',)),
    'voucher_types': ('VoucherType', ('Name','NumberingMethod','Parent')),
    'groups': ('Group', ('Name', 'Parent')),
    'companies': ('Company', ('Name', 'BooksFrom')),
    'ledgers': ('Ledger', ('Name', 'Parent', 'ClosingBalance', 'IsBillWiseOn')),
    'stock': ('StockItem', ('Name', 'BaseUnits', 'ClosingBalance', 'ClosingRate', 'ClosingValue', 'IsBatchWiseOn')),
}


def export_request(kind, company):
    if kind not in COLLECTIONS:
        raise ValueError('Unsupported read operation')
    if not company.strip():
        raise ValueError('Exact company name is required')
    object_type, fields = COLLECTIONS[kind]
    root = ET.Element('ENVELOPE')
    header = ET.SubElement(root, 'HEADER')
    for tag, value in [('VERSION', '1'), ('TALLYREQUEST', 'Export'),
                       ('TYPE', 'Collection'), ('ID', 'OfficeRead')]:
        ET.SubElement(header, tag).text = value
    desc = ET.SubElement(ET.SubElement(root, 'BODY'), 'DESC')
    variables = ET.SubElement(desc, 'STATICVARIABLES')
    ET.SubElement(variables, 'SVCURRENTCOMPANY').text = company
    ET.SubElement(variables, 'SVEXPORTFORMAT').text = '$$SysName:XML'
    message = ET.SubElement(ET.SubElement(desc, 'TDL'), 'TDLMESSAGE')
    collection = ET.SubElement(message, 'COLLECTION', NAME='OfficeRead')
    ET.SubElement(collection, 'TYPE').text = object_type
    for field in fields:
        ET.SubElement(collection, 'NATIVEMETHOD').text = field
    return ET.tostring(root, encoding='utf-8')


def parse_response(data, *, allow_tally_errors=False):
    # Decode before security checks: UTF-16 declarations must not bypass them.
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        data = data.decode('utf-16')
    else:
        data = data.decode('utf-8-sig')
    data = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', data)
    if '<!DOCTYPE' in data.upper() or '<!ENTITY' in data.upper():
        raise ValueError('Unsafe XML response')
    def clean_reference(match):
        value = match.group(1)
        code = int(value[1:],16) if value.lower().startswith('x') else int(value)
        return '' if code < 32 and code not in (9,10,13) else match.group(0)
    data = re.sub(r'&#(x[0-9a-fA-F]+|[0-9]+);', clean_reference, data)
    root = ET.fromstring(data)
    errors = [node.text for node in root.iter('LINEERROR')]
    if not allow_tally_errors and (errors or root.findtext('.//STATUS') == '0'):
        raise ValueError('Tally rejected the read request; check company and configuration')
    return root


def read(kind, company, port=9000):
    # Fixed loopback destination; no public listener, proxy, arbitrary XML or write API.
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=15)
    try:
        connection.request('POST', '/', body=export_request(kind, company),
                           headers={'Content-Type': 'text/xml; charset=utf-8'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Tally HTTP request failed')
        data = response.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise ValueError('Response too large; narrower export required')
        return parse_response(data)
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description='Read-only local Tally connection check')
    parser.add_argument('--company', required=True, help='Exact company name shown in Tally')
    parser.add_argument('--port', type=int, default=9000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Invalid port')
    try:
        root = read('companies', args.company, args.port)
        names = [node.get('NAME') or node.findtext('NAME') for node in root.iter('COMPANY')]
        if args.company not in names:
            raise ValueError('Exact company was not returned; check the spelling and loaded companies')
        print(json.dumps({'connected': True, 'company': args.company, 'mode': 'read-only'}))
    except (OSError, ValueError, ET.ParseError, http.client.HTTPException) as error:
        print(json.dumps({'connected': False, 'error': str(error)}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
