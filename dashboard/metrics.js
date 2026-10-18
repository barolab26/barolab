/* Render collected evidence. Missing measurements stay unknown. */
(function () {
  'use strict';
  const set = (id, value) => {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  };
  const number = value => value == null ? '—' : Number(value).toLocaleString('ko-KR');
  const kstDay = () => new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10);
  const kstTime = value => new Date(value).toLocaleString('ko-KR', {timeZone:'Asia/Seoul',hour12:false});
  const labels = { collected: '수집됨', partial: '일부 확인', not_collected: '미연결 / 미확인',
    submitted: '요청 접수', received_pending_key_check: '키 확인 대기' };

  function renderSummaryCards(analysis) {
    const platform = document.body.dataset.summaryPlatform;
    if (!platform) return;
    const todayDate = kstDay();
    const shift = days => new Date(Date.parse(todayDate + 'T00:00:00Z') + days * 86400000).toISOString().slice(0,10);
    const expected = platform === 'cf' ? analysis.expectedDomains : analysis.expectedNaverBlogs;
    const records = platform === 'cf' ? analysis.sites || [] : analysis.naverBlogs || [];
    const integer = value => Number.isSafeInteger(value) && value >= 0;
    function total(key, days, offset) {
      let known = 0, value = 0;
      const end = shift(offset), start = shift(offset - days + 1);
      for (const record of records) {
        const source = platform === 'cf' ? record.ga4 || {} : record;
        if (analysis.today > todayDate || source.date > todayDate) continue;
        if (!['collected','partial'].includes(source.status) || source.stale || source.timezone !== 'Asia/Seoul') continue;
        if (platform === 'cf') {
          const report = source.periods?.[key];
          if (!report || report.limited || report.start !== start || report.end !== end || !integer(report.users)) continue;
          value += report.users;
        } else {
          if (key === 'today' && source.date !== todayDate) continue;
          const dates = Array.from({length:days},(_,i)=>shift(offset - i));
          if (!dates.every(day=>integer(source.days?.[day]))) continue;
          value += dates.reduce((sum,day)=>sum + source.days[day],0);
        }
        known++;
      }
      return {value:known ? value : null, known, expected};
    }
    const today = total('today',1,0), yesterday = total('day',1,-1);
    const text = report => report.value == null ? '미수집' : `${number(report.value)}명${report.known < report.expected ? ' (확인분)' : ''}`;
    set('summary-visitors-value',text(today));
    set('summary-visitors-coverage',(today.known ? `${today.known}/${expected}개 수집 · 오늘 집계 중` : '오늘 통계 미수집') + (analysis.today !== todayDate ? ` · 자료 기준 ${analysis.today || '미확인'} · 갱신 필요` : ''));
    set('summary-visitors-note',platform === 'cf' ? 'GA4 도메인별 합계 · 도메인 간 중복 포함' : '네이버 공개 카운터 · 블로그 간 중복 포함');
    set('summary-stat-day',text(yesterday));
    if (platform === 'cf') {
      set('summary-stat-week',text(total('week',7,-1)));
      set('summary-stat-month',text(total('month',30,-1)));
    } else {
      set('summary-stat-recent',text(total('recent',5,0)));
    }
    const checked = platform === 'cf' ? analysis.checkedAt : analysis.naverCheckedAt;
    set('summary-visitors-updated',checked ? `수집 ${kstTime(checked)} KST · 30분 간격` : '원천 수집 대기');
    const node = document.getElementById('summary-visitors-value');
    if (node) node.title = `${todayDate} (KST) · 날짜가 일치하고 현재 확인된 원천만 합산`;
  }

  const moneyText = period => {
    const values = Object.entries(period?.amounts || {}).map(([currency, value]) =>
      new Intl.NumberFormat('ko-KR', { style: 'currency', currency,
        minimumFractionDigits: currency === 'KRW' ? 0 : 2,
        maximumFractionDigits: currency === 'KRW' ? 0 : 2 }).format(Number(value)));
    return values.length ? values.join(' + ') : period?.status === 'pending' ? '집계 중'
      : period?.status === 'not_applicable' ? '해당 없음' : '미수집';
  };
  const periodKeys = ['throughYesterday', 'yesterday', 'today', 'month'];
  function revenueRow(label, periods, note) {
    const row = document.createElement('tr');
    const name = document.createElement('th');
    name.scope = 'row';
    name.textContent = label;
    if (note) {
      const small = document.createElement('small');
      small.textContent = note;
      name.appendChild(small);
    }
    row.appendChild(name);
    for (const key of periodKeys) {
      const cell = document.createElement('td');
      cell.textContent = moneyText(periods?.[key]);
      if (Object.keys(periods?.[key]?.amounts || {}).length) {
        const small = document.createElement('small');
        small.textContent = key === 'today' ? '예상 · 확인분' : '확인분';
        cell.appendChild(small);
      }
      row.appendChild(cell);
    }
    return row;
  }
  function renderRevenue(data) {
    const categories = data.categories || [];
    const today = kstDay(), current = data.today === today;
    const yesterday = new Date(Date.parse(today+'T00:00:00Z')-86400000).toISOString().slice(0,10);
    set('metric-revenue-value', moneyText(current ? data.totals?.today : null));
    set('metric-revenue-badge', !current ? '갱신 필요' : data.status === 'partial' ? '일부 원천 연결' : '원천 미연결');
    set('metric-revenue-source', 'USD · KRW 원래 통화 기준');
    set('metric-revenue-growth', '예상 수익 · 확인분');
    set('revenue-period', `${today.slice(0,7)} · 어제 ${yesterday} · 오늘 ${today} · 한국 시간${current ? '' : ` · 자료 기준 ${data.today || '미확인'} · 갱신 필요`}`);
    set('revenue-updated', data.checkedAt ? `최근 수집 실행 ${new Date(data.checkedAt).toLocaleString('ko-KR', {timeZone:'Asia/Seoul'})} · 30분마다 수집`
      : '수익 원천 수집 대기');
    const table = document.getElementById('revenue-overview');
    if (table) {
      table.replaceChildren();
      for (const category of categories) {
        const known = category.sources.filter(s => Object.keys(s.daily || {}).length);
        const notes = known.map(s => `${s.label} · ${s.scope}${s.lastReportDay ? ` · ${s.lastReportDay}까지` : ''}${s.status === 'error' ? ' · 연결 실패, 이전 값' : s.stale ? ' · 수집 지연' : ''}`);
        table.appendChild(revenueRow(category.label, current ? category.periods : null, notes.join(' / ') || '수익 보고서 미연결'));
      }
      const total = revenueRow('확인된 수익 합계', current ? data.totals : null, '미연결 원천 제외 · 통화별 합계');
      total.className = 'revenue-total';
      table.appendChild(total);
    }
    const sources = document.getElementById('revenue-sources');
    if (sources) {
      sources.replaceChildren();
      for (const category of categories) for (const source of category.sources) {
        const item = document.createElement('div');
        item.className = 'revenue-source';
        const title = document.createElement('strong');
        title.textContent = `${source.label} · ${data.month || '기간 미확인'} 수집분 ${moneyText(source.periods?.month)}`;
        const note = document.createElement('p');
        note.textContent = `${source.scope} · ${source.reason}${source.stale ? ' · 수집 지연' : ''}`;
        const time = document.createElement('small');
        time.textContent = source.checkedAt ? `확인 ${new Date(source.checkedAt).toLocaleString('ko-KR', {timeZone:'Asia/Seoul'})}` : '수집 대기';
        item.append(title, note, time);
        sources.appendChild(item);
      }
    }
    const history = document.getElementById('revenue-daily');
    if (history) {
      history.replaceChildren();
      for (const day of [...(data.daily || [])].reverse()) {
        const row = document.createElement('tr');
        const date = document.createElement('th');
        date.scope = 'row'; date.textContent = day.date;
        row.appendChild(date);
        for (const category of categories) {
          const cell = document.createElement('td');
          cell.textContent = moneyText(day.categories[category.id]);
          row.appendChild(cell);
        }
        history.appendChild(row);
      }
    }
  }

  let refreshBusy=false, lastMetrics=null, renderedDay=kstDay(), cfTopPostsPeriod='recent24h';
  function renderMiniBars(containerId, points, isCurrency = false) {
    const box = document.getElementById(containerId);
    if (!box) return;
    box.replaceChildren();
    if (!points || !points.length) {
      box.textContent = '일별 추이 미수집';
      return;
    }
    const maxVal = Math.max(isCurrency ? 0.01 : 1, ...points.map(p => Number(p.value) || 0));
    for (const pt of points) {
      const col = document.createElement('div');
      col.className = 'cf-mini-bar-col';
      const valNum = Number(pt.value) || 0;
      const labelFormatted = isCurrency ? `$${valNum.toFixed(2)}` : `${number(valNum)}${pt.unit || '세션'}`;
      col.title = `${pt.day}: ${labelFormatted}`;
      const fill = document.createElement('div');
      fill.className = 'cf-mini-bar-fill' + (isCurrency ? ' green' : '');
      const heightPx = valNum > 0 ? Math.max(5, Math.round((valNum / maxVal) * 34)) : 3;
      fill.style.height = `${heightPx}px`;
      if (valNum === 0) fill.style.opacity = '0.25';
      const lbl = document.createElement('span');
      lbl.className = 'cf-mini-bar-label';
      lbl.textContent = pt.day.slice(5).replace('-', '/');
      col.append(fill, lbl);
      box.appendChild(col);
    }
  }

  function renderCFPopularPosts(analysis) {
    const listBox = document.getElementById('cf-popular-posts-list');
    if (!listBox) return;
    const topPosts = analysis?.topPosts || {};
    const items = (topPosts[cfTopPostsPeriod] || []).slice(0, 5);
    listBox.replaceChildren();
    if (!items.length) {
      const empty = document.createElement('p');
      empty.style.cssText = 'padding:14px;color:#64748b;font-size:12px;';
      empty.textContent = '해당 기간에 집계된 게시물 유입이 없습니다.';
      listBox.appendChild(empty);
      return;
    }
    const maxMetric = Math.max(1, ...items.map(it => it.pageViews || it.sessions || 1));
    items.forEach((item, idx) => {
      const row = document.createElement('div');
      row.className = 'rank-row';
      const num = document.createElement('div');
      num.className = 'rank-num';
      num.textContent = String(idx + 1);
      const titleWrap = document.createElement('div');
      titleWrap.className = 'rank-title';
      const badge = document.createElement('span');
      badge.className = 'rank-domain-badge';
      badge.textContent = item.domain;
      const link = document.createElement('a');
      link.href = item.url || `https://www.${item.domain}${item.path}`;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = item.title || item.path;
      link.title = `[${item.domain}] ${item.title || item.path} (${item.sessions} 세션 · ${item.pageViews} PV)`;
      titleWrap.append(badge, link);
      const barBg = document.createElement('div');
      barBg.className = 'rank-bar-bg';
      const bar = document.createElement('div');
      bar.className = 'rank-bar';
      const pct = Math.max(12, Math.min(100, Math.round(((item.pageViews || item.sessions) / maxMetric) * 100)));
      bar.style.width = `${pct}%`;
      barBg.appendChild(bar);
      const val = document.createElement('div');
      val.className = 'rank-val';
      val.textContent = `${number(item.sessions)}세션 · ${number(item.pageViews)}뷰`;
      row.append(num, titleWrap, barBg, val);
      listBox.appendChild(row);
    });
    const periodLabel = cfTopPostsPeriod === 'recent24h' ? '최근 24시간(어제·오늘 실시간 합산)' : '최근 7일 누적';
    set('cf-popular-posts-note', `GA4 ${periodLabel} · ${topPosts.connectedDomains ?? 16}/${topPosts.expectedDomains ?? 16}개 CF 도메인 실측 · 클릭 시 해당 글로 이동`);
  }

  function renderCFTrendsAndTopPosts(data) {
    const analysis = data?.trafficAnalysis || {};
    const traffic = data?.traffic || {};
    const revenue = data?.revenue || {};
    const sites = analysis.sites || [];
    const today = kstDay();
    const shift = days => new Date(Date.parse(today + 'T00:00:00Z') + days * 86400000).toISOString().slice(0, 10);

    let todaySess = 0, yesterdaySess = 0, weekSess = 0, weekPv = 0, weekConnected = 0;
    let weekStart = null, weekEnd = null;
    const dailySessMap = {};
    for (const r of sites) {
      const ga = r.ga4 || {};
      if (!['collected', 'partial'].includes(ga.status)) continue;
      const pToday = ga.periods?.today;
      const pDay = ga.periods?.day;
      const pWeek = ga.periods?.week;
      if (pToday && pToday.end === today) todaySess += Number(pToday.sessions || 0);
      if (pDay) yesterdaySess += Number(pDay.sessions || 0);
      if (pWeek) {
        weekSess += Number(pWeek.sessions || 0);
        weekPv += Number(pWeek.pageViews || 0);
        weekConnected++;
        weekStart = pWeek.start;
        weekEnd = pWeek.end;
      }
      for (const d of ga.daily || []) {
        if (d.day) dailySessMap[d.day] = (dailySessMap[d.day] || 0) + Number(d.sessions || 0);
      }
    }
    const last7Days = Array.from({ length: 7 }, (_, i) => shift(i - 6));
    const sessionBars = last7Days.map(d => ({
      day: d,
      value: d === today && dailySessMap[d] == null ? todaySess : (dailySessMap[d] || 0),
      unit: '세션'
    }));
    const displaySessions = weekConnected ? weekSess : traffic.sessions;
    set('metric-cf-sessions', displaySessions == null ? '미수집' : `${number(displaySessions)} 세션`);
    const subBox = document.getElementById('metric-cf-submetrics');
    if (subBox) {
      subBox.innerHTML = `<span class="sub-chip">오늘 <strong>${number(todaySess)}</strong>세션</span>` +
        `<span class="sub-chip">어제 <strong>${number(yesterdaySess)}</strong>세션</span>` +
        `<span class="sub-chip">7일 <strong>${number(weekPv)}</strong> PV</span>`;
    }
    renderMiniBars('chart-cf-sessions', sessionBars, false);
    if (weekConnected && weekStart && weekEnd) {
      set('metric-cf-period', `${weekStart} ~ ${weekEnd} (Asia/Seoul) · ${weekConnected}/${analysis.expectedDomains || 16}개 도메인 기준`);
    } else if (traffic.period) {
      const p = traffic.period;
      set('metric-cf-period', `${p[0]} ~ ${p[1]} (${p[2]}) · ${traffic.connectedSites}/${traffic.expectedSites}개 도메인 기준`);
    }

    const adsenseCat = (revenue.categories || []).find(c => c.id === 'adsense');
    const adsenseSources = adsenseCat?.sources || [];
    const dailyUsdMap = {};
    for (const src of adsenseSources) {
      if (src.currency === 'USD' && src.daily) {
        for (const [d, val] of Object.entries(src.daily)) {
          dailyUsdMap[d] = (dailyUsdMap[d] || 0) + Number(val || 0);
        }
      }
    }
    const revBars = last7Days.map(d => ({ day: d, value: dailyUsdMap[d] || 0 }));
    const weekUsd = revBars.reduce((acc, b) => acc + b.value, 0);
    const monthUsd = adsenseCat?.periods?.month?.amounts?.USD != null ? Number(adsenseCat.periods.month.amounts.USD) : null;
    const todayUsd = dailyUsdMap[today] ?? (adsenseCat?.periods?.today?.amounts?.USD != null ? Number(adsenseCat.periods.today.amounts.USD) : 0);
    const yesterdayUsd = dailyUsdMap[shift(-1)] ?? (adsenseCat?.periods?.yesterday?.amounts?.USD != null ? Number(adsenseCat.periods.yesterday.amounts.USD) : 0);

    set('metric-cf-revenue', monthUsd != null ? `$${weekUsd.toFixed(2)} (7일)` : '미수집');
    const revSubBox = document.getElementById('metric-cf-revenue-sub');
    if (revSubBox && monthUsd != null) {
      revSubBox.innerHTML = `<span class="sub-chip">오늘 <strong>$${todayUsd.toFixed(2)}</strong></span>` +
        `<span class="sub-chip">어제 <strong>$${yesterdayUsd.toFixed(2)}</strong></span>` +
        `<span class="sub-chip">${(revenue.month || today.slice(0, 7)).slice(5)}월 누적 <strong>$${monthUsd.toFixed(2)}</strong></span>`;
    }
    renderMiniBars('chart-cf-revenue', revBars, true);
    const sjSource = adsenseSources.find(s => s.id === 'adsense-sj') || adsenseSources[0];
    if (sjSource && Object.keys(dailyUsdMap).length) {
      set('metric-cf-revenue-note', `${sjSource.scope || 'SJ · CF 애드센스'} · 일별 API 실측 집계`);
    }

    renderCFPopularPosts(analysis);
  }

  document.getElementById('cf-top-posts-tabs')?.addEventListener('click', e => {
    const btn = e.target.closest('button[data-period]');
    if (!btn) return;
    cfTopPostsPeriod = btn.dataset.period;
    for (const b of document.querySelectorAll('#cf-top-posts-tabs button')) {
      b.classList.toggle('active', b === btn);
    }
    if (lastMetrics) renderCFPopularPosts(lastMetrics.trafficAnalysis || {});
  });

  function renderTrafficCoverage(analysis) {
    const today=kstDay();
    const sourceCoverage = window.BaroLabTraffic?.coverage(analysis, 'today');
    const currentCF = sourceCoverage?.ga4 ?? (analysis.sites || []).filter(r => !r.ga4?.stale && ['collected','partial'].includes(r.ga4?.status) && r.ga4?.periods?.today?.start === today && r.ga4?.periods?.today?.end === today).length;
    const naverCollected = (analysis.naverBlogs || []).filter(r=>r.status==='collected'&&!r.stale&&r.date===today&&Number.isSafeInteger(r.days?.[today])).length;
    set('metric-traffic-summary', `오늘 ${today} · GA4 CF ${currentCF}/${analysis.expectedDomains || 16}개 · 네이버 공개 방문자 ${naverCollected}/${analysis.expectedNaverBlogs || 5}개 현재 확인${analysis.today !== today ? ` · 자료 기준 ${analysis.today || '미확인'} · 갱신 필요` : ''} · 방문자·유입·검색어 상세는 성장 대시보드에서 확인`);
  }
  function refreshDay() {
    const today=kstDay();
    if(today===renderedDay) return;
    renderedDay=today;
    if(!lastMetrics) return;
    renderSummaryCards(lastMetrics.trafficAnalysis || {});
    renderRevenue(lastMetrics.revenue || {});
    renderCFTrendsAndTopPosts(lastMetrics);
    renderTrafficCoverage(lastMetrics.trafficAnalysis || {});
    window.BaroLabTraffic?.render(lastMetrics.trafficAnalysis || {});
    set('metrics-refresh-status', `한국 날짜 ${today} · 통계 갱신 대기`);
  }
  function renderCollectionHealth(health) {
    const anchor=document.getElementById('metrics-refresh-status');
    if(!anchor) return;
    let box=document.getElementById('collection-health');
    if(!box) {
      box=document.createElement('details');box.id='collection-health';
      box.style.cssText='margin-top:10px;max-width:900px;font-size:13px;line-height:1.7;overflow-wrap:anywhere';
      anchor.after(box);
    }
    box.replaceChildren();
    const names={success:'원천 수집 확인',partial:'일부 원천 실패·미확인',failed:'수집 실패',unknown:'원천 성공 미확인',stale:'수집 지연',backoff:'재시도 대기',skipped:'이번 회차 미실행'};
    const expiredRecord=health?.evidenceMode==='windows_static_fallback' && health.exportStale;
    const summary=document.createElement('summary');
    summary.style.cssText='cursor:pointer;font-weight:700;color:#334155';
    summary.textContent=`수집 운영 · ${expiredRecord ? '운영 기록 갱신 지연' : names[health?.collectionStatus] || '이력 미확인'} · 상세 보기`;
    box.append(summary);
    const note=document.createElement('p');note.style.margin='6px 0';
    note.textContent='프로세스 종료와 원천 수집 성공은 별도입니다. 외부 알림은 사용하지 않으며 PC 알림은 전달 여부를 보장하지 않습니다.';
    if(health?.nasBackend==='pending') note.textContent+=` · Windows 공유 상태 파일 · NAS API 반영 대기 · 운영 기록 기준 ${health.checkedAt ? kstTime(health.checkedAt)+' KST' : '미확인'}${health.exportedAt?' · 내보냄 '+kstTime(health.exportedAt)+' KST':' · 내보내기 미확인'}${health.exportStale?' · 운영 기록 갱신 필요 · 최신 원천 수집 결과는 각 원천의 수집 시각으로 확인합니다.':''}`;

    box.append(note);
    const excluded=document.createElement('p');excluded.style.margin='4px 0';
    excluded.textContent=health?.excludedSources?.length ? `전체 성공 판정 제외 범위: ${health.excludedSources.map(s=>s.source).join(', ')} · 미연결을 성공으로 간주하지 않음` : '설정된 필수 원천 전체를 성공 판정에 포함합니다.';
    if(health?.redactedSourceCount) excluded.textContent=`공개 상태 파일에서 수익 원천 상세 ${number(health.redactedSourceCount)}개 제외 · 전체 성공 판정 제외 범위 ${number(health.excludedSourcesCount)}건 · 회차 판정과 관측 이력은 원본 기준`;
    box.append(excluded);
    for(const days of [7,30]) {
      const w=health?.windows?.[String(days)];
      const line=document.createElement('p');line.style.margin='4px 0';
      const missingText=w?.scheduleCoverageVerified===true && typeof w.missingSlots==='number' ? `누락 추정 ${number(w.missingSlots)}회` : '스케줄 이력 미확인';
      line.textContent=w ? `${days}일 · 관측 ${number(w.observedRuns)}회 · 결과 확인 ${number(w.knownOutcomeDenominator)}회 중 성공 ${number(w.counts?.success)}회 · 미확인 ${number(w.counts?.unknown)}회 · ${missingText}${w.fullWindowObserved?'':' · 전체 기간 이력 미확보'}` : `${days}일 성공률 · 새 이력 수집 전, 미확인`;
      box.append(line);
    }
    const sources=health?.sources || [];
    const list=document.createElement('div');list.style.cssText='max-height:280px;overflow:auto;border-top:1px solid #e2e8f0;margin-top:6px';
    for(const s of [...sources].sort((a,b)=>(a.status==='success')-(b.status==='success'))) {
      const row=document.createElement('p');row.style.margin='5px 0';
      const time=s.verifiedLastSuccessAt ? new Date(s.verifiedLastSuccessAt).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}) : '확인 이력 없음';
      row.textContent=`${s.source} · ${names[s.status] || '미확인'} · ${s.scope} · 마지막 검증 성공 ${time}${s.duplicateAlertSuppressed?' · 반복 알림 억제':''}`;
      list.append(row);
    }
    box.append(list);
    const alert=document.createElement('p');alert.style.margin='6px 0';
    const latest=(health?.recentAlerts || []).at(-1);
    alert.textContent=latest ? `최근 경보 · ${latest.kind==='recovery'?'복구':'확인 필요'} · ${latest.source} · ${new Date(latest.at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})}` : '경보 이력 미확인';
    box.append(alert);
  }
  async function collectionEvidence(data) {
    if(data.collectionObservability && typeof data.collectionObservability==='object') return data.collectionObservability;
    try {
      const response=await fetch('/data/collection-health.json',{cache:'no-store'});
      if(!response.ok) throw new Error('status export unavailable');
      const health=await response.json();
      if(health.schema!==1 || health.evidenceMode!=='windows_static_fallback') throw new Error('unknown export');
      const now=Date.now(), fresh=value=>{const at=Date.parse(value);return Number.isFinite(at)&&now-at>=-300000&&now-at<=5400000;};
      const stale=!fresh(health.exportedAt)||!fresh(health.checkedAt);
      return {...health,nasBackend:'pending',exportStale:stale,
        collectionStatus:stale?'stale':health.collectionStatus,
        sources:(health.sources||[]).map(row=>stale&&row.status==='success'?{...row,status:'stale',stale:true}:row)};
    } catch (_) {return {collectionStatus:'unknown',nasBackend:'pending',evidenceMode:'static_fallback_unavailable'};}
  }
  async function refresh() {
    if(refreshBusy) return;
    refreshBusy=true;
    const button=document.getElementById('btn-manual-refresh');
    const buttonLabel=button?.textContent;
    if(button){button.disabled=true;button.textContent='조회 중…';}
    try {
      await Promise.all([window.BaroLabHistory?.syncCFPublications(), window.BaroLabHistory?.syncNaverPublications()]);
      const response = await fetch('/api/metrics', { cache: 'no-store' });
      if (!response.ok) throw new Error('조회 실패');
      const data = await response.json();
      lastMetrics=data;renderedDay=kstDay();
      renderCollectionHealth(await collectionEvidence(data));
      const collected=data.trafficAnalysis?.checkedAt;
      set('metrics-refresh-status',(collected ? `통계 수집 ${kstTime(collected)} KST · 화면 1분마다 갱신` : '통계 수집 이력 미확인') + (data.trafficAnalysis?.today !== kstDay() ? ` · 자료 기준 ${data.trafficAnalysis?.today || '미확인'} · 갱신 필요` : ''));
      renderSummaryCards(data.trafficAnalysis || {});
      window.BaroLabContent?.render(data.contentAudit);
      const audit=data.contentAudit;
      if(audit) {
        const inspected=audit.rows.filter(r=>r.index!=='unknown').length;
        const reasons=Object.entries(audit.inspectionPendingReasons || {}).map(([label,count])=>`${label} ${number(count)}개`).join(' · ');
        set('content-maintenance-summary',`공개 글 ${number(audit.inventoryTotal)}개 · 현재 개별 색인 확인 ${number(inspected)}개 · 미색인 확인 ${number(audit.counts.not_indexed)}개 · 평균 11~100위 후보 ${number(audit.counts.opportunity)}개 · ${reasons || '개별 검사 범위 확인 중'} · 미확인은 미색인 판정이 아닙니다`);
      }
      if(audit) {
        set('action-unindexed',`${number(audit.counts.not_indexed)}개 미색인 확인`);
        set('action-opportunity',`${number(audit.counts.opportunity)}개 보강 후보`);
        set('action-unchecked',`${number(audit.rows.filter(r=>r.index==='unknown').length)}개 색인 미확인`);
      }
      const index = data.indexing || {};
      const collection = index.collection || {};
      const automation = collection.automation || data.inspectionAutomation || {};
      const owner = automation.accounts?.sj || {};
      const queueParts = [];
      if(Number.isSafeInteger(collection.total)) queueParts.push(`공개 글 ${number(collection.total)}개 · 현재 26시간 내 색인 확인 ${number(collection.currentInspected)}개 · 누적 확인 이력 ${number(collection.everInspected)}개`);
      if(Number.isSafeInteger(collection.staleInspected)) queueParts.push(`색인 판정 만료 ${number(collection.staleInspected)}개 · 오류 ${number(collection.failed)}개 · 검사 시도 없음 ${number(collection.neverAttempted)}개 · 확인된 색인 판정 이력 없음 ${number(collection.neverInspected)}개`);
      const timeLabel=value=>new Date(value).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'});
      if(owner.lastRunAt || automation.checkedAt) queueParts.push(`마지막 자동 검사 ${timeLabel(owner.lastRunAt || automation.checkedAt)}`);
      if(Number.isSafeInteger(owner.attempted)) queueParts.push(`최근 실행 시도 ${number(owner.attempted)}건 · 완료 ${number(owner.completed)}건${Number.isSafeInteger(owner.maxUrls)?` · 최근 회차 상한 ${number(owner.maxUrls)}건`:''}`);
      if(owner.nextRetryAt) queueParts.push(`다음 재시도 ${timeLabel(owner.nextRetryAt)}`);
      if(automation.status) queueParts.push(`수집기 ${{running:'검사 진행 중',collected:'수집 완료',completed:'실행 완료',partial:'일부 수집',busy:'기존 검사 진행 중',browser_busy:'다른 계정 작업 사용 중',backoff:'검사 제한 재시도 대기',error:'실행 오류',idle:'다음 실행 대기',scheduled:'예약됨'}[automation.status] || automation.status}`);
      const autoStatusNode = document.getElementById('inspection-automation-status');
      const fullAutoText = queueParts.length ? `${queueParts.join(' · ')} · 상태 확인만 수행하며 색인 요청·발행은 하지 않습니다.` : '자동 검사 실행 이력 조회 중';
      if (autoStatusNode) {
        autoStatusNode.title = fullAutoText;
        autoStatusNode.textContent = Number.isSafeInteger(collection.currentInspected)
          ? `ⓘ 자동 색인 점검 (${number(collection.currentInspected)} / ${number(collection.total)}건 확인)`
          : 'ⓘ 자동 색인 점검 이력';
      }
      const traffic = data.traffic || {};
      const reasons = [...new Set((data.sites || []).filter(r => r.site?.platform === 'cf').map(r => r.google?.reason).filter(Boolean))];
      set('metric-index-badge', index.complete ? '전체 확인' : index.inspected ? '일부 확인' : reasons.some(r => r.includes('403') || r.includes('권한')) ? '검사 권한 확인 필요' : '자동 확인 미연결');
      set('metric-index-value', index.inspected ? `${number(index.indexed)} / ${number(index.inspected)}건` : '미확인');
      set('metric-index-source', index.inspected ? `검사 ${number(index.inspected)}건 중 색인 ${number(index.indexed)}건 · 네이버 미측정${reasons.length ? ' · 일부 속성 조회 불가' : ''}` : reasons.join(' · ') || 'Google 색인 원천 미연결 · 네이버 미측정');
      const indexSource = document.getElementById('metric-index-source');
      if (indexSource) indexSource.title = reasons.join('\n');
      set('metric-index-scope', `공개 글 목록 ${number(index.inventoryTotal)}건`);
      renderRevenue(data.revenue || {});
      set('metric-bridge-clicks', '클릭수 미수집');
      set('metric-bridge-landings', `${number(traffic.naverReferralSessions)} 세션`);
      set('metric-bridge-label', '네이버 출처 CF 유입');
      renderCFTrendsAndTopPosts(data);
      const analysis = data.trafficAnalysis || {};
      renderTrafficCoverage(analysis);
      set('metric-collected-at', data.checkedAt ? `수집 확인: ${kstTime(data.checkedAt)} KST` : '수집 이력 없음');
      const table = document.getElementById('metric-sites');
      if (table) {
        table.replaceChildren();
        for (const record of data.sites || []) {
          const row = document.createElement('tr');
          const google = record.google || {};
          const request = record.indexingRequest || {};
          const domainTraffic = analysis.sites?.find(r=>r.site.site_id===record.site.site_id)?.ga4;
          const naverTraffic = analysis.naverBlogs?.find(r=>r.site.site_id===record.site.site_id);
          const week = domainTraffic?.periods?.week;
          const trafficText = week ? `${week.users.toLocaleString('ko-KR')}명 · ${week.start} ~ ${week.end}${domainTraffic.stale ? ' · 수집 지연' : ''}`
            : naverTraffic ? `${naverTraffic.days?.[naverTraffic.date] ?? '미수집'}명 · ${naverTraffic.date || '날짜 미확인'} 공개 카운터${naverTraffic.stale ? ' · 수집 지연' : ''}`
            : record.traffic?.sessions == null ? record.traffic?.reason || '트래픽 미확인' : `${number(record.traffic.sessions)} 세션 · ${record.traffic.start} ~ ${record.traffic.end}`;
          const cells = [record.site.site_id,
            google.inspected ? `${number(google.indexed)} / ${number(google.inspected)} URL 확인` : (google.reason || '색인 미확인'),
            [['Google', request.google], ['네이버', request.naver]].filter(([, r]) => r)
              .map(([name, r]) => `${name}: ${labels[r.status] || r.status}`).join(' · ') || '요청 이력 없음',
            trafficText];
          for (const value of cells) {
            const cell = document.createElement('td');
            cell.style.cssText = 'padding:9px;border-bottom:1px solid #e2e8f0;font-size:12px;vertical-align:top;';
            cell.textContent = value;
            row.appendChild(cell);
          }
          table.appendChild(row);
        }
      }
      window.BaroLabTraffic?.render(data.trafficAnalysis || {});
    } catch (_) {
      set('metrics-refresh-status','통계 조회 실패 · 이전 조회 결과는 재확인이 필요합니다');
      set('metric-collected-at', '수집 상태 조회 실패 — 이전 수치를 현재 실적으로 확정하지 않습니다');
      set('revenue-updated', '수익 조회 실패 · 화면에 남은 값은 이전 조회 결과입니다');
      set('metric-revenue-badge', '조회 실패');
      window.BaroLabTraffic?.failed();
      window.BaroLabContent?.failed();
      set('content-maintenance-summary','관리 목록 조회 실패 · 재확인 필요');
      for(const id of ['action-unindexed','action-opportunity','action-unchecked']) set(id,'조회 실패 · 재확인 필요');
      set('summary-visitors-coverage', '조회 실패 · 이전 조회 결과');
    } finally {
      refreshBusy=false;
      if(button){button.disabled=false;button.textContent=buttonLabel;}
    }
  }
  refresh();
  document.getElementById('btn-manual-refresh')?.addEventListener('click',refresh);
  setInterval(refresh, 60000);
  setInterval(refreshDay, 1000);
  window.addEventListener('focus',refreshDay);
  window.addEventListener('pageshow',refreshDay);
  document.addEventListener('visibilitychange',refreshDay);
})();
