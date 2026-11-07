import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,MagicMock
from connector import import_diagnostics as diagnostics
from connector.worker import import_once

class ImportDiagnosticTests(unittest.TestCase):
    def test_response_with_lineerror_is_preserved_and_read_without_network(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(diagnostics,'folder',return_value=Path(temp)):
            target=diagnostics.begin(b'<ENVELOPE/>')
            raw=b'<RESPONSE><CREATED>0</CREATED><EXCEPTIONS>1</EXCEPTIONS><LINEERROR>Synthetic test exception</LINEERROR></RESPONSE>'
            diagnostics.received(target,200,raw)
            with patch('http.client.HTTPConnection') as connection:
                result=diagnostics.inspect(target)
                connection.assert_not_called()
            self.assertEqual(result['counts']['EXCEPTIONS'],'1')
            self.assertEqual(result['details'][0]['message'],'Synthetic test exception')
            self.assertEqual((target/'response.xml').read_bytes(),raw)
    def test_test_import_saves_evidence_and_production_does_not(self):
        for company in ('Upkar Agency TEST','Upkar Agency'):
            with tempfile.TemporaryDirectory() as temp,patch.object(diagnostics,'folder',return_value=Path(temp)),patch('connector.worker.COMPANY',company),patch('connector.worker.http.client.HTTPConnection') as factory:
                response=factory.return_value.getresponse.return_value
                response.status=200;response.read.return_value=b'<RESPONSE><CREATED>0</CREATED><ERRORS>0</ERRORS><EXCEPTIONS>1</EXCEPTIONS><LINEERROR>Synthetic reason</LINEERROR></RESPONSE>'
                self.assertEqual(import_once(b'<ENVELOPE/>',9000)[0],'needs_review')
                self.assertEqual(len(list(Path(temp).glob('*/response.xml'))),int(company.endswith(' TEST')))
    def test_cannot_send_test_import_if_request_capture_fails(self):
        with patch('connector.worker.COMPANY','Upkar Agency TEST'),patch.object(diagnostics,'begin',side_effect=OSError()),patch('connector.worker.http.client.HTTPConnection') as factory:
            self.assertEqual(import_once(b'<ENVELOPE/>',9000)[0],'needs_review')
            factory.return_value.request.assert_not_called()
