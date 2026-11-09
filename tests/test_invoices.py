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
            db.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?)',('draft','live',json.dumps({'kind':'Sales','date':'2026-11-02','party':'Test buyer','total':'118.00','voucher_number':'SYNTHETIC-1'}),'posted',1,1,1,'owner'))
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

    def test_external_job_id_resolves_unique_manual_invoice_with_amount_verification(self):
        target={'key':'abc123','kind':'Sales','date':'2026-11-02','party':'Test buyer','number':'SYNTHETIC-1','total':'118','source':'posted_app'}
        voucher=b'<ENVELOPE><COLLECTION><VOUCHER><GUID>different-native-guid</GUID><MASTERID> 42 </MASTERID><DATE>20261102</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME><VOUCHERNUMBER>SYNTHETIC-1</VOUCHERNUMBER><PARTYLEDGERNAME>Test buyer</PARTYLEDGERNAME><LEDGERENTRIES.LIST><LEDGERNAME>Test buyer</LEDGERNAME><AMOUNT>-118.00</AMOUNT></LEDGERENTRIES.LIST></VOUCHER></COLLECTION></ENVELOPE>'
        pdf=b'%PDF-1.4\nSynthetic\n%%EOF'
        with patch('connector.invoice_pdf.exchange',side_effect=[voucher,voucher,pdf]) as exchange:
            self.assertEqual(export_pdf(9000,'Upkar Agency',target),pdf)
            self.assertIn(b'$VoucherNumber',exchange.call_args_list[1].args[1])
            self.assertIn(b'ID:42',exchange.call_args_list[2].args[1])
        with patch('connector.invoice_pdf.exchange',side_effect=[voucher,voucher]) as exchange:
            with self.assertRaisesRegex(ValueError,'amount did not match'):export_pdf(9000,'Upkar Agency',target|{'total':'119'})
            self.assertEqual(exchange.call_count,2)
        duplicate=voucher.replace(b'</COLLECTION>',voucher[voucher.index(b'<VOUCHER>'):voucher.index(b'</COLLECTION>')]+b'</COLLECTION>')
        with patch('connector.invoice_pdf.exchange',side_effect=[voucher,duplicate]):
            with self.assertRaisesRegex(ValueError,'ambiguous'):export_pdf(9000,'Upkar Agency',target)

    def test_guid_whitespace_and_native_masterid_whitespace_are_supported(self):
        target={'key':'ABC123','kind':'Sales','date':'2026-11-02'}
        voucher=b'<ENVELOPE><VOUCHER><GUID> abc123 </GUID><MASTERID> 42 </MASTERID><DATE>20261102</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME></VOUCHER></ENVELOPE>'
        pdf=b'%PDF-1.4\nSynthetic\n%%EOF'
        with patch('connector.invoice_pdf.exchange',side_effect=[voucher,pdf]):self.assertEqual(export_pdf(9000,'Upkar Agency',target),pdf)

    def test_purchase_reference_resolution_checks_supplier_and_credit_amount(self):
        target={'key':'abc123','kind':'Purchase','date':'2026-11-02','party':'Test supplier','reference':'SUP-001','total':'118','source':'posted_app'}
        voucher=b'<ENVELOPE><VOUCHER><GUID>native-purchase</GUID><MASTERID>43</MASTERID><DATE>20261102</DATE><VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME><REFERENCE>SUP-001</REFERENCE><PARTYLEDGERNAME>Test supplier</PARTYLEDGERNAME><LEDGERENTRIES.LIST><LEDGERNAME>Test supplier</LEDGERNAME><AMOUNT>118</AMOUNT></LEDGERENTRIES.LIST></VOUCHER></ENVELOPE>'
        pdf=b'%PDF-1.4\nSynthetic\n%%EOF'
        with patch('connector.invoice_pdf.exchange',side_effect=[voucher,voucher,pdf]) as exchange:
            self.assertEqual(export_pdf(9000,'Upkar Agency',target),pdf)
            self.assertIn(b'$Reference',exchange.call_args_list[1].args[1])
        with self.assertRaises(ValueError):lookup_request('Upkar Agency','abc123','2026-11-02',number='BAD" OR TRUE',kind='Sales')

    def test_timeout_identifies_operation_and_closes_connection_without_retry(self):
        from connector.invoice_pdf import exchange, MAX_PDF
        for maximum,operation in ((MAX_PDF,'PDF rendering'),(1024*1024,'voucher lookup')):
            with patch('connector.invoice_pdf.http.client.HTTPConnection') as factory:
                connection=factory.return_value
                connection.getresponse.side_effect=TimeoutError()
                with self.assertRaisesRegex(ValueError,operation+' timed out.*response headers'):
                    exchange(9000,b'<ENVELOPE/>',maximum)
                connection.request.assert_called_once()
                connection.close.assert_called_once()

    def test_unverified_native_pdf_is_paused_without_contacting_tally(self):
        from connector.invoice_pdf import serve
        from unittest.mock import Mock
        cloud=Mock()
        cloud.send.return_value={'request':{'id':'test','lease':'lease','target':{}}}
        with patch.dict('os.environ',{},clear=True), patch('connector.invoice_pdf.export_pdf') as export:
            serve(cloud,9000,'Upkar Agency')
            export.assert_not_called()
        self.assertTrue(cloud.send.call_args.args[1]['error'])

    def test_admin_attachment_is_reused_and_never_reposts_voucher(self):
        self.request()
        with store.transaction() as db:
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',('pdf','live','Original.pdf','application/pdf','private/path',1))
            data={'draft_id':'draft','document_id':'pdf','confirmed':True}
            result=invoices.attach(db,data,'owner')
            status=invoices.status(db,result['id'])
            self.assertEqual(status['document_id'],'pdf')
            self.assertEqual(status['source'],'admin_attachment')
            self.assertIn('not verified automatically',status['note'])
            self.assertEqual(invoices.request(db,{'draft_id':'draft'},'owner')['id'],result['id'])
            self.assertEqual(db.execute('SELECT status FROM drafts').fetchone()[0],'posted')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
            for change in ({'confirmed':False},{'document_id':'missing'},{'draft_id':'missing'}):
                with self.assertRaises(ValidationError):invoices.attach(db,data|change,'owner')
            db.execute("UPDATE documents SET mode='demo' WHERE id='pdf'")
            with self.assertRaises(ValidationError):invoices.attach(db,data,'owner')
            db.execute("UPDATE documents SET mode='live',mime='image/png' WHERE id='pdf'")
            with self.assertRaises(ValidationError):invoices.attach(db,data,'owner')

    def test_both_register_types_can_store_original_pdfs_without_app_entry(self):
        with store.transaction() as db:
            vouchers=[{'id':kind,'kind':kind,'date':'2026-11-02','party':'Test party','cancelled':False,'optional':False} for kind in ('Sales','Purchase')]
            db.execute('INSERT INTO history_periods VALUES(?,?,?,?,?,?,?)',('2026-11-01','2026-11-30',json.dumps(vouchers),1,1,None,''))
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',('pdf','live','Original.pdf','application/pdf','private/path',1))
            for kind in ('Sales','Purchase'):
                source={'voucher_id':kind}
                attached=invoices.attach(db,source|{'document_id':'pdf','confirmed':True},'owner')
                self.assertEqual(invoices.request(db,source,'owner')['id'],attached['id'])
                self.assertEqual(invoices.status(db,attached['id'])['voucher']['kind'],kind)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)

    def test_paused_pdf_dispatch_does_not_fill_queue_or_block_attachment(self):
        self.request()
        with store.transaction() as db:
            db.execute("DELETE FROM report_requests")
            for i in range(30):
                db.execute('INSERT INTO report_requests VALUES(?,?,?,?,?,?,?,?)',(str(i),'invoice','{}','queued',None,None,1,1))
            result=invoices.request(db,{'draft_id':'draft'},'owner',dispatch=False)
            self.assertEqual(result['status'],'failed')
            self.assertIn('paused',invoices.status(db,result['id'])['error'])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM report_requests WHERE status='queued'").fetchone()[0],30)
