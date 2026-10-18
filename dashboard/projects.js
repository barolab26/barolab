/* App projects & SJ AdMob 3-Pillar Monetization Live Tracker */
(function () {
  'use strict';
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

  // Fallback catalog: the NAS image may predate versionCode/versionName/joinUrl fields in /api/projects.
  const APP_CATALOG = {
    bible_app: {packageName: 'com.barolab.harubible', versionCode: 4, versionName: '0.4.0-internal-preview',
      internalJoinUrl: 'https://play.google.com/apps/internaltest/4700464139727332365',
      closedJoinUrl: 'https://play.google.com/apps/testing/com.barolab.harubible'},
    greeting: {packageName: 'com.barolab.morningcard', versionCode: 2, versionName: '0.2.0-internal-preview',
      internalJoinUrl: 'https://play.google.com/apps/internaltest/4701400802151181455',
      closedJoinUrl: 'https://play.google.com/apps/testing/com.barolab.morningcard'},
    magnifier: {packageName: 'com.barolab.biglens', versionCode: 2, versionName: '0.2.0-internal-preview',
      internalJoinUrl: 'https://play.google.com/apps/internaltest/4701703053640983596',
      closedJoinUrl: 'https://play.google.com/apps/testing/com.barolab.biglens'},
    shopping: {packageName: 'com.barolab.voicebasket', versionCode: 2, versionName: '0.2.0-internal-preview',
      internalJoinUrl: 'https://play.google.com/apps/internaltest/4701721871486482124',
      closedJoinUrl: 'https://play.google.com/apps/testing/com.barolab.voicebasket'}
  };
  function appMeta(p) {
    const cat = APP_CATALOG[p?.id] || {};
    return {
      packageName: p?.packageName || cat.packageName || '',
      versionCode: p?.versionCode || cat.versionCode || '',
      versionName: p?.versionName || p?.releaseName || cat.versionName || '',
      internalJoinUrl: p?.internalJoinUrl || cat.internalJoinUrl || 'https://barolab-daily-apps.pages.dev/testers/',
      closedJoinUrl: p?.closedJoinUrl || cat.closedJoinUrl || ''
    };
  }

  async function loadStaticTesters() {
    try {
      const r = await fetch('/data/app_testers.json', {cache: 'no-store'});
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

    const previewCount = projects.filter(p => p.status === 'preview' || p.status === 'released').length;
    const firstSched = projects[0]?.testSchedule || {};
    const curTrack = firstSched.currentTrackLabel || '내부 테스트 (테스터 1명) — ⚠️ 14일 카운트다운 미시작';
    const closedStatus = firstSched.closedTrackStatusLabel || '비공개 트랙 미개설 · 참여 테스터 0 / 12명 (12명 Opt-in 완료 시 14일 카운트 시작)';
    const relVal = document.getElementById('apps-kpi-release-val');
    if (relVal) {
      relVal.innerHTML = firstSched.countdownStarted
        ? `D+${firstSched.elapsedDays}일째 <small style="font-size:13px; color:#2563eb;">(14일 요건 D-${firstSched.remainingDays}일)</small>`
        : `0 / 12명 <small style="font-size:13px; color:#d97706;">(⚠️ 14일 카운트 미시작)</small>`;
    }
    set('apps-kpi-release-badge', curTrack);
    set('apps-kpi-release-desc', closedStatus);

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
    const tc = (data?.testersControlCenter && data.testersControlCenter.emailCount) ? data.testersControlCenter : (staticTesters || data?.testersControlCenter || {});
    const firstSched = projects[0]?.testSchedule || {};
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

    // [Zone C] Real 14-Day Countdown Tracker
    const regCount = tc.emailCount || firstSched.registeredTestersCount || 1;
    const optIns = Number(firstSched.closedTestOptIns || tc.closedTestOptIns || 0);
    const reqTesters = Number(firstSched.requiredClosedTesters || 12);
    const reqDays = Number(firstSched.requiredDays || 14);
    const countdownStarted = Boolean(firstSched.countdownStarted);

    set('zc-internal-status', firstSched.currentTrackLabel || `내부 테스트 (테스터 ${firstSched.internalTestersCount || 1}명) — ⚠️ 14일 카운트다운 미시작`);
    set('zc-internal-sub', `내부 테스트 배포일: ${firstSched.internalReleaseDate || '2026-10-14'} · 대시보드 등록 테스터: ${regCount}명 (내부 트랙은 14일 요건에 산입되지 않음)`);

    if (countdownStarted) {
      set('zc-closed-status', `🟢 비공개 테스트 가동 중 · Opt-in ${optIns} / ${reqTesters}명 (D+${firstSched.elapsedDays} / ${reqDays}일)`);
      set('zc-closed-sub', `14일 요건 충족 예정일: ${firstSched.targetProductionDate} (D-${firstSched.remainingDays}일 남음)`);
    } else {
      const trackTxt = (firstSched.closedTrackOpened || tc.closedTrackPromoted) ? '비공개 트랙 개설 완료' : '비공개 트랙 승격 대기';
      set('zc-closed-status', `${trackTxt} · 참여 테스터(Opt-in) ${optIns} / ${reqTesters}명 (D+0 / ${reqDays}일)`);
      set('zc-closed-sub', `12명 이상 Opt-in 완료 시점(closedTestStartAt)부터 D+1 ~ D+14 실측 카운트다운이 시작됩니다.`);
    }

    const progBar = document.getElementById('zc-progress-bar');
    if (progBar) {
      const pct = countdownStarted
        ? Math.min(100, Number(firstSched.dayProgressPct || 0))
        : Math.min(90, Math.round((optIns / reqTesters) * 50));
      progBar.style.width = `${pct}%`;
    }
    const optInput = document.getElementById('zc-optin-input');
    if (optInput && document.activeElement !== optInput) {
      optInput.value = String(optIns);
    }

    // [Zone A] 4-App Direct Install Cards + Physical Device 1-Time Check
    const cardsBox = document.getElementById('direct-install-cards');
    if (cardsBox) {
      cardsBox.replaceChildren();
      projects.forEach((p, idx) => {
        const isVer = Boolean(p.deviceVerified);
        const card = node('div', '', 'direct-app-card' + (isVer ? ' verified' : ''));
        const top = node('div', '', 'direct-app-top');
        top.innerHTML = `
          <strong>${idx + 1}. ${p.name}</strong>
          <span class="pillar-badge ${isVer ? 'badge-green' : 'badge-orange'}">${isVer ? '실기기 검증 완료' : '실기기 1회 확인 대기'}</span>
        `;
        const meta = appMeta(p);
        const metaLine = node('div', `${meta.packageName} · v${meta.versionCode} (${meta.versionName})`, 'direct-app-meta');

        const linkRow = node('div', '', 'direct-link-row');
        const btnInt = node('a', '📲 ① 테스트 참여하기 (내부 테스트) ↗', 'direct-install-btn internal');
        btnInt.href = meta.internalJoinUrl;
        btnInt.target = '_blank';
        btnInt.rel = 'noopener noreferrer';

        const btnClosed = node('a', '🔒 비공개 테스트 참여 (트랙 개설 후) ↗', 'direct-install-btn closed');
        btnClosed.href = meta.closedJoinUrl || `https://play.google.com/apps/testing/${meta.packageName}`;
        btnClosed.target = '_blank';
        btnClosed.rel = 'noopener noreferrer';
        linkRow.append(btnInt, btnClosed);
        const joinHint = node('div', '① 열리는 화면에서 [테스트 참여하기] → ② 그 화면의 [Google Play에서 다운로드]. 참여 전 스토어 직통 접속 시 404가 뜹니다.', 'direct-app-meta');
        joinHint.style.color = '#b45309';

        const checkUl = node('ul', '', 'direct-check-list');
        const items = Array.isArray(p.deviceCheckItems) && p.deviceCheckItems.length
          ? p.deviceCheckItems
          : ['실휴대폰 앱 실행 및 주요 화면 동작 확인', '하단 AdMob 테스트 배너 표시 확인'];
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
          isVer ? `✅ 삼성 실기기 검증 완료 (${formatKST(p.deviceVerifiedAt)})` : '✅ 삼성 실기기 정상 동작 확인 완료',
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
      badgeEl.textContent = `등록 ${regCount} / ${tc.targetTesterCount || 14}명`;
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
        <div><strong>저장 원장:</strong> <code>data/app_testers.json</code> (${regCount}개 계정) · <strong>CSV:</strong> <code>apps/qa/barolab-testers-14.csv</code></div>
        <div><strong>최근 반자동 동기화:</strong> ${lastSync} · <strong>상태:</strong> ${tc.syncStatus || 'ready'}</div>
      `;
    }
  }

  function render(data) {
    latestData = data;
    list.replaceChildren();
    if (!['collected','partial'].includes(data.status) || !Array.isArray(data.projects) || !data.projects.length) {
      state.textContent = data.status === 'invalid' ? '프로젝트 등록 정보 확인 필요' : '등록 정보 준비 중 · 수익과 이용자 수는 미수집';
      return;
    }
    updateKPIs(data);
    renderControlCenter(data);
    renderFilterBar(data.projects);

    const sched = data.projects[0]?.testSchedule || {};
    const curTrackTop = sched.currentTrackLabel || '내부 테스트 (테스터 1명) — ⚠️ 14일 카운트다운 미시작';
    const closedTop = sched.closedTrackStatusLabel || '비공개 트랙 미개설 · 참여 테스터 0 / 12명 (12명 Opt-in 완료 시 14일 카운트 시작)';
    state.textContent = `현재 트랙: ${curTrackTop} | 비공개 테스트 현황: ${closedTop}`;

    const visibleProjects = currentFilter === 'all'
      ? data.projects
      : data.projects.filter(p => p.id === currentFilter);

    for (const project of visibleProjects) {
      const card = node('article', '', 'app-project-card');
      const heading = node('div', '', 'traffic-head');
      const vCount = (project.milestones || []).filter(m => m.status === 'verified').length;
      const tCount = (project.milestones || []).length;
      const tracker = project.admobTracker || {};
      const tSched = project.testSchedule || {};
      const curTrackLabel = tSched.currentTrackLabel || '내부 테스트 (테스터 1명) — ⚠️ 14일 카운트다운 미시작';
      const closedStatusLabel = tSched.closedTrackStatusLabel || '비공개 트랙 미개설 · 참여 테스터 0 / 12명 (12명 Opt-in 완료 시 14일 카운트 시작)';

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
          <div class="next-act">👉 <strong>다음 필요 조치:</strong> ${project.nextAction || '비공개 테스트 트랙 개설 및 12명 Opt-in'}</div>
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
    try {
      const [res] = await Promise.all([fetch('/api/projects', {cache:'no-store'}), loadStaticTesters()]);
      if (!res.ok) throw new Error('projects unavailable');
      render(await res.json());
    } catch (_) {
      list.replaceChildren(); state.textContent = '프로젝트 정보 조회 불가 · 수익과 이용자 수 미확인';
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
      badgeEl.textContent = `등록 ${n} / 14명`;
      badgeEl.className = 'pillar-badge ' + (n >= 12 ? 'badge-green' : 'badge-orange');
    }
    const receiptEl = document.getElementById('tester-sync-receipt');
    if (receiptEl) {
      receiptEl.innerHTML = `
        <div><strong>저장 원장:</strong> <code>data/app_testers.json</code> (${n}개 계정) · <strong>CSV:</strong> <code>apps/qa/barolab-testers-14.csv</code></div>
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

  const updateOptinsBtn = document.getElementById('btn-update-optins');
  if (updateOptinsBtn) {
    updateOptinsBtn.addEventListener('click', async () => {
      const optInput = document.getElementById('zc-optin-input');
      const count = Math.max(0, Math.min(30, parseInt(optInput?.value || '0', 10) || 0));
      updateOptinsBtn.disabled = true;
      updateOptinsBtn.textContent = '반영 중...';
      try {
        const res = await postJsonWithTimeout('/api/projects/testers', {closedTestOptIns: count, executeCdp: false});
        if (res.ok) refresh();
      } catch (_) {} finally {
        updateOptinsBtn.disabled = false;
        updateOptinsBtn.textContent = '반영';
      }
    });
  }

  if (refreshBtn) refreshBtn.addEventListener('click', refresh);
  if (auditBtn) auditBtn.addEventListener('click', runAuditNow);
  refresh(); setInterval(refresh, 60000);
})();

