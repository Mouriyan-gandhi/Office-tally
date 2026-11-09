'use strict';
// Report layouts deliberately preserve Tally's own field values until office-side mapping is verified.
const tallyReportNames={daybook:'Day book',sales:'Sales register',purchases:'Purchase register',ledger:'Ledger statement',receivables:'Bills receivable',payables:'Bills payable',trial:'Trial balance',profit:'Profit & loss',balance:'Balance sheet',stock:'Stock summary'};
let tallyReports=[];
async function openTallyReports(){
 nav('reports');
 const result=await api('reports');tallyReports=result.reports;if(state.page!=='reports')return;
 const day=today(),start=day.slice(0,4)+(Number(day.slice(5,7))>=4?'-04-01':'-01-01');
 $('#page').innerHTML=heading('Reports, straight from Tally.','Choose a period. The office connector fetches the report without changing your accounts.',`<button class="btn" data-action="reload-tally-reports">${icon('refresh')} Refresh</button>`)+`<div class="card"><form id="tally-report-form" class="card-body"><div class="form-grid"><div><label for="tally-report">Report</label><select name="report" id="tally-report">${Object.entries(tallyReportNames).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></div><div><label for="report-ledger">Ledger <small>(for ledger statement only)</small></label><input id="report-ledger" name="ledger" list="report-ledgers"><datalist id="report-ledgers">${snap().ledgers.map(l=>`<option value="${esc(l.name)}"></option>`).join('')}</datalist></div><div><label for="report-from">From</label><input type="date" id="report-from" name="from" value="${start}" required></div><div><label for="report-to">To</label><input type="date" id="report-to" name="to" value="${day}" required></div></div><button class="btn primary mt" type="submit" ${state.mode==='demo'?'disabled':''}>Request from office ${icon('arrow')}</button><p class="field-help mt">${state.mode==='demo'?'Full report requests are available in the connected Tally workspace.':'The office connector must be online. These requests are read-only.'}</p></form></div><section class="card mt"><div class="card-head"><div><h2>Requested reports</h2><p>Latest 30 requests · refresh to see a completed export.</p></div></div>${tallyReports.length?`<div class="table-wrap"><table><thead><tr><th>Report</th><th>Period</th><th>Status</th><th></th></tr></thead><tbody>${tallyReports.map(r=>`<tr><td>${esc(r.title)}</td><td>${esc(r.params.from)} — ${esc(r.params.to)}</td><td>${esc(r.status)}</td><td>${r.status==='ready'?`<button class="text-btn" data-tally-report="${esc(r.id)}">View ${icon('arrow')}</button>`:r.status==='failed'?esc(r.result?.error||'Export failed'):'Waiting for connector'}</td></tr>`).join('')}</tbody></table></div>`:empty('No reports requested yet','Choose a report and period above.','report')}</section><div class="notice mt">Exports are shown with original Tally field names and values. Polished report columns must be matched to your actual Tally output before production use.</div>`;
}
function showTallyReport(id){const report=tallyReports.find(r=>r.id===id);if(!report)return;state.report={title:report.title,rows:report.result.rows,columns:['field','value']};dialog(esc(report.title),`<p class="small muted">${esc(report.params.from)} — ${esc(report.params.to)} · ${esc(when(report.updated))}</p><div class="notice mt">${esc(report.result.note||'Original Tally report fields')}${report.result.truncated?' Export truncated at 20,000 fields.':''}</div>${simpleTable(report.result.rows,['field','value'])}`,`<button class="btn" data-action="export-report">${icon('down')} Export CSV</button><button class="btn primary" data-action="print-report">${icon('print')} Print / PDF</button>`);}
actions['open-tally-reports']=openTallyReports;
actions['reload-tally-reports']=openTallyReports;
document.addEventListener('click',event=>{const el=event.target.closest('[data-tally-report]');if(el)showTallyReport(el.dataset.tallyReport);});
document.addEventListener('submit',event=>{if(event.target.id!=='tally-report-form')return;event.preventDefault();run(async()=>{const params=Object.fromEntries(new FormData(event.target));await api('request-report',{...params,mode:state.mode});await openTallyReports();toast('Report requested. Refresh after the office connector responds.');});});

