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
 const cards=`<div class="phone-list">${rows.map(v=>`<article class="stock-card"><span class="entry-card-icon">${icon('invoice')}</span><div class="entry-card-copy"><strong>${esc(v.party||'Party not mapped yet')}</strong><span>${esc(dateText(v.date))} · ${esc(v.number||'Unnumbered')}</span><small>${esc(v.reference)}</small></div><div class="entry-card-value"><strong>${money(v.total)}</strong></div></article>`).join('')}</div>`;
 dialog(title,`<form id="register-filter" class="form-grid"><div><label for="register-from">From</label><input type="date" id="register-from" name="from" value="${esc(result.from)}" required></div><div><label for="register-to">To</label><input type="date" id="register-to" name="to" value="${esc(result.to)}" required></div><button class="btn primary" type="submit">Apply dates</button><button class="btn" type="button" data-action="register-refresh">${icon('refresh')} Refresh</button></form><div class="notice ${result.complete?'green':''} mt">${result.complete?'Every requested period has a cached export.':'History incomplete: '+pending.length+' date ranges are pending or need refresh.'} ${result.oldest_sync?'Oldest included period sync: '+esc(when(result.oldest_sync))+'.':''} Keep the office connector running for updates.</div><div class="summary-line mt"><span>${result.count} synced vouchers · ${offset+1>result.count?0:offset+1}–${Math.min(offset+rows.length,result.count)} shown</span><strong>${money(result.cached_total)}</strong></div><p class="field-help">Total of mapped synced vouchers in the selected dates.${result.unmapped_totals?' '+result.unmapped_totals+' vouchers need party mapping; their amounts are excluded from this total.':''}</p>${rows.length?cards+'<div class="desktop-table">'+simpleTable(rows,columns)+'</div>':empty('No synced vouchers in this period','This may be incomplete while history is importing.')}<div class="toolbar mt"><button class="btn" data-action="register-prev" ${offset===0?'disabled':''}>Previous</button><button class="btn" data-action="register-next" ${offset+rows.length>=result.count?'disabled':''}>Next</button></div><details class="mt"><summary>Period coverage</summary>${result.coverage.map(p=>`<p>${esc(p.from)} – ${esc(p.to)} · ${esc(p.status.replaceAll('_',' '))}${p.synced_at?' · '+esc(when(p.synced_at)):''}</p>`).join('')}</details><div class="notice mt">${esc(result.note)}</div>`,`<button class="btn" data-action="register-export">${icon('down')} Export all synced CSV</button><button class="btn" data-action="print-report">${icon('print')} Print this page</button>`);
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
