import unittest
from app.assistant import answer
from app.domain import business_today

class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.snapshot={'ledgers':[{'name':'A & Co','group':'Sundry Debtors','balance':'120.25'}, {'name':'Supplier','group':'Sundry Creditors','balance':'-100.00'}], 'stock':[{'name':'Bag','quantity':'4','unit':'pcs'}], 'synced_at':1}
    def test_source_and_exact_balances(self):
        result=answer('Customers owe',self.snapshot,[])
        self.assertIn('120.25',result['message'])
        self.assertEqual(result['synced_at'],1)
    def test_unknown_does_not_guess(self):
        self.assertIn('could not match',answer('Predict profit next year',self.snapshot,[])['message'])
    def test_sales_only_include_confirmed_entries(self):
        entries=[{'kind':'Sales','date':business_today().isoformat(),'status':s,'total':'100','party':'A & Co'} for s in ['draft','queued','posted']]
        result=answer('Sales today',self.snapshot,entries)
        self.assertIn('100.00',result['message'])
        self.assertEqual(len(result['rows']),1)
    def test_low_stock(self):
        self.assertEqual(answer('Low stock',self.snapshot,[])['rows'][0]['name'],'Bag')
    def test_historical_balances_not_returned_as_current(self):
        self.assertIn('historical',answer('Cash balance yesterday',self.snapshot,[])['message'])
    def test_threshold_filter(self):
        result=answer('Customer outstanding above 200',self.snapshot,[])
        self.assertEqual(result['rows'],[])
    def test_no_snapshot_does_not_claim_zero(self):
        self.assertIn('No data',answer('Customers owe',{'ledgers':[],'stock':[]},[])['message'])