let registerView=null,registerRequest=0;
async function openRegister(kind,from='',to='',offset=0){
 const request=++registerRequest;
 dialog(kind==='Sales'?'Sales register':'Purchase register','<div id="register-loading">Loading synced Tally vouchers…</div>');
 const query=new URLSearchParams({kind,offset:String(offset),limit:'200'});if(from)query.set('from',from);if(to)query.set('to',to);
 const result=await api('register?'+query);
 if(request!==registerRequest||!modal.open||!$('#register-loading'))return;
 registerView={kind,...result};
 const title=kind==='Sales'?'Sales register':'Purchase register';
 const pending=result.coverage.filter(p=>p.status!=='cached');
 const rows=result.rows,columns=['date','number','party','reference','total'];
 state.report={title:title+' — displayed page of synced Tally vouchers',rows,columns};
 const cards=`<div class="phone-list">${rows.map(v=>`<article class="stock-card"><span class="entry-card-icon">${icon('invoice')}</span><div class="entry-card-copy"><strong>${esc(v.party||'Party not mapped yet')}</strong><span>${esc(dateText(v.date))} · ${esc(v.number||'Unnumbered')}</span><small>${esc(v.reference)}</small><button class="text-btn" data-voucher-invoice="${esc(v.id)}">Invoice PDF</button></div><div class="entry-card-value"><strong>${money(v.total)}</strong></div></article>`).join('')}</div>`;
 dialog(title,`<form id="register-filter" class="form-grid"><div><label for="register-from">From</label><input type="date" id="register-from" name="from" value="${esc(result.from)}" required></div><div><label for="register-to">To</label><input type="date" id="register-to" name="to" value="${esc(result.to)}" required></div><button class="btn primary" type="submit">Apply dates</button><button class="btn" type="button" data-action="register-refresh">${icon('refresh')} Refresh</button></form><div class="notice ${result.complete?'green':''} mt">${result.complete?'Every requested period has a cached export.':'History incomplete: '+pending.length+' date ranges are pending or need refresh.'} ${result.oldest_sync?'Oldest included period sync: '+esc(when(result.oldest_sync))+'.':''} Keep the office connector running for updates.</div><div class="summary-line mt"><span>${result.count} synced vouchers · ${offset+1>result.count?0:offset+1}–${Math.min(offset+rows.length,result.count)} shown</span><strong>${money(result.cached_total)}</strong></div><p class="field-help">Total of mapped synced vouchers in the selected dates.${result.unmapped_totals?' '+result.unmapped_totals+' vouchers need party mapping; their amounts are excluded from this total.':''}</p>${rows.length?cards+'<div class="desktop-table">'+simpleTable(rows,columns)+'<p class="field-help">Invoice PDFs:</p>'+rows.map(v=>`<button class="btn small" data-voucher-invoice="${esc(v.id)}">${esc(v.number||v.date)} · PDF</button>`).join(' ')+'</div>':empty('No synced vouchers in this period','This may be incomplete while history is importing.')}<div class="toolbar mt"><button class="btn" data-action="register-prev" ${offset===0?'disabled':''}>Previous</button><button class="btn" data-action="register-next" ${offset+rows.length>=result.count?'disabled':''}>Next</button></div><details class="mt"><summary>Period coverage</summary>${result.coverage.map(p=>`<p>${esc(p.from)} – ${esc(p.to)} · ${esc(p.status.replaceAll('_',' '))}${p.synced_at?' · '+esc(when(p.synced_at)):''}</p>`).join('')}</details><div class="notice mt">${esc(result.note)}</div>`,`<button class="btn" data-action="register-export">${icon('down')} Export all synced CSV</button><button class="btn" data-action="print-report">${icon('print')} Print this page</button>`);
}
actions['register-refresh']=()=>openRegister(registerView.kind,registerView.from,registerView.to,registerView.offset);
actions['register-prev']=()=>openRegister(registerView.kind,registerView.from,registerView.to,Math.max(0,registerView.offset-200));
actions['register-next']=()=>openRegister(registerView.kind,registerView.from,registerView.to,registerView.offset+200);
actions['register-export']=async()=>{
 const view=registerView;if(view.count>50000)throw Error('Choose a smaller date range to export at most 50,000 vouchers.');
 const rows=[];
 for(let offset=0;offset<Math.max(1,view.count);offset+=1000){
  const query=new URLSearchParams({kind:view.kind,from:view.from,to:view.to,offset:String(offset),limit:'1000'});
  const page=await api('register?'+query);
  if(page.revision!==view.revision)throw Error('History changed during export. Refresh the register and export again.');
  rows.push(...page.rows);
 }
 csv(view.kind+' register — '+(view.complete?'synced periods':'INCOMPLETE HISTORY'),rows,['date','number','party','reference','total']);
 toast(view.complete?'Synced register exported.':'Exported available records; history is still incomplete.');
};
document.addEventListener('submit',event=>{if(event.target.id!=='register-filter')return;event.preventDefault();const values=Object.fromEntries(new FormData(event.target));run(()=>openRegister(registerView.kind,values.from,values.to));});

