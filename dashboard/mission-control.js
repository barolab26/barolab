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
    window.renderAdpostAccounts?.(snapshot.revenue,snapshot.date);
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
    renderSubscriptionQuotas(snapshot);
    window.dispatchEvent(new CustomEvent('barolab-mission-control',{detail:snapshot}));
  }

  function formatResetTime(val) {
    if (!val) return '';
    const ms = typeof val === 'number' ? (val < 1e12 ? val * 1000 : val) : Date.parse(val);
    if (!Number.isFinite(ms)) return '';
    return new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false
    }).format(new Date(ms));
  }

  function barColor(pct) {
    if (pct === null || pct === undefined || !Number.isFinite(pct)) return '#94a3b8';
    if (pct <= 15) return '#ef4444';
    if (pct <= 35) return '#f59e0b';
    return '#10b981';
  }

  function escapeHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function renderMiniGauge(label, pct, subText) {
    const valTxt = pct !== null && pct !== undefined ? `${pct.toFixed(0)}%` : '—';
    const widthPct = pct !== null && pct !== undefined ? Math.max(0, Math.min(100, pct)) : 0;
    const color = barColor(pct);
    return `
      <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:6px;padding:3.5px 5.5px;min-width:0;">
        <div style="display:flex;align-items:baseline;justify-content:space-between;gap:3px;font-size:9px;line-height:1.2;">
          <span style="color:#64748b;font-weight:700;white-space:nowrap;">${label}</span>
          <strong style="color:#0f172a;font-size:10px;font-weight:900;white-space:nowrap;">${valTxt}${subText ? `<span style="font-size:8.5px;color:#64748b;font-weight:600;"> ${subText}</span>` : ''}</strong>
        </div>
        <div style="height:4px;background:#f1f5f9;border-radius:999px;overflow:hidden;margin-top:2.5px;">
          <span style="display:block;height:100%;width:${widthPct}%;background:${color};border-radius:999px;transition:width .25s ease;"></span>
        </div>
      </div>
    `;
  }

  function renderSubscriptionQuotas(snapshot) {
    const brains = snapshot.brains || {};
    const quotas = brains.quotas || {};
    const usage = brains.usage || {};
    const byModel = Object.values(usage.byModel || {});
    const totalCalls = byModel.reduce((s, m) => s + (m.calls || 0), 0);
    const totalTokens = byModel.reduce((s, m) => s + (m.inputTokens || 0) + (m.outputTokens || 0), 0);
    const kieBal = quotas.kie?.balance;
    const summaryParts = [
      `오늘 ${totalCalls.toLocaleString('ko-KR')}회`,
      `${(totalTokens / 1000000).toFixed(2)}M tok`
    ];
    if (typeof kieBal === 'number') summaryParts.push(`KIE ${kieBal.toFixed(1)}C`);
    text('bento-subscription-summary', summaryParts.join(' · '));

    const host = document.getElementById('bento-subscription-quotas');
    if (!host) return;

    const cards = [];
    const codexAccs = quotas.codexQuota?.accounts || [];
    codexAccs.forEach((acc, idx) => {
      const shortId = String(acc.email || `codex-${idx + 1}`).split('@')[0];
      const bucket = acc.buckets?.codex || Object.values(acc.buckets || {})[0] || {};
      const prim = bucket.primary || {};
      const sec = bucket.secondary || {};
      const used7d = typeof prim.usedPercent === 'number' ? prim.usedPercent : null;
      const rem7d = used7d !== null ? Math.max(0, Math.min(100, 100 - used7d)) : null;
      const used5h = typeof sec.usedPercent === 'number' ? sec.usedPercent : null;
      const rem5h = used5h !== null ? Math.max(0, Math.min(100, 100 - used5h)) : null;
      const credits = bucket.credits?.balance ? Number(bucket.credits.balance) : null;
      const resetTxt = formatResetTime(prim.resetsAt || sec.resetsAt);
      const isAct = Boolean(acc.usable && acc.isLastUsed);
      const badgeText = !acc.usable ? '점검필요' : (isAct ? '⚡ 활성' : '대기');
      const badgeStyle = !acc.usable
        ? 'color:#b91c1c;background:#fef2f2;border:1px solid #fecaca;'
        : (isAct
          ? 'color:#047857;background:#d1fae5;border:1px solid #6ee7b7;'
          : 'color:#475569;background:#f1f5f9;border:1px solid #cbd5e1;');
      const creditChip = credits
        ? `<span style="font-size:8.5px;font-weight:800;color:#0369a1;background:#e0f2fe;border-radius:4px;padding:0.5px 4px;white-space:nowrap;">${Math.round(credits).toLocaleString()}C</span>`
        : '';

      const planLabel = bucket.planType ? String(bucket.planType).toUpperCase() : 'PRO';
      const codexGaugeGrid = rem5h !== null
        ? `<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px;">
             ${renderMiniGauge('7일 잔여', rem7d, '')}
             ${renderMiniGauge('5시간 잔여', rem5h, '')}
           </div>`
        : `<div>
             ${renderMiniGauge(`7일 한도 잔여 (${planLabel})`, rem7d, credits ? `· ${Math.round(credits).toLocaleString()}C 보유` : '')}
           </div>`;

      cards.push(`
        <article style="background:${isAct ? '#f0fdf4' : '#f8fafc'};border:1px solid ${isAct ? '#86efac' : '#cbd5e1'};border-left:3px solid #10b981;border-radius:8px;padding:5.5px 7px;min-width:0;display:flex;flex-direction:column;gap:4px;">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:4px;">
            <div style="display:flex;align-items:center;gap:4px;min-width:0;">
              <span style="font-size:8.5px;font-weight:900;color:#ffffff;background:#10b981;border-radius:3.5px;padding:0.5px 3.5px;line-height:1.2;">CDX${idx + 1}</span>
              <strong style="font-size:10.5px;color:#0f172a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(acc.email || '')}">${escapeHtml(shortId)}</strong>
            </div>
            <div style="display:flex;align-items:center;gap:3px;flex-shrink:0;">
              ${creditChip}
              <span style="font-size:8.5px;font-weight:800;border-radius:4px;padding:0.5px 4px;white-space:nowrap;${badgeStyle}">${badgeText}</span>
            </div>
          </div>
          ${codexGaugeGrid}
          <div style="display:flex;justify-content:space-between;align-items:center;font-size:8.5px;color:#64748b;line-height:1.1;white-space:nowrap;">
            <span>🔄 리셋 ${resetTxt || '—'}</span>
            <span style="font-weight:700;color:#475569;">호출 ${(acc.callCount || 0).toLocaleString('ko-KR')}회</span>
          </div>
        </article>
      `);
    });

    const agyAccs = quotas.agy?.accounts || [];
    agyAccs.forEach((acc, idx) => {
      const shortId = String(acc.email || `gemini-${idx + 1}`).split('@')[0];
      const groups = acc.groups || [];
      const gemGroup = groups.find(g => /gemini/i.test(g.name)) || groups[0] || {};
      const claudeGroup = groups.find(g => /claude|gpt/i.test(g.name)) || groups[1] || {};
      const gem5h = (gemGroup.buckets || []).find(b => b.window === '5h')?.remainingPercent ?? null;
      const gemWk = (gemGroup.buckets || []).find(b => b.window === 'weekly')?.remainingPercent ?? null;
      const cl5h = (claudeGroup.buckets || []).find(b => b.window === '5h')?.remainingPercent ?? null;
      const clWk = (claudeGroup.buckets || []).find(b => b.window === 'weekly')?.remainingPercent ?? null;
      const gemPrimary = gemWk ?? gem5h;
      const clPrimary = clWk ?? cl5h;
      const resetAt = (gemGroup.buckets || [])[0]?.resetAt || (claudeGroup.buckets || [])[0]?.resetAt;
      const resetTxt = formatResetTime(resetAt);
      const isAct = Boolean(acc.usable && acc.isLastUsed);
      const badgeText = !acc.usable ? '점검필요' : (isAct ? '⚡ 활성' : '대기');
      const badgeStyle = !acc.usable
        ? 'color:#b91c1c;background:#fef2f2;border:1px solid #fecaca;'
        : (isAct
          ? 'color:#4338ca;background:#e0e7ff;border:1px solid #a5b4fc;'
          : 'color:#475569;background:#f1f5f9;border:1px solid #cbd5e1;');

      cards.push(`
        <article style="background:${isAct ? '#f5f3ff' : '#f8fafc'};border:1px solid ${isAct ? '#c4b5fd' : '#cbd5e1'};border-left:3px solid #6366f1;border-radius:8px;padding:5.5px 7px;min-width:0;display:flex;flex-direction:column;gap:4px;">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:4px;">
            <div style="display:flex;align-items:center;gap:4px;min-width:0;">
              <span style="font-size:8.5px;font-weight:900;color:#ffffff;background:#6366f1;border-radius:3.5px;padding:0.5px 3.5px;line-height:1.2;">AGY${idx + 1}</span>
              <strong style="font-size:10.5px;color:#0f172a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(acc.email || '')}">${escapeHtml(shortId)}</strong>
            </div>
            <span style="font-size:8.5px;font-weight:800;border-radius:4px;padding:0.5px 4px;white-space:nowrap;flex-shrink:0;${badgeStyle}">${badgeText}</span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px;">
            ${renderMiniGauge('Gemini', gemPrimary, gem5h !== null && gemWk !== null && gem5h !== gemWk ? `(5h ${gem5h.toFixed(0)}%)` : '')}
            ${renderMiniGauge('Claude·GPT', clPrimary, cl5h !== null && clWk !== null && cl5h !== clWk ? `(5h ${cl5h.toFixed(0)}%)` : '')}
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;font-size:8.5px;color:#64748b;line-height:1.1;white-space:nowrap;">
            <span>🔄 리셋 ${resetTxt || '—'}</span>
            <span style="font-weight:700;color:#475569;">호출 ${(acc.callCount || 0).toLocaleString('ko-KR')}회</span>
          </div>
        </article>
      `);
    });

    const brainRows = snapshot.brainDisplay?.rows || [];
    const mappingRowText = brainRows.find(r => r.includes('@팀장') || r.includes('현재 두뇌')) || '';
    const mappingBanner = mappingRowText
      ? `<div style="grid-column:1 / -1;display:flex;align-items:center;justify-content:space-between;gap:6px;background:#f8fafc;border:1px dashed #cbd5e1;border-radius:6px;padding:3px 7px;font-size:9px;color:#475569;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(mappingRowText)}">
           <span style="font-weight:800;color:#334155;">🧠 배정</span>
           <span style="font-weight:700;color:#0f172a;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(mappingRowText.replace(/^현재 두뇌\s*\|\s*/, ''))}</span>
         </div>`
      : '';

    if (cards.length) {
      host.innerHTML = cards.join('') + mappingBanner;
    }
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
