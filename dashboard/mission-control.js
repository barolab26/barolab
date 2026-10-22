/* Both screens render the same versioned hub projection; polling never overlaps. */
(() => {
  'use strict';
  const titles = ['① 수익 · $100/day', '② AI 호출 · 크레딧', '③ 우분투 격리 크롬', '④ 오늘 발행 진행', '⑤ 크루 · Vault', '⑥ 완료 · 복구'];
  const host = document.createElement('section');
  host.id = 'mission-control'; host.setAttribute('aria-label', 'EGO 공용 실시간 관제');
  host.innerHTML = '<header><strong>EGO MISSION CONTROL</strong> <small id="mission-revision">연결 중</small></header><div class="mission-panels"></div>';
  const style = document.createElement('style');
  style.textContent = '#mission-control{margin:12px;padding:12px;background:#07152a;color:#fff;border:2px solid #22d3ee;border-radius:12px}#mission-control header{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}.mission-panels{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr));gap:10px;margin-top:10px}.mission-panel{padding:10px;border:1px solid #38bdf8;border-radius:8px;min-width:0}.mission-panel:nth-child(2n){border-color:#e879f9}.mission-panel h3{color:#fde047;font-size:14px;margin:0 0 6px}.mission-panel p{font-size:12px;line-height:1.6;margin:0;overflow-wrap:anywhere}.mission-alert{color:#fff;background:#b91c1c}';
  document.head.append(style);
  const main = document.querySelector('main') || document.body;
  main.prepend(host);
  const panels = titles.map(title => {
    const panel=document.createElement('article');panel.className='mission-panel';
    const heading=document.createElement('h3');heading.textContent=title;panel.append(heading);
    const content=document.createElement('div');panel.append(content);
    host.querySelector('.mission-panels').append(panel);return content;
  });
  const text = (id,value) => {const el=document.getElementById(id);if(el)el.textContent=value;};
  function apply(snapshot) {
    window.BaroLabMissionControl = snapshot;
    const age=Math.max(0,Math.floor((Date.now()-Date.parse(snapshot.generatedAt))/1000));
    text('mission-revision',`${snapshot.date} KST · ${snapshot.revision.slice(0,8)} · ${age}초 전`);
    host.dataset.revision=snapshot.revision;
    snapshot.panels.forEach((rows,index) => {
      const fragment=document.createDocumentFragment();
      for(const row of rows) {const p=document.createElement('p');p.textContent=row;if(/ALERT|BLOCKED|OFFLINE/.test(row))p.className='mission-alert';fragment.append(p);}
      panels[index].replaceChildren(fragment);
    });
    const cf=snapshot.channels.find(r=>r.id==='cf');
    const nv=snapshot.channels.find(r=>r.id==='naver');
    if(cf) {
      const label=`${cf.done ?? '—'}/${cf.target}편`;
      text('val-pub-cf',label);text('cf-master-gauge-pct',`${label} (${Math.round((cf.done||0)/cf.target*100)}%)`);
      text('cf-summary-completed-count',`${cf.done ?? '—'}건`);
      text('cf-summary-waiting-count',`${Math.max(0,cf.target-(cf.done||0))}건`);
      for(const id of ['bar-pub-cf','cf-master-gauge-fill']){const el=document.getElementById(id);if(el)el.style.width=`${Math.min(100,(cf.done||0)/cf.target*100)}%`;}
    }
    if(nv) {text('val-pub-naver',`${nv.done ?? '—'}/${nv.target} 공개 · 예약 ${nv.reserved ?? 0}`);text('nv-summary-total-progress',`${nv.done ?? '—'}/${nv.target} 공개 · 예약 ${nv.reserved ?? 0}`);}
    for(const account of snapshot.naverAccounts || []) {
      const slots=account.slots.filter(s=>s.publicationDate===snapshot.date);
      const published=slots.filter(s=>s.publicPublicationVerified===true).length;
      const reserved=slots.filter(s=>s.publicationStatus==='reserved').length;
      text(`mini-count-${account.accId}`,String(published+reserved));
      text(`mini-status-${account.accId}`,`공개 ${published} · 예약 ${reserved}`);
      const battery=document.getElementById(`nv-batt-${account.accId}`);
      if(battery)Array.from(battery.children).forEach((cell,index)=>{
        cell.className='batt-cell'+(index<published?' filled':index<published+reserved?' reserved':'');
        cell.textContent=index>=published && index<published+reserved?'✓':'';
      });
    }
    const done=snapshot.channels.reduce((sum,r)=>sum+(r.done||0),0),target=snapshot.channels.reduce((sum,r)=>sum+r.target,0);
    text('gauge-pub-pct',`${Math.round(done/target*100)}%`);
    for(const [id,value,max] of [['ring-pub-cf',cf?.done||0,16],['ring-pub-naver',nv?.done||0,7]]) {
      const ring=document.getElementById(id);
      if(ring){const length=id==='ring-pub-cf'?219.9:157.1;ring.style.strokeDashoffset=String(length*(1-Math.min(1,value/max)));}
    }
    const goal=document.querySelector('#kpi-todo-val')?.closest('.pillar');
    if(goal)goal.dataset.publicationTarget=String(target);
    text('kpi-todo-val',`${done}/${target}편`);text('kpi-todo-badge',`${done}/${target} 공개 발행`);
    text('kpi-todo-desc',snapshot.channels.map(r=>`${r.name} ${r.done ?? '—'}/${r.target}`).join(' · '));
    for(const row of snapshot.crew) {
      text(`crew-state-${row.role}`,`${row.state} · ${row.model || '모델 대기'}`);
      const el=document.getElementById(`crew-card-${row.role}`);
      if(el){el.classList.toggle('is-working',row.state==='RUNNING');el.title=row.action||'';}
    }
    window.dispatchEvent(new CustomEvent('barolab-mission-control',{detail:snapshot}));
  }
  window.applyMissionControl = () => {if(window.BaroLabMissionControl)apply(window.BaroLabMissionControl);};
  let lastRevision='';
  async function poll() {
    try {
      const response=await fetch('/api/mission-control',{cache:'no-store',signal:AbortSignal.timeout(2500)});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const snapshot=await response.json();
      if(snapshot.schema!=='barolab-mission-control-v2')throw new Error('스냅샷 규격 오류');
      if(snapshot.revision!==lastRevision){apply(snapshot);lastRevision=snapshot.revision;}
      else text('mission-revision',`${snapshot.date} KST · ${snapshot.revision.slice(0,8)} · ${Math.max(0,Math.floor((Date.now()-Date.parse(snapshot.generatedAt))/1000))}초 전`);
    } catch(error) {text('mission-revision','관제 연결 지연 · 마지막 수신 기록 유지');}
    setTimeout(poll,1000);
  }
  poll();
})();
