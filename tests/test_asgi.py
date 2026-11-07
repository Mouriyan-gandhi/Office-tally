import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app import server, store

HAVE_ASGI=all(importlib.util.find_spec(name) for name in ('starlette','httpx'))

@unittest.skipUnless(HAVE_ASGI,'Install requirements-test.txt for production transport checks')
class ASGITests(unittest.TestCase):
    def setUp(self):
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient
        from app.asgi import endpoint
        self.env=patch.dict(os.environ,{'OFFICE_BACKEND':'local'});self.env.start()
        self.temp=tempfile.TemporaryDirectory();self.original=store.DATA;store.DATA=Path(self.temp.name)
        server.PREVIEW=False;server.ATTEMPTS.clear()
        store.init();server.init_user('owner@example.test','test-password-123456')
        self.client=TestClient(Starlette(routes=[Route('/{path:path}',endpoint,methods=['GET','POST'])]))
    def tearDown(self):
        self.client.close();store.DATA=self.original;self.temp.cleanup();self.env.stop()

    def login(self):
        response=self.client.post('/api/login',json={'email':'owner@example.test','password':'test-password-123456'})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['csrf']

    def test_public_config_and_private_state(self):
        self.assertEqual(self.client.get('/api/config').status_code,200)
        self.assertEqual(self.client.get('/api/state?mode=live').status_code,401)

    def test_login_cookie_and_session_transport(self):
        self.login()
        response=self.client.get('/api/session')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['email'],'owner@example.test')
        self.assertEqual(int(response.headers['content-length']),len(response.content))

    def test_static_phone_css_and_no_directory_traversal(self):
        self.assertEqual(self.client.get('/phone.css').status_code,200)
        self.assertIn('text/css',self.client.get('/phone.css').headers['content-type'])
        self.assertEqual(self.client.get('/.env').status_code,404)

    def test_csrf_and_origin_survive_asgi_adapter(self):
        csrf=self.login()
        self.assertEqual(self.client.post('/api/demo',json={}).status_code,403)
        self.assertEqual(self.client.post('/api/demo',json={},headers={'X-CSRF-Token':csrf,'Origin':'https://wrong.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/demo',json={},headers={'X-CSRF-Token':csrf}).status_code,200)

    def test_health_check(self):
        self.assertEqual(self.client.get('/healthz').json(),{'status':'ok'})
