import base64
import http.client
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from app import server, store
from app.demo import seed
from tests.test_domain import receipt, invoice

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.original=store.DATA
        store.DATA=Path(self.temp.name)
        store.init()
        server.PREVIEW=False
        server.LIVE_WRITES=True
        server.DEVICE_TOKEN='test-connector-token-'+('x'*40)
        server.ATTEMPTS.clear()
        server.init_user('owner@example.test','Test-only-password-123')
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.port=self.http.server_address[1]
        self.cookie='';self.csrf=''
        self.request('POST','/api/login',{'email':'owner@example.test','password':'Test-only-password-123'})

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
        store.DATA=self.original;server.LIVE_WRITES=False;server.DEVICE_TOKEN='';server.PREVIEW=False
        self.temp.cleanup()

    def request(self,method,path,data=None,device=False,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=15)
        hdr={'Content-Type':'application/json','Cookie':self.cookie,'X-CSRF-Token':self.csrf}
        if device:hdr['Authorization']='Bearer '+server.DEVICE_TOKEN
        hdr.update(headers or {})
        conn.request(method,path,json.dumps(data) if data is not None else None,hdr)
        response=conn.getresponse();raw=response.read();status=response.status
        cookie=response.getheader('Set-Cookie')
        if cookie:self.cookie=cookie.split(';')[0]
        result=json.loads(raw) if raw.startswith(b'{') else raw
        if path=='/api/login' and status==200:self.csrf=result['csrf']
        conn.close();return status,result

    def draft(self,mode='demo',payload=None):
        status,result=self.request('POST','/api/drafts',{'mode':mode,'draft':payload or (receipt() if mode=='live' else receipt()|{'party':'Asha Retail · Demo','cash_bank':'Cash'})})
        self.assertEqual(status,200,result)
        with store.transaction() as db:row=db.execute('SELECT * FROM drafts WHERE id=?',(result['id'],)).fetchone()
        return dict(row)

    def approve(self,row,mode='demo'):
        return self.request('POST','/api/approve',{'mode':mode,'id':row['id'],'version':row['version'],'confirmation':'Upkar Agency'})

    def masters(self):
        snap={'company':'Upkar Agency','ledgers':[{'name':'Customer & Co','group':'Sundry Debtors','balance':'100'},{'name':'Bank','group':'Bank Accounts','balance':'1000'},{'name':'Supplier','group':'Sundry Creditors','balance':'-100'},*[{'name':n,'group':g,'balance':'0'} for n,g in [('Sales','Sales Accounts'),('Purchase','Purchase Accounts'),('CGST','Duties & Taxes'),('SGST','Duties & Taxes')]]],'stock':[{'name':'Bag <Large>','unit':'pcs','quantity':'20','rate':'100','value':'2000'}]}
        status,result=self.request('POST','/api/connector/snapshot',{'snapshot':snap},device=True)
        self.assertEqual(status,200,result)

    def test_auth_csrf_and_origin(self):
        self.assertEqual(self.request('GET','/api/state',headers={'Cookie':''})[0],401)
        self.assertEqual(self.request('POST','/api/demo',{},headers={'X-CSRF-Token':''})[0],403)
        self.assertEqual(self.request('POST','/api/demo',{},headers={'Origin':'https://attacker.example'})[0],403)
        self.assertEqual(self.request('POST','/api/connector/poll',{})[0],401)

    def test_demo_save_isolated_from_queue_and_live_data(self):
        self.request('POST','/api/demo',{})
        row=self.draft()
        self.assertEqual(self.approve(row)[0],200)
        self.assertEqual(self.approve(row)[0],400)
        with store.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
            self.assertIsNone(store.snapshot(db,'live')['synced_at'])

    def test_live_queue_result_and_no_duplicate_approval(self):
        self.masters();row=self.draft('live')
        self.assertEqual(self.approve(row,'live')[0],200)
        status,result=self.request('POST','/api/connector/poll',{},device=True)
        self.assertEqual(status,200,result);job=result['job']
        self.assertIsNotNone(job)
        self.assertIsNone(self.request('POST','/api/connector/poll',{},device=True)[1]['job'])
        self.assertEqual(self.approve(row,'live')[0],400)
        self.assertEqual(self.request('POST','/api/connector/result',{'id':job['id'],'lease':'wrong','status':'posted'},device=True)[0],401)
        self.assertEqual(self.request('POST','/api/connector/result',{'id':job['id'],'lease':job['lease'],'status':'posted','message':'confirmed'},device=True)[0],200)
        state=self.request('GET','/api/state?mode=live')[1]
        self.assertEqual(state['drafts'][0]['status'],'posted')
        self.assertEqual(state['drafts'][0]['result'],'confirmed')

    def test_expired_import_needs_review_instead_of_retry(self):
        self.masters();row=self.draft('live');self.approve(row,'live')
        self.request('POST','/api/connector/poll',{},device=True)
        with store.transaction() as db:db.execute('UPDATE jobs SET leased_at=?',(time.time()-200,))
        self.assertIsNone(self.request('POST','/api/connector/poll',{},device=True)[1]['job'])
        with store.transaction() as db:self.assertEqual(db.execute('SELECT status FROM drafts WHERE id=?',(row['id'],)).fetchone()[0],'needs_review')

    def test_stale_snapshot_and_disabled_posting(self):
        row=self.draft('live')
        self.assertEqual(self.approve(row,'live')[0],400)
        self.masters();server.LIVE_WRITES=False
        self.assertEqual(self.approve(row,'live')[0],400)

    def test_duplicate_supplier_bill_blocked(self):
        self.masters();one=self.draft('live',invoice('Purchase')|{'party':'Supplier'});self.approve(one,'live')
        two=self.draft('live',invoice('Purchase')|{'party':'Supplier'})
        self.assertIn('already submitted',self.approve(two,'live')[1]['error'])

    def test_preview_cannot_reach_live_or_connector(self):
        server.PREVIEW=True
        self.assertEqual(self.request('GET','/api/state?mode=live')[0],400)
        self.assertEqual(self.request('POST','/api/connector/poll',{},device=True)[0],401)

    def test_attachment_stored_and_linked_to_draft(self):
        with patch('app.server.extract',return_value={'available':True,'text':'Bill'}):
            status,result=self.request('POST','/api/upload',{'mode':'demo','name':'bill.png','content':base64.b64encode(b'\x89PNG\r\n\x1a\nTEST').decode()})
        self.assertEqual(status,200,result)
        payload=receipt();payload['document_id']=result['id']
        self.draft(payload=payload)
        self.assertEqual(self.request('GET','/api/documents/'+result['id'])[0],200)
        self.assertEqual(self.request('POST','/api/drafts',{'mode':'live','draft':payload})[0],400)

    def test_optimistic_edit_lock(self):
        row=self.draft()
        data={'mode':'demo','id':row['id'],'version':row['version'],'draft':receipt()}
        self.assertEqual(self.request('POST','/api/drafts',data)[0],200)
        self.assertEqual(self.request('POST','/api/drafts',data)[0],400)

    def test_report_queue_read_only_and_lease(self):
        data={'mode':'live','report':'profit','from':'2026-04-01','to':'2026-11-07'}
        self.assertEqual(self.request('POST','/api/request-report',data)[0],200)
        request=self.request('POST','/api/connector/poll-read',{},device=True)[1]['request']
        self.assertEqual(request['params']['report'],'profit')
        result={'id':request['id'],'lease':request['lease'],'result':{'rows':[{'field':'PROFIT','value':'100'}]}}
        self.assertEqual(self.request('POST','/api/connector/read-result',result,device=True)[0],200)
        self.assertEqual(self.request('GET','/api/reports')[1]['reports'][0]['status'],'ready')

    def test_operator_cannot_approve(self):
        row=self.draft()
        with store.transaction() as db:db.execute("UPDATE users SET role='operator'")
        self.assertEqual(self.approve(row)[0],403)

    def test_offline_cached_masters_can_queue_but_missing_masters_cannot(self):
        row=self.draft('live')
        self.assertEqual(self.approve(row,'live')[0],400)
        self.masters()
        with store.transaction() as db:db.execute('UPDATE snapshots SET updated=? WHERE mode=?',(time.time()-86400,'live'))
        self.assertEqual(self.approve(row,'live')[0],200)
        with store.transaction() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()[0],'queued')

    def test_duplicate_manual_number_is_blocked(self):
        self.masters()
        first=self.draft('live',invoice()|{'voucher_number':'TEST-1'})
        self.assertEqual(self.approve(first,'live')[0],200)
        second=self.draft('live',invoice()|{'voucher_number':'TEST-1'})
        self.assertIn('voucher number was already submitted',self.approve(second,'live')[1]['error'])

    def test_pdf_queue_failure_does_not_rollback_posting_confirmation(self):
        self.masters();draft=self.draft('live',invoice())
        self.assertEqual(self.approve(draft,'live')[0],200)
        _,reply=self.request('POST','/api/connector/poll',{},device=True);job=reply['job']
        with patch('app.invoices.request',side_effect=ValueError('Synthetic PDF failure')):
            status,result=self.request('POST','/api/connector/result',{'id':job['id'],'lease':job['lease'],'status':'posted','message':'Created'},device=True)
            self.assertEqual(status,200,result)
        with store.transaction() as db:self.assertEqual(db.execute('SELECT status FROM drafts WHERE id=?',(draft['id'],)).fetchone()[0],'posted')

    def test_invoice_attachment_requires_admin_csrf_and_existing_saved_voucher(self):
        with store.transaction() as db:
            db.execute('INSERT INTO history_periods VALUES(?,?,?,?,?,?,?)',('2026-11-01','2026-11-30',json.dumps([{'id':'native-test','kind':'Sales','date':'2026-11-02','party':'Test buyer','cancelled':False,'optional':False}]),1,1,None,''))
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',('pdf','live','Original.pdf','application/pdf','private/path',1))
        data={'mode':'live','voucher_id':'native-test','document_id':'pdf','confirmed':True}
        with patch.dict('os.environ',{'OFFICE_ENABLE_NATIVE_PDF':''}):
            self.assertIsNone(self.request('POST','/api/connector/poll-invoice',{},device=True)[1]['request'])
        self.assertEqual(self.request('POST','/api/attach-invoice',data,headers={'X-CSRF-Token':''})[0],403)
        status,result=self.request('POST','/api/attach-invoice',data)
        self.assertEqual(status,200,result)
        self.assertEqual(self.request('GET','/api/invoice-status?id='+result['id'])[1]['document_id'],'pdf')
        self.assertEqual(self.request('POST','/api/attach-invoice',data|{'voucher_id':'missing'})[0],400)
        with store.transaction() as db:db.execute("UPDATE users SET role='viewer'")
        self.assertEqual(self.request('POST','/api/attach-invoice',data)[0],403)
