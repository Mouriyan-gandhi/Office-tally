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
