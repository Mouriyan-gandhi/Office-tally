import unittest
from decimal import Decimal
from app.domain import normalize_draft, require_masters, ValidationError, business_today
from connector.xml_vouchers import build
from connector.worker import balance
import xml.etree.ElementTree as ET


def invoice(kind='Sales'):
    return {'kind':kind,'party':'Customer & Co','date':business_today().isoformat(),'reference':'INV-1',
            'account_ledger':'Sales' if kind=='Sales' else 'Purchase',
            'items':[{'name':'Bag <Large>','unit':'pcs','qty':'3','rate':'100.10','discount':'10'}],
            'taxes':[{'type':'CGST','ledger':'CGST','percent':'9'}, {'type':'SGST','ledger':'SGST','percent':'9'}]}


def receipt(kind='Receipt'):
    return {'kind':kind,'party':'Customer & Co','cash_bank':'Bank','date':business_today().isoformat(),'amount':'100.25'}

class DomainTests(unittest.TestCase):
    def test_decimal_totals_and_roundtrip(self):
        draft=normalize_draft(invoice())
        self.assertEqual(draft['subtotal'],'270.27')
        self.assertEqual(draft['total'],'318.91')
        self.assertEqual(normalize_draft(draft),draft)
        draft=normalize_draft(receipt())
        self.assertEqual(normalize_draft(draft),draft)

    def test_supplied_total_cannot_override_calculation(self):
        draft=invoice();draft['total']='1';draft['items'][0]['amount']='1'
        self.assertEqual(normalize_draft(draft)['total'],'318.91')

    def test_tax_combinations_rejected(self):
        draft=invoice();draft['taxes'].append({'type':'IGST','ledger':'IGST','percent':'18'})
        with self.assertRaises(ValidationError): normalize_draft(draft)
        draft=invoice();draft['taxes'].pop()
        with self.assertRaises(ValidationError): normalize_draft(draft)

    def test_invalid_quantities_and_money(self):
        for value in ['NaN','Infinity','-1','0','abc']:
            draft=invoice();draft['items'][0]['qty']=value
            with self.assertRaises(ValidationError): normalize_draft(draft)
        draft=receipt();draft['amount']='1.001'
        with self.assertRaises(ValidationError): normalize_draft(draft)

    def test_allocations_must_equal_amount(self):
        draft=receipt();draft['allocations']=[{'reference':'old bill','amount':'100'}]
        with self.assertRaises(ValidationError): normalize_draft(draft)

    def test_billwise_and_advanced_inventory_blocked(self):
        masters={'ledgers':[{'name':'Customer & Co','billwise':True},{'name':'Bank'}], 'stock':[]}
        with self.assertRaises(ValidationError): require_masters(normalize_draft(receipt()),masters)
        masters={'ledgers':[{'name':name,'group':group} for name,group in [('Customer & Co','Sundry Debtors'),('Sales','Sales Accounts'),('CGST','Duties & Taxes'),('SGST','Duties & Taxes')]], 'stock':[{'name':'Bag <Large>','unit':'pcs','batchwise':True}]}
        with self.assertRaisesRegex(ValidationError,'Batch/godown'): require_masters(normalize_draft(invoice()),masters)

    def test_all_voucher_xml_balanced_and_signs(self):
        for kind in ['Sales','Purchase','Receipt','Payment']:
            raw=build(invoice(kind) if kind in ('Sales','Purchase') else receipt(kind),'Upkar Agency','test-id')
            root=ET.fromstring(raw)
            voucher=root.find('.//VOUCHER')
            amounts=[Decimal(n.findtext('AMOUNT')) for n in voucher if n.tag in ('ALLLEDGERENTRIES.LIST','LEDGERENTRIES.LIST','ALLINVENTORYENTRIES.LIST')]
            self.assertEqual(sum(amounts),0)
            self.assertEqual(amounts[0]<0,kind in ('Sales','Payment'))
            self.assertEqual(root.findtext('.//PARTYLEDGERNAME'),'Customer & Co')
            self.assertEqual(root.findtext('.//SVCURRENTCOMPANY'),'Upkar Agency')
            self.assertEqual(voucher.get('REMOTEID'),'test-id')

    def test_native_balance_conversion(self):
        self.assertEqual(balance('-100.00'),'100.00')
        self.assertEqual(balance('100.00'),'-100.00')
        self.assertEqual(balance('100 Dr'),'100')
        self.assertEqual(balance('100 Cr'),'-100')
        self.assertEqual(balance(''),'')

class CompanyWriteTests(unittest.TestCase):
    def test_number_godown_override_roundoff_balanced(self):
        for kind in ('Sales','Purchase'):
            for roundoff in ('0.50','-0.50'):
                draft=invoice(kind)|{'voucher_number':'TEST-42','round_off':roundoff,'round_off_ledger':'Rounding'}
                draft['items'][0].update(godown='Main Location',amount_override='270.00',override_reason='Rounded price on source invoice')
                normalized=normalize_draft(draft)
                self.assertEqual(normalize_draft(normalized),normalized)
                root=ET.fromstring(build(normalized,'Upkar Agency','synthetic'))
                self.assertEqual(root.findtext('.//VOUCHERNUMBER'),'TEST-42')
                self.assertEqual(root.findtext('.//GODOWNNAME'),'Main Location')
                voucher=root.find('.//VOUCHER')
                self.assertEqual(sum(Decimal(n.findtext('AMOUNT')) for n in voucher if n.tag in ('ALLLEDGERENTRIES.LIST','LEDGERENTRIES.LIST','ALLINVENTORYENTRIES.LIST')),0)
    def test_reviewed_amount_requires_reason(self):
        draft=invoice();draft['items'][0]['amount_override']='270'
        with self.assertRaises(ValidationError):normalize_draft(draft)
    def test_no_bill_allocation_for_nonbillwise_party(self):
        self.assertIsNone(ET.fromstring(build(invoice(),'Upkar Agency','id')).find('.//BILLALLOCATIONS.LIST'))
        self.assertEqual(ET.fromstring(build(invoice(),'Upkar Agency','id',billwise=True)).findtext('.//BILLTYPE'),'New Ref')
    def test_test_company_cannot_use_cloud_database(self):
        import os
        from unittest.mock import patch
        from app.company import company_name
        with patch.dict(os.environ,{'OFFICE_TEST_COMPANY':'Upkar Agency TEST','OFFICE_BACKEND':'supabase'}):
            with self.assertRaises(RuntimeError):company_name()

    def test_invoice_party_and_tax_use_native_invoice_ledger_collection(self):
        for kind in ('Sales','Purchase'):
            root=ET.fromstring(build(invoice(kind),'Upkar Agency','id'))
            voucher=root.find('.//VOUCHER')
            self.assertIsNone(voucher.find('ALLLEDGERENTRIES.LIST'))
            ledgers=voucher.findall('LEDGERENTRIES.LIST')
            self.assertEqual(len(ledgers),3)
            self.assertEqual(ledgers[0].findtext('ISPARTYLEDGER'),'Yes')
            # Balance accounting ledger allocations, rather than treating inventory
            # amounts as if they were top-level financial ledger postings.
            amounts=[Decimal(n.findtext('AMOUNT')) for n in ledgers]
            amounts += [Decimal(n.findtext('AMOUNT')) for n in voucher.findall('ALLINVENTORYENTRIES.LIST/ACCOUNTINGALLOCATIONS.LIST')]
            self.assertEqual(sum(amounts),0)
