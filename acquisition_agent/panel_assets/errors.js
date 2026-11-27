'use strict';
let errorCenter=null, errorCenterBusy=false, errorCenterSignature='';
const errorSourceNames={local:'This Mac',notion:'Notion records',cloud:'Hosted sender',monitor:'Monitoring connection'};
function errorTime(value){if(!value)return 'Not recorded';return new Date(typeof value==='number'?value*1000:value).toLocaleString();}
function errorLink(label,url){try{const parsed=new URL(url);if(parsed.protocol!=='https:'||!['www.notion.so','github.com'].includes(parsed.hostname))return null;const a=node('a',label,'button quiet');a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return null;}}
function errorBlock(label,text){const box=node('div',undefined,'error-explanation');box.append(node('h3',label),node('p',text));return box;}
function renderErrorCenter(){
 if(!errorCenter)return;
 const d=errorCenter;clear($('errors-metrics'));
 $('errors-local-warning').hidden=d.local_logging_available!==false;
 for(const [label,count,note] of [['Needs attention',d.counts.open,'Errors and intentional holds'],['Resolved',d.counts.resolved,'Kept in your history'],['Hosted queue',d.sources.cloud.queued??'—','Waiting is not an error']]){const card=node('article',undefined,'metric');card.append(node('span',label),node('strong',String(count)),node('small',note));$('errors-metrics').append(card);}
 clear($('errors-sources'));
 $('errors-sources').append(node('span','This Mac · saved locally','tag'));
 for(const source of ['notion','cloud']){const s=d.sources[source]||{};const label=s.state==='connected'?'last read '+errorTime(s.checked_at):s.state==='unavailable'?'unavailable · showing saved information':'not connected on this Mac';$('errors-sources').append(node('span',errorSourceNames[source]+' · '+label,'tag'));}
 $('errors-waiting').textContent=d.waiting_note;
 $('errors-history-note').textContent=d.history_note+' This Mac and the hosted sender each keep up to '+d.retention+' recent incidents, with unresolved incidents kept first.';
 if($('errors-step').options.length===1)for(const [id,label]of Object.entries(d.steps)){const o=node('option',label);o.value=id;$('errors-step').append(o);}
 renderErrorList();
}
function renderErrorList(){
 if(!errorCenter)return;
 const status=$('errors-state').value,step=$('errors-step').value,source=$('errors-source').value,query=$('errors-search').value.trim().toLowerCase();
 const rows=errorCenter.incidents.filter(x=>(status==='all'||x.status===status)&&(!step||x.step===step)&&(!source||x.sources.includes(source))&&[x.company,x.title,x.code,x.step_label].filter(Boolean).join(' ').toLowerCase().includes(query));
 $('errors-count').textContent=rows.length+' incident'+(rows.length===1?'':'s')+' shown · repeated observations stay in one card';
 const signature=JSON.stringify(rows);if(signature===errorCenterSignature)return;
 const opened=new Set(Array.from($('errors-list').querySelectorAll('details[open]'),x=>x.dataset.incident));
 const first=$('errors-list').children.length===0;errorCenterSignature=signature;clear($('errors-list'));
 if(!rows.length){const empty=node('article',undefined,'card error-empty');empty.append(node('h2','No matching issues'),node('p',status==='open'?'No unresolved issues are recorded in the sources last read. Check the source timestamps above; this does not prove that every workflow step has run.':'Change a filter to see other saved incidents.'));$('errors-list').append(empty);return;}
 for(const [index,item]of rows.entries()){
  const card=node('details',undefined,'card error-incident');card.dataset.incident=item.id;card.open=opened.has(item.id)||(first&&index===0);
  const summary=node('summary'),top=node('div',undefined,'error-summary'),heading=node('div');heading.append(node('strong',item.title),node('p',[item.step_label,item.company||'System / session',item.sources.map(x=>errorSourceNames[x]).join(' + ')].join(' · '),'caption'));
  top.append(heading,node('span',item.status==='resolved'?'Resolved':({urgent:'Needs reconciliation',blocked:'Held for review',warning:'Attention',info:'On hold',error:'Error'})[item.severity],'tag error-severity '+(item.status==='resolved'?'is-resolved':'is-'+item.severity)));summary.append(top);card.append(summary);
  card.append(node('p','First observed '+errorTime(item.first_seen)+' · Last observed '+errorTime(item.last_seen)+' · '+item.occurrences+' observation'+(item.occurrences===1?'':'s'),'caption error-timestamps'));
  const body=node('div',undefined,'error-detail-grid');body.append(errorBlock('What happened',item.what),errorBlock('Likely cause',item.likely_cause),errorBlock('What it affects',item.impact),errorBlock('Easiest next step',item.easiest_fix),errorBlock('Another option',item.other_option),errorBlock('How to check the fix',item.verify));card.append(body);
  const actions=node('div',undefined,'form-actions');for(const [label,url]of [['Open Notion record',item.record_url],['Open affected run',item.run_url]]){if(url){const link=errorLink(label,url);if(link)actions.append(link);}}
  if(item.sources.includes('local')){const session=node('button','Open session activity','button quiet');session.type='button';session.onclick=()=>switchView('discovery');actions.append(session);}
  const copy=node('button','Copy diagnostic details','button quiet');copy.type='button';copy.onclick=async()=>{try{await navigator.clipboard.writeText(JSON.stringify(item,null,2));notice('Safe diagnostic details copied. No credentials or email bodies are included.');}catch{notice('Clipboard is unavailable. Use Export safe diagnostic details instead.',true);}};actions.append(copy);card.append(actions);
  const technical=node('details',undefined,'error-technical');technical.append(node('summary','Diagnostic details for troubleshooting'),node('pre',JSON.stringify({code:item.code,step:item.step,context:item.scope,status:item.status,...item.technical},null,2)));card.append(technical);$('errors-list').append(card);
 }
}
window.loadErrorCenter=async(force=false)=>{
 if(errorCenterBusy)return;errorCenterBusy=true;$('errors-refresh').disabled=true;
 try{
  if(!force){errorCenter=await api('/api/error-center');renderErrorCenter();}
  if(force||state?.csrf&&(!errorCenter?.last_refreshed||Date.now()/1000-errorCenter.last_refreshed>60)){
   $('errors-status').textContent='Reading Notion and hosted history… This does not send or retry emails.';
   errorCenter=await api('/api/error-center/refresh',{},100000);renderErrorCenter();
  }
  $('errors-status').textContent=errorCenter.last_refreshed?'Last source check '+errorTime(errorCenter.last_refreshed)+'. Sources marked unavailable still show cached history.':'Saved local history. Use Refresh all sources to read current Notion and hosted information.';
 }catch(e){$('errors-status').textContent=errorText(e)+' Saved history is preserved.';}
 finally{errorCenterBusy=false;$('errors-refresh').disabled=false;}
};
$('errors-refresh').onclick=()=>window.loadErrorCenter(true);
for(const id of ['errors-state','errors-step','errors-source'])$(id).onchange=renderErrorList;
$('errors-search').oninput=renderErrorList;
$('errors-export').onclick=()=>{if(!errorCenter)return;const blob=new Blob([JSON.stringify(errorCenter,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='shine-safe-diagnostics.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
setInterval(()=>{if(active==='errors'&&state?.csrf&&!errorCenterBusy)window.loadErrorCenter(true);},60000);
if(active==='errors')window.loadErrorCenter();
