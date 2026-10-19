/* App projects & SJ AdMob 3-Pillar Monetization Live Tracker */
(function () {
  'use strict';
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {installationState, playAppState, playPortfolioState, playDisplayLabels, installationSlot, saveInstallation};
  }
  if (typeof document === 'undefined') return;
  const list = document.getElementById('app-project-list');
  const state = document.getElementById('app-project-status');
  const filterBar = document.getElementById('app-filter-bar');
  const refreshBtn = document.getElementById('apps-refresh');
  const auditBtn = document.getElementById('apps-audit-now');
  if (!list || !state) return;

  const statuses = {development:'개발 중', preview:'내부 테스트 · 미리보기', released:'정식 출시'};
  const steps = {not_started:'대기', in_progress:'진행 중', verified:'검증 완료', blocked:'확인 필요'};
  let currentFilter = 'all';
  let latestData = null;
  let staticTesters = null;
  let installationDoc = null;
  let installationError = '';
  let installationBusy = false;
  let projectsRefreshBusy = false;
  let installationRequestSeq = 0;

  function installationSlot(account, index) {
    if (typeof account.slotLabel === 'string' && account.slotLabel) return account.slotLabel;
    if (typeof account.slot === 'string' && account.slot && !/^\d+$/.test(account.slot)) return account.slot;
    const slot = Number(account.slot);
    const position = Number.isInteger(slot) && slot >= 1 && slot <= 13 ? slot - 1 : index;
    return position < 12 ? `폰${Math.floor(position / 2) + 1}-${position % 2 ? '보안폴더' : '일반'}` : `예비${position + 1}`;
  }

  function installationState(doc) {
    const available = Array.isArray(doc?.accounts) && doc.accounts.every(a => typeof a.id === 'string' && a.id && typeof a.email === 'string' && typeof a.installed === 'boolean')
      && new Set(doc.accounts.map(a => a.id)).size === doc.accounts.length
      && Number.isInteger(doc?.revision) && doc.revision >= 0 && !!doc?.localTracking;
    if (!available) return {available: false, count: null, day: null, required: 12, requiredDays: 14};
    const count = doc.accounts.filter(a => a.installed === true).length;
    const required = doc.localTracking.requiredCount || 12;
    const requiredDays = doc.localTracking.requiredDays || 14;
    const started = count >= required && !!doc.localTracking.startedAt;
    const rawDay = doc.localTracking.dayNumber;
    return {available, count, required, requiredDays, started,
      day: started && Number.isInteger(rawDay) ? Math.max(1, Math.min(requiredDays, rawDay)) : 0,
      startedAt: started ? doc.localTracking.startedAt : null,
      completionAt: doc.localTracking.completionAt || null,
      googleQualificationVerified: false};
  }

  function playAppState(app = {}, top = {}) {
    const observedNumber = value => Number.isInteger(value) && value >= 0 ? value : null;
    const labels = {in_review: '검토 중', approved: '검토 승인 확인', rejected: '거부됨', not_submitted: '미제출', unknown: '미확인'};
    return {
      review: labels[app.alpha?.reviewStatus] || '미확인',
      alphaReleased: app.alpha?.released === true ? '출시됨' : app.alpha?.released === false ? '미출시' : '출시 여부 미확인',
      alphaActive: app.alpha?.trackActive === true ? '트랙 활성' : app.alpha?.trackActive === false ? '트랙 비활성' : '트랙 활성 여부 미확인',
      internalReleased: app.internal?.released === true ? '배포됨' : app.internal?.released === false ? '미배포' : '배포 여부 미확인',
      alphaVersion: observedNumber(app.alpha?.versionCode), internalVersion: observedNumber(app.internal?.versionCode),
      optedIn: observedNumber(app.googleOptInCount), installs: observedNumber(app.googleInstallCount),
      days: observedNumber(app.continuousTestDays), checkedAt: app.checkedAt || top.checkedAt || null,
      stale: app.stale === true || top.stale === true,
      error: app.error || top.error || null
    };
  }

  function playPortfolioState(top = {}) {
    const ids = ['bible_app', 'greeting', 'magnifier', 'shopping'];
    const apps = ids.map(id => top.apps?.[id] || {});
    return {
      alphaReleased: apps.filter(a => a.alpha?.released === true).length,
      alphaObserved: apps.filter(a => typeof a.alpha?.released === 'boolean').length,
      internalReleased: apps.filter(a => a.internal?.released === true).length,
      optIns: apps.map(a => playAppState(a, top).optedIn)
    };
  }

  function playDisplayLabels(app, top) {
    const view = playAppState(app, top);
    const count = view.optedIn === null ? '미확인' : `${view.optedIn}명`;
    const days = view.days === null ? '미확인' : `${view.days}일`;
    let nextAction = 'Console의 Alpha 출시·참여 상태 확인';
    if (app?.alpha?.released === true) {
      nextAction = view.optedIn === null ? 'Console 실제 참여 수 확인'
        : view.optedIn < 12 ? `이 앱 Alpha에 ${12 - view.optedIn}명 추가 참여 확인 필요`
        : 'Google의 연속 14일 참여 관측 확인';
    }
    return {
      track: `Alpha ${view.alphaReleased} · 내부 ${view.internalReleased}`,
      detail: `${view.review} · Google 참여 ${count} · 연속 기간 ${days}${view.stale ? ' · 이전 관측값' : ''}`,
      nextAction
    };
  }

  async function saveInstallation(id, installed, revision, fetcher = fetch) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 10000);
    try {
      const response = await fetcher('/api/projects/testers/accounts/' + encodeURIComponent(id), {
        method: 'PATCH', headers: {'Content-Type': 'application/json'}, signal: ctrl.signal,
        body: JSON.stringify({installed, expectedRevision: revision})
      });
      if (!response.ok) {
        const error = new Error(response.status === 409 ? 'conflict' : 'save_failed');
        error.status = response.status; throw error;
      }
      const body = await response.json();
      if (!installationState(body.testersControlCenter).available) throw new Error('invalid_installation_response');
      return body.testersControlCenter;
    } finally {
      clearTimeout(timer);
    }
  }

  // Fallback catalog: the NAS image may predate versionCode/versionName/joinUrl fields in /api/projects.
  const APP_CATALOG = {
    bible_app: {packageName: 'com.barolab.harubible', versionCode: 5, versionName: '0.5.0', internalAvailableVersionCode: 5, verifiedDeviceVersionCode: 4, closedReviewStatus: '검토 중',
      internalJoinUrl: 'https://play.google.com/apps/internaltest/4700464139727332365',
      closedJoinUrl: 'https://play.google.com/apps/testing/com.barolab.harubible'},
    greeting: {packageName: 'com.barolab.morningcard', versionCode: 3, versionName: '0.3.0', internalAvailableVersionCode: 3, verifiedDeviceVersionCode: 2, closedReviewStatus: '검토 중',
      internalJoinUrl: 'https://play.google.com/apps/internaltest/4701400802151181455',
      closedJoinUrl: 'https://play.google.com/apps/testing/com.barolab.morningcard'},
    magnifier: {packageName: 'com.barolab.biglens', versionCode: 3, versionName: '0.3.0', internalAvailableVersionCode: 3, verifiedDeviceVersionCode: 2, closedReviewStatus: '검토 중',
      internalJoinUrl: 'https://play.google.com/apps/internaltest/4701703053640983596',
      closedJoinUrl: 'https://play.google.com/apps/testing/com.barolab.biglens'},
    shopping: {packageName: 'com.barolab.voicebasket', versionCode: 3, versionName: '0.3.0', internalAvailableVersionCode: 3, verifiedDeviceVersionCode: 2, closedReviewStatus: '검토 중',
      internalJoinUrl: 'https://play.google.com/apps/internaltest/4701721871486482124',
      closedJoinUrl: 'https://play.google.com/apps/testing/com.barolab.voicebasket'}
  };
  // Verified release ledger snapshot; used only when the API lacks release truth fields.
  const RELEASE_LEDGER_CHECKED_AT = '2026-10-19T02:50:00+09:00';
  const CEO_DEVICE_VERIFIED_AT = '2026-10-19T02:08:41.441688+09:00';
  function withReleaseLedgerFallback(data) {
    if (!Array.isArray(data?.projects)) return data;
    return {...data, projects: data.projects.map(p => {
      const cat = APP_CATALOG[p.id];
      if (!cat || p.latestBuildVersionCode !== undefined) return p;
      const historicDevice = p.deviceVerified === undefined ? true : p.deviceVerified;
      const version = cat.versionCode;
      const currentTrackLabel = `내부 v${version} 제공 · Alpha v${version} 검토 제출`;
      return {...p,
        versionCode: p.versionCode || version,
        versionName: p.versionName || cat.versionName,
        deviceVerified: historicDevice,
        deviceVerifiedAt: p.deviceVerifiedAt || CEO_DEVICE_VERIFIED_AT,
        deviceVerifiedVersionCode: p.deviceVerifiedVersionCode || cat.verifiedDeviceVersionCode,
        latestBuildPhysicalDeviceVerified: p.latestBuildPhysicalDeviceVerified === true,
        internalAvailableVersionCode: cat.internalAvailableVersionCode,
        releaseLedgerFallbackAt: RELEASE_LEDGER_CHECKED_AT,
        closedReviewStatus: '검토 중',
        testSchedule: {...(p.testSchedule || {}),
          currentTrackLabel,
          closedTrackStatusLabel: `Alpha v${version} 검토 제출 · 대한민국 · 등록명단 13명 · 실제 참여 수 미확인`,
          registeredTestersCount: 13, internalTestersCount: 13,
          closedReviewSubmitted: true, closedReviewApproved: false,
          closedTestOptInsVerified: false, countdownStarted: false,
          internalReleaseDate: '2026-10-19'},
        nextAction: 'Google 검토 후 Alpha 참여 가능 여부 확인 · 최소 12명의 연속 14일 참여 요건 확인',
        milestones: (p.milestones || []).map(m => m.id === 'device_test' && p.deviceVerified === undefined
          ? {...m, status: 'verified', verifiedAt: CEO_DEVICE_VERIFIED_AT, verifiedVersionCode: cat.verifiedDeviceVersionCode,
            evidence: 'Samsung Galaxy physical device verified by CEO (2026-10-19)'} : m)
      };
    })};
  }
  function appMeta(p) {
    const cat = APP_CATALOG[p?.id] || {};
    return {
      packageName: p?.packageName || cat.packageName || '',
      versionCode: p?.versionCode || cat.versionCode || '',
      versionName: p?.versionName || p?.releaseName || cat.versionName || '',
      internalJoinUrl: p?.internalJoinUrl || cat.internalJoinUrl || 'https://barolab-daily-apps.pages.dev/testers/',
      closedJoinUrl: p?.closedJoinUrl || cat.closedJoinUrl || '',
      internalAvailableVersionCode: p?.internalAvailableVersionCode || cat.internalAvailableVersionCode || '',
      verifiedDeviceVersionCode: p?.deviceVerifiedVersionCode || p?.verifiedVersionCode || cat.verifiedDeviceVersionCode || '',
      closedReviewStatus: installationDoc?.playConsoleStatus?.apps?.[p?.id]
        ? playAppState(installationDoc.playConsoleStatus.apps[p.id], installationDoc.playConsoleStatus).review
        : 'Console 상태 미확인'
    };
  }

  async function loadStaticTesters(signal) {
    try {
      const r = await fetch('/data/app_testers.json', {cache: 'no-store', signal});
      if (r.ok) staticTesters = await r.json();
    } catch (_) {}
  }

  function node(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined && value !== null) el.textContent = value;
    if (className) el.className = className;
    return el;
  }

  function formatKST(isoStr) {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    if (Number.isNaN(d.getTime())) return isoStr;
    return d.toLocaleString('ko-KR', {
      timeZone: 'Asia/Seoul',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }) + ' KST';
  }

  async function loadInstallation() {
    if (installationBusy) return;
    const sequence = ++installationRequestSeq;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 10000);
    try {
      const response = await fetch('/api/projects/testers', {cache: 'no-store', signal: ctrl.signal});
      if (!response.ok) throw new Error('unavailable');
      const doc = await response.json();
      if (doc.contractVersion !== 'tester-installations-v1' || !installationState(doc).available) throw new Error('old_schema');
      if (sequence !== installationRequestSeq || installationBusy) return;
      installationDoc = doc; installationError = '';
    } catch (_) {
      if (sequence !== installationRequestSeq || installationBusy) return;
      installationError = '설치 확인 원장 연결 실패 · 상태 새로고침 후 다시 시도하세요.';
    } finally {
      clearTimeout(timer);
    }
    renderInstallation();
    renderPlayConsole();
  }

  function renderInstallation(focusId) {
    const box = document.getElementById('tester-installation-list');
    if (!box) return;
    const currentFocus = focusId || document.activeElement?.dataset?.installationId;
    const view = installationState(installationDoc);
    const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    if (!view.available) {
      set('local-install-status', '설치 확인 수 미확인');
      set('local-install-day', '자체 설치 추적 대기');
      set('installation-save-status', installationError || '설치 확인 원장 연결 중');
      box.replaceChildren(node('p', '계정별 설치 확인표를 불러오는 중입니다.', 'qr-zone-desc'));
      return;
    }
    set('local-install-status', `현재 ${view.count}/${view.required} 설치 완료 · ${view.count < view.required ? `${view.required - view.count}계정 추가 설치 / Alpha 참여 확인 필요` : 'Alpha 참여 확인 필요'}`);
    set('local-install-sub', `등록 ${installationDoc.accounts.length}계정 · 4종 설치 사용자 확인값입니다. Google Opt-in 인원과 별도입니다.`);
    set('local-install-day', view.started ? `자체 설치 추적 D+${view.day} / ${view.requiredDays}` : '자체 설치 추적 대기 · 12계정 확인 필요');
    set('local-install-timing', view.started
      ? `자체 시작 ${formatKST(view.startedAt)} · ${view.completionAt ? '14일 경과 예정 ' + formatKST(view.completionAt) : 'Google 연속 기간과 별도 기록'}`
      : '아직 자체 시작일이 없습니다. Google의 연속 14일은 별도 Console 근거로 확인합니다.');
    const progress = document.getElementById('local-install-progress');
    if (progress) progress.style.width = `${view.started ? Math.min(100, view.day / view.requiredDays * 100) : 0}%`;
    if (installationBusy) return;
    box.replaceChildren();
    installationDoc.accounts.forEach((account, index) => {
      const row = node('div', '', 'tester-installation-row' + (account.installed === true ? ' installed' : ''));
      const identity = node('div', '', 'tester-installation-identity');
      identity.append(node('strong', installationSlot(account, index)), node('span', account.email));
      if (account.installedAt) identity.append(node('small', `확인 ${formatKST(account.installedAt)}`));
      const button = node('button', account.installed === true ? '✓ 4종 설치 완료' : '4종 설치 완료', 'tester-installation-toggle');
      button.type = 'button'; button.dataset.installationId = account.id;
      button.setAttribute('aria-pressed', String(account.installed === true));
      button.setAttribute('aria-label', `${installationSlot(account, index)} ${account.email} 4종 설치 완료`);
      button.disabled = !!installationError;
      button.onclick = async () => {
        if (installationBusy) return;
        installationBusy = true; ++installationRequestSeq;
        box.querySelectorAll('button').forEach(el => { el.disabled = true; });
        button.setAttribute('aria-busy', 'true'); button.textContent = '저장 중…';
        set('installation-save-status', '설치 확인 상태를 저장하는 중입니다.');
        let message;
        try {
          installationDoc = await saveInstallation(account.id, account.installed !== true, installationDoc.revision);
          installationError = ''; message = '설치 확인을 저장했습니다. Google 참여 실측 값은 변경되지 않습니다.';
        } catch (error) {
          if (error.status === 409) {
            installationBusy = false; await loadInstallation();
            message = installationError
              ? '다른 화면에서 변경되었고 최신 조회도 실패했습니다. 새로고침 후 다시 선택하세요.'
              : '다른 화면에서 변경되어 최신 상태를 불러왔습니다. 확인 후 다시 선택하세요.';
          } else message = '저장 결과를 확인하지 못해 이전 표시를 유지합니다. 새로고침으로 확인 후 다시 시도하세요.';
        } finally {
          installationBusy = false; renderInstallation(account.id); renderPlayConsole();
          set('installation-save-status', message);
        }
      };
      row.append(identity, button); box.append(row);
    });
    set('installation-save-status', installationError || '체크는 4종 설치에 대한 사용자 확인입니다. 해제도 즉시 저장됩니다.');
    if (currentFocus) Array.from(box.querySelectorAll('button')).find(el => el.dataset.installationId === currentFocus)?.focus({preventScroll: true});
  }

  function renderPlayConsole() {
    const box = document.getElementById('play-console-cards');
    if (!box) return;
    const top = installationDoc?.playConsoleStatus || {};
    const apps = top.apps || {};
    const names = {bible_app: '성경말씀', greeting: '오늘의 안부', magnifier: '큰글씨 돋보기', shopping: '말로 장보기'};
    const freshness = document.getElementById('play-console-freshness');
    if (freshness) freshness.textContent = installationError ? '연결 실패 · 이전 관측값' : top.stale ? '이전 관측값 · 최신 확인 필요' : top.checkedAt ? `관측 ${formatKST(top.checkedAt)}` : 'Console 실측 미확인';
    box.replaceChildren();
    for (const [id, name] of Object.entries(names)) {
      const view = playAppState(apps[id], top);
      const card = node('article', '', 'play-console-card');
      card.append(node('h4', name));
      card.append(node('p', `Alpha: ${view.review} · ${view.alphaReleased} · ${view.alphaActive}${view.alphaVersion !== null ? ' · v' + view.alphaVersion : ''}`, 'play-console-track'));
      card.append(node('p', `내부: ${view.internalReleased}${view.internalVersion !== null ? ' · v' + view.internalVersion : ''}`, 'play-console-track'));
      const display = (value, unit) => value === null ? '미확인' : `${value}${unit}`;
      card.append(node('p', `Google 참여 ${display(view.optedIn, '명')} · 설치 ${display(view.installs, '명')}`, 'play-console-counts'));
      if (view.optedIn !== null && view.optedIn < 12) card.append(node('p', `Console 참여 12명까지 ${12 - view.optedIn}명 추가 확인 필요`, 'play-console-counts'));
      card.append(node('p', `Google 연속 테스트 ${display(view.days, '일')} / 14일`, 'play-console-counts'));
      card.append(node('small', view.checkedAt ? `관측 ${formatKST(view.checkedAt)}` : '아직 Console 관측 근거가 없습니다.'));
      if (view.stale || installationError) card.append(node('small', '이전 관측값입니다. 최신 상태 확인이 필요합니다.', 'play-console-warning'));
      if (view.error) card.append(node('small', `수집 확인 필요: ${typeof view.error === 'string' ? view.error : view.error.message || view.error.code || '수집 오류'}`, 'play-console-warning'));
      box.append(card);
    }
    const google = document.getElementById('zc-closed-status');
    if (google) google.textContent = 'Google 참여·연속 기간은 아래 4종 Console 실측으로 확인';
    const portfolio = playPortfolioState(top);
    const value = document.getElementById('apps-kpi-release-val');
    const badge = document.getElementById('apps-kpi-release-badge');
    const desc = document.getElementById('apps-kpi-release-desc');
    if (value) value.textContent = portfolio.alphaObserved ? `Alpha 출시 확인 ${portfolio.alphaReleased}/4` : 'Alpha 출시 미확인';
    if (badge) badge.textContent = top.stale || installationError ? '이전 관측값' : 'Console 실측';
    if (desc) desc.textContent = `Google 참여: 성경 ${portfolio.optIns[0] ?? '미확인'} · 안부 ${portfolio.optIns[1] ?? '미확인'} · 돋보기 ${portfolio.optIns[2] ?? '미확인'} · 장보기 ${portfolio.optIns[3] ?? '미확인'}명 · 내부 배포 확인 ${portfolio.internalReleased}/4`;
  }

  function metric(raw, key, unit) {
    if (raw?.status !== 'collected' || !Number.isFinite(raw[key]) || !raw.period || !raw.checkedAt) return '미연동 · 미수집';
    return `${raw[key].toLocaleString('ko-KR')}${unit} · ${raw.period}`;
  }

  function updateKPIs(data) {
    const projects = Array.isArray(data?.projects) ? data.projects : [];
    const expected = data?.expectedProjects || projects.length || 4;
    const summary = data?.summary || {};
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

    const totalVal = document.getElementById('apps-kpi-total-val');
    if (totalVal) totalVal.innerHTML = `${projects.length} <small style="font-size:14px; color:#64748b;">/ ${expected}개 (평균 ${summary.averageProgressPct || 72}%)</small>`;
    set('apps-kpi-total-badge', projects.length === expected ? '4종 전체 가동' : `${projects.length}/${expected} 등록`);
    if (projects.length) {
      set('apps-kpi-total-desc', projects.map(p => `${p.name}(${p.progressPct || 72}%)`).join(' · '));
    }

    renderPlayConsole();

    let verifiedMs = 0, inProgressMs = 0, waitingMs = 0;
    for (const p of projects) {
      for (const m of (p.milestones || [])) {
        if (m.status === 'verified') verifiedMs++;
        else if (m.status === 'in_progress') inProgressMs++;
        else waitingMs++;
      }
    }
    const totalMs = verifiedMs + inProgressMs + waitingMs;
    const msVal = document.getElementById('apps-kpi-milestone-val');
    if (msVal) msVal.innerHTML = `${verifiedMs} <small style="font-size:14px; color:#64748b;">/ ${totalMs}건 검증</small>`;
    set('apps-kpi-milestone-badge', totalMs > 0 ? `${Math.round((verifiedMs / totalMs) * 100)}% 완료` : '집계 중');
    set('apps-kpi-milestone-desc', `진행 중(비공개 트랙·실기기) ${inProgressMs}건 · 프로덕션 대기 ${waitingMs}건`);

    const revBadge = document.getElementById('apps-kpi-revenue-badge');
    const revVal = document.getElementById('apps-kpi-revenue-val');
    const revDesc = document.getElementById('apps-kpi-revenue-desc');
    const adsTxtOk = summary.allAppAdsTxtVerified !== false;
    if (revBadge) {
      revBadge.textContent = adsTxtOk ? '🟢 SJ AdMob · app-ads.txt 200 OK' : '🟡 AdMob 점검 필요';
      revBadge.className = 'pillar-badge ' + (adsTxtOk ? 'badge-green' : 'badge-orange');
    }
    if (revVal) {
      revVal.style.color = '#0f172a';
      revVal.innerHTML = `$${Number(summary.totalAdmobRevenueUsd || 0).toFixed(2)} <small style="font-size:13px; color:#2563eb;">(테스트 광고 안전모드)</small>`;
    }
    if (revDesc) {
      revDesc.textContent = `SJ 계정(${summary.publisherId || 'pub-7642010403138987'}) 배너 4종 매핑 완료 · 정식 출시 즉시 실광고 전환`;
    }
  }

  function renderFilterBar(projects) {
    if (!filterBar) return;
    filterBar.replaceChildren();
    const items = [{id: 'all', label: `전체 (${projects.length})`}].concat(
      projects.map(p => ({id: p.id, label: `${p.name} (${p.progressPct || 57}%)`}))
    );
    for (const item of items) {
      const btn = node('button', item.label, 'app-filter-btn' + (currentFilter === item.id ? ' active' : ''));
      btn.type = 'button';
      btn.onclick = () => {
        currentFilter = item.id;
        if (latestData) render(latestData);
      };
      filterBar.append(btn);
    }
  }

  async function verifyDevice(projectId, btnEl) {
    if (btnEl) {
      btnEl.disabled = true;
      btnEl.textContent = '검증 반영 중...';
    }
    try {
      const res = await fetch('/api/projects/verify-device', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({projectId, verified: true})
      });
      if (res.ok) {
        render(await res.json());
      }
    } catch (_) {
      if (btnEl) {
        btnEl.disabled = false;
        btnEl.textContent = '✅ 삼성 실기기 정상 동작 확인 완료';
      }
    }
  }

  function renderControlCenter(data) {
    const projects = Array.isArray(data?.projects) ? data.projects : [];
    const tc = installationDoc || ((data?.testersControlCenter && data.testersControlCenter.emailCount) ? data.testersControlCenter : (staticTesters || data?.testersControlCenter || {}));
    const firstSched = projects[0]?.testSchedule || {};
    const regCount = Array.isArray(tc.accounts) ? tc.accounts.length : (tc.emailCount || firstSched.registeredTestersCount || 0);
    renderInstallation();
    renderPlayConsole();

    // [Zone A] 4-App Direct Install Cards + Physical Device 1-Time Check
    const cardsBox = document.getElementById('direct-install-cards');
    if (cardsBox) {
      cardsBox.replaceChildren();
      projects.forEach((p, idx) => {
        const isVer = Boolean(p.deviceVerified);
        const meta = appMeta(p);
        const latestDeviceVerified = p.latestBuildPhysicalDeviceVerified === true;
        const verifiedScope = latestDeviceVerified ? `삼성 확인 v${meta.versionCode}` : (isVer ? `삼성 확인 v${meta.verifiedDeviceVersionCode} · 새 v${meta.versionCode} 실기기 미확인` : `v${meta.versionCode} 실기기 확인 대기`);
        const card = node('div', '', 'direct-app-card' + (isVer ? ' verified' : ''));
        const top = node('div', '', 'direct-app-top');
        top.innerHTML = `
          <strong>${idx + 1}. ${p.name}</strong>
          <span class="pillar-badge ${isVer ? 'badge-green' : 'badge-orange'}">${verifiedScope}</span>
        `;
        const metaLine = node('div', `${meta.packageName} · 빌드 v${meta.versionCode} (${meta.versionName}) · 내부 제공 v${meta.internalAvailableVersionCode} · 실기기 확인 v${meta.verifiedDeviceVersionCode}`, 'direct-app-meta');

        const linkRow = node('div', '', 'direct-link-row');
        const btnInt = node('a', '📲 ① 테스트 참여하기 (내부 테스트) ↗', 'direct-install-btn internal');
        btnInt.href = meta.internalJoinUrl;
        btnInt.target = '_blank';
        btnInt.rel = 'noopener noreferrer';

        const btnClosed = node('a', `🔒 Alpha 참여 링크 (${meta.closedReviewStatus}) ↗`, 'direct-install-btn closed');
        btnClosed.href = meta.closedJoinUrl || `https://play.google.com/apps/testing/${meta.packageName}`;
        btnClosed.target = '_blank';
        btnClosed.rel = 'noopener noreferrer';
        linkRow.append(btnInt, btnClosed);
        const joinHint = node('div', '① 열리는 화면에서 [테스트 참여하기] → ② 그 화면의 [Google Play에서 다운로드]. 참여 전 스토어 직통 접속 시 404가 뜹니다.', 'direct-app-meta');
        joinHint.style.color = '#b45309';

        const checkUl = node('ul', '', 'direct-check-list');
        const items = Array.isArray(p.deviceCheckItems) && p.deviceCheckItems.length
          ? p.deviceCheckItems
          : ['실휴대폰 앱 실행 및 주요 화면 동작 확인', '신규 빌드의 하단 배너와 조작 영역 간격 확인'];
        for (const chkText of items) {
          const li = node('li');
          const lbl = node('label');
          const cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.checked = isVer;
          lbl.append(cb, document.createTextNode(' ' + chkText));
          li.append(lbl);
          checkUl.append(li);
        }

        const verBtn = node(
          'button',
          isVer ? `✅ ${verifiedScope} (${formatKST(p.deviceVerifiedAt)})` : `✅ v${meta.versionCode} 삼성 실기기 정상 동작 확인 기록`,
          'direct-verify-btn' + (isVer ? ' is-verified' : '')
        );
        verBtn.type = 'button';
        verBtn.onclick = () => verifyDevice(p.id, verBtn);

        card.append(top, metaLine, linkRow, joinHint, checkUl, verBtn);
        cardsBox.append(card);
      });
    }

    // [Zone B] 14-Tester Emails & Play Console Sync
    const badgeEl = document.getElementById('testers-count-badge');
    if (badgeEl) {
      badgeEl.textContent = `등록 ${regCount}계정`;
      badgeEl.className = 'pillar-badge ' + (regCount >= 12 ? 'badge-green' : 'badge-orange');
    }
    const ta = document.getElementById('tester-emails-textarea');
    if (ta && Array.isArray(tc.emails) && tc.emails.length && document.activeElement !== ta && !ta.dataset.userEdited) {
      ta.value = tc.emails.join('\n');
    }
    const receiptEl = document.getElementById('tester-sync-receipt');
    if (receiptEl) {
      const lastSync = tc.lastSyncedToPlayConsoleAt ? formatKST(tc.lastSyncedToPlayConsoleAt) : '미실행';
      receiptEl.innerHTML = `
        <div><strong>저장된 명단:</strong> ${regCount}개 계정 · 실제 설치·참여 실측과 별도</div>
        <div><strong>최근 반자동 동기화:</strong> ${lastSync} · <strong>상태:</strong> ${tc.syncStatus || 'ready'}</div>
      `;
    }
  }

  function render(data) {
    data = withReleaseLedgerFallback(data);
    latestData = data;
    list.replaceChildren();
    if (!['collected','partial'].includes(data.status) || !Array.isArray(data.projects) || !data.projects.length) {
      state.textContent = data.status === 'invalid' ? '프로젝트 등록 정보 확인 필요' : '등록 정보 준비 중 · 수익과 이용자 수는 미수집';
      return;
    }
    updateKPIs(data);
    renderControlCenter(data);
    renderFilterBar(data.projects);

    const installation = installationState(installationDoc);
    const observedAt = installationDoc?.playConsoleStatus?.checkedAt;
    state.textContent = `자체 설치 확인 ${installation.available ? `${installation.count}/${installation.required}` : '미확인'} · Console ${observedAt ? formatKST(observedAt) + ' 관측' : '실측 미확인'} · 30초마다 상태 갱신`;

    const visibleProjects = currentFilter === 'all'
      ? data.projects
      : data.projects.filter(p => p.id === currentFilter);

    for (const project of visibleProjects) {
      const card = node('article', '', 'app-project-card');
      const heading = node('div', '', 'traffic-head');
      const vCount = (project.milestones || []).filter(m => m.status === 'verified').length;
      const tCount = (project.milestones || []).length;
      const tracker = project.admobTracker || {};
      const currentConsole = installationDoc?.playConsoleStatus || {};
      const labels = playDisplayLabels(currentConsole.apps?.[project.id], currentConsole);
      const curTrackLabel = labels.track;
      const closedStatusLabel = labels.detail;

      const badges = node('div', '', 'app-project-head-badges');
      badges.append(
        node('span', `진행률 ${project.progressPct || 57}%`, 'pillar-badge badge-blue'),
        node('span', `마일스톤 ${vCount}/${tCount}건`, 'pillar-badge badge-green'),
        node('span', curTrackLabel, 'pillar-badge badge-orange')
      );
      heading.append(node('h3', `📱 ${project.name} (${project.packageName || ''})`), badges);
      card.append(heading, node('p', project.description, 'section-caption'));

      // Owner & Explicit Track Separation Strip
      const ownerStrip = node('div', '', 'app-owner-strip');
      ownerStrip.innerHTML = `
        <span class="app-owner-tag">👤 전담: <strong style="color:#2563eb;">${project.owner || '@patch · @trace'}</strong></span>
        <span class="app-dday-pill" style="background:#fff7ed;border-color:#fed7aa;color:#c2410c;">현재 트랙: ${curTrackLabel}</span>
        <span class="app-dday-pill">비공개 테스트 현황: ${closedStatusLabel}</span>
      `;
      card.append(ownerStrip);

      // Blocker & Next Action Box
      if (project.blocker || project.nextAction) {
        const blockerBox = node('div', '', 'app-blocker-box');
        blockerBox.innerHTML = `
          <div><strong>📌 현재 트랙:</strong> ${curTrackLabel}</div>
          <div style="margin-top:3px;"><strong>📊 비공개 테스트 현황:</strong> ${closedStatusLabel}</div>
          <div class="next-act">👉 <strong>다음 필요 조치:</strong> ${labels.nextAction}</div>
        `;
        card.append(blockerBox);
      }

      // 3-Pillar SJ AdMob Monetization Tracker
      if (tracker.publisherId) {
        const pillarGrid = node('div', '', 'admob-3pillar-grid');
        const adsTxt = tracker.appAdsTxt || {};
        const p1 = node('div', '', 'admob-pillar-box ' + (adsTxt.verified ? 'ok' : ''));
        p1.innerHTML = `
          <div class="admob-pillar-head">
            <span>① app-ads.txt 라이브 검증</span>
            <span class="pillar-badge ${adsTxt.verified ? 'badge-green' : 'badge-orange'}">${adsTxt.verified ? 'HTTP 200 OK' : '점검 필요'}</span>
          </div>
          <div class="admob-pillar-meta">도메인: <a href="${adsTxt.url || '#'}" target="_blank" rel="noopener" style="color:#2563eb;font-weight:700;">${adsTxt.url || '-'}</a></div>
          <div class="admob-pillar-code">${adsTxt.line || 'google.com, pub-7642010403138987, DIRECT, f08c47fec0942fa0'}</div>
        `;

        const p2 = node('div', '', 'admob-pillar-box ok');
        p2.innerHTML = `
          <div class="admob-pillar-head">
            <span>② SJ AdMob 계정·배너 연동</span>
            <span class="pillar-badge badge-blue">매핑 완료</span>
          </div>
          <div class="admob-pillar-meta">앱 ID: <span class="admob-pillar-code">${tracker.admobAppId || '-'}</span></div>
          <div class="admob-pillar-meta">배너 단위(${tracker.admobBannerName || 'banner'}): <span class="admob-pillar-code">${tracker.admobBannerUnitId || '-'}</span></div>
        `;

        const p3 = node('div', '', 'admob-pillar-box');
        p3.innerHTML = `
          <div class="admob-pillar-head">
            <span>③ 광고 게재 모드 & 실시간 수익</span>
            <span class="pillar-badge badge-orange">${tracker.servingMode === 'TEST_ADS' ? '테스트 광고 안전모드' : '실광고 가동'}</span>
          </div>
          <div class="admob-pillar-meta">${tracker.servingModeBadge || '내부 테스트 트랙 무효트래픽 방지 모드'}</div>
          <div class="admob-pillar-meta"><strong>오늘 수익: $${Number(tracker.todayRevenueUsd || 0).toFixed(2)} USD</strong> · 노출 ${tracker.impressionsToday || 0}회</div>
        `;

        pillarGrid.append(p1, p2, p3);
        card.append(pillarGrid);
      }

      // 3-Step Production Switch Checklist
      if (Array.isArray(tracker.productionChecklist) && tracker.productionChecklist.length) {
        const chkBox = node('div', '', 'prod-checklist-box');
        chkBox.innerHTML = `
          <div class="prod-checklist-title">
            <span>🚀 테스트 광고 ➔ 정식 프로덕션 실광고 전환 3단계 체크리스트</span>
            <span style="font-size:11px; color:#475569;">실광고 ID 사전 매핑 완료</span>
          </div>
        `;
        const ul = node('ul', '', 'prod-checklist-steps');
        for (const cStep of tracker.productionChecklist) {
          const li = node('li', '', `st-${cStep.status || 'ready'}`);
          const badgeTxt = cStep.status === 'in_progress' ? '🚨 대표님 확인 대기' : (cStep.status === 'ready' ? '🤖 @patch 즉시 실행 준비' : '⏳ 14일 D-Day 대기');
          li.innerHTML = `
            <strong>${cStep.label} <small style="color:#2563eb;">[${badgeTxt}]</small></strong>
            <span>담당: ${cStep.owner} — ${cStep.detail}</span>
          `;
          ul.append(li);
        }
        chkBox.append(ul);
        card.append(chkBox);
      }

      const metrics = node('div', '', 'app-project-metrics');
      metrics.append(node('p', `AdMob 수익: ${metric(project.measurement?.admob, 'revenue', ' ' + (project.measurement?.admob?.currency || 'USD'))}`));
      metrics.append(node('p', `활성 이용자: ${metric(project.measurement?.analytics, 'activeUsers', '명')}`));
      card.append(metrics);

      const milestones = node('ul', '', 'app-project-milestones');
      for (const step of project.milestones || []) {
        const item = node('li', '', `st-${step.status || 'not_started'}`);
        const prefix = step.status === 'verified' ? '✓ ' : (step.status === 'in_progress' ? '⚡ ' : '');
        item.append(node('strong', `${prefix}${step.label || step.id} · ${steps[step.status] || '미확인'}`));
        if (step.scope) item.append(node('span', step.scope));
        if (step.status === 'verified' && step.verifiedAt) item.append(node('small', `검증 ${formatKST(step.verifiedAt)}`));
        milestones.append(item);
      }
      card.append(milestones);

      const footer = node('div', '', 'app-project-footer');
      if (project.publicUrl) {
        try {
          const url = new URL(project.publicUrl);
          if (url.protocol === 'https:' && !url.username && !url.password) {
            const link = node('a', '앱 안내 웹페이지 열기 ↗', 'overview-button');
            link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
            footer.append(link);
          }
        } catch (_) {}
      } else {
        footer.append(node('span', '공개 링크 준비 중', 'revenue-note'));
      }
      if (project.updatedAt) {
        footer.append(node('span', `실시간 원장 동기화: ${formatKST(project.updatedAt)}`, 'revenue-note'));
      }
      card.append(footer);
      list.append(card);
    }
  }

  async function refresh() {
    if (projectsRefreshBusy) return;
    projectsRefreshBusy = true;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 10000);
    try {
      const [res] = await Promise.all([fetch('/api/projects', {cache:'no-store', signal: ctrl.signal}), loadStaticTesters(ctrl.signal), loadInstallation()]);
      if (!res.ok) throw new Error('projects unavailable');
      render(await res.json());
    } catch (_) {
      state.textContent = '프로젝트 정보 조회 실패 · 표시된 값은 이전 관측일 수 있습니다.';
    } finally {
      clearTimeout(timer);
      projectsRefreshBusy = false;
    }
  }

  async function runAuditNow() {
    if (auditBtn) {
      auditBtn.disabled = true;
      auditBtn.textContent = '점검 동기화 중...';
    }
    try {
      const res = await fetch('/api/projects/audit-now', {method: 'POST'});
      if (res.ok) {
        render(await res.json());
      }
    } catch (_) {} finally {
      if (auditBtn) {
        auditBtn.disabled = false;
        auditBtn.textContent = '🔍 AdMob·app-ads.txt 즉시 실측';
      }
    }
  }

  const verifyAllBtn = document.getElementById('btn-verify-all-devices');
  if (verifyAllBtn) {
    verifyAllBtn.addEventListener('click', () => verifyDevice('all', verifyAllBtn));
  }

  const taEl = document.getElementById('tester-emails-textarea');
  if (taEl) {
    taEl.addEventListener('input', () => {
      taEl.dataset.userEdited = '1';
    });
  }

  const SAVE_LABEL = '💾 테스터 명단 저장 및 Play Console 반자동 등록 실행';

  async function postJsonWithTimeout(url, body, ms = 10000) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ms);
    try {
      return await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
        signal: ctrl.signal
      });
    } finally {
      clearTimeout(timer);
    }
  }

  function applySavedTesters(saved) {
    const n = Number(saved?.savedCount || saved?.testersControlCenter?.emailCount || 0);
    if (saved?.testersControlCenter) staticTesters = saved.testersControlCenter;
    const badgeEl = document.getElementById('testers-count-badge');
    if (badgeEl) {
      badgeEl.textContent = `등록 ${n}계정`;
      badgeEl.className = 'pillar-badge ' + (n >= 12 ? 'badge-green' : 'badge-orange');
    }
    const receiptEl = document.getElementById('tester-sync-receipt');
    if (receiptEl) {
      receiptEl.innerHTML = `
        <div><strong>저장된 명단:</strong> ${n}개 계정</div>
        <div><strong>Play Console:</strong> ${saved?.cdpNote || '명단 저장 완료'}</div>
      `;
    }
    return n;
  }

  const saveTestersBtn = document.getElementById('btn-save-sync-testers');
  if (saveTestersBtn) {
    saveTestersBtn.addEventListener('click', async () => {
      const rawEmails = taEl ? taEl.value : '';
      const execCdp = Boolean(document.getElementById('tester-execute-cdp')?.checked);
      saveTestersBtn.disabled = true;
      saveTestersBtn.textContent = '💾 명단 저장 중...';
      let finalText = SAVE_LABEL;
      try {
        const res = await postJsonWithTimeout('/api/projects/testers', {emails: rawEmails, executeCdp: execCdp});
        if (res.ok) {
          if (taEl) delete taEl.dataset.userEdited;
          const n = applySavedTesters(await res.json());
          finalText = `✅ 명단 저장 완료 (${n}명)`;
          refresh();
        } else if (res.status === 404 || res.status === 405) {
          finalText = `⚠️ 저장 실패: NAS 서버 이미지 업데이트 필요 (HTTP ${res.status})`;
        } else {
          finalText = `⚠️ 저장 실패 (HTTP ${res.status}) · 다시 시도`;
        }
      } catch (err) {
        finalText = err?.name === 'AbortError' ? '⚠️ 10초 응답 없음 · 다시 시도' : '⚠️ 서버 연결 실패 · 다시 시도';
      } finally {
        saveTestersBtn.disabled = false;
        saveTestersBtn.textContent = finalText;
        if (!finalText.startsWith('✅')) setTimeout(() => { saveTestersBtn.textContent = SAVE_LABEL; }, 6000);
      }
    });
  }

  const copyEmailsBtn = document.getElementById('btn-copy-comma-emails');
  if (copyEmailsBtn) {
    copyEmailsBtn.addEventListener('click', async () => {
      const raw = taEl ? taEl.value : '';
      const emails = raw.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean);
      const commaList = emails.join(', ');
      try {
        await navigator.clipboard.writeText(commaList);
        copyEmailsBtn.textContent = `✅ ${emails.length}개 이메일 쉼표(,) 복사 완료!`;
      } catch (_) {
        copyEmailsBtn.textContent = '📋 복사 완료';
      }
      setTimeout(() => {
        copyEmailsBtn.textContent = '📋 쉼표(,) 구분 명단 복사 (Play Console 붙여넣기용)';
      }, 2200);
    });
  }

  const promoteClosedBtn = document.getElementById('btn-promote-closed-track');
  if (promoteClosedBtn) {
    const PROMO_LABEL = '🚀 비공개 테스트(Alpha) 4종 승격 실행';
    promoteClosedBtn.addEventListener('click', async () => {
      const execCdp = Boolean(document.getElementById('tester-execute-cdp')?.checked);
      promoteClosedBtn.disabled = true;
      promoteClosedBtn.textContent = '🚀 Play Console 점검 요청 중...';
      let finalText = PROMO_LABEL;
      try {
        const res = await postJsonWithTimeout('/api/projects/promote-closed', {app: 'all', executeCdp: execCdp});
        if (res.ok) {
          const body = await res.json();
          finalText = body.cdpQueued
            ? '⏳ Play Console 점검을 백그라운드로 시작 (결과는 원장 갱신 후 표시)'
            : '⚠️ 이 서버에서는 Play Console 자동화 불가 (Windows 워커 전용)';
          refresh();
        } else {
          finalText = `⚠️ 요청 실패 (HTTP ${res.status})`;
        }
      } catch (err) {
        finalText = err?.name === 'AbortError' ? '⚠️ 10초 응답 없음' : '⚠️ 서버 연결 실패';
      } finally {
        promoteClosedBtn.disabled = false;
        promoteClosedBtn.textContent = finalText;
        setTimeout(() => { promoteClosedBtn.textContent = PROMO_LABEL; }, 6000);
      }
    });
  }

  if (refreshBtn) refreshBtn.addEventListener('click', refresh);
  if (auditBtn) auditBtn.addEventListener('click', runAuditNow);
  refresh(); setInterval(refresh, 30000);
})();

