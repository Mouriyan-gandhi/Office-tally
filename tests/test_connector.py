import unittest
import xml.etree.ElementTree as ET
from connector.read_company import export_request, parse_response


class ConnectorTests(unittest.TestCase):
    def test_exports_only_and_escapes_company(self):
        for kind in ('companies', 'ledgers', 'stock'):
            root = ET.fromstring(export_request(kind, 'Upkar & Sons <Test>'))
            self.assertEqual(root.findtext('./HEADER/TALLYREQUEST'), 'Export')
            self.assertEqual(root.findtext('.//SVCURRENTCOMPANY'), 'Upkar & Sons <Test>')
            self.assertIsNone(root.find('.//IMPORTDATA'))

    def test_unknown_operation_rejected(self):
        with self.assertRaises(ValueError):
            export_request('create-voucher', 'Upkar Agency')

    def test_tally_error_rejected(self):
        with self.assertRaises(ValueError):
            parse_response(b'<ENVELOPE><LINEERROR>Company not found</LINEERROR></ENVELOPE>')

    def test_entity_declaration_rejected(self):
        with self.assertRaises(ValueError):
            parse_response(b'<!DOCTYPE x [<!ENTITY a "data">]><x>&a;</x>')

    def test_valid_response(self):
        root = parse_response(b'<ENVELOPE><COMPANY NAME="Upkar Agency"/></ENVELOPE>')
        self.assertEqual(root.find('COMPANY').get('NAME'), 'Upkar Agency')


if __name__ == '__main__':
    unittest.main()

class XMLCompatibilityTests(unittest.TestCase):
    def test_reserved_name_control_reference(self):
        root = parse_response(b'<R><NAME>&#4; Not Applicable</NAME></R>')
        self.assertEqual(root.findtext('NAME'),' Not Applicable')
    def test_utf16_dtd_rejected(self):
        with self.assertRaises(ValueError):
            parse_response('<!DOCTYPE x [<!ENTITY a "test">]><x>&a;</x>'.encode('utf-16'))
