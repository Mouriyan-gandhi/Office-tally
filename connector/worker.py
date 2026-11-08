"""Outbound-only Windows worker. Run on the PC where TallyPrime is running."""
import argparse
import http.client
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlparse
import urllib.request
from decimal import Decimal
from connector.read_company import read, parse_response, MAX_RESPONSE
from connector.xml_vouchers import build
from app.domain import normalize_draft, require_masters
from app.reporting import request_xml, flatten
from connector.history import read_period, failure_reason
from connector.network import reason as network_reason

from app.company import COMPANY


def quantity(value):
    match = re.search(r'-?\d[\d,]*(?:\.\d+)?', value or '')
    return match.group(0).replace(',', '') if match else ''


def balance(value):
    amount = quantity(value)
    if not amount:
        return ''
    number = Decimal(amount)
    if re.search(r'\bDr\b', value, re.I):
        return str(abs(number))
    if re.search(r'\bCr\b', value, re.I):
        return str(-abs(number))
    return str(-number)


def snapshot(port):
    company = read('companies', COMPANY, port)
    names = [row.get('NAME') or row.findtext('NAME') for row in company.iter('COMPANY')]
    if COMPANY not in names:
        raise ValueError('Configured company is not loaded in Tally')
    groups = read('groups', COMPANY, port)
    ancestry = {row.get('NAME') or row.findtext('NAME'):row.findtext('PARENT','') for row in groups.iter('GROUP')}
    categories = {'Sundry Debtors','Sundry Creditors','Cash-in-Hand','Bank Accounts','Sales Accounts','Purchase Accounts','Duties & Taxes','Indirect Incomes','Indirect Expenses'}
    def category(parent):
        seen = set()
        while parent not in categories and parent in ancestry and parent not in seen:
            seen.add(parent)
            parent = ancestry[parent]
        return parent
    ledgers = read('ledgers', COMPANY, port)
    stock = read('stock', COMPANY, port)
    godowns = read('godowns',COMPANY,port)
    types = read('voucher_types',COMPANY,port)
    yes = lambda value: str(value).casefold() == 'yes'
    books_from = next((row.findtext('BOOKSFROM','') for row in company.iter('COMPANY') if (row.get('NAME') or row.findtext('NAME')) == COMPANY), '')
    return {'company': COMPANY, 'books_from': books_from,
        'godowns':[{'name':v.get('NAME') or v.findtext('NAME','')} for v in godowns.iter('GODOWN')],
        'voucher_types':[{'name':v.get('NAME') or v.findtext('NAME',''),'numbering':v.findtext('NUMBERINGMETHOD',''),'parent':v.findtext('PARENT','')} for v in types.iter('VOUCHERTYPE')], 'ledgers': [
        {'name': row.get('NAME') or row.findtext('NAME') or '', 'group': category(row.findtext('PARENT', '')), 'parent':row.findtext('PARENT',''),
         'balance': balance(row.findtext('CLOSINGBALANCE', '')), 'billwise': yes(row.findtext('ISBILLWISEON'))}
        for row in ledgers.iter('LEDGER')], 'stock': [
        {'name': row.get('NAME') or row.findtext('NAME') or '', 'unit': row.findtext('BASEUNITS', ''),
         'quantity': quantity(row.findtext('CLOSINGBALANCE')), 'value': quantity(row.findtext('CLOSINGVALUE')),
         'rate': quantity(row.findtext('CLOSINGRATE')), 'batchwise': yes(row.findtext('ISBATCHWISEON')),
         'godown_required': bool(row.findall('.//GODOWNNAME'))}
        for row in stock.iter('STOCKITEM')]}


class Cloud:
    def __init__(self, url, token):
        parsed = urlparse(url)
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')):
            raise ValueError('Use HTTPS; HTTP is allowed only for local development')
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('Use the app origin without paths or embedded credentials')
        if len(token) < 32:
            raise ValueError('Connector token must have at least 32 characters')
        self.url, self.token = url.rstrip('/'), token

    def send(self, route, payload):
        request = urllib.request.Request(self.url + '/api/connector/' + route, data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=90) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError('App response too large')
            return json.loads(raw)


def import_once(xml, port):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    try:
        evidence = None
        if COMPANY == 'Upkar Agency TEST':
            from connector import import_diagnostics
            evidence = import_diagnostics.begin(xml)
            print('TEST import evidence: '+str(evidence),flush=True)
        connection.request('POST', '/', body=xml, headers={'Content-Type': 'text/xml; charset=utf-8'})
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE + 1)
        if evidence is not None:
            try:
                import_diagnostics.received(evidence,response.status,raw)
                print('TEST import response saved. Run: py -m connector.import_diagnostics',flush=True)
            except OSError:
                print('TEST response could not be saved; outcome still checked from memory.',flush=True)
        if response.status != 200 or len(raw) > MAX_RESPONSE:
            return 'needs_review', 'Import result uncertain; inspect Tally before retrying'
        root = parse_response(raw,allow_tally_errors=True)
        created = int(root.findtext('.//CREATED', '0'))
        errors = int(root.findtext('.//ERRORS', '0'))
        exceptions = int(root.findtext('.//EXCEPTIONS', '0'))
        other_changes = sum(int(root.findtext('.//'+tag,'0')) for tag in ('ALTERED','DELETED','CANCELLED'))
        if created == 1 and errors == 0 and exceptions == 0 and other_changes == 0:
            return 'posted', 'Tally confirmed one voucher created'
        if exceptions:
            return 'needs_review', 'Tally recorded an import exception; inspect Alt+O > Exceptions before resolving or resubmitting'
        if created == 0 and other_changes == 0 and errors:
            return 'rejected', ('Tally rejected the voucher; inspect its import log' + ('; run py -m connector.import_diagnostics on Windows for the saved response' if COMPANY == 'Upkar Agency TEST' else ''))
        return 'needs_review', 'No single voucher creation confirmed; inspect Tally'
    except Exception:
        return 'needs_review', 'No reliable response; inspect Tally before any retry'
    finally:
        connection.close()


