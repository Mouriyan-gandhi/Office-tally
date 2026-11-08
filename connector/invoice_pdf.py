"""Read-only native invoice export. Never imports, alters or recreates a voucher."""
from datetime import date
from decimal import Decimal, InvalidOperation
import http.client
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from connector.read_company import export_request,parse_response

MAX_PDF=8*1024*1024


def exchange(port,xml,maximum):
    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=60)
    stage='sending request'
    try:
        connection.request('POST','/',body=xml,headers={'Content-Type':'text/xml; charset=utf-8'})
        stage='waiting for response headers'
        response=connection.getresponse()
        stage='reading response body'
        raw=response.read(maximum+1)
        if response.status!=200 or len(raw)>maximum:raise ValueError('Tally invoice export failed or exceeded its size limit')
        return raw
    except TimeoutError:
        operation='PDF rendering' if maximum==MAX_PDF else 'voucher lookup'
        raise ValueError(f'Tally {operation} timed out after 60 seconds while {stage}. Check the Windows Tally screen for an export/print dialog or prompt; do not resend the voucher') from None
    finally:connection.close()


def lookup_request(company,key,day,*,number=None,reference=None,kind=None):
    if not re.fullmatch(r'[A-Za-z0-9:-]{1,160}',key):raise ValueError('Unsupported voucher identity')
    day=date.fromisoformat(day).strftime('%Y%m%d')
    root=ET.fromstring(export_request('companies',company))
    variables=root.find('.//STATICVARIABLES')
    for name in ('SVFROMDATE','SVTODATE'):ET.SubElement(variables,name,TYPE='Date').text=day
    collection=root.find('.//COLLECTION')
    for child in list(collection):collection.remove(child)
    ET.SubElement(collection,'TYPE').text='Voucher'
    for field in ('GUID','RemoteID','MasterID','Date','VoucherTypeName','VoucherNumber','Reference','PartyLedgerName','IsCancelled','IsOptional','AllLedgerEntries.*'):
        ET.SubElement(collection,'NATIVEMETHOD').text=field
    ET.SubElement(collection,'FILTERS').text='OfficeInvoiceIdentity'
    if number is None and reference is None:
        condition=f'(($GUID = "{key}") OR ($RemoteID = "{key}"))'
    else:
        identity=number if number is not None else reference
        if not re.fullmatch(r'[A-Za-z0-9 /_.:-]{1,100}',identity) or kind not in ('Sales','Purchase'):
            raise ValueError('Voucher number cannot be used for safe invoice lookup; use the synced register invoice option')
        field='VoucherNumber' if number is not None else 'Reference'
        condition=f'(${field} = "{identity}") AND ($VoucherTypeName = "{kind}")'
    condition+=' AND ($Date >= ##SVFromDate) AND ($Date <= ##SVToDate)'
    ET.SubElement(root.find('.//TDLMESSAGE'),'SYSTEM',TYPE='Formulae',NAME='OfficeInvoiceIdentity').text=condition
    return ET.tostring(root,encoding='utf-8')


def pdf_request(company,master_id):
    master_id=str(master_id).strip()
    if not re.fullmatch(r'[0-9]{1,15}',master_id):raise ValueError('Invalid native voucher ID')
    root=ET.Element('ENVELOPE');header=ET.SubElement(root,'HEADER')
    for name,value in [('VERSION','1'),('TALLYREQUEST','Export'),('TYPE','Data'),('ID','OfficeNativeInvoice')]:ET.SubElement(header,name).text=value
    desc=ET.SubElement(ET.SubElement(root,'BODY'),'DESC');variables=ET.SubElement(desc,'STATICVARIABLES')
    for name,value in [('SVCURRENTCOMPANY',company),('SVEXPORTFORMAT','$$SysName:PDF'),('SVEXPORTFORMATVAR','$$SysName:PDF')]:ET.SubElement(variables,name).text=value
    message=ET.SubElement(ET.SubElement(desc,'TDL'),'TDLMESSAGE')
    report=ET.SubElement(message,'REPORT',NAME='OfficeNativeInvoice')
    ET.SubElement(report,'USE').text='Printed Invoice'
    ET.SubElement(report,'OBJECT').text=f'Voucher : "ID:{master_id}"'
    for variable in ('SVExportFormat','SVExportFormatVar'):
        ET.SubElement(report,'SET').text=f'{variable} : $$SysName:PDF'
        ET.SubElement(report,'LOCAL').text=f'Form : Printed Invoice : Set Always : {variable} : $$SysName:PDF'
    return ET.tostring(root,encoding='utf-8')


def normalized_identity(value):
    value=str(value or '').strip()
    # Hexadecimal GUID casing is cosmetic. Other external IDs stay case-sensitive.
    return value.casefold() if re.fullmatch(r'[0-9a-fA-F-]+',value) else value


