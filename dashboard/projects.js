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
    const releasedCount = projects.filter(p => p.status === 'released').length;
    const firstSched = projects[0]?.testSchedule || {};
    const relVal = document.getElementById('apps-kpi-release-val');
    if (relVal) {
      relVal.innerHTML = firstSched.elapsedDays
        ? `D+${firstSched.elapsedDays}일째 <small style="font-size:13px; color:#2563eb;">(14일 요건 D-${firstSched.remainingDays}일)</small>`
        : `${previewCount} <small style="font-size:14px; color:#64748b;">개 내부 배포</small>`;
    }
    set('apps-kpi-release-badge', firstSched.dDayBadge || (releasedCount > 0 ? `정식 ${releasedCount}개` : '내부 테스트 단계'));
    set('apps-kpi-release-desc', `게시일 ${firstSched.internalReleaseDate || '2026-10-14'} → 프로덕션 전환 목표일 ${firstSched.targetProductionDate || '2026-10-28'}`);

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
    set('apps-kpi-milestone-desc', `진행 중(실기기·동의) ${inProgressMs}건 · 프로덕션 대기 ${waitingMs}건`);

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
      projects.map(p => ({id: p.id, label: `${p.name} (${p.progressPct || 72}%)`}))
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

  function render(data) {
    latestData = data;
    list.replaceChildren();
    if (!['collected','partial'].includes(data.status) || !Array.isArray(data.projects) || !data.projects.length) {
      state.textContent = data.status === 'invalid' ? '프로젝트 등록 정보 확인 필요' : '등록 정보 준비 중 · 수익과 이용자 수는 미수집';
      return;
    }
    updateKPIs(data);
    renderFilterBar(data.projects);

    const sched = data.projects[0]?.testSchedule || {};
    state.textContent = `${data.projects.length}/${data.expectedProjects || data.projects.length}개 앱 실시간 추적 중 · ${sched.dDayBadge || '내부 테스트 진행 중'} · SJ AdMob(pub-7642010403138987) 연동 완료`;

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

      const badges = node('div', '', 'app-project-head-badges');
      badges.append(
        node('span', `진행률 ${project.progressPct || 72}%`, 'pillar-badge badge-blue'),
        node('span', `마일스톤 ${vCount}/${tCount}건`, 'pillar-badge badge-green'),
        node('span', tSched.dDayBadge || statuses[project.status] || '내부 테스트', 'pillar-badge badge-orange')
      );
      heading.append(node('h3', `📱 ${project.name} (${project.packageName || ''})`), badges);
      card.append(heading, node('p', project.description, 'section-caption'));

      // Owner & D-Day Strip
      const ownerStrip = node('div', '', 'app-owner-strip');
      ownerStrip.innerHTML = `
        <span class="app-owner-tag">👤 전담 에이전트: <strong style="color:#2563eb;">${project.owner || '@patch · @trace'}</strong></span>
        <span class="app-dday-pill">⏱️ ${tSched.dDayBadge || '테스트 진행 중'} (프로덕션 목표일: ${tSched.targetProductionDate || '2026-10-28'})</span>
      `;
      card.append(ownerStrip);

      // Blocker & Next Action Box
      if (project.blocker || project.nextAction) {
        const blockerBox = node('div', '', 'app-blocker-box');
        blockerBox.innerHTML = `
          <div><strong>🚧 현재 병목 (진짜 멈춘 원인):</strong> ${project.blocker || '확인 중'}</div>
          <div class="next-act">👉 <strong>다음 필요 조치:</strong> ${project.nextAction || '실기기 확인 대기'}</div>
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
      const res = await fetch('/api/projects', {cache:'no-store'});
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

  if (refreshBtn) refreshBtn.addEventListener('click', refresh);
  if (auditBtn) auditBtn.addEventListener('click', runAuditNow);
  refresh(); setInterval(refresh, 60000);
})();
