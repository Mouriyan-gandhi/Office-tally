import json
import sqlite3
import unittest
from datetime import date
from unittest.mock import patch
from app import history
from app.domain import ValidationError
from connector.history import request_xml, vouchers
from connector.read_company import parse_response

XML='''<ENVELOPE><BODY><DATA><COLLECTION><VOUCHER><GUID>synthetic-1</GUID><DATE>20261102</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME><VOUCHERNUMBER>TEST-1</VOUCHERNUMBER><ALLLEDGERENTRIES.LIST><LEDGERNAME>Test customer</LEDGERNAME><AMOUNT>-118</AMOUNT></ALLLEDGERENTRIES.LIST><ALLLEDGERENTRIES.LIST><LEDGERNAME>Test sales</LEDGERNAME><AMOUNT>100</AMOUNT></ALLLEDGERENTRIES.LIST><ALLLEDGERENTRIES.LIST><LEDGERNAME>Test tax</LEDGERNAME><AMOUNT>18</AMOUNT></ALLLEDGERENTRIES.LIST></VOUCHER></COLLECTION></DATA></BODY></ENVELOPE>'''

class HistoryTests(unittest.TestCase):
    def setUp(self):
        clock=patch('app.history.date',wraps=date);self.clock=clock;mock=clock.start();mock.today.return_value=date(2026,11,30)
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute("CREATE TABLE history_periods(start TEXT PRIMARY KEY,end_date TEXT,payload TEXT,updated REAL,attempted REAL,lease TEXT,error TEXT)")
    def tearDown(self):self.db.close();self.clock.stop()
    def sample(self):return vouchers(parse_response(XML.encode('utf-16')),'2026-11-01','2026-11-30')
    def save(self,rows):
        self.db.execute('UPDATE history_periods SET updated=1,attempted=0')
        p=history.poll(self.db,'2026-11-01')
        history.accept(self.db,p|{'vouchers':rows})
        return p
    def test_utf16_and_debit_credit(self):
        rows=self.sample();self.assertEqual(rows[0]['lines'][0]['amount'],'118')
        self.save(rows);result=history.statement(self.db,'Test customer')
        self.assertEqual(result['rows'][0]['debit'],'118');self.assertEqual(result['rows'][0]['credit'],'0')
    def test_repeat_replaces_and_deleted_voucher_disappears(self):
        self.save(self.sample());self.save(self.sample())
        self.assertEqual(len(history.statement(self.db,'Test customer')['rows']),1)
        self.save([]);self.assertEqual(history.statement(self.db,'Test customer')['rows'],[])
    def test_failed_export_retains_old_cache_and_bad_lease_rejected(self):
        self.save(self.sample())
        self.db.execute('UPDATE history_periods SET updated=1,attempted=0')
        p=history.poll(self.db,'2026-11-01')
        with self.assertRaises(PermissionError):history.accept(self.db,p|{'lease':'wrong','vouchers':[]})
        history.accept(self.db,p|{'error':True})
        result=history.statement(self.db,'Test customer')
        self.assertEqual(len(result['rows']),1);self.assertTrue(result['coverage'][0]['error'])
    def test_cancelled_optional_and_duplicate_id(self):
        self.save([self.sample()[0]|{'cancelled':True}]);self.assertEqual(history.statement(self.db,'Test customer')['rows'],[])
        with self.assertRaises(ValidationError):self.save(self.sample()*2)
    def test_invalid_xml_does_not_mean_empty_success(self):
        with self.assertRaises(ValueError):vouchers(parse_response(b'<ENVELOPE/>'),'2026-11-01','2026-11-30')
        with self.assertRaises(ValueError):vouchers(parse_response(XML.encode()),'2026-10-01','2026-10-31')
        self.assertEqual(vouchers(parse_response(b'<ENVELOPE><COLLECTION/></ENVELOPE>'),'2026-11-01','2026-11-30'),[])
    def test_periods_and_readonly_request(self):
        self.assertEqual(list(history.periods(date(2024,2,10),date(2024,3,2))),[('2024-02-10','2024-02-29'),('2024-03-01','2024-03-02')])
        root=parse_response(request_xml('Upkar Agency','2026-11-01','2026-11-30'))
        self.assertEqual(root.findtext('.//TALLYREQUEST'),'Export')
        self.assertIn('AllLedgerEntries.*',[n.text for n in root.findall('.//NATIVEMETHOD')])
        self.assertIsNone(root.find('.//FILTER'))
        self.assertEqual(root.findtext('.//FILTERS'),'OfficeHistoryPeriod')
        self.assertEqual(root.find('.//SVFROMDATE').get('TYPE'),'Date')
        self.assertEqual(root.find('.//SVTODATE').get('TYPE'),'Date')

    def test_control_character_obfuscation_cannot_hide_dtd(self):
        for encoding in ('utf-8','utf-16'):
            with self.assertRaises(ValueError):
                parse_response('<!DOC\x00TYPE x [<!ENTITY a "bad">]><x>&a;</x>'.encode(encoding))

    def test_diagnostics_explain_known_errors_without_echoing_unknown_data(self):
        from connector.history import failure_reason
        self.assertIn('date filter',failure_reason(ValueError('Tally returned vouchers outside the requested period')))
        self.assertIn('45 seconds',failure_reason(TimeoutError()))
        self.assertNotIn('private-party-secret',failure_reason(ValueError('private-party-secret')))

    def test_register_includes_tally_vouchers_without_app_drafts_and_no_duplicates(self):
        self.save(self.sample())
        snap={'ledgers':[{'name':'Test customer','group':'Sundry Debtors'}]}
        result=history.register(self.db,'Sales',snap,'2026-11-01','2026-11-30')
        self.assertEqual(result['count'],1);self.assertEqual(result['cached_total'],'118')
        self.assertEqual(result['rows'][0]['party'],'Test customer')
        self.assertTrue(result['complete'])
        revision=result['revision']
        self.save([self.sample()[0]|{'number':'ALTERED','party':'Test customer','reference':'SOURCE-REF'}])
        result=history.register(self.db,'Sales',snap,'2026-11-01','2026-11-30')
        self.assertEqual(result['count'],1);self.assertEqual(result['rows'][0]['number'],'ALTERED')
        self.assertEqual(result['rows'][0]['reference'],'SOURCE-REF');self.assertNotEqual(revision,result['revision'])
        self.save([])
        self.assertEqual(history.register(self.db,'Sales',snap,'2026-11-01','2026-11-30')['count'],0)

    def test_register_paging_custom_types_exclusions_and_pending_periods(self):
        base=self.sample()[0]
        self.save([base|{'id':'one','kind':'Wholesale Sale','party':'Test customer'},base|{'id':'two','optional':True},base|{'id':'three','cancelled':True}])
        snap={'voucher_types':[{'name':'Wholesale Sale','parent':'Sales'}]}
        result=history.register(self.db,'Sales',snap,'2026-10-01','2026-11-30',0,1)
        self.assertEqual(result['count'],1);self.assertFalse(result['complete'])
        self.assertEqual(result['coverage'][0]['status'],'pending')
        self.assertEqual(history.register(self.db,'Sales',snap,'2026-10-01','2026-11-30',1,1)['rows'],[])
        self.assertEqual(history.register(self.db,'Purchase',snap,'2026-10-01','2026-11-30')['count'],0)

    def test_register_never_invents_an_unmapped_total(self):
        self.save(self.sample())
        result=history.register(self.db,'Sales',{},'2026-11-01','2026-11-30')
        self.assertEqual(result['rows'][0]['total'],'');self.assertEqual(result['unmapped_totals'],1)
        with self.assertRaises(ValidationError):history.register(self.db,'Sales',{},'bad','2026-11-30')
        with self.assertRaises(ValidationError):history.register(self.db,'Sales',{},'2026-11-01','2026-11-30',-1)

    def test_current_month_refresh_has_priority_without_starving_backfill(self):
        self.db.execute("INSERT INTO history_periods VALUES(?,?,?,?,?,?,?)",('2026-11-01','2026-11-30','[]',1,1,None,''))
        p=history.poll(self.db,'2026-10-01')
        self.assertEqual(p['from'],'2026-11-01')
        history.accept(self.db,p|{'vouchers':[]})
        p=history.poll(self.db,'2026-10-01')
        self.assertEqual(p['from'],'2026-10-01')

    def test_export_revision_detects_changes_with_same_timestamp(self):
        with patch('app.history.time.time',return_value=123456):
            self.save(self.sample())
            before=history.register(self.db,'Sales',{},'2026-11-01','2026-11-30')['revision']
            self.save([self.sample()[0]|{'number':'CHANGED-IN-SAME-TICK'}])
            after=history.register(self.db,'Sales',{},'2026-11-01','2026-11-30')['revision']
        self.assertNotEqual(before,after)

    def test_clean_lines_deduplication_and_no_doubled_totals(self):
        # Exact doubled half list (ALLLEDGERENTRIES + LEDGERENTRIES bug)
        doubled = [
            {'ledger': 'Customer A', 'amount': '70800'},
            {'ledger': 'Sales @ 18%', 'amount': '-60000'},
            {'ledger': 'CGST @ 9%', 'amount': '-5400'},
            {'ledger': 'SGST @ 9%', 'amount': '-5400'},
            {'ledger': 'Customer A', 'amount': '70800'},
            {'ledger': 'Sales @ 18%', 'amount': '-60000'},
            {'ledger': 'CGST @ 9%', 'amount': '-5400'},
            {'ledger': 'SGST @ 9%', 'amount': '-5400'},
        ]
        cleaned = history.clean_lines(doubled)
        self.assertEqual(len(cleaned), 4)
        customer_amt = sum(float(l['amount']) for l in cleaned if l['ledger'] == 'Customer A')
        self.assertEqual(customer_amt, 70800.0)

        # Legitimate multi-line voucher with two items allocated to same Sales Account
        multi = [
            {'ledger': 'Customer B', 'amount': '2360'},
            {'ledger': 'Sales Accounts', 'amount': '-1000'},
            {'ledger': 'Sales Accounts', 'amount': '-1000'},
            {'ledger': 'CGST', 'amount': '-180'},
            {'ledger': 'SGST', 'amount': '-180'},
        ]
        cleaned_multi = history.clean_lines(multi)
        self.assertEqual(len(cleaned_multi), 5)

    def test_reconcile_drafts_with_tally_updates_altered_fields(self):
        self.db.execute("CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, mode TEXT, payload TEXT, status TEXT, version INTEGER, created REAL, updated REAL, author TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, draft_id TEXT UNIQUE, payload TEXT, status TEXT, lease TEXT, leased_at REAL, result TEXT, created REAL)")
        initial_payload = json.dumps({'kind': 'Sales', 'party': 'Old Party', 'total': '5000', 'voucher_number': '101', 'reference': 'REF-1'})
        self.db.execute("INSERT INTO drafts VALUES('draft-1', 'live', ?, 'posted', 1, 100, 100, 'test')", (initial_payload,))
        self.db.execute("INSERT INTO jobs VALUES('job-1', 'draft-1', '{}', 'completed', NULL, NULL, 'Confirmed', 100)")

        tally_voucher = {
            'id': 'tally-guid-1',
            'remote_id': 'job-1',
            'kind': 'Sales',
            'number': '101-ALTERED',
            'party': 'New Overwritten Party',
            'date': '2026-11-15',
            'reference': 'REF-1',
            'lines': [
                {'ledger': 'New Overwritten Party', 'amount': '70800'},
                {'ledger': 'Sales Accounts', 'amount': '-60000'},
                {'ledger': 'CGST', 'amount': '-5400'},
                {'ledger': 'SGST', 'amount': '-5400'}
            ]
        }
        history.reconcile_drafts_with_tally(self.db, [tally_voucher])
        updated_row = self.db.execute("SELECT payload FROM drafts WHERE id='draft-1'").fetchone()
        updated_payload = json.loads(updated_row['payload'])
        self.assertEqual(updated_payload['party'], 'New Overwritten Party')
        self.assertEqual(updated_payload['total'], '70800')
        self.assertEqual(updated_payload['voucher_number'], '101-ALTERED')