def verify_voucher(voucher,target):
    if voucher.findtext('VOUCHERTYPENAME','').strip()!=target['kind'] or voucher.findtext('DATE','').strip()!=target['date'].replace('-',''):
        raise ValueError('Native voucher type/date changed; refresh before exporting')
    if target.get('party') and voucher.findtext('PARTYLEDGERNAME','').strip()!=target['party'].strip():
        raise ValueError('Native voucher party did not match')
    if any(voucher.findtext(tag,'').strip().casefold()=='yes' for tag in ('ISCANCELLED','ISOPTIONAL')):
        raise ValueError('Cancelled/optional voucher has no final invoice')


def resolve_voucher(port,company,target):
    root=parse_response(exchange(port,lookup_request(company,target['key'],target['date']),1024*1024))
    vouchers=list(root.iter('VOUCHER'))
    matches=[v for v in vouchers if normalized_identity(target['key']) in {
        normalized_identity(v.get('REMOTEID')),normalized_identity(v.get('GUID')),
        normalized_identity(v.findtext('GUID')),normalized_identity(v.findtext('REMOTEID'))}]
    if len(matches)==1:
        verify_voucher(matches[0],target)
        return matches[0]
    if len(matches)>1:raise ValueError('Native voucher identity was ambiguous; no PDF returned')
    # An external import/job ID is not assumed to be Tally's native GUID.
    # Resolve a posted app voucher using its exact number + date + type, then
    # independently verify party and signed party amount. Never select by amount alone.
    number=target.get('number') or None
    reference=target.get('reference') if target['kind']=='Purchase' and not number else None
    if target.get('source')!='posted_app' or not (number or reference) or not target.get('party') or not target.get('total'):
        raise ValueError('Native voucher identity did not match; use this voucher from the synced Sales/Purchase register to export by its native GUID')
    root=parse_response(exchange(port,lookup_request(company,target['key'],target['date'],number=number,reference=reference,kind=target['kind']),1024*1024))
    candidates=list(root.iter('VOUCHER'))
    exact=[v for v in candidates if v.findtext('VOUCHERNUMBER' if number else 'REFERENCE','').strip()==(number or reference).strip() and
           (number is not None or v.findtext('PARTYLEDGERNAME','').strip()==target['party'].strip()) and
           v.findtext('DATE','').strip()==target['date'].replace('-','') and
           v.findtext('VOUCHERTYPENAME','').strip()==target['kind']]
    if len(exact)!=1:raise ValueError('Native voucher number/date/type was missing or ambiguous; no PDF returned')
    voucher=exact[0];verify_voucher(voucher,target)
    try:
        amounts=[-Decimal(v.findtext('AMOUNT','').replace(',','').strip()) for v in voucher
                 if v.tag in ('ALLLEDGERENTRIES.LIST','LEDGERENTRIES.LIST') and v.findtext('LEDGERNAME','').strip()==target['party'].strip()]
        expected=Decimal(target['total'])*(1 if target['kind']=='Sales' else -1)
        if not amounts or not expected.is_finite() or any(not a.is_finite() for a in amounts) or sum(amounts,Decimal(0))!=expected:
            raise ValueError('Native voucher party amount did not match; no PDF returned')
    except InvalidOperation:raise ValueError('Native voucher amount could not be verified') from None
    return voucher


def export_pdf(port,company,target):
    if target.get('kind') not in ('Sales','Purchase'):raise ValueError('Only Sales and Purchase invoices are supported')
    voucher=resolve_voucher(port,company,target)
    pdf=exchange(port,pdf_request(company,voucher.findtext('MASTERID','')),MAX_PDF)
    if not pdf.startswith(b'%PDF-') or b'%%EOF' not in pdf[-2048:]:
        raise ValueError('Tally did not return a native PDF. Windows export compatibility needs verification; no substitute invoice was generated')
    return pdf


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Read-only native Tally invoice PDF check; never submits vouchers')
    parser.add_argument('--key',required=True);parser.add_argument('--date',required=True)
    parser.add_argument('--kind',choices=('Sales','Purchase'),default='Sales')
    parser.add_argument('--output',required=True);parser.add_argument('--port',type=int,default=9000)
    args=parser.parse_args()
    from app.company import COMPANY
    output=Path(args.output)
    if output.exists():raise SystemExit('Choose a new output filename; existing files are not overwritten')
    try:
        pdf=export_pdf(args.port,COMPANY,{'key':args.key,'date':args.date,'kind':args.kind})
        with output.open('xb') as stream:stream.write(pdf)
        print('Native Tally PDF saved to '+str(output))
    except ValueError as error:raise SystemExit(str(error)) from None

if __name__=='__main__':main()


def serve(cloud,port,company):
    import base64
    request=cloud.send('poll-invoice',{}).get('request')
    if not request:return
    result={'id':request['id'],'lease':request['lease']}
    try:result['pdf']=base64.b64encode(export_pdf(port,company,request['target'])).decode()
    except Exception as error:
        result['error']=True
        print('Native PDF export not completed: '+(str(error) if type(error) is ValueError else type(error).__name__)+'. Voucher posting status is unchanged.',flush=True)
    cloud.send('invoice-result',result)