def process(job, masters, journal, port, allow_writes):
    if not allow_writes:
        return 'rejected', 'Writes are disabled on this device'
    identifier = job['id']
    previous = journal.execute('SELECT status,message FROM imports WHERE id=?', (identifier,)).fetchone()
    if previous:
        return tuple(previous)
    try:
        if job.get('company') != COMPANY:
            raise ValueError('Unexpected company')
        draft = normalize_draft(job['draft'])
        require_masters(draft, masters)
        billwise = next((v.get('billwise',False) for v in masters['ledgers'] if v['name']==draft['party']),False)
        xml = build(draft, COMPANY, identifier,billwise=billwise)
    except (ValueError, KeyError, TypeError):
        return 'rejected', 'Voucher validation failed on the office device'
    journal.execute('INSERT INTO imports VALUES(?,?,?)', (identifier, 'needs_review', 'An import was started; inspect Tally before retrying'))
    journal.commit()
    status, message = import_once(xml, port)
    journal.execute('UPDATE imports SET status=?,message=? WHERE id=?', (status, message, identifier))
    journal.commit()
    return status, message


def main():
    parser = argparse.ArgumentParser(description='Upkar Agency outbound connector')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--port', type=int, default=9000)
    args = parser.parse_args()
    cloud = Cloud(os.environ.get('OFFICE_APP_URL', ''), os.environ.get('OFFICE_CONNECTOR_TOKEN', ''))
    allow = os.environ.get('OFFICE_ALLOW_TALLY_WRITES') == 'YES'
    folder = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / ('OfficeTally-Test' if COMPANY.endswith(' TEST') else 'OfficeTally')
    folder.mkdir(parents=True, exist_ok=True)
    journal = sqlite3.connect(folder / 'import-journal.db')
    journal.execute('CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY,status TEXT NOT NULL,message TEXT NOT NULL)')
    print('Company: '+COMPANY+'. Writes: ' + ('enabled' if allow else 'disabled'), flush=True)
    try:
        while True:
            try:
                masters = snapshot(args.port)
                cloud.send('snapshot', {'snapshot': masters})
                report = cloud.send('poll-read', {}).get('request')
                if report:
                    connection = http.client.HTTPConnection('127.0.0.1', args.port, timeout=30)
                    try:
                        connection.request('POST','/',body=request_xml(report['params'], COMPANY), headers={'Content-Type':'text/xml; charset=utf-8'})
                        response = connection.getresponse()
                        raw = response.read(MAX_RESPONSE+1)
                        if response.status != 200 or len(raw)>MAX_RESPONSE:
                            raise ValueError('Report export failed')
                        result = flatten(parse_response(raw))
                    except Exception:
                        result = {'rows':[], 'error':'Tally report export failed. Verify the report and period in Tally.'}
                    finally:
                        connection.close()
                    cloud.send('read-result', {'id':report['id'], 'lease':report['lease'], 'result':result})
                if allow:
                    job = cloud.send('poll', {}).get('job')
                    if job:
                        status, message = process(job, masters, journal, args.port, allow)
                        cloud.send('result', {'id': job['id'], 'lease': job['lease'], 'status': status, 'message': message})
                try:
                    from connector.invoice_pdf import serve
                    serve(cloud,args.port,COMPANY)
                except Exception:
                    print('Native invoice service unavailable; voucher posting is unchanged.',flush=True)
                print('Master sync complete.', flush=True)
                # Independent of posting and report processing: history failures must
                # never stop master sync or erase previously saved periods.
                try:
                    raw_start = masters.get('books_from','')
                    books_from = raw_start[:4]+'-'+raw_start[4:6]+'-'+raw_start[6:8] if len(raw_start)==8 else raw_start
                    period = cloud.send('poll-history', {'books_from':books_from}).get('period')
                    if period:
                        result = dict(period)
                        try:
                            result['vouchers'] = read_period(args.port, COMPANY, period['from'], period['to'])
                        except Exception as error:
                            result['error'] = True
                            print('History detail: '+failure_reason(error),flush=True)
                        cloud.send('history-result',result)
                        print('History '+period['from']+' to '+period['to']+(': retained previous cache; export failed.' if result.get('error') else ': synced.'),flush=True)
                except Exception:
                    print('History sync unavailable; master sync remains active.',flush=True)

            except Exception as error:
                print(('Connection check failed: '+network_reason(error)) if isinstance(error,urllib.error.URLError) else ('Local Tally/app check failed ('+type(error).__name__+'). Verify company, Tally port and app availability.'),flush=True)
                if args.once:
                    raise SystemExit(1) from None
            if args.once:
                break
            time.sleep(20)
    except KeyboardInterrupt:
        pass
    finally:
        journal.close()

if __name__ == '__main__':
    main()