let invoiceView=null,invoiceTimer=null;
async function openNativeInvoice(source){
 if(state.mode!=='live')throw Error('Native invoices are available for posted Tally vouchers in the Tally workspace.');
 clearTimeout(invoiceTimer);invoiceView={source,file:null};const view=invoiceView;
 dialog('Tally invoice PDF','<div id="native-invoice-panel"><p>Requesting the original invoice from the office connector…</p></div>');
 const result=await api('request-invoice',{...source,mode:'live'});
 if(invoiceView!==view||!modal.open||!$('#native-invoice-panel'))return;
 invoiceView.id=result.id;await refreshNativeInvoice();
}
async function refreshNativeInvoice(){
 const view=invoiceView;if(!view?.id||!modal.open||!$('#native-invoice-panel'))return;
 const result=await api('invoice-status?id='+encodeURIComponent(view.id));
 if(invoiceView!==view||!modal.open||!$('#native-invoice-panel'))return;
 view.voucher=result.voucher;
 if(result.status==='ready'){
  const response=await fetch('/api/documents/'+encodeURIComponent(result.document_id),{credentials:'same-origin'});
  if(!response.ok)throw Error('Sign in again or refresh to download the private invoice.');
  const blob=await response.blob();if(invoiceView!==view||!modal.open||!$('#native-invoice-panel'))return;view.file=new File([blob],result.filename||'Tally-invoice.pdf',{type:'application/pdf'});
  dialog('Invoice PDF',`<div id="native-invoice-panel"><div class="notice green">${esc(result.note||'The invoice PDF is ready.')}</div><p class="mt">On phones that support file sharing, choose WhatsApp from the share sheet and select the recipient. Otherwise download the PDF and attach it in WhatsApp.</p><p class="field-help mt">This file is private. No public invoice link is created and nothing is sent automatically.</p></div>`,`<button class="btn" data-action="download-native-invoice">${icon('down')} Download PDF</button><button class="btn primary" data-action="share-native-invoice">${icon('whatsapp')} Share invoice</button><button class="btn" data-action="attach-invoice-pdf">Attach original PDF</button><button class="btn" data-action="refresh-native-invoice">Get updated PDF</button>`);
 }else if(result.status==='failed'){
  dialog('Invoice export needs checking',`<div id="native-invoice-panel"><div class="notice error">${esc(result.error||'Tally did not return its native PDF.')}</div><p class="mt">Your voucher’s posting status is unchanged. Do not submit another sale to obtain an invoice.</p></div>`,`<button class="btn primary" data-action="attach-invoice-pdf">Attach original PDF</button><button class="btn" data-action="refresh-native-invoice">Retry PDF export only</button>`);
 }else{
  dialog(result.automatic_export_enabled?'Waiting for Tally invoice':'Attach your invoice PDF',`<div id="native-invoice-panel"><p>${result.automatic_export_enabled?'The office connector will export this already saved voucher. Keep Tally and the connector running.':'Automatic PDF export is paused while Tally compatibility is checked. Attach the original PDF below to download and share it from this register.'}</p><p class="field-help mt">This does not create or submit another voucher.</p></div>`,`<button class="btn primary" data-action="attach-invoice-pdf">Attach original PDF</button><button class="btn" data-action="check-native-invoice">${icon('refresh')} Check status</button>`);
  if(result.automatic_export_enabled)invoiceTimer=setTimeout(()=>run(refreshNativeInvoice),5000);
 }
}
actions['check-native-invoice']=refreshNativeInvoice;
actions['refresh-native-invoice']=()=>openNativeInvoice({...invoiceView.source,refresh:true});
actions['download-native-invoice']=()=>{const file=invoiceView?.file;if(!file)throw Error('Wait for the PDF to be ready.');const url=URL.createObjectURL(file),a=document.createElement('a');a.href=url;a.download=file.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);};
actions['share-native-invoice']=async()=>{
 const file=invoiceView?.file;if(!file)throw Error('Wait for the PDF to be ready.');
 if(navigator.canShare?.({files:[file]})){
  try{await navigator.share({files:[file],title:'Tally invoice'});}catch(error){if(error.name!=='AbortError')throw error;}
 }else{
  actions['download-native-invoice']();
  dialog('Attach your downloaded invoice',`<p>Your PDF has been downloaded. Open WhatsApp, choose the recipient and attach the PDF using its document/paperclip option.</p><div class="notice mt">A WhatsApp web link cannot automatically attach a private PDF.</div>`,`<a class="btn primary" target="_blank" rel="noopener noreferrer" href="https://wa.me/?text=${encodeURIComponent('Please find the invoice attached.')}">${icon('whatsapp')} Open WhatsApp</a>`);
 }
};
document.addEventListener('click',event=>{const button=event.target.closest('[data-native-invoice],[data-voucher-invoice]');if(!button)return;run(()=>openNativeInvoice(button.dataset.nativeInvoice?{draft_id:button.dataset.nativeInvoice}:{voucher_id:button.dataset.voucherInvoice}));});

