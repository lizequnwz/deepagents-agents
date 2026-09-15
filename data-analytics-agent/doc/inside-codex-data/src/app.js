(() => {
  'use strict';
  const data=JSON.parse(document.getElementById('lesson-data').textContent);
  const $=(s,root=document)=>root.querySelector(s);
  const $$=(s,root=document)=>[...root.querySelectorAll(s)];
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const decode=s=>new TextDecoder().decode(Uint8Array.from(atob(s),c=>c.charCodeAt(0)));
  let statusTimer;
  function announce(text){$('#status').textContent=text;clearTimeout(statusTimer);statusTimer=setTimeout(()=>$('#status').textContent='',3500);}
  async function copy(text){try{await navigator.clipboard.writeText(text);announce('Copied.');}catch{const field=$('#copy-fallback');field.value=text;field.hidden=false;if(!drawer.open){sourceTrigger=document.activeElement;$('#source-title').textContent='Copy text';$('#source-content').innerHTML='';drawer.showModal();}field.focus();field.select();announce('Clipboard unavailable. Text selected in the drawer; use your device’s Copy command.');}}
  const drawer=$('#source-drawer');let sourceTrigger=null;
  function openSources(ids,title,trigger){sourceTrigger=trigger||document.activeElement;$('#copy-fallback').hidden=true;$('#source-title').textContent=title||'Source evidence';$('#source-content').innerHTML=ids.map(id=>{
    const entries=data.sources[id];if(!entries)return '';
    return `<section class="source-group"><h3>${esc(id)}</h3>${entries.map(e=>`<article><span class="source-file">${esc(e.path.split('/').slice(-3).join('/'))}</span><p class="exact-path">${esc(e.path)}:${e.start}–${e.end}</p><button data-copy="${esc(e.path+':'+e.start+'-'+e.end)}">Copy path + lines</button><details><summary>Read source excerpt · lines ${e.start}–${e.excerptEnd}</summary><pre>${esc(e.excerpt)}</pre></details></article>`).join('')}</section>`;
    }).join('');drawer.showModal();$('#close-source').focus();
  }
  $('#close-source').addEventListener('click',()=>drawer.close());
  drawer.addEventListener('close',()=>{sourceTrigger?.focus({preventScroll:true});});
  drawer.addEventListener('keydown',event=>{
    if(event.key!=='Tab'||event.ctrlKey||event.metaKey||event.altKey)return;
    const controls=$$('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary',drawer).filter(el=>el.getClientRects().length);
    const first=controls[0],last=controls.at(-1);
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  });
  drawer.addEventListener('click',e=>{if(e.target===drawer){const r=drawer.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)drawer.close();}});
  document.addEventListener('click',e=>{
    const source=e.target.closest('[data-sources]');if(source)openSources(source.dataset.sources.split(' '),source.dataset.sourceTitle||'Under the Hood · source evidence',source);
    const button=e.target.closest('[data-copy]');if(button)copy(button.dataset.copy);
  });
  $$('.model').forEach(model=>{
    $$('[data-model]',model).forEach(button=>button.addEventListener('click',()=>{
      const expanded=button.getAttribute('aria-expanded')==='true';
      $$('[data-model]',model).forEach(b=>b.setAttribute('aria-expanded','false'));
      const panel=$('.model-detail',model);panel.hidden=expanded;
      if(!expanded){button.setAttribute('aria-expanded','true');const c=data.concepts[+button.dataset.model];panel.innerHTML=`<span class="eyebrow">Inside ${esc(c.name)}</span><p>${esc(c.detail)}</p>`;}
    }));
  });
  $('#expand-architecture').addEventListener('click',e=>{const open=e.currentTarget.getAttribute('aria-expanded')==='true';e.currentTarget.setAttribute('aria-expanded',String(!open));$('#expanded-architecture').hidden=open;e.currentTarget.textContent=open?'Expand the report / dashboard path ↓':'Return to four boxes ↑';});

  let step=0;
  function setStep(i){step=Math.max(0,Math.min(8,i));const s=data.walkthrough[step];
    $$('[data-step]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.step===step)));
    $$('.walk-node').forEach(n=>{n.classList.toggle('active',n.dataset.concept===s.active);$('i',n).textContent=n.dataset.concept===s.active?'ACTIVE':'';});
    $('#step-content').innerHTML=`<span class="eyebrow">Step ${step+1} / ${esc(s.owner)}</span><h3>${esc(s.title)}</h3><p>${esc(s.text)}</p><div class="io-pair"><div><span>Input</span><p>${esc(s.input)}</p></div><div><span>Produces</span><p>${esc(s.output)}</p></div></div>`;
    $('#step-count').textContent=`${step+1} / 9`;$('#step-prev').disabled=step===0;$('#step-next').disabled=step===8;
  }
  $$('[data-step]').forEach(b=>b.onclick=()=>setStep(+b.dataset.step));$('#step-prev').onclick=()=>setStep(step-1);$('#step-next').onclick=()=>setStep(step+1);setStep(0);

  let family='Analyze';
  function selectSkill(name){const s=data.skills.find(s=>s.name===name);$$('[data-skill]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.skill===name)));
    $('#skill-detail').innerHTML=`<span class="eyebrow">${esc(s.family)} / responsibility</span><h3>${esc(s.name)}</h3><p class="skill-purpose">${esc(s.purpose)}</p><dl><div><dt>When invoked</dt><dd>${esc(s.when)}</dd></div><div><dt>Needs</dt><dd>${esc(s.inputs)}</dd></div><div><dt>Owns</dt><dd>${esc(s.owns)}</dd></div><div><dt>Boundary</dt><dd>${esc(s.notOwns)}</dd></div></dl><div class="skill-rules"><span class="eyebrow">Two summarized rules</span><ul>${s.rules.map(r=>`<li>${esc(r)}</li>`).join('')}</ul></div><p class="companions"><strong>Common companions / handoffs</strong><br>${s.handoffs.map(h=>esc(h)).join(' · ')}<small>Context dependent, not a fixed execution graph.</small></p><details><summary>Example request</summary><p>“${esc(s.example)}”</p></details><button class="source-button" data-sources="K:${esc(s.name)}" data-source-title="${esc(s.name)} · instruction source">Inspect skill source ↗</button>`;
  }
  function selectFamily(name){family=name;$$('[data-family]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.family===name)));const members=data.skills.filter(s=>s.family===name);$('.skill-list').innerHTML=members.map(s=>`<button data-skill="${esc(s.name)}">${esc(s.name)}</button>`).join('');$$('[data-skill]').forEach(b=>b.onclick=()=>selectSkill(b.dataset.skill));selectSkill(name==='Analyze'?'metric-diagnostics':members[0].name);}
  $('.family-tabs').innerHTML=data.families.map(([name,desc,tone])=>`<button class="${tone}" data-family="${name}"><strong>${name}</strong><span>${desc}</span></button>`).join('');
  $$('[data-family]').forEach(b=>b.onclick=()=>selectFamily(b.dataset.family));selectFamily(family);
  function distinguish(i){const d=data.differences[i];$('#distinction-content').innerHTML=`<div><strong>${esc(d[0])}</strong><p>${esc(d[2])}</p></div><span aria-hidden="true">≠</span><div><strong>${esc(d[1])}</strong><p>${esc(d[3])}</p></div>`;}
  $('#distinction-select').onchange=e=>distinguish(+e.target.value);distinguish(0);

  const traces=[['Evidence is a saved analytical input.','A query key identifies reviewed rows and recorded provenance. It is an artifact reference, not a warehouse table name.'],['A component declares its evidence.','A stable component id and queryId connect the visible metric to the reviewed population. Intentional source subsets and display transforms must preserve scope.'],['Inspection follows the binding backward.','The reader can inspect saved definitions, rows, SQL, and evidence flow. This source view does not automatically rerun the original query.']];
  function trace(i){$$('[data-trace]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.trace===i)));$('#trace-detail').innerHTML=`<h3>${traces[i][0]}</h3><p>${traces[i][1]}</p>`;}
  $$('[data-trace]').forEach(b=>b.onclick=()=>trace(+b.dataset.trace));trace(0);
  function evidence(i){$$('[data-evidence]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.evidence===i)));const p=data.evidenceParts[i];$('#evidence-detail').innerHTML=`<h3>${esc(p[1])}</h3><p>${esc(p[2])}</p>`;}
  $$('[data-evidence]').forEach(b=>b.onclick=()=>evidence(+b.dataset.evidence));evidence(0);
  let nextIdentity=false;$('#identity-refresh').onclick=()=>{nextIdentity=!nextIdentity;$('#identity-status').textContent=nextIdentity?'Snapshot B · 17.1% · next period · IDs preserved':'Snapshot A · 18.4% · original period';$('#identity-refresh').textContent=nextIdentity?'Return to original snapshot':'Simulate next snapshot →';$('.identity-graph').classList.remove('refreshed');requestAnimationFrame(()=>$('.identity-graph').classList.add('refreshed'));};
  let state={renamed:false,moved:false,hidden:false,fresh:false};
  function renderState(){const e={queryId:'engagement-quarterly',engaged:state.fresh?171:184,eligible:1000,rate:state.fresh?'17.1%':'18.4%',source:'illustrative teaching fixture'};$('#evidence-json').textContent=JSON.stringify(e,null,2);$('#preview-title').textContent=state.renamed?'Quarterly participation':'Advisor engagement';$('#preview-value').textContent=e.rate;$('#preview-card').hidden=state.hidden;$('#preview-card').classList.toggle('moved',state.moved);$('#hidden-message').hidden=!state.hidden;$('#hide-card').textContent=state.hidden?'Show card':'Hide card';$('#stale-warning').hidden=!state.fresh;$('#refresh-evidence').disabled=state.fresh;$('#evidence-invariant').textContent=state.fresh?'Evidence changed only through the simulated refresh.':'Stored evidence is unchanged by presentation edits.';}
  $('#rename-card').onclick=()=>{state.renamed=!state.renamed;renderState();};$('#move-card').onclick=()=>{state.moved=!state.moved;renderState();};$('#hide-card').onclick=()=>{state.hidden=!state.hidden;renderState();};$('#reset-card').onclick=()=>{state={renamed:false,moved:false,hidden:false,fresh:false};renderState();};$('#refresh-evidence').onclick=()=>{state.fresh=true;renderState();};renderState();
  function life(i){$$('[data-lifecycle]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.lifecycle===i)));$('#lifecycle-detail').innerHTML=`<strong>${i+1}. ${esc(data.lifecycle[i][0])}</strong><p>${esc(data.lifecycle[i][1])}</p>`;}
  $$('[data-lifecycle]').forEach(b=>b.onclick=()=>life(+b.dataset.lifecycle));life(0);
  const delivery={local:['Local preview','Compiled HTML + bound snapshot sidecar','The local HTTP path loads reviewed data for the browser runtime. Source execution remains outside the page.'],offline:['Portable offline HTML','Reviewed snapshot embedded in the artifact','Rendering travels with the file. Fresh source reads, host-assisted conversion, and scheduling still need their capabilities.'],sites:['Sites publication','Exact compiled UI + hosted snapshot and presentation','The delivery workflow packages the current app, transfers bound assets, and checks readback while preserving Site access and user state.']};
  function deliver(key){$$('[data-delivery]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.delivery===key)));const d=delivery[key];$('#delivery-detail').innerHTML=`<span class="eyebrow">${d[0]}</span><h3>${d[1]}</h3><p>${d[2]}</p>`;}
  $$('[data-delivery]').forEach(b=>b.onclick=()=>deliver(b.dataset.delivery));deliver('local');
  function capabilities(){const source=$('#cap-source').checked,sites=$('#cap-sites').checked;$('#capability-result').textContent=`${source?'Fresh investigation can use the authorized source.':'Existing snapshots can render, but fresh investigation / refresh needs source access.'} ${sites?'Authorized publication can use Sites.':'Local preview and offline export remain possible; Sites publication is unavailable.'}`;}
  $('#cap-source').onchange=capabilities;$('#cap-sites').onchange=capabilities;capabilities();
  function pattern(i){$$('[data-pattern]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.pattern===i)));const p=data.patterns[i];$('#pattern-detail').innerHTML=`<span class="eyebrow">Engineering takeaway ${i+1} / 9</span><h3>${esc(p[0])}</h3><dl><div><dt>What Data does</dt><dd>${esc(p[1])}</dd></div><div><dt>Why this can help</dt><dd>${esc(p[2])}</dd></div><div><dt>Where to use it</dt><dd>${esc(p[3])}</dd></div></dl><button class="source-button" data-sources="${p[4]}">Inspect the basis ↗</button>`;}
  $$('[data-pattern]').forEach(b=>b.onclick=()=>pattern(+b.dataset.pattern));pattern(0);
  function tradeoff(i){const t=data.tradeoffs[i];$('#tradeoff-detail').innerHTML=`<h3>${esc(t[0])}</h3><p class="tradeoff-tension">${esc(t[1])}</p><div class="tradeoff-pair"><div><span class="eyebrow">For a smaller agent</span><p>${esc(t[2])}</p></div><div><span class="eyebrow">When the product grows</span><p>${esc(t[3])}</p></div></div><button class="source-button" data-sources="${t[4]}">Inspect the basis ↗</button>`;}
  $('#tradeoff-select').onchange=e=>tradeoff(+e.target.value);tradeoff(0);

  const scenes=$$('.scene');let current=0,present=false,raf=false,savedDetails=[];
  function updateScene(){raf=false;let found=0;scenes.forEach((s,i)=>{if(s.getBoundingClientRect().top<=innerHeight*.42)found=i;});current=found;$('#scene-select').value=scenes[current].id;$('#scene-position').textContent=`${String(current+1).padStart(2,'0')} / ${scenes.length}`;$('#present-scene-title').textContent=data.sceneTitles[current];$('#scene-prev').disabled=current===0;$('#scene-next').disabled=current===scenes.length-1;$('#read-progress').style.width=`${(current+1)/scenes.length*100}%`;}
  window.addEventListener('scroll',()=>{if(!raf){raf=true;requestAnimationFrame(updateScene);}},{passive:true});
  function go(i){current=Math.max(0,Math.min(scenes.length-1,i));scenes[current].scrollIntoView({behavior:present||matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});history.replaceState(null,'','#'+scenes[current].id);}
  $('#scene-select').onchange=e=>go(scenes.findIndex(s=>s.id===e.target.value));$('#scene-prev').onclick=()=>go(current-1);$('#scene-next').onclick=()=>go(current+1);
  function togglePresentation(force){present=typeof force==='boolean'?force:!present;document.body.classList.toggle('presenting',present);$('#presentation-toggle').setAttribute('aria-pressed',String(present));$('#presentation-toggle').textContent=present?'Exit presentation':'Presentation mode';$('#presentation-controls').hidden=!present;
    if(present){savedDetails=$$('.scene details').map(d=>d.open);$$('.scene details').forEach(d=>d.open=false);document.body.focus({preventScroll:true});go(current);announce('Presentation mode. Arrow keys or Space advance scenes. Escape exits. Interactive controls keep their normal keys.');}
    else{$$('.scene details').forEach((d,i)=>d.open=savedDetails[i]||false);$('#presentation-toggle').focus({preventScroll:true});}
  }
  $('#presentation-toggle').onclick=()=>togglePresentation();$('#exit-present').onclick=()=>togglePresentation(false);
  document.addEventListener('keydown',e=>{if(!present||drawer.open||e.altKey||e.ctrlKey||e.metaKey)return;if(e.key==='Escape'){togglePresentation(false);return;}if(e.target.closest('button,a,input,select,textarea,summary,[contenteditable],iframe'))return;if(['ArrowRight','ArrowDown',' ','PageDown'].includes(e.key)){e.preventDefault();go(current+1);}if(['ArrowLeft','ArrowUp','PageUp'].includes(e.key)){e.preventDefault();go(current-1);}});
  updateScene();
  $('#open-review').onclick=()=>{const wrap=$('#review-viewer');wrap.hidden=!wrap.hidden;$('#open-review').setAttribute('aria-expanded',String(!wrap.hidden));if(!wrap.hidden&&!$('#review-frame').srcdoc)$('#review-frame').srcdoc=decode(data.reviewHtml);};
  function download(payload,name,type){const link=document.createElement('a');const bytes=Uint8Array.from(atob(payload),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type}));link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),2000);}
  $('#download-review').onclick=()=>download(data.reviewHtml,'data-plugin-standalone-review-2026-09-14.html','text/html');$('#download-markdown').onclick=()=>download(data.reviewMarkdown,'data-plugin-standalone-review-2026-09-14.md','text/markdown');
  $('#all-sources').onclick=e=>openSources(Object.keys(data.sources).filter(k=>!k.startsWith('K:')),'Complete source ledger',e.currentTarget);
  // Keep the learning content printable without pulling the complete nested research document into print.
  let printState;window.addEventListener('beforeprint',()=>{printState=$$('.hood').map(d=>d.open);$$('.hood').forEach(d=>d.open=true);});window.addEventListener('afterprint',()=>{if(printState)$$('.hood').forEach((d,i)=>d.open=printState[i]);printState=null;});
})();
