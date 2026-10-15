let currentId = null;
let currentProfile = null;
const $ = (id) => document.getElementById(id);
const fmt = (n) => Number(n || 0).toLocaleString();
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
async function api(path, options={}) {
  const response = await fetch(path, options);
  if (!response.ok) { let message=`Request failed (${response.status})`; try { message=(await response.json()).detail || message; } catch {} throw new Error(message); }
  if (response.status === 204) return null;
  return response.json();
}
function toast(text) { const el=$('toast'); el.textContent=text; el.classList.remove('hidden'); setTimeout(()=>el.classList.add('hidden'),2800); }
function showWorkspace() { $('empty').classList.add('hidden'); $('dashboard').classList.remove('hidden'); }
function showEmpty() { $('dashboard').classList.add('hidden'); $('empty').classList.remove('hidden'); currentId=null; }
function setBusy(button,busy,label) { button.disabled=busy; button.dataset.label ||= button.textContent; button.textContent=busy?label:button.dataset.label; }
const displayNumber = (n) => Number(n || 0).toLocaleString(undefined,{maximumFractionDigits:2});
async function refreshList() {
  const {datasets}=await api('/api/datasets');
  $('dataset-list').innerHTML=datasets.length?datasets.map(d=>`<button class="dataset-link" data-id="${esc(d.id)}" title="${esc(d.name)}">▧ &nbsp;${esc(d.name)}</button>`).join(''):'<p class="muted small">No datasets yet</p>';
  document.querySelectorAll('.dataset-link').forEach(b=>b.onclick=()=>loadDataset(b.dataset.id));
}
async function loadDataset(id) {
  currentId=id;
  const [metaList, profile, overview]=await Promise.all([api('/api/datasets'),api(`/api/datasets/${id}/profile`),api(`/api/datasets/${id}/analysis`)]);
  const meta=metaList.datasets.find(d=>d.id===id);
  currentProfile=profile; showWorkspace(); $('dataset-name').textContent=meta?.name||'Dataset overview'; $('dataset-subtitle').textContent=`${fmt(profile.rows)} rows · ${profile.columns} columns · Uploaded locally`;
  $('metrics').innerHTML=[['ROWS',fmt(profile.rows),'Records in this dataset'],['COLUMNS',fmt(profile.columns),'Fields available to explore'],['MISSING VALUES',fmt(profile.column_details.reduce((a,c)=>a+c.missing,0)),'Across all columns'],['DUPLICATES',fmt(profile.duplicate_rows),'Duplicate rows found']].map(([l,v,f])=>`<div class="metric"><div class="metric-label">${l}</div><div class="metric-value">${v}</div><div class="metric-foot">${f}</div></div>`).join('');
  $('profile-body').innerHTML=profile.column_details.map(c=>`<tr><td>${esc(c.name)}</td><td><span class="type-pill">${esc(c.dtype)}</span></td><td><span class="missing-bar"><i style="width:${Math.min(100,c.missing_pct)}%"></i></span>${c.missing_pct}%</td><td>${fmt(c.unique)}</td><td>${c.kind==='numeric'?`${esc(c.min)} – ${esc(c.max)}`:esc(c.samples.join(', ')||'—')}</td></tr>`).join('');
  const cols=profile.column_details.map(c=>c.name); ['chart-x','chart-y'].forEach(id=>$(id).innerHTML=cols.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join(''));
  const numeric=profile.column_details.filter(c=>c.kind==='numeric').map(c=>c.name);
  const dates=profile.column_details.filter(c=>/date|time|day|timestamp/i.test(c.name)||c.samples.some(v=>!Number.isNaN(Date.parse(v)))).map(c=>c.name);
  const categorical=profile.column_details.filter(c=>c.kind!=='numeric').map(c=>c.name);
  $('decision-date').innerHTML=dates.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');
  $('decision-metric').innerHTML=numeric.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');
  $('decision-segment').innerHTML='<option value="">No breakdown</option>'+categorical.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');
  const revenue=numeric.find(c=>/revenue|sales|amount|profit|total/i.test(c)); if(revenue)$('decision-metric').value=revenue;
  const segment=categorical.find(c=>/region|product|category|segment|channel/i.test(c)); if(segment)$('decision-segment').value=segment;
  $('decision-btn').disabled=!dates.length||!numeric.length;
  const correlations=overview.correlations;
  $('correlation-list').innerHTML=correlations.length?correlations.slice(0,8).map(c=>`<div class="corr-item"><span>${esc(c.left)} ↔ ${esc(c.right)}</span><span class="corr-track"><i style="width:${Math.abs(c.value)*100}%"></i></span><span class="corr-value">${c.value>0?'+':''}${c.value.toFixed(2)}</span></div>`).join(''):'<div class="no-results">Add at least two numeric columns with overlapping values to see correlations.</div>';
  await refreshList();
}
async function upload(file) {
  if(!file)return;
  $('upload-error').classList.add('hidden');
  const form=new FormData(); form.append('file',file);
  const label=$('dropzone').querySelector('b'); label.textContent='Uploading and profiling…';
  try { const data=await api('/api/datasets',{method:'POST',body:form}); await loadDataset(data.dataset.id); toast('Dataset is ready to explore.'); }
  catch(e){$('upload-error').textContent=e.message;$('upload-error').classList.remove('hidden');}
  finally {label.innerHTML='Drop your CSV here or <u>browse files</u>'; $('file-input').value='';}
}
$('file-input').onchange=e=>upload(e.target.files[0]);
$('demo-btn').onclick=async()=>{try{const response=await fetch('/static/sample_revenue.csv');if(!response.ok)throw new Error('Could not load the sample dataset');const file=new File([await response.blob()],'sample_revenue_risk.csv',{type:'text/csv'});await upload(file);}catch(e){$('upload-error').textContent=e.message;$('upload-error').classList.remove('hidden')}};
$('upload-top').onclick=()=>$('file-input').click();
$('upload-again').onclick=()=>{$('file-input').click();};
const dz=$('dropzone'); dz.ondragover=e=>{e.preventDefault();dz.classList.add('dragover')}; dz.ondragleave=()=>dz.classList.remove('dragover'); dz.ondrop=e=>{e.preventDefault();dz.classList.remove('dragover');upload(e.dataTransfer.files[0])};
$('clean-btn').onclick=async()=>{const b=$('clean-btn');setBusy(b,true,'Cleaning…');try{const out=await api(`/api/datasets/${currentId}/clean`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({drop_duplicates:true,impute:$('impute').value})});$('clean-result').textContent=`Removed ${out.report.duplicates_removed} duplicate rows; filled ${Object.values(out.report.missing_filled).reduce((a,x)=>a+x.count,0)} missing values.`;$('clean-result').classList.remove('hidden');await loadDataset(currentId);toast('Cleaned working copy saved.');}catch(e){toast(e.message)}finally{setBusy(b,false)}};
$('chart-btn').onclick=async()=>{const b=$('chart-btn');setBusy(b,true,'Building…');try{const fig=await api(`/api/datasets/${currentId}/chart`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:$('chart-kind').value,x:$('chart-x').value,y:$('chart-y').value})});$('chart-area').innerHTML='';Plotly.newPlot($('chart-area'),fig.data,fig.layout,{responsive:true,displayModeBar:false});}catch(e){toast(e.message)}finally{setBusy(b,false)}};
$('decision-btn').onclick=async()=>{const b=$('decision-btn'),area=$('decision-result');setBusy(b,true,'Comparing periods…');area.innerHTML='<div class="decision-empty">Comparing the latest periods and tracing segment movement…</div>';try{const result=await api(`/api/datasets/${currentId}/analysis/decision-brief`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date_column:$('decision-date').value,metric_column:$('decision-metric').value,segment_column:$('decision-segment').value||null,aggregation:$('decision-aggregation').value,period:$('decision-period').value})});const sign=result.change>0?'+':'';const pct=result.percent_change===null?'new activity':`${result.percent_change>0?'+':''}${result.percent_change}%`;const headline=result.status==='decline'?`${esc(result.metric)} is down ${Math.abs(result.percent_change||0)}%`:result.status==='growth'?`${esc(result.metric)} is up ${result.percent_change}%`:result.status==='new_activity'?`${esc(result.metric)} increased from zero`:`${esc(result.metric)} is relatively stable`;const tone=result.status==='decline'?'risk':result.status==='growth'?'growth':'stable';const drivers=result.segment_drivers.length?`<div class="driver-table"><div class="driver-head"><span>${esc(result.segment_column||'Segment')}</span><span>Previous</span><span>Latest</span><span>Change</span><span>Net share</span></div>${result.segment_drivers.map(d=>`<div class="driver-row"><b>${esc(d.segment)}</b><span>${displayNumber(d.previous)}</span><span>${displayNumber(d.current)}</span><span class="${d.change<0?'negative':'positive'}">${d.change>0?'+':''}${displayNumber(d.change)}</span><span>${d.contribution_pct===null?'—':`${d.contribution_pct>0?'+':''}${d.contribution_pct}%`}</span></div>`).join('')}</div>`:'<div class="decision-empty">No segment breakdown selected.</div>';area.innerHTML=`<div class="brief-top"><div><span class="status-pill ${tone}">${result.status.replace('_',' ')}</span><h3>${headline}</h3><p>${esc(result.previous.label)} → ${esc(result.current.label)} · ${esc(result.aggregation)} per ${esc(result.period)}</p></div><div class="brief-kpi"><small>PERIOD CHANGE</small><strong class="${result.change<0?'negative':'positive'}">${sign}${displayNumber(result.change)}</strong><span>${pct}</span></div></div><div class="driver-title">Where the movement came from</div>${drivers}<div class="next-check"><b>Recommended next check</b><p>${esc(result.recommendation)}</p></div><div class="coverage-note">${displayNumber(result.coverage.valid_rows)} valid rows · ${displayNumber(result.coverage.excluded_rows)} excluded · Segment shares describe movement, not cause.</div>`;}catch(e){area.innerHTML=`<div class="decision-error">${esc(e.message)}</div>`;}finally{setBusy(b,false)}};
$('anomaly-btn').onclick=async()=>{const b=$('anomaly-btn'),out=$('anomaly-result');setBusy(b,true,'Scanning…');try{const columns=currentProfile.column_details.filter(c=>c.kind==='numeric').map(c=>c.name);const data=await api(`/api/datasets/${currentId}/analysis/anomalies`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({columns})});out.textContent=`Isolation Forest flagged ${data.anomaly_count} unusual rows across ${fmt(data.sampled_rows)} analyzed records${data.sampled_rows<currentProfile.rows?' (sampled for speed)':''}. First row numbers: ${data.anomalies.slice(0,12).map(x=>x.row).join(', ')||'none found'}.`;out.classList.remove('hidden');}catch(e){toast(e.message)}finally{setBusy(b,false)}};
async function ask(question) { if(!question.trim())return; $('answer').textContent='Analyzing your question…';$('answer').classList.remove('hidden');const b=$('ask-btn');setBusy(b,true,'Thinking…');try{const out=await api(`/api/datasets/${currentId}/ask`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})});$('answer').innerHTML=`${esc(out.answer)}<small>Source: ${esc(out.source)}</small>`;}catch(e){$('answer').textContent=e.message;}finally{setBusy(b,false)} }
$('ask-btn').onclick=()=>ask($('question').value); $('question').onkeydown=e=>{if(e.key==='Enter')ask($('question').value)}; document.querySelectorAll('.suggestions button').forEach(b=>b.onclick=()=>{$('question').value=b.textContent;ask(b.textContent)});
$('download-btn').onclick=()=>{window.location=`/api/datasets/${currentId}/download`};
document.querySelectorAll('.nav-item').forEach(b=>b.onclick=()=>{document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));b.classList.add('active');$('crumb').textContent=b.textContent.trim();if(currentId){const target={overview:'dataset-name',data:'profile-body',analysis:'correlation-list',assistant:'question'}[b.dataset.view];$(target)?.scrollIntoView({behavior:'smooth',block:'center'});}});
document.querySelectorAll('.suggestions button').forEach(b=>b.onclick=()=>{$('question').value=b.textContent;ask(b.textContent)});
refreshList().catch(()=>{});
