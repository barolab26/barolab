/* Both screens render the same versioned hub projection; polling never overlaps. */
(() => {
  'use strict';
  const text = (id,value) => {const el=document.getElementById(id);if(el)el.textContent=value;};
  function apply(snapshot) {
    window.BaroLabMissionControl = snapshot;
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
    const kin=snapshot.channels.find(r=>r.id==='kin');
    const threads=snapshot.channels.find(r=>r.id==='threads');
    if(kin) {
      text('overview-kin-verified',`${kin.done ?? '—'} / ${kin.target}건`);
      text('gauge-kin-pct',`${Math.round((kin.done||0)/kin.target*100)}%`);
      text('overview-kin-remaining',`${Math.max(0,kin.target-(kin.done||0))}건`);
    }
    if(threads) {
      text('bento-threads-today',`${threads.done ?? '—'} / ${threads.target}건`);
      text('gauge-threads-pct',`${Math.round((threads.done||0)/threads.target*100)}%`);
    }
    for(const [row,id,ring,length] of [[kin,'bar-kin-verified','ring-kin-quota',144.5],[threads,'bar-threads-today','ring-threads-quota',144.5]]) {
      if(!row)continue;
      const ratio=Math.min(1,(row.done||0)/row.target),bar=document.getElementById(id),circle=document.getElementById(ring);
      if(bar)bar.style.width=`${ratio*100}%`;
      if(circle)circle.style.strokeDashoffset=String(length*(1-ratio));
    }
    if(window.renderCF16Grid)window.renderCF16Grid();
    const revenueView=window.BaroLabRevenue;
    if(revenueView && snapshot.revenue) {
      for(const [category,id,currency] of [['adsense','adsense','USD'],['adpost','adpost','KRW'],['affiliate','affiliate','KRW']]) {
        const period=revenueView.categoryPeriod(snapshot.revenue,category,'today',snapshot.date);
        text(`val-rev-${id}`,revenueView.moneyText(period));
        if(category==='adsense') {
          const amount=revenueView.currencyValue(period,currency);
          text('gauge-rev-pct',amount===null?'—':`${Math.min(100,amount).toFixed(1)}%`);
          text('metric-revenue-value',revenueView.moneyText(period));
          const arc=document.getElementById('arc-revenue-goal');
          if(arc)arc.style.strokeDashoffset=String(119.4*(1-Math.min(1,(amount||0)/100)));
        }
      }
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
    text('gauge-mem-sub',`노드 ${snapshot.vault.nodes}개`);
    text('bento-memory-node-pill',`시냅스 엣지 ${snapshot.vault.edges}개 · 해결 ${snapshot.vault.episodes}회`);
    for(const row of snapshot.crew) {
      text(`crew-state-${row.role}`,`${row.state} · ${row.model || '모델 대기'}`);
      const el=document.getElementById(`crew-card-${row.role}`);
      if(el){el.classList.toggle('is-working',row.state==='RUNNING');el.title=[row.action,row.lastActivity && new Date(row.lastActivity).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})].filter(Boolean).join(' · ');}
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

    } catch(error) { /* Keep the last received card values during a disconnect. */ }
    setTimeout(poll,1000);
  }
  poll();
})();
