import socket
import ssl
import unittest
import urllib.error
from connector.network import reason

class NetworkDiagnosticsTests(unittest.TestCase):
    def test_explains_failure_without_echoing_urls_or_tokens(self):
        cases=[(socket.gaierror(),'DNS'),(TimeoutError(),'timed out'),(ssl.SSLCertVerificationError(),'certificate'),(ConnectionRefusedError(),'refused')]
        for cause,label in cases:self.assertIn(label,reason(urllib.error.URLError(cause)))
        self.assertNotIn('private-token',reason(urllib.error.URLError('private-token')))
        self.assertIn('pairing',reason(urllib.error.HTTPError('https://private-token',401,'denied',{},None)))
        self.assertIn('starting',reason(urllib.error.HTTPError('https://private-token',503,'down',{},None)))
