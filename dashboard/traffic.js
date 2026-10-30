/* Domain reports: users deduplicated per period; channel percentages use sessions. */
(function () {
  'use strict';
  const params = new URLSearchParams(location.search);
  let data = null, selected = params.get('domain') || '',
    period = ['day','week','month','today'].includes(params.get('period')) ? params.get('period') : 'month',
    engine = ['google','naver','bing'].includes(params.get('engine')) ? params.get('engine') : 'google';
  const $ = id => document.getElementById(id);
  const set = (id, value) => { if ($(id)) $(id).textContent = value; };
  const number = value => value == null ? '미수집' : Number(value).toLocaleString('ko-KR');
  const kstDay = () => new Date(Date.now() + 9 * 3600000).toISOString().slice(0,10);
  const currentReport = report => report?.start === kstDay() && report?.end === kstDay();
  const names = { search:'검색', external:'외부 원시 세션', direct:'직접', paid:'광고', other:'기타' };
  function coverage(analysis, selectedPeriod = 'month') {
    const result = { ga4: 0, google: 0, ga4Partial: 0, googlePartial: 0 };
    if (selectedPeriod === 'today' && analysis.today > kstDay()) return result;
    for (const record of analysis.sites || []) {
      for (const key of ['ga4', 'google']) {
        const source = record[key] || {};
        const report = source.periods?.[key === 'google' && selectedPeriod === 'today' ? 'day' : selectedPeriod];
        if (source.stale || !['collected','partial'].includes(source.status) || !report?.start || !report?.end) continue;
        if (key === 'ga4' && selectedPeriod === 'today' && !currentReport(report)) continue;
        result[key]++;
        if (source.status === 'partial' || report.partialPeriod || report.limited || report.sourceLimited) result[`${key}Partial`]++;
      }
    }
    return result;
  }
  function cell(row, text, tag = 'td') {
    const node = document.createElement(tag); node.textContent = text;
    if (tag === 'th') node.scope = 'row';
    row.appendChild(node); return node;
  }
  function share(report, kind) {
    if (!report || report.sourceLimited || !report.sourceReconciled) return '미확정';
    if (!report.sessions) return '0회';
    return `${number(report.mix[kind])}회 · ${(100 * report.mix[kind] / report.sessions).toFixed(1)}%`;
  }
  function choose(domain) {
    selected = domain; if ($('traffic-domain')) $('traffic-domain').value = domain;
    render();
  }
  function render() {
    if (!data) return;
    const sites = data.sites || [];
    renderOverview();
    renderNaver();
    const record = sites.find(r => r.site.site_id === selected);
    const health = coverage(data, period);
    const partial = health.ga4Partial + health.googlePartial;
    set('traffic-connected', `선택 기간 · CF 방문자 ${health.ga4}/${data.expectedDomains}개 · Google 검색 보고서 ${health.google}/${data.expectedDomains}개 현재 확인${partial ? ` · 일부 제한 ${partial}개 보고서` : ''}`);
    set('traffic-collected', data.checkedAt ? `수집 실행 ${new Date(data.checkedAt).toLocaleString('ko-KR', {timeZone:'Asia/Seoul'})} · 30분마다 수집` : '통계 원천 수집 대기');
    const table = $('traffic-domains');
    if (!table) return;
    table.replaceChildren();
    const ordered = [...sites].sort((a,b) => (b.ga4?.periods?.month?.users ?? -1) - (a.ga4?.periods?.month?.users ?? -1));
    for (const site of ordered) {
      const row = document.createElement('tr');
      if (site.site.site_id === selected) row.className = 'traffic-selected';
      const first = cell(row, '', 'th');
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = site.site.site_id; button.onclick = () => choose(site.site.site_id);
      button.setAttribute('aria-pressed', String(site.site.site_id === selected)); first.appendChild(button);
      const state = document.createElement('small');
      state.textContent = site.ga4?.status === 'error' ? '연결 실패 · 이전 값' : site.ga4?.stale ? '수집 지연' : site.ga4?.status === 'partial' ? '일부 데이터 제한' : 'GA4 · 잠정 집계'; first.appendChild(state);
      for (const key of ['day','week','month']) {
        const value = site.ga4?.periods?.[key];
        const node = cell(row, value ? `${number(value.users)}명${value.limited ? ' (일부)' : ''}` : '미수집');
        node.title = value ? `${value.start} ~ ${value.end} · 한국 시간` : site.ga4?.reason || '통계 미연결';
      }
      const candidate = site.ga4?.periods?.[period];
      const report = period === 'today' && !currentReport(candidate) ? null : candidate;
      cell(row, share(report, 'search')); cell(row, share(report, 'external'));
      const search = site.google?.periods?.[period === 'today' ? 'day' : period];
      const queries = search?.queries || [];
      cell(row, search ? `${number(search.impressions)}회 노출 · ${number(queries.length)}개 검색어 행` : '보고서 미연결');
      table.appendChild(row);
    }
    if (!record) return;
    const ga = record.ga4 || {}, candidate = ga.periods?.[period];
    const report = period === 'today' && !currentReport(candidate) ? null : candidate;
    set('traffic-domain-title', `${selected} · 유입 분석`);
    set('traffic-range', report ? `${report.start} ~ ${report.end} · 한국 시간 · ${period === 'today' ? '오늘 집계 중' : '잠정 집계'}` : ga.reason || 'GA4 미연결');
    set('traffic-users', report ? `${number(report.users)}명` : '미수집');
    set('traffic-sessions', report ? `${number(report.sessions)}회` : '미수집');
    set('traffic-pageviews', report ? `${number(report.pageViews)}회` : '미수집');
    set('traffic-source-warning', ga.status === 'error' || ga.stale ? `${ga.reason || '수집 지연'} · 마지막 성공 ${ga.checkedAt || '없음'}`
      : report?.limited || report?.sourceLimited || (report && !report.sourceReconciled) ? '통계 제한 또는 유입 합계 불일치 · 비중을 확정하지 않습니다.' : '방문자: 기간 내 중복 제거 · 유입 비중: 세션 기준');
    const mix = $('traffic-mix'); mix.replaceChildren();
    for (const [kind,label] of Object.entries(names)) {
      const box = document.createElement('div'); box.className = `traffic-mix-item traffic-${kind}`;
      const title = document.createElement('span'); title.textContent = label;
      const value = document.createElement('strong'); value.textContent = share(report, kind);
      box.append(title,value); mix.appendChild(box);
    }
    const sources = $('traffic-sources'); sources.replaceChildren();
    for (const source of report?.sources || []) {
      const row = document.createElement('tr'); cell(row, source.source); cell(row, source.medium);
      cell(row, names[source.kind]); cell(row, `${number(source.sessions)}회`); sources.appendChild(row);
    }
    if (!sources.children.length) { const row=document.createElement('tr'); const node=cell(row, report ? '해당 기간에 관측된 유입 없음' : '유입 보고서 미수집'); node.colSpan=4; sources.appendChild(row); }
    // Replace the old ambiguous Naver-origin funnel with explicitly attributed external sessions.
    const attribution = report?.sourceAttribution;
    const canonicalKeys = ['naver_blog','naver_kin','naver_cafe','threads'];
    const countKnown = value => Number.isSafeInteger(value) && value >= 0;
    const attributed = ga.status !== 'error' && !ga.stale && !report?.limited && !report?.sourceLimited && report?.sourceReconciled === true
      && attribution?.status === 'collected' && countKnown(attribution.qualifiedExternalSessions)
      && canonicalKeys.every(key => countKnown(attribution.canonicalExternalSessions?.[key]));
    const canonicalLabels = {naver_blog:'네이버 블로그',naver_kin:'지식iN',naver_cafe:'카페',threads:'Threads'};
    const exclusionLabels = {local:'로컬',self:'자기 사이트',internal:'내부 출처'};
    const exclusionText = Object.entries(exclusionLabels).map(([key,label]) =>
      `${label} ${attributed && countKnown(attribution.exclusions?.[key]) ? number(attribution.exclusions[key]) + '회' : '—'}`).join(' · ');
    const qEl = $('traffic-qualified-sources');
    if (qEl) {
      qEl.textContent = `외부 유입(${selected}): ` + Object.entries(canonicalLabels).map(([key,label]) => `${label} ${attributed ? number(attribution.canonicalExternalSessions[key]) + '회' : '—'}`).join(' · ');
      qEl.title = `외부 원시 세션: ${report && countKnown(report.mix?.external) ? number(report.mix.external) + '회' : '미확정'} | 내부 제외 후: ${attributed ? number(attribution.qualifiedExternalSessions) + '회' : '미확정'} | 제외(${exclusionText})`;
    }
    // Aggregate 16 CF domains external inbound for the Tab 2 right-column summary card
    const extTotals = { naver_blog: 0, naver_kin: 0, naver_cafe: 0, threads: 0, rawExternal: 0, qualified: 0 };
    for (const sRec of sites) {
      const sRep = sRec.ga4?.periods?.[period === 'today' ? 'day' : period];
      if (!sRep) continue;
      if (countKnown(sRep.mix?.external)) extTotals.rawExternal += sRep.mix.external;
      const sAttr = sRep.sourceAttribution;
      if (sAttr?.status === 'collected') {
        if (countKnown(sAttr.qualifiedExternalSessions)) extTotals.qualified += sAttr.qualifiedExternalSessions;
        for (const k of canonicalKeys) {
          if (countKnown(sAttr.canonicalExternalSessions?.[k])) extTotals[k] += sAttr.canonicalExternalSessions[k];
        }
      }
    }
    set('ext-inbound-kin', `${number(extTotals.naver_kin)}세션`);
    set('ext-inbound-threads', `${number(extTotals.threads)}세션`);
    set('ext-inbound-blog', `${number(extTotals.naver_blog)}세션`);
    set('ext-inbound-total', `외부유입 총 ${number(extTotals.qualified || extTotals.rawExternal)}세션`);
    set('metric-bridge-label', `${selected} · 내부 출처 제외 네이버 세션`);
    const naverSessions = attributed ? ['naver_blog','naver_kin','naver_cafe'].reduce((sum,key) => sum + attribution.canonicalExternalSessions[key], 0) : null;
    set('metric-bridge-landings', naverSessions === null ? '미확정' : `${number(naverSessions)}회`);
    set('metric-traffic-summary', `선택 기간 · CF ${health.ga4}/${data.expectedDomains}개 GA4 현재 확인 · 도메인별 방문자/검색 보고서 기준`);
    renderSearch(record);
    renderTrend(record);
  }
  function renderOverview() {
    if (!$('rank-overview')) return;
    const ranking = data.rankings?.[period === 'today' ? 'day' : period];
    const domains = data.sites || [], naver = data.naverBlogs || [], today = kstDay();
    function visitors(records, cf) {
      const known = records.filter(r => {
        if (data.today > today) return false;
        const source = cf ? r.ga4 || {} : r;
        const value = cf ? source.periods?.today?.users : source.days?.[today];
        return !source.stale && ['collected','partial'].includes(source.status) && Number.isSafeInteger(value)
          && (cf ? currentReport(source.periods?.today) && !source.periods.today.limited : source.date === today);
      });
      const value = known.length ? known.reduce((sum,r)=>sum+(cf?r.ga4.periods.today.users:r.days[today]),0) : null;
      return {value,known:known.length};
    }
    const cf = visitors(domains,true), nv = visitors(naver,false);
    set('overview-today-cf',cf.value==null?'미수집':`${number(cf.value)}명`);
    set('overview-today-naver',nv.value==null?'미수집':`${number(nv.value)}명`);
    set('overview-visitors-coverage',`CF ${cf.known}/${data.expectedDomains || 16} · 네이버 ${nv.known}/${data.expectedNaverBlogs || 5}개 수집 · 오늘 ${today}${cf.known || nv.known ? ' 집계 중' : ' 미수집'}${data.today !== today ? ` · 자료 기준 ${data.today || '미확인'} · 갱신 필요` : ''}`);
    for (const limit of [5,10,50,100]) {
      const band=ranking?.bands?.find(b=>b.limit===limit);
      set(`rank-${limit}`,ranking?.connectedDomains ? `${number(band?.observations)}행` : '미수집');
      set(`rank-${limit}-scope`,band && ranking?.connectedDomains ? `${band.domains}개 도메인 · 노출 10회 이상 ${band.observations-band.lowSample}개` : 'Google 보고서 수집 대기');
      const link=$(`rank-${limit}-link`);if(link)link.href=`growth.html?period=${period}&rank=${limit}&scope=all#traffic-keyword-status`;
    }
    const ranges = ranking?.ranges || [];
    const start = ranges.map(r=>r[0]).sort()[0], end=ranges.map(r=>r[1]).sort().at(-1);
    const periodText = ranges.map(r=>`${r[0]} ~ ${r[1]}`).join(' / ');
    set('rank-source',ranking ? `Google 평균 게재순위 · ${periodText || '기간 미확인'} (PT) · 현재 수집 ${ranking.connectedDomains}/${ranking.expectedDomains}개 도메인 · 검색어 관측 행, 글 수 아님${ranking.partialPeriods ? ` · ${ranking.partialPeriods}개는 기간 일부` : ''}` : 'Google 검색 보고서 수집 대기');
    set('rank-highlight-selection', ranking?.highlightSelection || '도메인별 대표 관측 우선 · 최대 5행');
    const protectedAccount=domains.find(r=>r.naver?.status==='protected')?.naver;
    set('rank-naver-status',protectedAccount ? `네이버 순위 미측정 · ${protectedAccount.reason}` : '네이버 순위 미측정 · 실제 검색결과 측정 연결 필요');
    const body=$('rank-highlights');body.replaceChildren();
    for (const item of ranking?.highlights || []) {
      const row=document.createElement('tr');cell(row,item.query);
      cell(row,Number(item.position).toFixed(1));cell(row,number(item.impressions));cell(row,number(item.clicks));
      const link=document.createElement('a');link.href=`growth.html?domain=${encodeURIComponent(item.domain)}&period=${period}#traffic-keyword-status`;
      link.textContent=item.domain;cell(row,'').appendChild(link);body.appendChild(row);
    }
    if (!body.children.length) {const row=document.createElement('tr');const node=cell(row,ranking?.connectedDomains?'선택 기간에 공개된 100위 이내 관측 없음':'검색 보고서 미수집');node.colSpan=5;body.appendChild(row);}
  }
  function renderNaver() {
    const body=$('growth-naver-counters');if(!body)return;body.replaceChildren();
    const today=kstDay(), yesterday=new Date(Date.parse(today+'T00:00:00Z')-86400000).toISOString().slice(0,10);
    for(const item of data.naverBlogs || []) {
      const row=document.createElement('tr'),fresh=!item.stale&&item.status==='collected'&&data.today<=today&&item.date<=today;
      const link=document.createElement('a');link.href=item.site.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=item.site.site_id.replace('naver:','');cell(row,'').appendChild(link);
      cell(row,fresh?number(item.days?.[today]):'미수집');cell(row,fresh?number(item.days?.[yesterday]):'미수집');
      const dates=Array.from({length:5},(_,i)=>new Date(Date.parse(today+'T00:00:00Z')-i*86400000).toISOString().slice(0,10));
      cell(row,fresh&&dates.every(d=>Number.isSafeInteger(item.days[d]))?number(dates.reduce((s,d)=>s+item.days[d],0)):'미수집');
      cell(row,(fresh?'공개 카운터 수집됨':item.reason || '수집 지연') + (data.today !== today ? ` · 자료 기준 ${data.today || '미확인'} · 갱신 필요` : ''));body.appendChild(row);
    }
  }
  function sourceDateLabel(value) {
    if(typeof value !== 'string' || !value.trim()) return '날짜 미확인';
    const match=value.match(/^\/Date\((-?\d+)(?:[+-]\d{4})?\)\/$/);
    const parsed=match ? new Date(Number(match[1])) : /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value) ? new Date(value) : null;
    return parsed && Number.isFinite(parsed.getTime()) ? `${parsed.toISOString().slice(0,10)} (UTC)` : `원문 ${value.slice(0,100)}`;
  }
  function renderSearch(record) {
    let source = record[engine] || {};
    const key = period === 'today' ? 'day' : period;
    let report = source.periods?.[key];
    const portal = engine !== 'google';
    if (portal && Array.isArray(source.queries) && source.checkedAt) {
      report = {...source, queries:source.queries.map(q=>({...q,position:engine==='naver' ? null : q.averageImpressionPosition ?? q.position ?? null,
        ctr:q.ctr ?? (q.ctrPercent == null ? null : q.ctrPercent/100)}))};
    }

    const allScope = $('traffic-keyword-scope')?.value === 'all';
    if (allScope && engine === 'google') {
      const reports = (data.sites || []).filter(r=>!r.google?.stale && ['collected','partial'].includes(r.google?.status) && r.google?.periods?.[key]);
      if (reports.length) {
        source = {source:`Google · 전체 CF ${reports.length}/${data.expectedDomains}개 도메인별 합계`,timezone:'America/Los_Angeles'};
        report = {start:reports.map(r=>r.google.periods[key].start).sort()[0],end:reports.map(r=>r.google.periods[key].end).sort().at(-1),
          partialPeriod:reports.some(r=>r.google.periods[key].partialPeriod),
          impressions:reports.reduce((s,r)=>s+r.google.periods[key].impressions,0),clicks:reports.reduce((s,r)=>s+r.google.periods[key].clicks,0),
          queries:reports.flatMap(r=>r.google.periods[key].queries.map(q=>({...q,domain:r.site.site_id})))};
      } else report=null;
    }
    const body = $('traffic-keywords'); body.replaceChildren();
    const rankValue = $('traffic-rank-limit')?.value || '0';
    const [minimumRank, limit] = rankValue.includes('-') ? rankValue.split('-').map(Number) : [0,Number(rankValue)];
    const minimum = Number($('traffic-min-impressions')?.value || 0);
    const queryText = ($('traffic-query-filter')?.value || '').trim().toLocaleLowerCase();
    const queries = [...(report?.queries || [])].filter(q=>
      (engine === 'naver' || !limit || (typeof q.position === 'number' && Number.isFinite(q.position) && q.position > 0 && q.position >= minimumRank && q.position <= limit)) && (q.impressions == null ? minimum === 0 : q.impressions >= minimum) && String(q.query || '').toLocaleLowerCase().includes(queryText))
      .sort((a,b) => b.clicks - a.clicks || b.impressions - a.impressions || a.position - b.position);
    set('traffic-keyword-status', report ? `${report.start} ~ ${report.end} · ${source.timezone} · ${source.source || ''} · ${report.partialPeriod ? '제공 가능한 기간만 집계 · ' : ''}${source.stale ? '이전 수집값 · ' : ''}${number(report.impressions)}회 노출 / ${number(report.clicks)}회 클릭 · 조건 ${queries.length}행${queries.length>100?' 중 상위 100행 표시':''}`
      : source.reason || (engine === 'bing' ? 'Bing 웹마스터 검색 보고서 미연결' : '검색 보고서 미연결'));
    const tipText = engine === 'google' ? '평균 게재순위는 고정 검색 순위가 아닙니다. 상위 검색어/URL만 제공되며 비공개 검색어는 제외됩니다.'
      : engine === 'naver' ? '네이버 검색 유입은 위 GA4에서 확인합니다. 서치어드바이저의 키워드/노출/클릭 보고서 기준입니다.'
      : 'Bing 웹마스터 보고서 연결 기준입니다.';
    if (portal) {
      const statusNames={partial:'일부 보고서',stale:'이전 확인 자료',collected:'보고서 확인',not_connected:'미연결',report_unavailable:'보고서 미제공',error:'조회 실패',backoff:'재시도 대기'};
      const checked=source.checkedAt ? new Date(source.checkedAt).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}) : '미확인';
      const scope=engine==='naver' ? source.period?.label || '서치어드바이저 제공 기간'
        : `등록 속성 ${source.property || '미확인'}`;
      const totals=engine==='naver' ? ` · 클릭 ${number(source.clicks)} · 노출 ${source.impressionsDisplay ? source.impressionsDisplay : number(source.impressions)}` : '';
      set('traffic-keyword-status',`${source.source || (engine==='naver'?'Naver Search Advisor':'Bing Webmaster')} · ${statusNames[source.status] || '미확인'}${source.stale?' · 수집 지연':''} · 확인 ${checked} · ${scope}${totals} · 조건 ${queries.length}행${queries.length>100?' (상위 100행)':''}`);
    }
    const tracking=record.keywordTracking || {}, observations=tracking.observations || [];
    const latestDate=observations.map(q=>q.date).filter(Boolean).sort().at(-1);
    const observed=observations.filter(q=>q.date===latestDate && q.status==='observed' && typeof q.position==='number' && Number.isFinite(q.position));
    const note=$('traffic-keyword-note');
    if(note) {
      note.textContent = `${record.site.site_id} 관심 키워드 추적: 대상 ${tracking.watchlist?.length ?? 0}개 중 관측 ${observed.length}개`;
      note.title = tipText;
    }
    const kwTip = $('traffic-keyword-tip');
    if (kwTip) kwTip.title = tipText;
    for (const query of queries.slice(0,100)) {
      const row = document.createElement('tr'); const queryCell=cell(row, query.query);
      if(engine==='bing') {
        const dateNote=document.createElement('small');dateNote.style.display='block';
        dateNote.textContent=`원천 날짜 ${sourceDateLabel(query.sourceDate)}`;queryCell.appendChild(dateNote);
      }
      cell(row, number(query.clicks)); cell(row, number(query.impressions));
      cell(row, query.ctr == null ? '—' : `${(query.ctr*100).toFixed(1)}%`);
      cell(row, query.position == null ? '미제공' : Number(query.position).toFixed(1));
      const link = document.createElement('a');
      const domain=query.domain || record.site.site_id;
      if (!query.page) { cell(row, allScope ? `${domain} · 페이지 미제공` : '보고서 미제공'); body.appendChild(row); continue; }
      try {
        const url=new URL(query.page);
        if (url.protocol==='https:' && [domain,`www.${domain}`].includes(url.hostname)) {
          link.href=url.href; link.target='_blank'; link.rel='noopener noreferrer';
          link.textContent=(allScope?domain:'')+decodeURIComponent(url.pathname); cell(row,'').appendChild(link);
        } else cell(row,'주소 미확인');
      } catch (_) { cell(row,'주소 미확인'); }
      body.appendChild(row);
    }
    if (!body.children.length) { const row=document.createElement('tr'); const node=cell(row, report ? '조건에 맞는 공개 검색어 없음' : source.reason || '검색어 보고서 미수집'); node.colSpan=6;body.appendChild(row); }
  }
  function renderTrend(record) {
    const target=$('traffic-trend'); if(!target) return; target.replaceChildren();
    const points=record.ga4?.daily || [], max=Math.max(1,...points.map(p=>p.users));
    for (const point of points) {
      const bar=document.createElement('div');bar.className='traffic-trend-day';
      bar.title=`${point.day}: ${number(point.users)}명`;
      const value=document.createElement('div');value.style.height=`${Math.max(2,point.users/max*80)}px`;
      const label=document.createElement('small');label.textContent=point.day.slice(5);
      bar.append(value,label);target.appendChild(bar);
    }
    if (!points.length) target.textContent='일별 방문자 보고서 미수집';
  }
  $('traffic-period')?.addEventListener('change',e=>{period=e.target.value;render();});
  $('traffic-domain')?.addEventListener('change',e=>choose(e.target.value));
  $('traffic-engine')?.addEventListener('change',e=>{engine=e.target.value;render();});
  for(const id of ['traffic-rank-limit','traffic-min-impressions','traffic-query-filter','traffic-keyword-scope']) $(id)?.addEventListener('input',render);
  if($('traffic-rank-limit') && ['5','10','50','100','11-50'].includes(params.get('rank'))) $('traffic-rank-limit').value=params.get('rank');
  if($('traffic-keyword-scope') && params.get('scope')==='all') $('traffic-keyword-scope').value='all';
  window.BaroLabTraffic = { coverage, getData: () => data, render(next) {
    data=next;
    if ($('traffic-period')) $('traffic-period').value=period;
    if ($('traffic-engine')) $('traffic-engine').value=engine;
    const select=$('traffic-domain');
    if (select) {
      select.replaceChildren();
      for (const record of data.sites || []) {
        const option=document.createElement('option');option.value=record.site.site_id;option.textContent=record.site.site_id;select.appendChild(option);
      }
      if (!(data.sites || []).some(r=>r.site.site_id===selected)) selected='baronote.kr';
      if (!(data.sites || []).some(r=>r.site.site_id===selected)) selected=data.sites?.[0]?.site.site_id || '';
      select.value=selected;
    }
    render();
    window.BaroLabTopKpi?.refresh();
  }, failed() {
    set('traffic-collected','보고서 조회 실패 · 화면에 남은 값은 이전 조회 결과입니다.');
    set('rank-source','보고서 조회 실패 · 아래 순위는 이전 조회 결과입니다.');
    set('overview-visitors-coverage','통계 조회 실패 · 이전 조회 결과');
  } };
})();
