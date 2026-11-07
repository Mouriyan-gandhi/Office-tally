import unittest
from connector.vouchers import MoneyDraft

class VoucherTests(unittest.TestCase):
    def test_balanced_directions(self):
        for kind, sign in [('Receipt', 1), ('Payment', -1)]:
            entries = MoneyDraft(kind, 'Customer', 'Bank', '100.25').entries()
            self.assertEqual(sum(amount for _, amount in entries), 0)
            self.assertEqual(entries[0][1] > 0, sign > 0)

    def test_invalid_amounts(self):
        for value in ['NaN', 'Infinity', '-1', '0', '1.001', 'abc']:
            with self.assertRaises(ValueError):
                MoneyDraft('Receipt', 'Customer', 'Bank', value).validate()

    def test_same_ledger(self):
        with self.assertRaises(ValueError):
            MoneyDraft('Payment', 'Bank', ' bank ', '10').validate()
