"""Read-only native invoice export. Never imports, alters or recreates a voucher."""
from datetime import date
import http.client
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from connector.read_company import export_request,parse_response

MAX_PDF=8*1024*1024


def exchange(port,xml,maximum):
    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=60)
    try:
        connection.request('POST','/',body=xml,headers={'Content-Type':'text/xml; charset=utf-8'})
        response=connection.getresponse();raw=response.read(maximum+1)
        if response.status!=200 or len(raw)>maximum:raise ValueError('Tally invoice export failed or exceeded its size limit')
        return raw
    finally:connection.close()


def lookup_request(company,key,day):
    if not re.fullmatch(r'[A-Za-z0-9:-]{1,160}',key):raise ValueError('Unsupported voucher identity')
    day=date.fromisoformat(day).strftime('%Y%m%d')
    root=ET.fromstring(export_request('companies',company))
    variables=root.find('.//STATICVARIABLES')
    for name in ('SVFROMDATE','SVTODATE'):ET.SubElement(variables,name,TYPE='Date').text=day
    collection=root.find('.//COLLECTION')
    for child in list(collection):collection.remove(child)
    ET.SubElement(collection,'TYPE').text='Voucher'
    for field in ('GUID','RemoteID','MasterID','Date','VoucherTypeName','PartyLedgerName','IsCancelled','IsOptional'):
        ET.SubElement(collection,'NATIVEMETHOD').text=field
    ET.SubElement(collection,'FILTERS').text='OfficeInvoiceIdentity'
    ET.SubElement(root.find('.//TDLMESSAGE'),'SYSTEM',TYPE='Formulae',NAME='OfficeInvoiceIdentity').text=f'($GUID = "{key}") OR ($RemoteID = "{key}")'
    return ET.tostring(root,encoding='utf-8')


def pdf_request(company,master_id):
    if not re.fullmatch(r'[0-9]{1,15}',str(master_id)):raise ValueError('Invalid native voucher ID')
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


def export_pdf(port,company,target):
    if target.get('kind') not in ('Sales','Purchase'):raise ValueError('Only Sales and Purchase invoices are supported')
    raw=exchange(port,lookup_request(company,target['key'],target['date']),1024*1024)
    root=parse_response(raw);vouchers=list(root.iter('VOUCHER'))
    if len(vouchers)!=1:raise ValueError('Native voucher identity could not be resolved uniquely; no PDF returned')
    voucher=vouchers[0]
    identities={voucher.get('REMOTEID'),voucher.findtext('GUID'),voucher.findtext('REMOTEID')}
    if target['key'] not in identities:raise ValueError('Native voucher identity did not match')
    if voucher.findtext('VOUCHERTYPENAME')!=target['kind'] or voucher.findtext('DATE')!=target['date'].replace('-',''):
        raise ValueError('Native voucher type/date changed; refresh before exporting')
    if target.get('party') and voucher.findtext('PARTYLEDGERNAME')!=target['party']:raise ValueError('Native voucher party did not match')
    if any(voucher.findtext(tag,'').casefold()=='yes' for tag in ('ISCANCELLED','ISOPTIONAL')):raise ValueError('Cancelled/optional voucher has no final invoice')
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
