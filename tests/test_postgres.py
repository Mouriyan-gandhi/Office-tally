"""Real PostgreSQL checks, enabled by CI or an isolated local test database.
No test connects to the user's Supabase project or live Tally company.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.test_cloud import CONFIG, USER
from tests.test_domain import receipt, invoice

TEST_DSN=os.environ.get('OFFICE_TEST_DATABASE_URL','')

@unittest.skipUnless(TEST_DSN,'Set OFFICE_TEST_DATABASE_URL to an isolated local PostgreSQL test database')
class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.env=patch.dict(os.environ,CONFIG|{'OFFICE_BACKEND':'supabase','DATABASE_URL':TEST_DSN,'OFFICE_ALLOW_LOCAL_POSTGRES':'YES'})
        cls.env.start()
        with psycopg.connect(TEST_DSN,autocommit=True) as db:
            db.execute('CREATE SCHEMA IF NOT EXISTS storage')
            db.execute('CREATE TABLE IF NOT EXISTS storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint,allowed_mime_types text[])')
            for role in ['anon','authenticated','service_role']:
                if not db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():
                    from psycopg import sql
                    db.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
            db.execute(Path('supabase/migrations/202611070001_office.sql').read_text())
    @classmethod
    def tearDownClass(cls):cls.env.stop()
    def setUp(self):
        import psycopg
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient
        from app import server
        from app.asgi import endpoint
        self.server=server
        with psycopg.connect(TEST_DSN,autocommit=True) as db:
            db.execute('TRUNCATE office.users,office.sessions,office.drafts,office.jobs,office.snapshots,office.audit,office.report_requests,office.documents RESTART IDENTITY CASCADE')
        server.PREVIEW=False;server.LIVE_WRITES=True;server.DEVICE_TOKEN='isolated-test-device-token-'+('x'*32);server.ATTEMPTS.clear()
        self.auth=patch('app.cloud.sign_in',return_value={'id':USER['id'],'email':USER['email']});self.auth.start()
        self.verify=patch('app.cloud.verify_admin');self.verify.start()
        self.client=TestClient(Starlette(routes=[Route('/{path:path}',endpoint,methods=['GET','POST'])]),base_url='https://testserver')
        response=self.client.post('/api/login',json={'email':USER['email'],'password':'test-only'})
        self.assertEqual(response.status_code,200,response.text)
        self.csrf=response.json()['csrf']
    def tearDown(self):
        self.client.close();self.auth.stop();self.verify.stop();self.server.LIVE_WRITES=False;self.server.DEVICE_TOKEN=''
    def post(self,path,data,device=False):
        headers={'Authorization':'Bearer '+self.server.DEVICE_TOKEN} if device else {'X-CSRF-Token':self.csrf}
        return self.client.post('/api/'+path,json=data,headers=headers)
    def masters(self):
        snap={'company':'Upkar Agency','ledgers':[{'name':'Customer & Co','group':'Sundry Debtors','balance':'100'},{'name':'Bank','group':'Bank Accounts','balance':'1000'}, {'name':'Supplier','group':'Sundry Creditors','balance':'-100'},*[{'name':n,'group':g,'balance':'0'} for n,g in [('Sales','Sales Accounts'),('Purchase','Purchase Accounts'),('CGST','Duties & Taxes'),('SGST','Duties & Taxes')]]], 'stock':[{'name':'Bag <Large>','unit':'pcs','quantity':'20','rate':'100','value':'2000'}]}
        response=self.post('connector/snapshot',{'snapshot':snap},True)
        self.assertEqual(response.status_code,200,response.text)
    def test_schema_and_private_bucket(self):
        from app import store
        import psycopg
        store.init()
        with psycopg.connect(TEST_DSN) as db:
            self.assertEqual(db.execute("SELECT public FROM storage.buckets WHERE id='office-invoices'").fetchone()[0],False)
            self.assertEqual(db.execute("SELECT count(*) FROM pg_tables WHERE schemaname='office' AND rowsecurity").fetchone()[0],9)
    def test_anonymous_and_authenticated_roles_cannot_read_data(self):
        import psycopg
        for role in ['anon','authenticated','service_role']:
            with psycopg.connect(TEST_DSN) as db:
                db.execute('SET ROLE '+role)
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):db.execute('SELECT * FROM office.drafts')
    def test_admin_session_is_hashed_and_cookie_is_secure(self):
        from app import store
        cookie=self.client.cookies.get('office_session')
        with store.transaction() as db:
            row=db.execute('SELECT * FROM sessions').fetchone()
            self.assertNotEqual(row['id'],cookie)
            self.assertEqual(len(row['id']),64)
            self.assertEqual(db.execute('SELECT password FROM users').fetchone()['password'],'supabase-auth-only')
        self.assertEqual(self.client.get('/api/state?mode=live').status_code,200)
    def test_live_receipt_queue_and_confirmation(self):
        self.masters()
        response=self.post('drafts',{'mode':'live','draft':receipt()})
        self.assertEqual(response.status_code,200,response.text)
        draft=self.client.get('/api/state?mode=live').json()['drafts'][0]
        response=self.post('approve',{'mode':'live','id':draft['id'],'version':draft['version'],'confirmation':'Upkar Agency'})
        self.assertEqual(response.status_code,200,response.text)
        job=self.post('connector/poll',{},True).json()['job']
        self.assertIsNotNone(job)
        self.assertIsNone(self.post('connector/poll',{},True).json()['job'])
        response=self.post('connector/result',{'id':job['id'],'lease':job['lease'],'status':'posted','message':'Test result'},True)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/state?mode=live').json()['drafts'][0]['status'],'posted')
    def test_snapshots_upsert_and_demo_isolation(self):
        self.masters();self.masters()
        self.assertEqual(self.post('demo',{}).status_code,200)
        self.assertTrue(self.client.get('/api/state?mode=demo').json()['snapshot']['stock'])
        self.assertEqual(self.client.get('/api/state?mode=live').json()['snapshot']['stock'][0]['name'],'Bag <Large>')
    def test_private_file_upload_download(self):
        import base64
        image=b'\x89PNG\r\n\x1a\nTEST'
        with patch('app.cloud.put_file') as put,patch('app.cloud_uploads.extract',return_value={'available':True,'text':'Test bill'}):
            response=self.post('upload',{'mode':'live','name':'test.png','content':base64.b64encode(image).decode()})
        self.assertEqual(response.status_code,200,response.text)
        identifier=response.json()['id']
        self.assertTrue(put.call_args.args[0].startswith('upkar-agency/live/'))
        with patch('app.cloud.get_file',return_value=image):
            response=self.client.get('/api/documents/'+identifier)
        self.assertEqual(response.content,image)
        self.client.cookies.clear()
        with patch('app.cloud.get_file') as get:
            self.assertEqual(self.client.get('/api/documents/'+identifier).status_code,401)
            get.assert_not_called()
    def test_revoked_admin_is_denied(self):
        from app.cloud import CloudAuthError
        with patch('app.cloud.verify_admin',side_effect=CloudAuthError('Revoked')):
            self.assertEqual(self.client.get('/api/state?mode=live').status_code,401)
    def test_windows_connector_round_trip_for_all_four_vouchers(self):
        import sqlite3
        import threading
        import xml.etree.ElementTree as ET
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from connector.worker import snapshot,process
        imports=[]
        class TallyStub(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=ET.fromstring(self.rfile.read(int(self.headers['Content-Length'])))
                if request.findtext('.//TALLYREQUEST')=='Import Data':
                    imports.append(request)
                    body=b'<RESPONSE><CREATED>1</CREATED><ALTERED>0</ALTERED><ERRORS>0</ERRORS></RESPONSE>'
                else:
                    kind=request.findtext('.//COLLECTION/TYPE')
                    response=ET.Element('ENVELOPE')
                    def row(tag,name,fields):
                        element=ET.SubElement(response,tag,NAME=name)
                        for key,value in fields.items():ET.SubElement(element,key).text=value
                    if kind=='Company':row('COMPANY','Upkar Agency',{})
                    elif kind=='Group':row('GROUP','Local customers',{'PARENT':'Sundry Debtors'})
                    elif kind=='Ledger':
                        for name,group,amount in [('Customer & Co','Local customers','-100'),('Supplier','Sundry Creditors','100'),('Bank','Bank Accounts','-1000'),('Sales','Sales Accounts','0'),('Purchase','Purchase Accounts','0'),('CGST','Duties & Taxes','0'),('SGST','Duties & Taxes','0')]:
                            row('LEDGER',name,{'PARENT':group,'CLOSINGBALANCE':amount,'ISBILLWISEON':'No'})
                    elif kind=='StockItem':row('STOCKITEM','Bag <Large>',{'BASEUNITS':'pcs','CLOSINGBALANCE':'20 pcs','CLOSINGRATE':'100/pcs','CLOSINGVALUE':'2000','ISBATCHWISEON':'No'})
                    body=ET.tostring(response)
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        tally=ThreadingHTTPServer(('127.0.0.1',0),TallyStub)
        thread=threading.Thread(target=tally.serve_forever,daemon=True);thread.start()
        journal=sqlite3.connect(':memory:')
        journal.execute('CREATE TABLE imports(id TEXT PRIMARY KEY,status TEXT,message TEXT)')
        try:
            masters=snapshot(tally.server_address[1])
            self.assertEqual(masters['ledgers'][0]['group'],'Sundry Debtors')
            self.assertEqual(masters['ledgers'][0]['balance'],'100')
            self.assertEqual(self.post('connector/snapshot',{'snapshot':masters},True).status_code,200)
            for kind in ['Sales','Purchase','Receipt','Payment']:
                payload=invoice(kind) if kind in ('Sales','Purchase') else receipt(kind)
                if kind in ('Purchase','Payment'):payload['party']='Supplier'
                result=self.post('drafts',{'mode':'live','draft':payload})
                self.assertEqual(result.status_code,200,result.text)
                identifier=result.json()['id']
                draft=next(d for d in self.client.get('/api/state?mode=live').json()['drafts'] if d['id']==identifier)
                result=self.post('approve',{'mode':'live','id':identifier,'version':draft['version'],'confirmation':'Upkar Agency'})
                self.assertEqual(result.status_code,200,result.text)
                job=self.post('connector/poll',{},True).json()['job']
                status,message=process(job,masters,journal,tally.server_address[1],True)
                self.assertEqual(status,'posted',message)
                result=self.post('connector/result',{'id':job['id'],'lease':job['lease'],'status':status,'message':message},True)
                self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(len(imports),4)
            self.assertEqual({xml.findtext('.//VOUCHERTYPENAME') for xml in imports},{'Sales','Purchase','Receipt','Payment'})
            process(job,masters,journal,tally.server_address[1],True)
            self.assertEqual(len(imports),4,'Duplicate delivery must not import again')
        finally:
            journal.close();tally.shutdown();tally.server_close();thread.join()