actions['attach-invoice-pdf']=()=>{
 clearTimeout(invoiceTimer);
 const voucher=invoiceView.voucher||{};
 dialog('Attach original invoice PDF',`<form id="attach-invoice-form"><div class="notice">${esc(voucher.kind||'')} · ${esc(voucher.date||'')} · ${esc(voucher.party||'')}${voucher.number?' · '+esc(voucher.number):''}</div><p class="mt">Choose the PDF exported from Tally, or the supplier’s original purchase invoice. The app stores your file without changing its layout.</p><label for="original-invoice-file">Original PDF</label><input id="original-invoice-file" type="file" accept="application/pdf,.pdf" required><label class="mt"><input id="original-invoice-confirm" type="checkbox" style="width:22px;min-height:22px;margin-right:8px;vertical-align:middle" required> I checked that the company, party, invoice number, date and total match this voucher.</label><p class="field-help mt">The app cannot verify these details automatically. Attaching a file does not create, alter or resend a Tally voucher.</p><button class="btn primary mt" type="submit">Save invoice PDF</button></form>`);
};
document.addEventListener('submit',event=>{
 if(event.target.id!=='attach-invoice-form')return;
 event.preventDefault();
 const view=invoiceView,file=$('#original-invoice-file').files[0],confirmed=$('#original-invoice-confirm').checked;
 run(async()=>{
  if(!file||!confirmed)throw Error('Choose a PDF and confirm its details.');
  if(file.size>8*1024*1024)throw Error('Choose a PDF smaller than 8 MB.');
  const bytes=new Uint8Array(await file.arrayBuffer());
  if(new TextDecoder().decode(bytes.slice(0,5))!=='%PDF-'||!new TextDecoder().decode(bytes.slice(-2048)).includes('%%EOF'))throw Error('Choose a complete PDF file.');
  const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('Could not read the PDF.'));reader.readAsDataURL(file);});
  const uploaded=await api('upload',{mode:'live',name:file.name,content});
  const result=await api('attach-invoice',{...view.source,mode:'live',document_id:uploaded.id,confirmed:true});
  if(invoiceView!==view)return;
  view.id=result.id;
  dialog('Invoice PDF','<div id="native-invoice-panel">Opening the attached invoice…</div>');
  await refreshNativeInvoice();
 });
});
