import sqlite3
import unittest
from unittest.mock import patch
from connector.worker import process, Cloud, import_once
from tests.test_domain import receipt
from app.reporting import request_xml, flatten, parameters
import xml.etree.ElementTree as ET

class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE imports(id TEXT PRIMARY KEY,status TEXT,message TEXT)')
        self.masters={'ledgers':[{'name':'Customer & Co','group':'Sundry Debtors'},{'name':'Bank','group':'Bank Accounts'}],'stock':[]}
        self.job={'id':'job-1','company':'Upkar Agency','draft':receipt()}
    def tearDown(self):self.db.close()

    def test_duplicate_delivery_imports_once(self):
        with patch('connector.worker.import_once',return_value=('posted','ok')) as send:
            self.assertEqual(process(self.job,self.masters,self.db,9000,True)[0],'posted')
            self.assertEqual(process(self.job,self.masters,self.db,9000,True)[0],'posted')
            send.assert_called_once()

    def test_uncertain_result_never_retried(self):
        with patch('connector.worker.import_once',return_value=('needs_review','timeout')) as send:
            process(self.job,self.masters,self.db,9000,True)
            self.assertEqual(process(self.job,self.masters,self.db,9000,True)[0],'needs_review')
            send.assert_called_once()

    def test_crash_marker_prevents_second_import(self):
        self.db.execute('INSERT INTO imports VALUES(?,?,?)',('job-1','needs_review','started'))
        self.db.commit()
        with patch('connector.worker.import_once') as send:
            self.assertEqual(process(self.job,self.masters,self.db,9000,True)[0],'needs_review')
            send.assert_not_called()

    def test_disabled_writes_and_wrong_company(self):
        with patch('connector.worker.import_once') as send:
            self.assertEqual(process(self.job,self.masters,self.db,9000,False)[0],'rejected')
            self.job['company']='Different company'
            self.assertEqual(process(self.job,self.masters,self.db,9000,True)[0],'rejected')
            send.assert_not_called()

    def test_cloud_refuses_plaintext_remote_and_credentials(self):
        for url in ['http://example.com','https://a:b@example.com','https://example.com/path']:
            with self.assertRaises(ValueError):Cloud(url,'x'*40)
        Cloud('https://example.com','x'*40)

    def test_report_allowlist_and_xml_escaping(self):
        params={'report':'ledger','from':'2026-04-01','to':'2026-11-07','ledger':'A & B <Account>'}
        root=ET.fromstring(request_xml(params,'Upkar Agency'))
        self.assertEqual(root.findtext('.//LEDGERNAME'),'A & B <Account>')
        self.assertEqual(root.findtext('.//REPORTNAME'),'Ledger Vouchers')
        self.assertEqual(root.findtext('.//TALLYREQUEST'),'Export Data')
        with self.assertRaises(ValueError): parameters(params|{'report':'Execute Arbitrary TDL'})
        with self.assertRaises(ValueError): parameters(params|{'from':'2027-01-01'})
        self.assertEqual(flatten(ET.fromstring('<R><AMOUNT>10</AMOUNT></R>'))['rows'][0]['value'],'10')

class ImportResultTests(unittest.TestCase):
    def response(self, xml):
        from unittest.mock import MagicMock
        connection=MagicMock()
        connection.getresponse.return_value.status=200
        connection.getresponse.return_value.read.return_value=xml
        return connection

    def test_created_with_error_is_uncertain_not_retryable(self):
        connection=self.response(b'<R><CREATED>1</CREATED><ERRORS>1</ERRORS></R>')
        with patch('connector.worker.http.client.HTTPConnection',return_value=connection):
            self.assertEqual(import_once(b'<ENVELOPE/>',9000)[0],'needs_review')

    def test_single_created_is_confirmed(self):
        connection=self.response(b'<R><CREATED>1</CREATED><ERRORS>0</ERRORS></R>')
        with patch('connector.worker.http.client.HTTPConnection',return_value=connection):
            self.assertEqual(import_once(b'<ENVELOPE/>',9000)[0],'posted')

    def test_no_created_and_error_is_rejected(self):
        connection=self.response(b'<R><CREATED>0</CREATED><ERRORS>1</ERRORS></R>')
        with patch('connector.worker.http.client.HTTPConnection',return_value=connection):
            self.assertEqual(import_once(b'<ENVELOPE/>',9000)[0],'rejected')
