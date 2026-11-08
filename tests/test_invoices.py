import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app import invoices,store
from app.domain import ValidationError
from connector.invoice_pdf import lookup_request,pdf_request,export_pdf
import xml.etree.ElementTree as ET

class NativeInvoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.original=store.DATA;store.DATA=Path(self.temp.name);store.init()
    def tearDown(self):store.DATA=self.original;self.temp.cleanup()
    def request(self):
        with store.transaction() as db:
            db.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?)',('draft','live',json.dumps({'kind':'Sales','date':'2026-11-02','party':'Test buyer'}),'posted',1,1,1,'owner'))
            db.execute('INSERT INTO jobs(id,draft_id,payload,status,created) VALUES(?,?,?,?,?)',('abc123','draft','{}','posted',1))
            result=invoices.request(db,{'draft_id':'draft'},'owner')
            self.assertEqual(invoices.request(db,{'draft_id':'draft'},'owner')['id'],result['id'])
            return invoices.poll(db)
    def test_private_pdf_queue_and_idempotent_result(self):
        request=self.request();pdf=b'%PDF-1.4\nSynthetic test fixture\n%%EOF'
        data={'id':request['id'],'lease':request['lease'],'pdf':base64.b64encode(pdf).decode()}
        invoices.receive(data);invoices.receive(data)
        with store.transaction() as db:
            status=invoices.status(db,request['id']);self.assertEqual(status['status'],'ready')
            doc=db.execute('SELECT * FROM documents WHERE id=?',(status['document_id'],)).fetchone()
            self.assertEqual(Path(doc['path']).read_bytes(),pdf)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],1)
    def test_lease_and_nonpdf_are_rejected(self):
        request=self.request()
        with self.assertRaises(PermissionError):invoices.receive({'id':request['id'],'lease':'wrong','error':True})
        with self.assertRaises(ValidationError):invoices.receive({'id':request['id'],'lease':request['lease'],'pdf':base64.b64encode(b'<html>not an invoice</html>').decode()})
        with store.transaction() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],0)
    def test_failed_export_does_not_change_posted_voucher(self):
        request=self.request();invoices.receive({'id':request['id'],'lease':request['lease'],'error':True})
        with store.transaction() as db:
            self.assertEqual(invoices.status(db,request['id'])['status'],'failed')
            self.assertEqual(db.execute('SELECT status FROM drafts').fetchone()[0],'posted')
    def test_export_never_imports_and_uses_native_printed_invoice(self):
        for xml in (lookup_request('Upkar Agency','abc123','2026-11-02'),pdf_request('Upkar Agency','123')):
            root=ET.fromstring(xml);self.assertEqual(root.findtext('.//TALLYREQUEST'),'Export');self.assertIsNone(root.find('.//IMPORTDATA'))
        root=ET.fromstring(pdf_request('Upkar Agency','123'))
        self.assertEqual(root.findtext('.//USE'),'Printed Invoice');self.assertIn('ID:123',root.findtext('.//OBJECT'))
        with self.assertRaises(ValueError):pdf_request('Upkar Agency','123" : malicious')
    def test_native_identity_and_pdf_are_verified(self):
        voucher=b'<ENVELOPE><COLLECTION><VOUCHER><GUID>abc123</GUID><MASTERID>42</MASTERID><DATE>20261102</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME><PARTYLEDGERNAME>Test buyer</PARTYLEDGERNAME></VOUCHER></COLLECTION></ENVELOPE>'
        target={'key':'abc123','kind':'Sales','date':'2026-11-02','party':'Test buyer'}
        pdf=b'%PDF-1.4\nSynthetic\n%%EOF'
        with patch('connector.invoice_pdf.exchange',side_effect=[voucher,pdf]) as exchange:
            self.assertEqual(export_pdf(9000,'Upkar Agency',target),pdf)
            self.assertEqual(exchange.call_count,2)
        with patch('connector.invoice_pdf.exchange',side_effect=[voucher,b'<R>unsupported</R>']):
            with self.assertRaisesRegex(ValueError,'did not return a native PDF'):export_pdf(9000,'Upkar Agency',target)
        with patch('connector.invoice_pdf.exchange',return_value=voucher):
            with self.assertRaisesRegex(ValueError,'identity did not match'):export_pdf(9000,'Upkar Agency',target|{'key':'different'})
