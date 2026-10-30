// Shared synchronous sidebar. Keep navigation markup and badge sync in this file only.
(() => {
  const host = document.getElementById('barolab-sidebar');
  if (!host) return;
  host.outerHTML = `<aside id="barolab-sidebar" class="sidebar" aria-label="주요 메뉴"><div class="brand"><div class="brand-badge" aria-hidden="true">B</div><div class="brand-text"><strong>BAROLAB</strong><span>DECK v3</span></div></div><nav class="nav" aria-label="대시보드"><div class="nav-label">종합 관제</div><a class="nav-item" href="index.html"><span class="nav-icon" aria-hidden="true">&#127968;</span><div><strong>통합 종합상황실</strong><small>할일·색인·방문자·수익</small></div><span class="badge-count st-green">LIVE</span></a>
<a class="nav-item" href="growth.html"><span class="nav-icon" aria-hidden="true">&#128200;</span><div><strong>성장 대시보드</strong><small>방문자 추세 &amp; 애드센스</small></div><span class="badge-count st-blue">GA4</span></a>
<a class="nav-item" href="memory.html"><span class="nav-icon" aria-hidden="true">&#10022;</span><div><strong>기억 그래프 (Vault)</strong><small>자율 학습 대기 ✦</small></div><span class="badge-count st-green" id="memory-sidebar-count">0</span></a>
<a class="nav-item" href="chat.html"><span class="nav-icon" aria-hidden="true">&#128172;</span><div><strong>AI 크루 회의실</strong><small>팀장·닥터·퍼블리·트레이스·패치·레이더</small></div><span class="badge-count st-green">6인</span></a>
<div class="nav-label">채널별 상세 대시보드</div><a class="nav-item" href="naver.html"><span class="nav-icon" aria-hidden="true">&#128994;</span><div><strong>네이버 블로그 (5)</strong><small>3대 전략 로테이션 &amp; CDP</small></div><span class="badge-count st-green" id="naver-sidebar-count">5계정</span></a>
<a class="nav-item" href="cf.html"><span class="nav-icon" aria-hidden="true">&#9889;</span><div><strong>CF 블로그 (16)</strong><small>MustPick 허브 · 애드센스</small></div><span class="badge-count st-blue" id="cf-sidebar-count">16도메인</span></a>
<a class="nav-item" href="kin.html"><span class="nav-icon" aria-hidden="true">&#128161;</span><div><strong>네이버 지식iN</strong><small id="kin-sidebar-note">계정 교대 · 운영 기록 확인 중</small></div><span class="badge-count st-green" id="kin-sidebar-status">대기</span></a>
<a class="nav-item" href="threads.html"><span class="nav-icon" aria-hidden="true">@</span><div><strong>Threads</strong><small id="threads-sidebar-note">@mustpickinfo · 연결 대기</small></div><span class="badge-count st-amber" id="threads-sidebar-status">연결 대기</span></a>
<a class="nav-item" href="brunch.html"><span class="nav-icon" aria-hidden="true">&#128214;</span><div><strong>브런치 스토리</strong><small id="brunch-sidebar-note">머스트픽 · 작가 심사 중</small></div><span class="badge-count st-blue" id="brunch-sidebar-status">서랍 3편</span></a>
<a class="nav-item" href="premium.html"><span class="nav-icon" aria-hidden="true">&#11088;</span><div><strong>프리미엄콘텐츠</strong><small id="premium-sidebar-note">yoon_master · 심사 진행 중</small></div><span class="badge-count st-amber" id="premium-sidebar-status">심사중</span></a>
<div class="nav-label">앱 프로젝트</div><a class="nav-item" href="apps.html"><span class="nav-icon" aria-hidden="true">&#128241;</span><div><strong id="apps-sidebar-title">앱 프로젝트 (4)</strong><small>생활 앱 · 출시 &amp; 수익화 관제</small></div><span class="badge-count st-blue" id="apps-sidebar-count">4종</span></a>
<div class="nav-label">향후 확장 예정</div>
<div class="nav-item" aria-disabled="true"><span class="nav-icon" aria-hidden="true">&#128308;</span><div><strong>티스토리 (14)</strong><small>Google 애드센스 다계정</small></div><span class="badge-count">준비중</span></div>
<div class="nav-item" aria-disabled="true"><span class="nav-icon" aria-hidden="true">&#9749;</span><div><strong>네이버 카페</strong><small>외부유입 바이럴</small></div><span class="badge-count">대기</span></div>
</nav><div class="sidebar-assistant"><div class="assistant-head"><span>&#129302; MASTER AI</span><span style="color:#10b981;">● ON</span></div><p class="assistant-quote">CF 16 · 네이버 5 · 닥터 EXIF 세탁 엔진 가동 중</p></div><a class="nav-item sidebar-settings" href="settings.html"><span class="nav-icon" aria-hidden="true">&#9881;&#65039;</span><div><strong>설정 · API 연결</strong><small>API / LLM 모델 연결</small></div></a><div class="sidebar-footer"><span>BaroLab Deck</span><span>KST</span></div></aside>`;
  const sidebar = document.getElementById('barolab-sidebar');
  function updateActivePage() {
    const page = location.pathname.split('/').pop() || 'index.html';
    if (page === 'rnd.html') {
      location.replace('chat.html');
      return;
    }
    if (page === 'index.html' && location.hash === '#app-projects') {
      location.replace('apps.html');
      return;
    }
    sidebar.querySelectorAll('a.nav-item').forEach(link => {
      const target = new URL(link.getAttribute('href'), location.href);
      const targetPage = target.pathname.split('/').pop();
      const active = targetPage === page && !target.hash;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }
  updateActivePage();
  window.addEventListener('hashchange', updateActivePage);
  function updateKinState(state) {
    const badge = document.getElementById('kin-sidebar-status');
    const note = document.getElementById('kin-sidebar-note');
    if (!badge || !note) return;
    const data = state && state.data;
    const automation = data && data.automation || {};
    let label = '미확인', detail = '운영 기록 미확인';
    if (!state || state.status === 'loading') {label = '조회 중';detail = '계정 교대 · 운영 기록 확인 중';}
    else if (state.status === 'error') {label = '조회 실패';detail = '운영 기록 조회 실패';}
    else if (state.stale) {label = '갱신 필요';detail = '운영 기록이 오래됨 · 상세 확인';}
    else if (automation.activeRunId) {label = '작업 중';detail = '단일 회차 진행 · 종료 후 60분 대기';}
    else if (automation.cadenceState === 'experiment_completed') {label = '시험 종료';detail = '게시 시험 종료 · 유입 측정 보완은 별도 진행';}
    else if (automation.enabled === false) {label = '꺼짐';detail = '자동 운영 설정 꺼짐';}
    else {
      const observed = automation.lastRun && automation.lastRun.registeredTasks || data && data.schedule && data.schedule.registeredTasks;
      const observedAt = observed && Date.parse(observed.checkedAt);
      const task = observed && observed.status === 'observed' && Number.isFinite(observedAt)
        && Date.now() - observedAt >= -60000 && Date.now() - observedAt < 30 * 60000 && Array.isArray(observed.tasks)
        ? observed.tasks.find(item => item.taskName === 'BaroLab-Kin-Seven-Day-Pilot') : null;
      if (task && task.registered === true && task.enabled === true && automation.enabled === true) {
        label = '대기';detail = '계정 교대 · 종료 후 최소 60분';
      } else if (task && (task.registered === false || task.enabled === false)) {
        label = '작업 확인';detail = '자동 실행 작업 등록·활성 상태 확인 필요';
      } else {label = '확인 필요';detail = '설정과 실제 자동 실행 기록을 확인하세요';}
    }
    if (window.BaroLabKinSummary && typeof window.BaroLabKinSummary.operationState === 'function') {
      const operation = window.BaroLabKinSummary.operationState(state || {status:'loading',data:null,stale:true});
      label = operation.label;detail = operation.detail;
    }
    badge.textContent = label;note.textContent = detail;
    const model = document.getElementById('kin-settings-model');
    const accounts = document.getElementById('kin-settings-accounts');
    if (model) model.textContent = data
      ? (typeof automation.model === 'string' && automation.model ? automation.model + (automation.provider === 'authenticated-codex-subscription' ? ' · Codex · 추론 '+(automation.reasoningEffort || '미기록')+' · 최근 실행' : '') + (state.stale || state.status === 'error' ? ' · 마지막 기록' : '') : '운영 기록에 전용 모델 정보 없음')
      : (state && state.status === 'error' ? '조회 실패' : '조회 중');
    if (accounts) accounts.textContent = data && Array.isArray(data.accounts) && data.accounts.length
      ? data.accounts.join(' · ') : '계정 기록 미확인';
  }
  updateKinState(window.BaroLabKinSummary && window.BaroLabKinSummary.getState());
  window.addEventListener('barolab-kin-updated', event => updateKinState(event.detail));

  // Ensure every page shows the exact same live sidebar badges even without page-specific summary scripts
  async function syncSharedSidebarBadges() {
    if (typeof fetch !== 'function') return;
    // The memory page owns its badge through the validated, pinned API.
    // Avoid an extra legacy-origin graph GET (and a stale count overwriting it).
    const memoryPage = location.pathname.split('/').pop() === 'memory.html';
    if (memoryPage) {
      const memBadge = document.getElementById('memory-sidebar-count');
      if (memBadge) memBadge.textContent = '—';
    }
    // 1. Memory Graph count on other pages
    if (!memoryPage) try {
      const res = await fetch('/api/memory/summary', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
      if (res && res.ok) {
        const data = await res.json();
        const total = data?.stats?.total ?? data?.stats?.total_nodes ?? (Array.isArray(data?.nodes) ? data.nodes.length : null);
        const memBadge = document.getElementById('memory-sidebar-count');
        if (memBadge && Number.isFinite(total)) memBadge.textContent = String(total);
      }
    } catch (_) {}

    // 2. App Projects count
    try {
      const res = await fetch('/api/projects', { cache: 'no-store' });
      if (res && res.ok) {
        const data = await res.json();
        const count = Array.isArray(data?.projects) ? data.projects.length : null;
        if (Number.isFinite(count) && count > 0) {
          const appBadge = document.getElementById('apps-sidebar-count');
          const appTitle = document.getElementById('apps-sidebar-title');
          if (appBadge) appBadge.textContent = String(count);
          if (appTitle) appTitle.textContent = `앱 프로젝트 (${count})`;
        }
      }
    } catch (_) {}

    // 3. KnowledgeIn status fallback when kin-summary.js is not loaded on this page
    if (!window.BaroLabKinSummary) {
      try {
        const res = await fetch('data/kin.json', { cache: 'no-store' });
        if (res && res.ok) {
          const data = await res.json();
          const checked = Date.parse(data?.checkedAt);
          const stale = !Number.isFinite(checked) || Date.now() - checked > 30 * 60000;
          updateKinState({ status: 'ready', data, stale });
        } else {
          updateKinState({ status: 'error', data: null, stale: true });
        }
      } catch (_) {
        updateKinState({ status: 'error', data: null, stale: true });
      }
    }

    // 4. Brunch Story sidebar status sync
    try {
      const bRes = await fetch('/api/brunch', { cache: 'no-store' });
      if (bRes && bRes.ok) {
        const bData = await bRes.json();
        const bBadge = document.getElementById('brunch-sidebar-status');
        const bNote = document.getElementById('brunch-sidebar-note');
        const dCnt = bData?.kpi?.drawerCount ?? 3;
        const pCnt = bData?.kpi?.publishedCount ?? 0;
        const approved = bData?.account?.canPublishLive === true;
        if (bBadge) {
          bBadge.textContent = approved ? `발행 ${pCnt}편` : `서랍 ${dCnt}편`;
          bBadge.className = `badge-count ${approved ? 'st-green' : 'st-blue'}`;
        }
        if (bNote) {
          bNote.textContent = approved ? `머스트픽 · 작가 가동중` : `머스트픽 · 작가 심사 중`;
        }
      }
    } catch (_) {}
  }
  syncSharedSidebarBadges();
})();
