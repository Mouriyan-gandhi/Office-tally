import unittest
from app.ocr import suggestions
from app.domain import normalize_draft
from tests.test_domain import invoice

class OCRTests(unittest.TestCase):
    def test_simple_bill_suggestions(self):
        text='Supplier\nInvoice No: INV-1\nDate: 2026-11-07\nBackpack\nQuantity: 10 pcs Rate: 450.00\nCGST 9%: 405.00\nSGST 9%: 405.00'
        result=suggestions(text)
        self.assertEqual(result['items'][0]['qty'],'10')
        self.assertEqual(result['items'][0]['rate'],'450.00')
        self.assertEqual(result['tax_rates'],{'CGST':9.0,'SGST':9.0})
        self.assertEqual(result['date'],'2026-11-07')
    def test_unknown_layout_does_not_invent_items(self):
        self.assertEqual(suggestions('Unreadable supplier photo')['items'],[])
    def test_printed_total_mismatch_blocks_draft(self):
        data=invoice();data['printed_total']='400'
        with self.assertRaises(ValueError):normalize_draft(data)
        data['printed_total']='318.91'
        self.assertEqual(normalize_draft(data)['total'],'318.91')
