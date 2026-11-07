import json
import os
import unittest
from unittest.mock import patch, MagicMock
from app import cloud
from app.postgres import translated, Row

CONFIG = {
    'SUPABASE_URL':'https://example.supabase.co',
    'SUPABASE_PUBLISHABLE_KEY':'sb_publishable_test_only',
    'SUPABASE_SECRET_KEY':'sb_secret_test_only',
    'OFFICE_OWNER_EMAIL':'owner@example.test',
}
USER = {'id':'7f0f78ce-6655-4f42-ae8d-1c5354e46f32','email':'owner@example.test','email_confirmed_at':'2026-01-01T00:00:00Z'}

class CloudTests(unittest.TestCase):
    def setUp(self): self.env=patch.dict(os.environ,CONFIG);self.env.start()
    def tearDown(self):self.env.stop()

    def test_only_confirmed_configured_owner_is_allowed(self):
        self.assertTrue(cloud.owner_allowed(USER))
        for value in [USER|{'email':'stranger@example.test'},USER|{'email_confirmed_at':None},USER|{'banned_until':'2099-01-01T00:00:00Z'},USER|{'deleted_at':'2026-01-01'}]:
            self.assertFalse(cloud.owner_allowed(value))

    def test_unknown_admin_does_not_call_password_endpoint(self):
        with patch('app.cloud.request') as request:
            with self.assertRaises(PermissionError):cloud.sign_in('other@example.test','ignored')
            request.assert_not_called()

    def test_sign_in_verifies_identity_and_never_returns_auth_tokens(self):
        with patch('app.cloud.request',side_effect=[json.dumps({'access_token':'ephemeral-test-token'}).encode(),json.dumps(USER).encode()]) as request:
            result=cloud.sign_in('owner@example.test','test-password')
            self.assertEqual(result,{'id':USER['id'],'email':USER['email']})
            self.assertEqual(request.call_args_list[1].kwargs['token'],'ephemeral-test-token')
            self.assertNotIn('access_token',result)

    def test_changed_admin_identity_is_rejected(self):
        with patch('app.cloud.request',return_value=json.dumps(USER|{'id':'different'}).encode()):
            with self.assertRaises(PermissionError):cloud.verify_admin(USER['id'])

    def test_secret_is_sent_as_api_key_not_as_bearer_token(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{}'
        opener=MagicMock();opener.open.return_value=response
        with patch('urllib.request.build_opener',return_value=opener):
            cloud.request('GET','/storage/v1/bucket/office-invoices',secret=True)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Apikey'),CONFIG['SUPABASE_SECRET_KEY'])
        self.assertIsNone(request.get_header('Authorization'))

    def test_public_bucket_is_refused(self):
        with patch('app.cloud.request',return_value=b'{"public":true}'):
            with self.assertRaises(cloud.CloudError):cloud.check_bucket()

    def test_legacy_secret_configuration_rejected(self):
        with patch.dict(os.environ,{'SUPABASE_SECRET_KEY':'legacy-jwt-not-accepted'}):
            with self.assertRaises(cloud.CloudError):cloud.settings()

    def test_postgres_upsert_translation_and_parameters(self):
        sql=translated('INSERT OR REPLACE INTO snapshots VALUES(?,?,?)')
        self.assertIn('ON CONFLICT(mode) DO UPDATE',sql)
        self.assertEqual(sql.count('%s'),3)
        self.assertEqual(translated('SELECT * FROM users WHERE email=?'),'SELECT * FROM users WHERE email=%s')
        row=Row(total=3)
        self.assertEqual(row[0],3);self.assertEqual(row['total'],3)
