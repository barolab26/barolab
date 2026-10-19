(() => {
  'use strict';
  const accounts = ['adinfo0905', 'stone0747'];
  const states = { discovered: '질문 발굴', drafted: '답변 초안', submitted_unverified: '제출 · 공개 미확인', published_verified: '공개 검증 완료' };
  const byId = id => document.getElementById(id);
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  }
  function publicUrl(value) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && url.hostname === 'kin.naver.com' && !url.port && !url.username && !url.password && /^\/(?:qna\/detail\.naver|qna\/detail\.nhn)$/.test(url.pathname) && /^\d+$/.test(url.searchParams.get('docId') || '') ? url.href : null;
    } catch (_) { return null; }
  }
  function link(parent, title, value) {
    const href = publicUrl(value);
    if (!href) return false;
    const anchor = node('a', title);
    anchor.href = href; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer';
    parent.append(anchor); return true;
  }
  function time(value) {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime()) ? date.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) + ' KST' : '미확인';
  }
  function measurement(data) {
    const report = data && typeof data === 'object' ? data : {};
    byId('kin-measurement-status').textContent = report.checkedAt ? (report.startDate + ' ~ ' + report.endDate + ' · KST · 수집 ' + time(report.checkedAt) + ' · ' + ({collected:'수집 완료 · 잠정 집계',partial:'일부만 수집',not_collected:'미수집'}[report.status] || '상태 미확인')) : '유입 측정 기록 미수집';
    byId('kin-measurement-counts').replaceChildren();
    [['sessions','세션'],['engagedSessions','참여 세션'],['pageViews','페이지뷰'],['matchedSessions','답변 기록과 연결한 세션']].forEach(([key,label]) => {
      const card = node('div'); card.append(node('span',label),node('strong',Number.isSafeInteger(report[key]) ? report[key] : '미확인')); byId('kin-measurement-counts').append(card);
    });
    byId('kin-measurement-scope').textContent = report.checkedAt ? 'Must-good · Must-pick / naver_kin · referral · cf_bridge. ' + (report.periodKind === 'baseline' ? '기준 기간 집계 · 시험 유입은 아직 미집계. ' : '시험 시작일부터 어제까지 집계. ') + (report.lagNote || '') + (report.complete ? '' : ' 일부 대상의 수집이 완료되지 않아 전체 합계는 미확인입니다.') + '\n' + (report.trackingValidationNote || '') : 'GA4 연결·수집 범위 미확인';
    byId('kin-measurement-revenue').textContent = report.revenueReason || '게시자 광고 수익 미확인';
    const rows = byId('kin-measurement-rows'); rows.replaceChildren();
    (Array.isArray(report.rows) ? report.rows : []).slice(0,100).forEach(item => {
      const row = node('tr'); row.append(node('td',(item.day || '') + '\n' + (item.host || '')));
      const attribution = node('td');
      if (item.mappingStatus === 'ledger_matched' && accounts.includes(item.account)) {
        attribution.append(node('span',item.account + ' · 질문 ' + item.questionId));
        if (item.state === 'published_verified') link(attribution,'공개 검증 답변',item.answerUrl);
      } else attribution.textContent = 'UTM 확인 · 답변 기록 연결 미확인';
      row.append(attribution); ['sessions','engagedSessions','pageViews'].forEach(key=>row.append(node('td',Number.isSafeInteger(item[key]) ? item[key] : '미확인'))); rows.append(row);
    });
    if (!rows.children.length) { const row=node('tr'),cell=node('td', report.complete ? '조회 기간에 측정된 해당 UTM 유입이 없습니다.' : '답변별 측정 내역 미확인'); cell.colSpan=5; row.append(cell); rows.append(row); }
    const daily=byId('kin-daily'); daily.replaceChildren();
    (Array.isArray(report.dailyFunnel) ? report.dailyFunnel : []).forEach(item=>{const row=node('tr'); ['day','discovered','drafted','attempted','published_verified'].forEach(key=>row.append(node('td',key === 'day' && report.funnelTodayProvisional && item.day === report.funnelEndDate ? item.day + (report.funnelPeriodKind === 'pretrial_check' ? ' · 사전 점검' : ' · 오늘 집계 진행 중') : (item[key] ?? '미확인')))); daily.append(row);});
    if (!daily.children.length) { const row=node('tr'),cell=node('td','일별 운영 집계 미확인');cell.colSpan=5;row.append(cell);daily.append(row); }
  }
  function render(data) {
    const automation = data.automation || {};
    const globalCap = Number.isSafeInteger(automation.globalDailyCap) ? automation.globalDailyCap : 20;
    const accountCap = Number.isSafeInteger(automation.accountDailyCap) ? automation.accountDailyCap : 10;
    const scheduleDetails = (typeof automation.enabled === 'boolean' ? (automation.enabled ? '자동 운영 켜짐 (상시 모드 · 전역 블로그 락 분리 완료)' : '자동 운영 꺼짐') : '자동 운영 상태 미확인') + '\n계정 교대 · 직전 작업 종료 후 18~22분 지터 교대 간격(개별 계정 40~45분 안전 텀)으로 다음 작업 진행';
    byId('kin-schedule').textContent = (automation.scheduleDescription ? automation.scheduleDescription + '\n' : '') + scheduleDetails;
    const runStates = {not_run:'실행 기록 없음',idle:'실행 시간 대기',review_pending:'운영 검토 중',registered:'예약 등록',completed_cycle:'회차 처리 완료',blocked:'확인 필요',skipped:'건너뜀',measurement_completed:'측정 완료',waiting:'다음 작업 대기',running:'작업 진행 중',reserved:'작업 진행 중',recovered_wait:'중단 확인 · 다시 대기',already_running:'작업 진행 중'};
    byId('kin-last-run').textContent = automation.activeRunId ? '현재 작업 시작: ' + time(automation.activeStartedAt) + ' · 작업 진행 중' : '최근 작업 완료: ' + time(automation.lastRunAt) + (automation.state ? ' · ' + (runStates[automation.state] || automation.state) : '');
    const lastOperation = automation.lastOperation;
    let operationResult = '최근 작업 결과 미확인';
    if (lastOperation && typeof lastOperation === 'object') {
      const questionState = lastOperation.questionState || lastOperation.question_state;
      let result = questionState === 'published_verified' ? '답변 공개 검증 완료' : (questionState === 'submitted_unverified' || questionState === 'publishing' ? '제출 시도 · 공개 검증 미완료' : (lastOperation.submitted === false ? '등록 전 중단 · 신규 제출 없음 (한도 미차감)' : '작업 결과 확인 필요'));
      if (automation.activeRunId && ['started','running','reserved'].includes(lastOperation.state)) result = '작업 진행 중 · 제출 결과 미확인';
      const reasons = {operation_TimeoutExpired:'작업 시간 초과로 등록 전 중단',answer_history_incomplete:'기존 답변 중복 확인 미완료',own_answer_inventory_incomplete:'기존 답변 중복 확인 미완료',inventory_incomplete:'기존 답변 중복 확인 미완료',no_eligible_reviewed_answer:'적합한 검수 완료 답변 없음',independent_review_rejected:'답변 검수 기준 미충족',question_unavailable:'해당 질문에 답변할 수 없음'};
      if (reasons[lastOperation.reason]) result += ' · ' + reasons[lastOperation.reason];
      operationResult = '최근 작업 결과: ' + (accounts.includes(lastOperation.account) ? lastOperation.account + ' · ' : '') + result + ' · ' + time(lastOperation.updatedAt || lastOperation.updated_at);
    }
    byId('kin-operation-result').textContent = operationResult;
    byId('kin-next-run').textContent = automation.activeRunId ? '작업 진행 중' + (accounts.includes(automation.activeAccount) ? ' · ' + automation.activeAccount : '') + ' · 다음 작업은 이 작업이 종료된 뒤 30~40분 지터 후에 가능합니다.' : '다음 작업 가능 시각: ' + time(automation.nextEligibleAt) + (accounts.includes(automation.nextAccount) ? ' · ' + automation.nextAccount : '');
    const daily = data.daily || {};
    const adAtt = (daily.byAccount && daily.byAccount.adinfo0905 && daily.byAccount.adinfo0905.attempted) || 0;
    const stAtt = (daily.byAccount && daily.byAccount.stone0747 && daily.byAccount.stone0747.attempted) || 0;
    const totAtt = Number.isSafeInteger(daily.attempted) ? daily.attempted : (adAtt + stAtt);
    byId('kin-operations').textContent = `오늘 제출 현황: adinfo0905 (오늘 ${adAtt}/${accountCap}건) · stone0747 (오늘 ${stAtt}/${accountCap}건) · 전체 (${totAtt}/${globalCap}건)\n발굴 트랙 비중: Track A 최신선점 50% : Track B 검색상위 50%`;
    byId('kin-daily-remaining').textContent = '오늘 남은 제출 한도: ' + Math.max(0, globalCap - totAtt) + '/' + globalCap + ' · adinfo0905 ' + Math.max(0, accountCap - adAtt) + '/' + accountCap + ' · stone0747 ' + Math.max(0, accountCap - stAtt) + '/' + accountCap + (daily.date ? ' · ' + daily.date + ' KST' : '');
    const sourceRecords = data.records || data.recent;
    const records = Array.isArray(sourceRecords) ? sourceRecords.filter(row => row && accounts.includes(row.account)) : [];
    const countHost = byId('kin-counts'); countHost.replaceChildren();
    Object.entries(states).forEach(([key, title]) => {
      const card = node('div'); card.append(node('span', title));
      const count = data.counts ? (data.counts[key] ?? 0) : undefined;
      card.append(node('strong', Number.isSafeInteger(count) && count >= 0 ? count : '미확인')); countHost.append(card);
    });
    const checkedAt = data.collected_at || data.checkedAt;
    byId('kin-updated').textContent = '마지막 기록: ' + time(checkedAt);
    const age = Date.now() - new Date(checkedAt).getTime();
    byId('kin-status').textContent = data.status || '운영 기록 확인';
    if (Number.isFinite(age) && age > 86400000) byId('kin-status').textContent += ' · 24시간 이상 지난 기록';
    const blocked = String(data.blocked_reason || data.blockedReason || '').replaceAll('operation_TimeoutExpired', '작업 시간 초과로 등록 전 중단');
    byId('kin-blocked').hidden = !blocked; byId('kin-blocked').textContent = blocked;
    byId('kin-accounts').replaceChildren();
    accounts.forEach(account => {
      const details = Array.isArray(data.accounts) ? data.accounts.find(row => row && typeof row === 'object' && (row.account === account || row.id === account)) : null;
      const card = node('div', undefined, 'kin-account'); card.append(node('strong', account));
      const accountCounts = data.byAccount && data.byAccount[account];
      let accountText = details ? (details.status || '실행 상태 미확인') : '계정별 실행 상태 미확인';
      if (accountCounts && typeof accountCounts === 'object') {
        accountText = Object.entries(states).map(([key, label]) => {
          const count = accountCounts[key] ?? 0;
          return label + ' ' + (Number.isSafeInteger(count) && count >= 0 ? count : '미확인');
        }).join(' · ');
        if (Number.isSafeInteger(accountCounts.publishing) && accountCounts.publishing > 0) accountText += '\n제출 처리 중 ' + accountCounts.publishing;
      }
      const accountBlocked = (data.accountBlockedReasons && data.accountBlockedReasons[account]) || (details && details.blocked_reason);
      if (accountBlocked) accountText += '\n' + (accountBlocked === 'operation_TimeoutExpired' ? '작업 시간 초과로 등록 전 중단' : accountBlocked);
      card.append(node('p', accountText));
      byId('kin-accounts').append(card);
    });
    const body = byId('kin-records'); body.replaceChildren();
    records.slice(0, 100).forEach(record => {
      const row = node('tr'); const question = node('td');
      if (!link(question, record.title || record.question_title || '질문 확인', record.question_url)) question.append(node('span', record.title || record.question_title || '질문 제목 미확인'));
      question.append(node('small', record.account)); row.append(question);
      const state = record.status || record.state;
      row.append(node('td', states[state] || (state === 'publishing' ? '제출 처리 중' : '상태 미확인')));
      row.append(node('td', record.draft_text || record.answer_text || (state === 'discovered' ? '초안 작성 전' : '본문 비공개 · 운영 기록에서 관리')));
      const evidence = node('td');
      if (state === 'published_verified' && link(evidence, '검증한 공개 답변', record.public_url || record.answer_url)) evidence.append(node('small', time(record.verified_at || record.updated_at)));
      else evidence.textContent = '공개 검증 미완료';
      if (record.blocked_reason) evidence.append(node('small', record.blocked_reason));
      row.append(evidence); body.append(row);
    });
    if (!records.length) { const row = node('tr'); const cell = node('td', '표시할 질문·답변 기록이 없습니다.'); cell.colSpan = 4; row.append(cell); body.append(row); }
  }
  let loading = false;
  async function refresh() {
    if (loading) return;
    loading = true; byId('kin-refresh').disabled = true;
    try {
      const response = await fetch('data/kin.json', { cache: 'no-store', signal: AbortSignal.timeout(15000) });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Invalid snapshot');
      render(data);
      window.dispatchEvent(new CustomEvent('barolab-kin-updated',{detail:{status:'ready',data,fetchedAt:new Date().toISOString(),stale:!Number.isFinite(Date.parse(data.checkedAt)) || Date.now()-Date.parse(data.checkedAt)>30*60000,error:null}}));
      try {
        const measured = await fetch('data/kin-measurement.json', {cache:'no-store', signal:AbortSignal.timeout(15000)});
        measurement(measured.ok ? await measured.json() : data.measurement);
      } catch (_) { measurement(data.measurement); }
    } catch (_) {
      render({ status: '운영 기록을 불러오지 못했습니다. 새로고침으로 다시 확인하세요.', blocked_reason: '실행 결과 미확인 · 게시와 유입을 완료로 집계하지 않습니다.' });
      measurement(null);
      window.dispatchEvent(new CustomEvent('barolab-kin-updated',{detail:{status:'error',data:null,fetchedAt:null,stale:true,error:'지식iN 운영 기록 조회 실패'}}));
    } finally { loading = false; byId('kin-refresh').disabled = false; }
  }
  byId('kin-refresh').addEventListener('click', refresh);
  refresh();
})();
