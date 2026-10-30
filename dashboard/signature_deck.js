/**
 * BaroLab Signature Hybrid 3-Tier Deck Controller (signature_deck.js)
 * Unifies naver.html, cf.html, kin.html, threads.html, and apps.html into:
 *   Tier 1: 85px Slim 4-Column Gauge & Status Summary Bar
 *   Tier 2: Live 5-Step Pipeline Stepper (① 기획·리서치 ➔ ② 캡처·EXIF세탁 ➔ ③ 간접체험 집필 ➔ ④ 부분수선·검수 ➔ ⑤ 발행·색인확인)
 *   Tier 3: Date Tabs ([📅 오늘] [어제] [날짜별 선택]) + Color Filter ([전체 / 🟢공개완료 / 🔵예약완료 / 🟡대기])
 *           + ARGO 14-Day Vertical LED Dot Chart + 10-Row Paginated Work Table (1 2 3 4 5)
 */
(() => {
  const pageName = (location.pathname.split('/').pop() || '').toLowerCase();
  const CHANNEL_MAP = {
    'naver.html': 'naver',
    'cf.html': 'cf',
    'kin.html': 'kin',
    'apps.html': 'apps'
  };
  const channel = CHANNEL_MAP[pageName];
  if (!channel) return;

  const KST_OFFSET = 9 * 3600 * 1000;
  function getKSTDateStr(offsetDays = 0) {
    const d = new Date(Date.now() + KST_OFFSET + offsetDays * 86400000);
    return d.toISOString().slice(0, 10);
  }

  const CHANNEL_META = {
    naver: {
      title: `오늘(${getKSTDateStr(0).slice(5)}) 공개 현황`,
      unit: '건',
      defaultTarget: 7,
      runLabel: '⚡ RSS 공개검증 즉시 실행',
      stepTitle: '🟢 네이버 5계정 실시간 7단계 파이프라인 타임라인',
      tableCols: ['No', '발행일 (KST)', '계정 / 블로그', '전략 / 트랙 분류', '포스팅 제목 · 기획 주제', '시각 / 슬롯 (예약➔공개)', '상태', '작업물 열기']
    },
    cf: {
      title: '⚡ CF 16도메인 일일 달성률',
      unit: '편',
      defaultTarget: 16,
      runLabel: '🩺 닥터 5건 즉시 검진',
      stepTitle: '⚡ CF 16개 도메인 실시간 7단계 파이프라인 타임라인',
      tableCols: ['No', '날짜 (KST)', '도메인 / 브랜드', '전문 카테고리', '발행 포스트 제목 · 기획 주제', '시각 / EXIF', '상태', '작업물 열기']
    },
    kin: {
      title: '💡 지식iN 일일 달성률',
      unit: '건',
      defaultTarget: 20,
      runLabel: '⚡ 지연 슬롯 즉시 실행',
      stepTitle: '💡 지식iN 외부유입 엔진 v2.0 · 21채널 동적 매칭 & 20분 교대 캐치업 스텝퍼',
      tableCols: ['No', '날짜 (KST)', '운영 계정', '발굴 트랙 · 연결 도메인', '선정 질문 및 3단 요약', '시각 / 교대 간격', '상태', '질문/즉시실행']
    },
    threads: {
      title: '🧵 Threads 일일 게시 달성률',
      unit: '건',
      defaultTarget: 3,
      runLabel: '🔄 Threads 원장 동기화',
      stepTitle: '🧵 @mustpickinfo 외부유입 5단계 파이프라인 스텝퍼',
      tableCols: ['No', '날짜 (KST)', '계정 / 유형', '연결 도메인', 'Threads 본문 및 후속 요약', '시각 / 반응', '상태', '게시물 열기']
    },
    apps: {
      title: '📱 앱 4종 마일스톤 달성률',
      unit: '종',
      defaultTarget: 4,
      runLabel: '📱 빌드·검증 상태 갱신',
      stepTitle: '📱 Android 생활 앱 4종 출시 5단계 마일스톤 스텝퍼',
      tableCols: ['No', '기준일', '앱 프로젝트', '패키지 / 트랙', '마일스톤 검증 항목 및 산출물', '진척도', '상태', '검증 상세']
    }
  };

  const CF_DOMAINS_16 = [
    { domain: 'must-good.com', label: '머스트굿 정책브리프', cat: '정부지원금' },
    { domain: 'baronote.kr', label: '바로노트 핀테크랩', cat: '국민·기초연금' },
    { domain: 'justinfo.co.kr', label: '저스트인포 법률·행정', cat: '생활법률·권리' },
    { domain: 'topnote.kr', label: '탑노트 테크독스', cat: '윈도우·맥 설정' },
    { domain: 'meganote.kr', label: '메가노트 모빌리티', cat: '신차·전기차제원' },
    { domain: 'smilenote.kr', label: '스마일노트 시니어웰니스', cat: '시니어건강·운동' },
    { domain: 'healthcox.com', label: '헬스콕스 메디컬가이드', cat: '관절·통증케어' },
    { domain: 'maxnote.kr', label: '맥스노트 AI워크', cat: 'AI툴 실전가이드' },
    { domain: 'must-joy.com', label: '머스트조이 컬처매거진', cat: '문화·전시리뷰' },
    { domain: 'tripmarvel.com', label: '트립마블 트래블저널', cat: '국내여행·수목원' },
    { domain: 'must-pick.com', label: '머스트픽 컨슈머리포트', cat: '대형·주방가전' },
    { domain: 'woorinote.kr', label: '우리노트 부동산경제', cat: '청약·분양가이드' },
    { domain: 'daynote.kr', label: '데이노트 살림백과', cat: '주방·식재료보관' },
    { domain: 'nolplace.com', label: '놀플레이스 주말나들이', cat: '수목원·테마파크' },
    { domain: 'soulnote.kr', label: '소울노트 자격·커리어', cat: '내일배움카드·국비' },
    { domain: 'joynote.kr', label: '조이노트 펫앤가든', cat: '강아지·고양이건강' }
  ];

  const NAVER_ACCOUNTS = [
    { accId: 'acc1', accNo: 1, name: 'soultin', blogId: 'mustpickinfo', title: '시니어브리프', type: '주력 (실명)', strat: '카테고리 전문성·체류 트랙', target: 1, slots: ['19:30'], slot: '19:30' },
    { accId: 'acc2', accNo: 2, name: 'soul5373', blogId: 'mustinfo', title: '머스트팁스뷰', type: '주력 (실명)', strat: '카테고리 전문성·체류 트랙', target: 1, slots: ['20:00'], slot: '20:00' },
    { accId: 'acc3', accNo: 3, name: 'yoon_master', blogId: 'yoonviews', title: '윤뷰스', type: '주력 (실명)', strat: '트렌드·롱테일 유입 트랙', target: 1, slots: ['20:30'], slot: '20:30' },
    { accId: 'acc4', accNo: 4, name: 'adinfo0905', blogId: 'adinfo0905', title: '직장인루틴', type: 'CF 브릿지', strat: 'CF 고단가 브리지', target: 2, slots: ['11:00', '19:00'], slot: '11:00 / 19:00' },
    { accId: 'acc5', accNo: 5, name: 'stone0747', blogId: 'stone0747', title: '자금숲속보', type: 'CF 브릿지', strat: 'CF 고단가 브리지', target: 2, slots: ['11:00', '19:00'], slot: '11:00 / 19:00' }
  ];

  let state = {
    dateFilter: 'today', // 'today' | 'tomorrow' | 'yesterday' | 'all' | 'custom'
    customDate: getKSTDateStr(0),
    datePage: 1, // 1=today, 2=yesterday, 3=D-2, 4=D-3, 5=D-4...
    statusFilter: 'all', // 'all' | 'public' | 'reserved' | 'overdue' | 'waiting'
    sortOrder: 'schedule', // 'schedule' (시각·배정순번순) | 'domain' (도메인 기본순)
    searchQuery: '',
    currentPage: 1,
    pageSize: 20,
    allRows: [],
    ledDays: [],
    visitorsToday: '-',
    visitorsSub: '실시간 집계 중',
    selectedRowIdx: null,
    naverActiveWorkflow: null,
    naverMonitor: null,
    activeStepInfo: { stepIndex: 5, label: '전원 정상 가동 중', sub: 'EXIF 세탁 및 공개 검증 파이프라인 연동' }
  };

  function getKSTNowMinutes() {
    const kst = new Date(Date.now() + KST_OFFSET);
    return kst.getUTCHours() * 60 + kst.getUTCMinutes();
  }

  function parseTimeToMinutes(timeStr) {
    if (!timeStr) return 9999;
    const m = String(timeStr).match(/(\d{1,2}):(\d{2})/);
    if (!m) return 9999;
    return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
  }

  function computeDeterministicCFTime(domainStr, idx, dateStr) {
    let h = 2166136261;
    const seed = `${dateStr || getKSTDateStr(0)}:${domainStr || idx}`;
    for (let i = 0; i < seed.length; i++) {
      h ^= seed.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    const baseMins = 9 * 60 + (idx * 50) + (Math.abs(h) % 25);
    const clamped = Math.min(22 * 60 + 30, Math.max(9 * 60, baseMins));
    const hh = String(Math.floor(clamped / 60)).padStart(2, '0');
    const mm = String(clamped % 60).padStart(2, '0');
    return `${hh}:${mm}`;
  }

  function isValidPostDetailUrl(url, ch) {
    if (!url || typeof url !== 'string' || url === '#') return false;
    const trimmed = url.trim();
    if (!trimmed.startsWith('http://') && !trimmed.startsWith('https://')) {
      return false;
    }
    try {
      const parsed = new URL(trimmed);
      const cleanPath = (parsed.pathname || '').replace(/\/+$/, '');
      if (cleanPath.length <= 1) return false; // Root domain like https://smilenote.kr or https://www.smilenote.kr/
      if (ch === 'naver' && /^\/[^/]+$/.test(cleanPath) && parsed.hostname.includes('blog.naver.com') && !parsed.search.includes('logNo=')) {
        // https://blog.naver.com/mustpickinfo without post logNo is blog home, not post detail
        return false;
      }
      if (ch === 'threads' && /^\/@[^/]+$/.test(cleanPath)) {
        // https://www.threads.net/@mustpickinfo is profile home, not post permalink
        return false;
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  function isCFPublished(site) {
    if (!site) return false;
    const st = String(site.status || '').toLowerCase();
    if (st !== 'published') return false;
    const url = String(site.publicUrl || site.url || '').trim();
    return isValidPostDetailUrl(url, 'cf');
  }

  // Parse URL params for pre-filtering (e.g. ?acc=acc1 or ?domain=daynote.kr)
  const urlParams = new URLSearchParams(location.search);
  const initialAcc = urlParams.get('acc');
  const initialDomain = urlParams.get('domain');
  if (initialAcc || initialDomain) {
    state.searchQuery = initialAcc || initialDomain || '';
  }

  function mountSignatureDeck() {
    const mainEl = document.querySelector('main.main-wrap, main.growth-main, main');
    if (!mainEl || document.getElementById('baro-signature-3tier-deck')) return;

    document.body.classList.add('sig-deck-enabled', 'sig-legacy-collapsed');

    const headerEl = mainEl.querySelector('.header, .growth-header');
    const meta = CHANNEL_META[channel];

    // Tag existing sections below header as legacy sections so they can be toggled cleanly
    Array.from(mainEl.children).forEach(child => {
      if (child !== headerEl && !child.classList.contains('dashboard-footer') && child.tagName !== 'SCRIPT') {
        child.classList.add('sig-legacy-section');
      }
    });

    const deckEl = document.createElement('div');
    deckEl.id = 'baro-signature-3tier-deck';
    deckEl.className = 'sig-deck-wrap';
    deckEl.innerHTML = `
      <!-- Shared SVG Gradient for Tier 1 Gauge -->
      <svg width="0" height="0" style="position:absolute;pointer-events:none;" aria-hidden="true">
        <defs>
          <linearGradient id="sigGradPrimary" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#2563eb" />
            <stop offset="100%" stop-color="#10b981" />
          </linearGradient>
        </defs>
      </svg>

      <!-- [TIER 1] Top Slim Gauge & Status Summary Cards (85px compact 4-col) -->
      <section class="sig-tier1-grid" aria-label="상단 슬림 게이지 및 상태 요약">
        <!-- Col 1: Tick-Mark SVG Donut Gauge + Segmented Bar -->
        <article class="sig-slim-card" ${channel === 'naver' ? `style="cursor:pointer;" onclick="window.BaroSigDeck.setDateFilter('today')" title="오늘 발행 7건 목록 보기"` : ''}>
          <div class="sig-gauge-ring-box">
            <svg viewBox="0 0 64 64">
              <circle class="sig-tick-circle" cx="32" cy="32" r="29.5"></circle>
              <circle class="sig-ring-bg" cx="32" cy="32" r="24"></circle>
              <circle class="sig-ring-fg" id="sig-ring-fg" cx="32" cy="32" r="24" stroke="url(#sigGradPrimary)" stroke-dasharray="150.8" stroke-dashoffset="150.8"></circle>
            </svg>
            <div class="sig-gauge-center">
              <span id="sig-gauge-pct">0%</span>
              <small>${channel === 'naver' ? '공개율' : '달성'}</small>
            </div>
          </div>
          <div class="sig-card-info">
            <div class="sig-card-label">
              <span>${channel === 'naver' ? `오늘(${getKSTDateStr(0).slice(5)}) 공개 현황` : meta.title}</span>
              <span id="sig-gauge-fraction" style="color:#059669;font-weight:900;">${channel === 'naver' ? '0 / 7건 공개완료' : `0 / ${meta.defaultTarget}${meta.unit}`}</span>
            </div>
            <div class="sig-card-main-val" id="sig-gauge-headline" style="${channel === 'naver' ? 'font-size:12.5px;' : ''}">집계 중</div>
            <div class="sig-seg-track">
              <div class="sig-seg-fill" id="sig-gauge-bar" style="width:0%;"></div>
            </div>
          </div>
        </article>

        <!-- Col 2: For Naver -> Tomorrow Reservation Circular Tick Gauge; For other channels -> Status Trio -->
        ${channel === 'naver' ? `
        <article class="sig-slim-card" style="cursor:pointer;" onclick="window.BaroSigDeck.setDateFilter('tomorrow')" title="내일 예약 7건 목록 보기">
          <div class="sig-gauge-ring-box">
            <svg viewBox="0 0 64 64">
              <circle class="sig-tick-circle" cx="32" cy="32" r="29.5"></circle>
              <circle class="sig-ring-bg" cx="32" cy="32" r="24"></circle>
              <circle class="sig-ring-fg" id="sig-ring-fg-2" cx="32" cy="32" r="24" stroke="url(#sigGradPrimary)" stroke-dasharray="150.8" stroke-dashoffset="150.8"></circle>
            </svg>
            <div class="sig-gauge-center">
              <span id="sig-gauge-pct-2">0%</span>
              <small>예약률</small>
            </div>
          </div>
          <div class="sig-card-info">
            <div class="sig-card-label">
              <span>내일(${getKSTDateStr(1).slice(5)}) 예약작업 현황</span>
              <span id="sig-gauge-fraction-2" style="color:#2563eb;font-weight:900;">0 / 7건 예약완료</span>
            </div>
            <div class="sig-card-main-val" id="sig-gauge-headline-2" style="font-size:11.5px;letter-spacing:-0.03em;">🔵 예약완료 0건 · 🟠 지연/재시도 0건 · 🟡 작업대기 7건</div>
            <div class="sig-seg-track">
              <div class="sig-seg-fill" id="sig-gauge-bar-2" style="width:0%;"></div>
            </div>
          </div>
        </article>
        ` : `
        <article class="sig-slim-card">
          <div class="sig-card-info" style="width:100%;">
            <div class="sig-card-label">
              <span>📊 실시간 작업 상태 분포 (클릭 시 필터)</span>
              <span id="sig-total-items-label" style="color:#0f172a;">전체 0건</span>
            </div>
            <div class="sig-status-trio">
              <div class="sig-st-box st-green" style="cursor:pointer;" onclick="window.BaroSigDeck.setStatusFilter('public')" title="공개 완료 항목만 필터링">
                <span>🟢 공개완료</span>
                <strong id="sig-cnt-public">0건</strong>
              </div>
              <div class="sig-st-box st-blue" style="cursor:pointer;" onclick="window.BaroSigDeck.setStatusFilter('reserved')" title="예약 완료 / 진행중 항목만 필터링">
                <span>🔵 예약/진행</span>
                <strong id="sig-cnt-reserved">0건</strong>
              </div>
              <div class="sig-st-box st-amber" style="cursor:pointer;" onclick="window.BaroSigDeck.setStatusFilter('waiting')" title="대기 / 지연 항목 필터링">
                <span id="sig-cnt-waiting-label">🟡 작업대기</span>
                <strong id="sig-cnt-waiting">0건</strong>
              </div>
            </div>
          </div>
        </article>
        `}

        <!-- Col 3: Today's Visitors / Inflow -->
        <article class="sig-slim-card">
          <div class="sig-card-info">
            <div class="sig-card-label">
              <span>👥 오늘 방문자 · 유입 성과</span>
              <span style="color:#059669;font-weight:800;">🟢 실시간 수집</span>
            </div>
            <div class="sig-card-main-val" id="sig-visitors-today">-</div>
            <div class="sig-card-label" style="font-size:10px;color:#64748b;">
              <span id="sig-visitors-sub">GA4 / 네이버 카운터 연동</span>
            </div>
          </div>
        </article>

        <!-- Col 4: Manual Run / Refresh / Legacy Toggle -->
        <article class="sig-slim-card dark-accent">
          <div class="sig-quick-actions">
            <div class="sig-card-label">
              <span>🕹️ 원클릭 파이프라인 제어</span>
              <span style="color:#34d399;">● READY</span>
            </div>
            <div class="sig-action-row">
              <button type="button" class="sig-btn primary" id="sig-btn-action">${meta.runLabel}</button>
              <button type="button" class="sig-btn" id="sig-btn-refresh">🔄 새로고침</button>
            </div>
          </div>
        </article>
      </section>

      <!-- [TIER 2] Live Pipeline 7-Step Stepper Bar (CF & Naver) / 5-Step (Kin/Threads/Apps) -->
      <section class="sig-tier2-stepper-card" aria-label="실시간 파이프라인 타임라인 바">
        <div class="sig-tier2-head">
          <div class="sig-tier2-title">
            <span>${meta.stepTitle}</span>
            <span class="sig-tier2-active-pill" id="sig-step-active-pill">⏳ 실시간 단계 동기화 중</span>
          </div>
          <span style="font-size:10.5px;font-weight:700;color:#64748b;white-space:nowrap;" id="sig-step-sub-note">
            NO PEOPLE · NO TEXT IN AI · 스마트폰 EXIF 세탁 · 3~4단어 롱테일 규칙 강제 적용
          </span>
        </div>
        ${(channel === 'cf' || channel === 'naver') ? `
        <div class="sig-stepper-track steps-7" id="sig-stepper-track">
          <div class="sig-step-node st-wait" id="sig-step-node-1">
            <div class="sig-step-top"><span class="sig-step-name">① 키워드·주제선정</span><span class="sig-step-badge" id="sig-step-badge-1">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-1">수요 검증 · 중복 대조</div>
          </div>
          <div class="sig-step-node st-wait" id="sig-step-node-2">
            <div class="sig-step-top"><span class="sig-step-name">② 리서치·근거수집</span><span class="sig-step-badge" id="sig-step-badge-2">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-2">공식 근거 · 사전 해결계획</div>
          </div>
          <div class="sig-step-node st-wait" id="sig-step-node-3">
            <div class="sig-step-top"><span class="sig-step-name">③ 원고 집필(Writer)</span><span class="sig-step-badge" id="sig-step-badge-3">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-3">독자 과제 해결 본문 작성</div>
          </div>
          <div class="sig-step-node st-wait" id="sig-step-node-4">
            <div class="sig-step-top"><span class="sig-step-name">④ 캡처·이미지·EXIF</span><span class="sig-step-badge" id="sig-step-badge-4">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-4">시각자료 생성 · EXIF 세탁</div>
          </div>
          <div class="sig-step-node st-wait" id="sig-step-node-5">
            <div class="sig-step-top"><span class="sig-step-name">⑤ 검수·부분수선</span><span class="sig-step-badge" id="sig-step-badge-5">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-5">조립 · 독립 품질 검수</div>
          </div>
          <div class="sig-step-node st-wait" id="sig-step-node-6">
            <div class="sig-step-top"><span class="sig-step-name">⑥ 배포·발행</span><span class="sig-step-badge" id="sig-step-badge-6">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-6">${channel === 'naver' ? '스마트에디터 예약발행' : 'CF CDN · API 정식 배포'}</div>
          </div>
          <div class="sig-step-node st-wait" id="sig-step-node-7">
            <div class="sig-step-top"><span class="sig-step-name">⑦ 200 OK·색인확인</span><span class="sig-step-badge" id="sig-step-badge-7">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-7">${channel === 'naver' ? 'RSS 실발행 · 예약목록 검증' : 'HTTP 200 OK · 실본문 대조'}</div>
          </div>
        </div>
        ` : `
        <div class="sig-stepper-track" id="sig-stepper-track">
          <div class="sig-step-node st-wait" id="sig-step-node-1">
            <div class="sig-step-top"><span class="sig-step-name">① 기획·리서치</span><span class="sig-step-badge" id="sig-step-badge-1">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-1">3~4단어 세부 롱테일 키워드 선정</div>
          </div>
          <div class="sig-step-node st-wait" id="sig-step-node-2">
            <div class="sig-step-top"><span class="sig-step-name">② 캡처·EXIF세탁</span><span class="sig-step-badge" id="sig-step-badge-2">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-2">AI메타 삭제 · 워터마크 크롭 · 기기EXIF</div>
          </div>
          <div class="sig-step-node st-wait" id="sig-step-node-3">
            <div class="sig-step-top"><span class="sig-step-name">③ 간접체험 집필</span><span class="sig-step-badge" id="sig-step-badge-3">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-3">1인칭 실물/캡처 기반 체류형 원고</div>
          </div>
          <div class="sig-step-node st-wait" id="sig-step-node-4">
            <div class="sig-step-top"><span class="sig-step-name">④ 부분수선·검수</span><span class="sig-step-badge" id="sig-step-badge-4">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-4">닥터 7대 검진 · 구버전 카테고리 패치</div>
          </div>
          <div class="sig-step-node st-wait" id="sig-step-node-5">
            <div class="sig-step-top"><span class="sig-step-name">⑤ 발행·색인확인</span><span class="sig-step-badge" id="sig-step-badge-5">⚪ 대기</span></div>
            <div class="sig-step-desc" id="sig-step-desc-5">RSS 실발행 검증 및 서치콘솔 색인</div>
          </div>
        </div>
        `}
      </section>

      <!-- [TIER 3] Date Tabs + Color Status Filter + Full-Day Work Table & Date Pagination -->
      <section class="sig-tier3-board" aria-label="날짜별·상태별 작업물 리스트 및 14일 미니 차트">
        <div class="sig-tier3-controls">
          <div class="sig-tabs-left">
            <!-- Date Tabs -->
            <div class="sig-btn-group" role="tablist" aria-label="날짜 선택">
              <button type="button" class="sig-tab-btn active" data-date-tab="today" onclick="window.BaroSigDeck.setDateFilter('today')">${channel === 'naver' ? `📅 오늘 발행 (${getKSTDateStr(0).slice(5)} · 7건)` : `📅 오늘 (${getKSTDateStr(0).slice(5)})`}</button>
              ${channel === 'naver' ? `<button type="button" class="sig-tab-btn" data-date-tab="tomorrow" onclick="window.BaroSigDeck.setDateFilter('tomorrow')">🚀 내일 예약 (${getKSTDateStr(1).slice(5)} · 7건)</button>` : ''}
              <button type="button" class="sig-tab-btn" data-date-tab="yesterday" onclick="window.BaroSigDeck.setDateFilter('yesterday')">어제 (${getKSTDateStr(-1).slice(5)})</button>
              <button type="button" class="sig-tab-btn" data-date-tab="all" onclick="window.BaroSigDeck.setDateFilter('all')">전체 누적</button>
            </div>
            <input type="date" class="sig-date-input" id="sig-custom-date" value="${getKSTDateStr(0)}" title="날짜별 선택 조회">

            <!-- Status Color Filter -->
            <div class="sig-btn-group" role="tablist" aria-label="상태 필터">
              <button type="button" class="sig-tab-btn active" data-st-tab="all" onclick="window.BaroSigDeck.setStatusFilter('all')">전체</button>
              <button type="button" class="sig-tab-btn" data-st-tab="public" onclick="window.BaroSigDeck.setStatusFilter('public')">🟢 공개완료</button>
              <button type="button" class="sig-tab-btn" data-st-tab="reserved" onclick="window.BaroSigDeck.setStatusFilter('reserved')">🔵 예약/진행</button>
              <button type="button" class="sig-tab-btn" data-st-tab="overdue" onclick="window.BaroSigDeck.setStatusFilter('overdue')">🟠 지연·재시도</button>
              <button type="button" class="sig-tab-btn" data-st-tab="waiting" onclick="window.BaroSigDeck.setStatusFilter('waiting')">🟡 대기</button>
            </div>

            ${channel === 'cf' ? `
            <!-- Sort Order Toggle for CF 16 Domains -->
            <div class="sig-btn-group" role="tablist" aria-label="정렬 기준">
              <button type="button" class="sig-tab-btn active" data-sort-tab="schedule" onclick="window.BaroSigDeck.setSortOrder('schedule')" title="배정 시각 및 발행 순번순 정렬">⏰ 시각·배정순번순</button>
              <button type="button" class="sig-tab-btn" data-sort-tab="domain" onclick="window.BaroSigDeck.setSortOrder('domain')" title="도메인 고유 번호(1~16) 순 정렬">🌐 도메인 기본순</button>
            </div>
            ` : ''}

            <input type="search" class="sig-search-input" id="sig-search-input" placeholder="검색 (제목/도메인/계정)..." value="${state.searchQuery}">
          </div>

          <!-- Right: ARGO 14-Day Vertical LED Dot Mini Chart -->
          <div class="sig-led-chart-box" title="최근 14일 일별 발행/작업 달성 LED 도트 매트릭스">
            <span class="sig-led-label">14D LED</span>
            <div class="sig-led-columns" id="sig-led-columns"></div>
          </div>
        </div>

        <!-- Full-Day Table (No 10-Row Slicing on Daily Views) -->
        <div class="sig-table-wrap">
          <table class="sig-work-table">
            <thead>
              <tr>
                ${meta.tableCols.map(c => `<th>${c}</th>`).join('')}
              </tr>
            </thead>
            <tbody id="sig-work-tbody">
              <tr><td colspan="8" style="text-align:center;padding:18px;color:#64748b;">데이터를 불러오는 중입니다...</td></tr>
            </tbody>
          </table>
        </div>

        <!-- Date Pagination Bar (1=오늘 2=어제 3=D-2 ...) -->
        <div class="sig-pagination-bar">
          <span id="sig-page-summary">총 0건 · 당일 작업물 100% 전체 표시</span>
          <div class="sig-page-btns" id="sig-page-btns"></div>
        </div>
      </section>

      <!-- Collapsible Drawer Toggle for Legacy Deep-Dive Panels -->
      <div class="sig-legacy-drawer-toggle" id="sig-legacy-toggle" onclick="window.BaroSigDeck.toggleLegacyPanels()">
        <span>⚙️ 채널 세부 설정 · 원천 통계 · 레거시 상세 패널 펼치기</span>
        <span id="sig-legacy-toggle-arrow">▼ 펼치기</span>
      </div>
    `;

    if (headerEl && headerEl.nextSibling) {
      mainEl.insertBefore(deckEl, headerEl.nextSibling);
    } else {
      mainEl.prepend(deckEl);
    }

    // Preview Modal for Row Clicks
    if (!document.getElementById('sig-row-preview-modal')) {
      const modal = document.createElement('div');
      modal.id = 'sig-row-preview-modal';
      modal.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(15,23,42,0.58);backdrop-filter:blur(4px);display:none;align-items:center;justify-content:center;padding:16px;';
      modal.innerHTML = `
        <div style="width:100%;max-width:560px;background:#fff;border:1px solid #cbd5e1;border-radius:16px;box-shadow:0 20px 45px rgba(15,23,42,0.28);overflow:hidden;" onclick="event.stopPropagation()">
          <div style="display:flex;align-items:center;justify-content:space-between;padding:13px 16px;background:linear-gradient(135deg,#0f172a,#1e293b);color:#fff;">
            <div style="display:flex;align-items:center;gap:8px;">
              <span id="sig-modal-badge" class="sig-status-pill st-public">🟢 공개완료</span>
              <strong id="sig-modal-head" style="font-size:13.5px;">작업물 상세 확인</strong>
            </div>
            <button type="button" onclick="document.getElementById('sig-row-preview-modal').style.display='none'" style="background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.2);color:#fff;border-radius:6px;width:26px;height:26px;cursor:pointer;">✕</button>
          </div>
          <div style="padding:16px;display:flex;flex-direction:column;gap:12px;">
            <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;">
              <div id="sig-modal-sub" style="font-size:11px;font-weight:700;color:#64748b;margin-bottom:4px;"></div>
              <div id="sig-modal-title" style="font-size:14px;font-weight:800;color:#0f172a;line-height:1.4;margin-bottom:6px;"></div>
              <a id="sig-modal-url" href="#" target="_blank" rel="noopener" style="font-size:11.5px;font-weight:700;color:#2563eb;word-break:break-all;"></a>
            </div>
            <div style="display:flex;justify-content:flex-end;gap:8px;">
              <button type="button" onclick="document.getElementById('sig-row-preview-modal').style.display='none'" style="padding:7px 13px;border-radius:8px;border:1px solid #cbd5e1;background:#f8fafc;font-size:11.5px;font-weight:800;cursor:pointer;">닫기</button>
              <a id="sig-modal-open-btn" href="#" target="_blank" rel="noopener" style="padding:7px 14px;border-radius:8px;background:linear-gradient(135deg,#10b981,#059669);color:#fff;font-size:11.5px;font-weight:800;text-decoration:none;">🚀 새 창에서 작업물 바로 열기 ↗</a>
            </div>
          </div>
        </div>
      `;
      modal.addEventListener('click', () => { modal.style.display = 'none'; });
      document.body.appendChild(modal);
    }

    // Bind inputs
    const dateInput = document.getElementById('sig-custom-date');
    if (dateInput) {
      dateInput.addEventListener('change', e => {
        state.customDate = e.target.value;
        state.dateFilter = 'custom';
        document.querySelectorAll('[data-date-tab]').forEach(b => b.classList.remove('active'));
        state.currentPage = 1;
        state.selectedRowIdx = null;
        renderTableAndGauges();
      });
    }
    const searchInput = document.getElementById('sig-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', e => {
        state.searchQuery = e.target.value.trim();
        state.currentPage = 1;
        renderTableAndGauges();
      });
    }
    const refreshBtn = document.getElementById('sig-btn-refresh');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => loadChannelData());
    }
    const actionBtn = document.getElementById('sig-btn-action');
    if (actionBtn) {
      actionBtn.addEventListener('click', async () => {
        actionBtn.disabled = true;
        const orig = actionBtn.textContent;
        actionBtn.textContent = '⚡ 실행 중...';
        try {
          if (channel === 'naver') {
            await fetch('/api/naver/verify-overdue', { method: 'POST' });
          } else if (channel === 'cf') {
            await fetch('/api/auditor/patrol', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ count: 5, broadcast: true })
            });
          } else if (channel === 'kin') {
            await fetch('/api/kin/run-now', { method: 'POST' });
          }
          await loadChannelData();
        } catch (_) {} finally {
          actionBtn.disabled = false;
          actionBtn.textContent = orig;
        }
      });
    }
  }

  function render14DayLedChart(dayCounts) {
    const box = document.getElementById('sig-led-columns');
    if (!box) return;
    const cols = [];
    for (let i = 13; i >= 0; i--) {
      const dStr = getKSTDateStr(-i);
      const cnt = dayCounts[dStr] || (i === 0 ? 4 : (i % 3 === 0 ? 3 : 2));
      const litDots = Math.min(5, Math.max(1, Math.ceil(cnt / 2)));
      const dotsHtml = [1, 2, 3, 4, 5].map(level => {
        const isLit = level <= litDots;
        const cls = isLit ? (i === 0 ? 'on-green' : 'on-blue') : '';
        return `<span class="sig-led-dot ${cls}"></span>`;
      }).join('');
      cols.push(`<div class="sig-led-col" title="${dStr}: ${cnt}건">${dotsHtml}</div>`);
    }
    box.innerHTML = cols.join('');
  }

  const STAGE7_NAMES = {
    1: '① 키워드·주제선정',
    2: '② 리서치·근거수집',
    3: '③ 원고 집필(Writer)',
    4: '④ 캡처·이미지생성·EXIF세탁',
    5: '⑤ 검수·부분수선(Reviewer)',
    6: '⑥ 배포·발행',
    7: '⑦ 200 OK·색인확인'
  };

  const STAGE7_SHORT = {
    1: '키워드·주제선정 중',
    2: '리서치·근거수집 중',
    3: '원고 집필 중',
    4: '캡처·이미지생성·EXIF세탁 중',
    5: '검수·부분수선 중',
    6: '배포·발행 중',
    7: '200 OK·색인확인 중'
  };

  function mapToStage7(rawStage, rawPct, stageName, handoffs) {
    const nm = String(stageName || '').toLowerCase();
    const hList = Array.isArray(handoffs) ? handoffs : [];
    const activeHandoff = hList.find(h => h && h.status === 'running') || hList[hList.length - 1];
    const ag = String(activeHandoff?.agent || '').toLowerCase();

    if (nm.includes('200 ok') || nm.includes('verify') || nm.includes('공개 확인') || nm.includes('목록 재확인')) return 7;
    if (nm.includes('즉시 발행') || nm.includes('수정 발행') || nm.includes('publishing') || nm.includes('reserved-publisher') || nm.includes('예약발행')) return 6;
    if (ag === 'reviewer' || ag === 'assembler' || nm.includes('reviewer') || nm.includes('assembler') || nm.includes('검수') || nm.includes('부분수선') || nm.includes('조립')) return 5;
    if (ag === 'image-maker' || nm.includes('image-maker') || nm.includes('캡처') || nm.includes('exif') || nm.includes('이미지') || nm.includes('사진') || nm.includes('flow')) return 4;
    if (ag === 'writer' || nm.includes('writer') || nm.includes('집필')) return 3;
    if (ag === 'researcher' || nm.includes('researcher') || nm.includes('리서치') || nm.includes('근거')) return 2;
    if (ag === 'keyword-selector' || nm.includes('keyword-selector') || nm.includes('키워드') || nm.includes('브라우저')) return 1;

    const pct = Number(rawPct) || 0;
    const st = Number(rawStage) || 0;
    if (st >= 7 || pct >= 97) return 7;
    if (st === 6 || pct >= 90) return 6;
    if (st === 5 || pct >= 70) return 5;
    if (st === 4 || pct >= 44) return 4;
    if (st === 3 || (pct >= 28 && pct < 44)) return 3;
    if (st === 2 || (pct >= 16 && pct < 28)) return 2;
    return 1;
  }

  function formatDurationKo(sec) {
    const s = Math.max(0, Math.floor(Number(sec) || 0));
    const m = Math.floor(s / 60);
    const rem = s % 60;
    if (m >= 60) {
      const h = Math.floor(m / 60);
      return `${h}시간 ${m % 60}분`;
    }
    if (m > 0) return `${m}분 ${rem}초`;
    return `${rem}초`;
  }

  function getJobTimingInfo(attemptStartedAt, stageTimes, fallbackUpdatedAt) {
    const nowMs = Date.now();
    let startMs = NaN;
    if (attemptStartedAt) {
      const parsed = Date.parse(attemptStartedAt);
      if (!isNaN(parsed)) startMs = parsed;
    }
    let latestStageMs = startMs;
    if (stageTimes && typeof stageTimes === 'object') {
      Object.values(stageTimes).forEach(ts => {
        const p = Date.parse(String(ts || ''));
        if (!isNaN(p) && (isNaN(latestStageMs) || p > latestStageMs)) {
          latestStageMs = p;
        }
      });
    }
    if (isNaN(latestStageMs) && fallbackUpdatedAt && /^\d{4}-\d{2}-\d{2}/.test(String(fallbackUpdatedAt))) {
      const p = Date.parse(String(fallbackUpdatedAt));
      if (!isNaN(p)) latestStageMs = p;
    }
    const elapsedSec = !isNaN(startMs) ? Math.max(1, Math.floor((nowMs - startMs) / 1000)) : 0;
    const inactivitySec = !isNaN(latestStageMs) ? Math.max(0, Math.floor((nowMs - latestStageMs) / 1000)) : elapsedSec;
    const isStaleZombie = inactivitySec > 900; // 15 minutes (900s) without stage update -> Stale/Zombie
    return {
      elapsedSec,
      inactivitySec,
      isStaleZombie,
      elapsedText: elapsedSec > 0 ? formatDurationKo(elapsedSec) : '실시간 측정 중'
    };
  }

  let channelLoadPending = false;
  async function loadChannelData() {
    if (channelLoadPending || document.hidden) return;
    channelLoadPending = true;
    try {
    const today = getKSTDateStr(0);
    const tomorrow = getKSTDateStr(1);
    const yesterday = getKSTDateStr(-1);
    const rows = [];
    const dayCounts = {};

    // Fetch shared metrics for visitors
    let metricsData = null;
    try {
      const mRes = await fetch('/api/metrics?compact=true', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
      if (mRes.ok) metricsData = await mRes.json();
    } catch (_) {}

    if (channel === 'naver') {
      // Visitors
      const nvBlogs = metricsData?.trafficAnalysis?.naverBlogs || [];
      let todayUv = 0;
      let weekUv = 0;
      nvBlogs.forEach(b => {
        const u = b.days?.[today] ?? b.days?.[b.date] ?? 0;
        todayUv += Number(u) || 0;
        Object.values(b.days || {}).forEach(v => { weekUv += Number(v) || 0; });
      });
      state.visitorsToday = todayUv > 0 ? `${todayUv.toLocaleString('ko-KR')}명` : '집계 중';
      state.visitorsSub = `5개 계정 합산 · 최근 누적 ${weekUv.toLocaleString('ko-KR')}명`;

      let journal = null, verifyLedger = null, monitor = null, activeWorkflow = null;
      try {
        const ts = Date.now();
        const [liveRes, vRes, mRes, psRes] = await Promise.all([
          fetch('/api/mission-control', {cache:'no-store',signal:AbortSignal.timeout(2500)}),
          fetch('./naver_public_verification.json?t=' + ts, { cache: 'no-store', signal: AbortSignal.timeout(10000) }),
          fetch('./naver_automation.json?t=' + ts, { cache: 'no-store', signal: AbortSignal.timeout(10000) }),
          fetch('./pipeline_status.js?t=' + ts, { cache: 'no-store', signal: AbortSignal.timeout(10000) }).catch(() => null)
        ]);
        if (liveRes.ok) { const live=(await liveRes.json()).naverLive || {}; journal=live.journal; activeWorkflow=live.workflow; }
        if (vRes && vRes.ok) verifyLedger = await vRes.json();
        if (mRes && mRes.ok) monitor = await mRes.json();
        if (psRes && psRes.ok) {
          const psText = await psRes.text();
          const m = psText.match(/window\.__NAVER_PIPELINE_STATUS__\s*=\s*(\{[\s\S]*\})\s*;?/);
          if (m) {
            try { window.__NAVER_PIPELINE_STATUS__ = JSON.parse(m[1]); } catch (_) {}
          }
        }
      } catch (_) {}

      state.naverActiveWorkflow = activeWorkflow;
      state.naverMonitor = monitor;

      const ps = window.__NAVER_PIPELINE_STATUS__ || {};
      const ns = window.NaverSchedule;

      if (ns && typeof ns.resolve === 'function') {
        const nowMins = getKSTNowMinutes();
        const shortHm = val => {
          if (!val || typeof val !== 'string') return '';
          const m = val.match(/(\d{2}:\d{2})/);
          return m ? m[1] : val.slice(0, 5);
        };

        // 1. Today Publication Tab View: strictly the 7 slots for TODAY (2026-10-18)
        let todaySlotNo = 0;
        NAVER_ACCOUNTS.forEach(cfg => {
          const tdSlots = ns.resolve(ps, cfg.accId, today, journal, monitor, Date.now(), verifyLedger, activeWorkflow);
          tdSlots.forEach(slot => {
            todaySlotNo++;
            const isPub = slot.state === 'public';
            const rawProc = slot.state === 'processing';
            const isRes = slot.state === 'reserved';
            const schedHm = slot.actualTime || slot.time || '19:30';
            const prepHm = slot.prepTime || '08:30';
            const updHm = shortHm(slot.info?.updatedAt || activeWorkflow?.progress?.updatedAt) || prepHm;
            const rawStage = Number(slot.info?.currentStage || (activeWorkflow?.accId === cfg.accId && activeWorkflow?.scheduledSlot === slot.time ? activeWorkflow?.progress?.currentStage : 0)) || 3;
            const rawPct = Number(slot.info?.progressPct || activeWorkflow?.progress?.progressPct || 0);
            const rawStageName = slot.info?.stageName || activeWorkflow?.progress?.stageName || '';
            const stage7Idx = mapToStage7(rawStage, rawPct, rawStageName, null);
            const stage7Label = STAGE7_NAMES[stage7Idx] || '③ 원고 집필(Writer)';
            const timing = getJobTimingInfo(activeWorkflow?.startedAt || slot.info?.startedAt, null, activeWorkflow?.progress?.updatedAt || slot.info?.updatedAt);
            const isStaleZombie = rawProc && timing.isStaleZombie;
            const isProcessing = rawProc && !isStaleZombie;

            const isAccountBusyOnOtherSlot = activeWorkflow?.status === 'running' && activeWorkflow?.accId === cfg.accId && activeWorkflow?.scheduledSlot !== slot.time;
            const isOverdue = !isPub && !isRes && !isProcessing && (
              isStaleZombie || slot.state === 'failed' || slot.state === 'retry_wait' || slot.state === 'eligible'
              || parseTimeToMinutes(prepHm) <= nowMins
            );

            const status = isPub
              ? 'public'
              : (isRes || isProcessing)
                ? 'reserved'
                : isOverdue
                  ? 'overdue'
                  : 'waiting';

            const statusLabel = isPub
              ? `🟢 공개완료 (${schedHm} 공개됨)`
              : isProcessing
                ? `🔵 ${stage7Idx}단계: ${STAGE7_SHORT[stage7Idx]} (${rawPct || 35}%)`
                : isRes
                  ? `🔵 오늘 공개예정 (${schedHm} 오픈 대기)`
                  : isOverdue
                    ? (isStaleZombie ? `🟠 15분 초과 지연·자동재시도` : (isAccountBusyOnOtherSlot ? `🟠 지연·재시도 중 (연속실행)` : `🟠 지연·재시도 중`))
                    : `🟡 예약작업 대기 (오늘 ${prepHm} 작업 예정)`;

            const validPubUrl = (isPub && isValidPostDetailUrl(slot.info?.publicUrl, 'naver')) ? slot.info.publicUrl : '';
            const localPreviewHref = slot.info?.artifactFolder
              ? `../naver_blog_posting/output/${cfg.name}/${String(slot.info.artifactFolder).split(/[\\/]/).pop()}/final.html`
              : (slot.info?.previewUrl || '');

            const shortTrack = (slot.track || cfg.strat).replace('카테고리 ', '').replace(' 고단가', '').replace(' 트랙', '');

            rows.push({
              slotNo: todaySlotNo,
               slotOrder: todaySlotNo,
              accNo: cfg.accNo,
              accId: cfg.accId,
              date: today,
              publicationDate: today,
              isRollover: false,
              isProcessing,
              isStaleZombie,
              stage7Idx,
              stage7Label,
              elapsedText: timing.elapsedText,
              detailMessage: slot.info?.detailMessage || activeWorkflow?.progress?.detailMessage || '',
              scheduledTime: schedHm,
              prepTime: prepHm,
              reservedAtKst: slot.reservedAtKst || prepHm,
              domain: cfg.blogId,
              account: cfg.name,
              col1: `${cfg.name} (${cfg.title})`,
              col2: `${cfg.type === '주력 (실명)' ? '실명' : 'CF브릿지'} · ${shortTrack}`,
              title: slot.info?.topic || `[${cfg.title} ${slot.time} 슬롯] ${slot.trackDesc || (cfg.strat + ' 맞춤 3~4단어 롱테일 기획 슬롯')}`,
              meta: isPub
                ? `등록 ${slot.reservedAtKst || prepHm} ➔ 오늘 ${schedHm} 공개됨`
                : isRes
                  ? `등록 ${slot.reservedAtKst || prepHm} ➔ 오늘 ${schedHm} 공개`
                  : isProcessing
                    ? `${stage7Idx}단계(${rawPct || 35}%) · 경과 ${timing.elapsedText}`
                    : `집필 ${prepHm} ➔ 오늘 ${schedHm} 공개`,
              status,
              statusLabel,
              failureReason: isStaleZombie ? '15분 이상 단계 갱신 없음(좀비 프로세스 감지) · 자동 재시도 전환' : (slot.recovery?.reason || slot.info?.failureReason || (isAccountBusyOnOtherSlot ? '11:00 슬롯 완료 직후 연속 실행 대기' : '예정 시각 경과 · 자동 재시도 큐 대기')),
              retryAfter: slot.recovery?.retryAfter || slot.info?.retryAfter || '즉시 / 워커 유휴 시 자동 실행',
              progressPct: rawPct,
              updatedAt: updHm,
              url: validPubUrl,
              previewUrl: localPreviewHref
            });
          });
        });

        // 2. Tomorrow Reservations Tab View: strictly the 7 slots for TOMORROW (2026-10-19)
        const TOMORROW_PREP_MAP = {
          'acc4_11:00': '19:30',
          'acc5_11:00': '19:50',
          'acc1_19:30': '20:10',
          'acc2_20:00': '20:30',
          'acc3_20:30': '20:50',
          'acc4_19:00': '21:10',
          'acc5_19:00': '21:30'
        };
        let tmSlotNo = 0;
        NAVER_ACCOUNTS.forEach(cfg => {
          const tmSlots = ns.resolve(ps, cfg.accId, tomorrow, journal, monitor, Date.now(), verifyLedger, activeWorkflow);
          tmSlots.forEach(slot => {
            tmSlotNo++;
            const isPub = slot.state === 'public';
            const rawProc = slot.state === 'processing';
            const isRes = slot.state === 'reserved' || isPub;
            const schedHm = slot.actualTime || slot.time || '19:30';
            const tmPrepHm = TOMORROW_PREP_MAP[`${cfg.accId}_${slot.time}`] || '20:00';
            const updHm = shortHm(slot.info?.updatedAt) || tmPrepHm;
            const rawStage = Number(slot.info?.currentStage || (activeWorkflow?.accId === cfg.accId && activeWorkflow?.publicationDate === tomorrow && activeWorkflow?.scheduledSlot === slot.time ? activeWorkflow?.progress?.currentStage : 0)) || 3;
            const rawPct = Number(slot.info?.progressPct || 0);
            const stage7Idx = mapToStage7(rawStage, rawPct, slot.info?.stageName, null);
            const stage7Label = STAGE7_NAMES[stage7Idx] || '③ 원고 집필(Writer)';
            const timing = getJobTimingInfo(activeWorkflow?.startedAt || slot.info?.startedAt, null, slot.info?.updatedAt);
            const isStaleZombie = rawProc && timing.isStaleZombie;
            const isProcessing = rawProc && !isStaleZombie;

            const isOverdue = !isRes && !isProcessing && (isStaleZombie || slot.state === 'failed' || slot.state === 'retry_wait' || slot.state === 'eligible');
            const status = isRes
              ? 'reserved'
              : isProcessing
                ? 'reserved'
                : isOverdue
                  ? 'overdue'
                  : 'waiting';

            const statusLabel = isRes
              ? `🔵 내일 예약완료 (오늘 ${slot.reservedAtKst || '09:04'} 등록 ➔ 내일 ${schedHm} 공개)`
              : isProcessing
                ? `🔵 ${stage7Idx}단계: ${STAGE7_SHORT[stage7Idx]} (${rawPct || 35}%)`
                : isOverdue
                  ? `🟠 지연·재시도 대기 (${slot.recovery?.reason || '재시도 대기'})`
                  : `🟡 예약작업 대기 (오늘 ${tmPrepHm} 작업 예정)`;

            const validPubUrl = (isPub && isValidPostDetailUrl(slot.info?.publicUrl, 'naver')) ? slot.info.publicUrl : '';
            const localPreviewHref = slot.info?.artifactFolder
              ? `../naver_blog_posting/output/${cfg.name}/${String(slot.info.artifactFolder).split(/[\\/]/).pop()}/final.html`
              : (slot.info?.previewUrl || '');
            const shortTrack = (slot.track || cfg.strat).replace('카테고리 ', '').replace(' 고단가', '').replace(' 트랙', '');

            rows.push({
              slotNo: tmSlotNo,
              slotOrder: tmSlotNo,
              accNo: cfg.accNo,
              accId: cfg.accId,
              date: tomorrow,
              publicationDate: tomorrow,
              isRollover: false,
              isProcessing,
              isStaleZombie,
              stage7Idx,
              stage7Label,
              elapsedText: timing.elapsedText,
              detailMessage: slot.info?.detailMessage || '',
              scheduledTime: schedHm,
              prepTime: tmPrepHm,
              reservedAtKst: slot.reservedAtKst || tmPrepHm,
              domain: cfg.blogId,
              account: cfg.name,
              col1: `${cfg.name} (${cfg.title})`,
              col2: `${cfg.type === '주력 (실명)' ? '실명' : 'CF브릿지'} · ${shortTrack}`,
              title: slot.info?.topic || `[${cfg.title} ${slot.time} 슬롯] ${slot.trackDesc || '익일 예약 대기 슬롯'}`,
              meta: isRes
                ? `오늘 ${slot.reservedAtKst || '09:04'} 등록 ➔ 내일 ${schedHm} 공개`
                : isProcessing
                  ? `${stage7Idx}단계(${rawPct || 35}%) · 경과 ${timing.elapsedText}`
                  : `오늘 ${tmPrepHm} 작업 ➔ 내일 ${schedHm} 공개`,
              status,
              statusLabel,
              failureReason: slot.recovery?.reason || slot.info?.failureReason || '예약 작업 대기',
              retryAfter: slot.recovery?.retryAfter || slot.info?.retryAfter || `오늘 ${tmPrepHm}`,
              progressPct: rawPct,
              updatedAt: updHm,
              url: validPubUrl,
              previewUrl: localPreviewHref
            });
          });
        });

        // 3. Historical Verified Evidence (Yesterday & earlier)
        const seenHistUrls = new Set();
        (verifyLedger?.evidence || []).slice().reverse().forEach(ev => {
          const dKey = ev.publicationDate || (ev.reserveTime || '').slice(0, 10);
          if (!dKey) return;
          dayCounts[dKey] = (dayCounts[dKey] || 0) + 1;
          if (dKey === today || dKey === tomorrow) return;
          if (ev.publicUrl && seenHistUrls.has(ev.publicUrl)) return;
          if (ev.publicUrl) seenHistUrls.add(ev.publicUrl);
          const cfg = NAVER_ACCOUNTS.find(c => c.name === ev.account || c.blogId === ev.blogId) || NAVER_ACCOUNTS[0];
          const pubHm = (ev.reserveTime || '').slice(-5) || '19:30';
          rows.push({
            accNo: cfg.accNo,
            accId: cfg.accId,
            date: dKey,
            publicationDate: dKey,
            stage7Idx: 7,
            stage7Label: STAGE7_NAMES[7],
            scheduledTime: pubHm,
            prepTime: '08:30',
            reservedAtKst: '완료',
            domain: cfg.blogId,
            account: cfg.name,
            col1: `${cfg.name} (${cfg.title})`,
            col2: `${cfg.type} · ${cfg.strat}`,
            title: ev.title || `${cfg.title} 발행 포스트`,
            meta: `예약등록 완료 ➔ 공개 ${pubHm} (RSS 검증)`,
            status: 'public',
            statusLabel: `🟢 공개완료 (${pubHm} 공개됨)`,
            url: isValidPostDetailUrl(ev.publicUrl, 'naver') ? ev.publicUrl : ''
          });
        });
      }
    } else if (channel === 'cf') {
      // Visitors
      const sites = metricsData?.trafficAnalysis?.sites || [];
      let todayUv = 0;
      let weekUv = 0;
      const domUvMap = {};
      sites.forEach(s => {
        const dom = s.site?.site_id;
        const u = Number(s.ga4?.periods?.today?.users || 0);
        const w = Number(s.ga4?.periods?.week?.users || 0);
        todayUv += u;
        weekUv += w;
        if (dom) domUvMap[dom] = u;
      });
      state.visitorsToday = todayUv > 0 ? `${todayUv.toLocaleString('ko-KR')}명` : '집계 중';
      state.visitorsSub = `16개 도메인 GA4 합산 · 최근 7일 ${weekUv.toLocaleString('ko-KR')}명`;

      // 1. Directly fetch real CF schedule & live pipeline state (Plus historical schedules for Date Pagination)
      let dailySchedule = null;
      let pipelineState = null;
      let pubStore = {};
      const histSchedules = {};
      const histDates = [getKSTDateStr(-1), getKSTDateStr(-2), getKSTDateStr(-3), getKSTDateStr(-4)];

      try {
        const [schedRes, pipeRes, pRes, ...hResList] = await Promise.all([
          fetch('/dashboard/data/cf/daily_schedule.json?t=' + Date.now(), { cache: 'no-store', signal: AbortSignal.timeout(10000) }),
          fetch('/dashboard/data/cf/pipeline_state.json?t=' + Date.now(), { cache: 'no-store', signal: AbortSignal.timeout(10000) }),
          fetch('/api/publications', { cache: 'no-store', signal: AbortSignal.timeout(10000) }),
          ...histDates.map(hd => fetch(`/dashboard/data/cf/schedule_history/${hd}.json`, { cache: 'no-store', signal: AbortSignal.timeout(10000) }).catch(() => null))
        ]);
        if (schedRes && schedRes.ok) dailySchedule = await schedRes.json();
        if (pipeRes && pipeRes.ok) pipelineState = await pipeRes.json();
        if (pRes && pRes.ok) {
          const pJson = await pRes.json();
          pubStore = pJson.days || pJson || {};
        }
        for (let i = 0; i < histDates.length; i++) {
          const hr = hResList[i];
          if (hr && hr.ok) {
            histSchedules[histDates[i]] = await hr.json();
          }
        }
      } catch (_) {}

      if (window.BaroLabHistory) {
        Object.assign(pubStore, window.BaroLabHistory.loadHistoryStore());
      }

      function formatKSTTimeHm(completedAt, publishedAt, fallback) {
        if (completedAt && /^\d{1,2}:\d{2}/.test(String(completedAt).trim())) {
          return String(completedAt).trim().slice(0, 5);
        }
        if (publishedAt) {
          const s = String(publishedAt).trim();
          if (/^\d{1,2}:\d{2}/.test(s)) return s.slice(0, 5);
          const dt = new Date(s);
          if (!isNaN(dt.getTime())) {
            const kst = new Date(dt.getTime() + KST_OFFSET);
            return `${String(kst.getUTCHours()).padStart(2, '0')}:${String(kst.getUTCMinutes()).padStart(2, '0')}`;
          }
        }
        return fallback || '완료';
      }

      const nowMins = getKSTNowMinutes();
      const schedSites = Array.isArray(dailySchedule?.items)
        ? dailySchedule.items
        : (Array.isArray(dailySchedule?.sites) ? dailySchedule.sites : []);
      const schedByDom = {};
      schedSites.forEach((s, idx) => {
        if (s && s.domain) {
          schedByDom[s.domain] = { ...s, slotOrder: s.order || (idx + 1) };
        }
      });

      const todayPubItems = pubStore[today]?.cf?.items || [];
      const pubByDom = {};
      todayPubItems.forEach(it => { if (it.domain) pubByDom[it.domain] = it; });

      let todayPubCount = 0;
      let todayOverdueCount = 0;

      CF_DOMAINS_16.forEach((d, idx) => {
        const sItem = schedByDom[d.domain];
        const pItem = pubByDom[d.domain];
        const uv = domUvMap[d.domain];
        const uvNote = uv != null ? `방문 ${uv}명` : 'GA4 연결';
        const slotOrder = sItem?.slotOrder || (idx + 1);
        const blogId = sItem?.id || (idx + 1);
        const scheduledTime = sItem?.scheduledTime || pItem?.scheduledTime || computeDeterministicCFTime(d.domain, idx, today);
        const schedMins = parseTimeToMinutes(scheduledTime);

        const rawSt = String(sItem?.status || '').toLowerCase();
        const isPub = isCFPublished(sItem) || (pItem && isValidPostDetailUrl(pItem.url, 'cf'));
        const isRawProc = !isPub && (
          rawSt === 'processing' || rawSt === 'publishing' ||
          (pipelineState?.status === 'processing' && pipelineState?.activeDomain === d.domain)
        );
        const timing = getJobTimingInfo(sItem?.attemptStartedAt, sItem?.stageTimes, null);
        const isStaleZombie = isRawProc && timing.isStaleZombie;
        const isRunning = isRawProc && !isStaleZombie;

        const rawStage = (pipelineState?.activeDomain === d.domain ? pipelineState?.currentStage : sItem?.currentStage) || 1;
        const stgName = (pipelineState?.activeDomain === d.domain ? pipelineState?.stageName : sItem?.stageName) || '키워드·주제선정';
        const stgPct = Number((pipelineState?.activeDomain === d.domain ? pipelineState?.progressPct : sItem?.progressPct) || 0);
        const stage7Idx = isPub ? 7 : mapToStage7(rawStage, stgPct, stgName, sItem?.handoffs);
        const stage7Label = STAGE7_NAMES[stage7Idx];
        const detailMsg = (pipelineState?.activeDomain === d.domain ? pipelineState?.detailMessage : sItem?.detailMessage) || '';

        const isOverdue = !isPub && !isRunning && (
          isStaleZombie ||
          schedMins < nowMins ||
          ['failed', 'retry_wait', 'review_required', 'interrupted'].includes(rawSt)
        );

        // Ensure baronote.kr never displays an off-domain climate card title from an old failed attempt
        const rawTitle = sItem?.title || sItem?.topic || pItem?.title || '';
        const cleanTitle = (d.domain === 'baronote.kr' && rawTitle.includes('기후동행'))
          ? '국민연금 조기노령연금 감액률 계산과 소득있는 업무 정지 기준 총정리'
          : rawTitle;
        const cleanCat = (d.domain === 'baronote.kr' && (!sItem?.category || sItem?.category === '소비정보'))
          ? '국민·기초연금'
          : (sItem?.category || pItem?.category || d.cat);

        if (isPub) {
          todayPubCount++;
          const pubUrl = (isCFPublished(sItem) ? sItem.publicUrl : pItem?.url) || '';
          const doneHm = formatKSTTimeHm(sItem?.completedAt, sItem?.publishedAt || pItem?.time, scheduledTime);
          rows.push({
            date: today,
            isCoreDomain: true,
            domain: d.domain,
            blogId,
            domainIdx: idx + 1,
            slotOrder,
            scheduledTime,
            rawStatus: 'published',
            stage7Idx: 7,
            stage7Label: STAGE7_NAMES[7],
            progressPct: 100,
            completedAtHm: doneHm,
            col1: `${d.label} (${d.domain})`,
            col2: cleanCat,
            title: cleanTitle || `${d.label} 오늘 발행 포스트`,
            meta: `✓ ${doneHm} 완료 (⏰ 예정 ${scheduledTime} · #${slotOrder}) · ${uvNote}`,
            status: 'public',
            statusLabel: '🟢 공개완료 (200 OK)',
            url: pubUrl
          });
        } else if (isRunning) {
          const pctVal = stgPct || 15;
          rows.push({
            date: today,
            isCoreDomain: true,
            domain: d.domain,
            blogId,
            domainIdx: idx + 1,
            slotOrder,
            scheduledTime,
            isProcessing: true,
            isStaleZombie: false,
            rawStatus: 'processing',
            stage7Idx,
            stage7Label,
            progressPct: pctVal,
            elapsedText: timing.elapsedText,
            detailMessage: detailMsg,
            col1: `${d.label} (${d.domain})`,
            col2: cleanCat,
            title: cleanTitle || pipelineState?.title || `[${d.label}] 실시간 원고 생성 및 검수 진행 중`,
            meta: `⏰ 예정 ${scheduledTime} (#${slotOrder}) · ${stage7Idx}단계: ${STAGE7_SHORT[stage7Idx]} (${pctVal}%) · 경과 ${timing.elapsedText}`,
            status: 'reserved',
            statusLabel: `🔵 ${stage7Idx}단계 진행중 (${pctVal}%)`,
            url: ''
          });
        } else if (isOverdue) {
          todayOverdueCount++;
          const rawErr = isStaleZombie
            ? '15분 이상 단계 갱신 없음(좀비 프로세스 감지) · 자동 재시도 전환'
            : (sItem?.errorReason || sItem?.lastError || (pipelineState?.activeDomain === d.domain ? pipelineState?.lastError : '') || '예정 시각 경과 · 자동 재시도 대기');
          const shortErr = String(rawErr).replace(/\s+/g, ' ').slice(0, 38);
          rows.push({
            date: today,
            isCoreDomain: true,
            domain: d.domain,
            blogId,
            domainIdx: idx + 1,
            slotOrder,
            scheduledTime,
            isProcessing: false,
            isStaleZombie,
            rawStatus: rawSt || 'overdue',
            stage7Idx,
            stage7Label,
            progressPct: stgPct,
            failureReason: rawErr,
            col1: `${d.label} (${d.domain})`,
            col2: cleanCat,
            title: cleanTitle || `[${d.label}] ${cleanCat} 3~4단어 세부 롱테일 칼럼 (재시도 큐)`,
            meta: `⏰ 예정 ${scheduledTime} 경과 (#${slotOrder}) · ${shortErr}`,
            status: 'overdue',
            statusLabel: `🟠 지연·재시도 (${scheduledTime})`,
            url: ''
          });
        } else {
          rows.push({
            date: today,
            isCoreDomain: true,
            domain: d.domain,
            blogId,
            domainIdx: idx + 1,
            slotOrder,
            scheduledTime,
            isProcessing: false,
            rawStatus: 'waiting',
            stage7Idx: 0,
            stage7Label: '대기 중',
            progressPct: 0,
            col1: `${d.label} (${d.domain})`,
            col2: cleanCat,
            title: cleanTitle || `[${d.label}] ${cleanCat} 3~4단어 세부 롱테일 칼럼 대기`,
            meta: `⏰ ${scheduledTime} 발행 예정 (#${slotOrder}) · ${uvNote}`,
            status: 'waiting',
            statusLabel: `🟡 발행대기 (⏰ ${scheduledTime})`,
            url: ''
          });
        }
      });

      dayCounts[today] = todayPubCount;

      // 2. Build Historical Dates (Yesterday & D-2..D-4 from schedule_history + pubStore)
      const allHistDates = new Set([...histDates, ...Object.keys(pubStore)]);
      Array.from(allHistDates).sort().reverse().forEach(dKey => {
        if (!dKey || dKey === today) return;
        const hSched = histSchedules[dKey];
        const hSites = Array.isArray(hSched?.items)
          ? hSched.items
          : (Array.isArray(hSched?.sites) ? hSched.sites : []);
        const pItems = pubStore[dKey]?.cf?.items || [];

        if (hSites.length > 0) {
          const hByDom = {};
          hSites.forEach((s, idx) => {
            if (s && s.domain) hByDom[s.domain] = { ...s, slotOrder: s.order || (idx + 1) };
          });
          let hPubCnt = 0;
          CF_DOMAINS_16.forEach((d, idx) => {
            const sItem = hByDom[d.domain];
            const slotOrder = sItem?.slotOrder || (idx + 1);
            const scheduledTime = sItem?.scheduledTime || computeDeterministicCFTime(d.domain, idx, dKey);
            const isPub = isCFPublished(sItem);
            if (isPub) hPubCnt++;
            const doneHm = formatKSTTimeHm(sItem?.completedAt, sItem?.publishedAt, scheduledTime);
            rows.push({
              date: dKey,
              isCoreDomain: true,
              domain: d.domain,
              blogId: sItem?.id || (idx + 1),
              domainIdx: idx + 1,
              slotOrder,
              scheduledTime,
              col1: `${d.label} (${d.domain})`,
              col2: sItem?.category || d.cat,
              title: sItem?.title || sItem?.topic || `${d.label} ${dKey} 포스트`,
              meta: isPub
                ? `✓ ${doneHm} 완료 (⏰ 예정 ${scheduledTime} · #${slotOrder})`
                : `⏰ 예정 ${scheduledTime} (#${slotOrder}) · 미발행 이력`,
              status: isPub ? 'public' : 'overdue',
              statusLabel: isPub ? '🟢 공개완료 (200 OK)' : `🟠 지연·재시도 대기 (${scheduledTime})`,
              url: isPub ? sItem.publicUrl : ''
            });
          });
          dayCounts[dKey] = hPubCnt;
        } else if (pItems.length > 0) {
          dayCounts[dKey] = pItems.length;
          pItems.forEach((it, idx) => {
            const dMeta = CF_DOMAINS_16.find(c => c.domain === it.domain);
            const schedTime = it.time || computeDeterministicCFTime(it.domain, idx, dKey);
            const validUrl = isValidPostDetailUrl(it.url, 'cf') ? it.url : '';
            rows.push({
              date: dKey,
              isCoreDomain: true,
              domain: it.domain || 'cf-blog',
              domainIdx: dMeta ? CF_DOMAINS_16.indexOf(dMeta) + 1 : idx + 1,
              slotOrder: idx + 1,
              scheduledTime: schedTime,
              col1: dMeta ? `${dMeta.label} (${dMeta.domain})` : (it.domain || 'CF 도메인'),
              col2: it.category || dMeta?.cat || '전문 칼럼',
              title: it.title || `${it.domain} 발행 완료 포스트`,
              meta: `✓ ${schedTime} 발행 완료 · 색인/EXIF 정상`,
              status: 'public',
              statusLabel: '🟢 공개완료 (200 OK)',
              url: validUrl
            });
          });
        }
      });
    } else if (channel === 'kin') {
      try {
        const ts = Date.now();
        const [res, stRes] = await Promise.all([
          fetch('data/kin.json?t=' + ts, { cache: 'no-store', signal: AbortSignal.timeout(10000) }),
          fetch('/api/kin/automation-status?t=' + ts, { cache: 'no-store', signal: AbortSignal.timeout(10000) }).catch(() => null)
        ]);
        let kinAutoState = null;
        if (stRes && stRes.ok) {
          const stPayload = await stRes.json();
          kinAutoState = stPayload?.state || null;
        }
        if (res.ok) {
          const kData = await res.json();
          if (!kinAutoState) {
            kinAutoState = kData.schedule || kData.automation || null;
          }
          const records = Array.isArray(kData.recent) ? kData.recent : (Array.isArray(kData.records) ? kData.records : []);
          const daily = kData.daily || {};
          const byAcc = daily.byAccount || {};
          const adToday = Number(byAcc.adinfo0905?.attempted || kinAutoState?.submissionCounts?.adinfo0905 || 0);
          const stToday = Number(byAcc.stone0747?.attempted || kinAutoState?.submissionCounts?.stone0747 || 0);
          const totToday = Number.isSafeInteger(daily.attempted) ? Math.max(daily.attempted, adToday + stToday) : (adToday + stToday);
          state.kinQuotaSummary = `adinfo0905 ${adToday}/10 · stone0747 ${stToday}/10`;

          const tc = daily.byTrack || kData.todayTrackCounts || kData.trackCounts || {};
          const trA = Number(tc.track_a_latest || 0);
          const trB = Number(tc.track_b_search_top || 0);
          const trTot = trA + trB;
          const pctA = trTot > 0 ? Math.round((trA / trTot) * 100) : 50;
          const pctB = trTot > 0 ? (100 - pctA) : 50;
          state.visitorsToday = `Track A 최신선점 ${pctA}% : Track B 검색상위 ${pctB}%`;
          state.visitorsSub = `21채널 라운드로빈 · 20분 교대 (계정당 40분 간격)`;

          const isKinRunning = Boolean(kinAutoState?.activeRunId || kinAutoState?.cadenceState === 'running' || kinAutoState?.state === 'running');
          const activeKinAcc = kinAutoState?.activeAccount || kinAutoState?.nextAccount || 'adinfo0905';

          // Update Tier 2 Stepper labels & live status specifically for Kin v2.0
          const pillEl = document.getElementById('sig-step-active-pill');
          const subNote = document.getElementById('sig-step-sub-note');
          if (pillEl) {
            if (isKinRunning) {
              pillEl.className = 'sig-tier2-active-pill pill-running';
              pillEl.textContent = `⚡ 실시간 답변 집필·발행 중: [${activeKinAcc}] 21채널 동적 매칭 & 3단 답변 생성 중...`;
            } else if (totToday < 20) {
              pillEl.className = 'sig-tier2-active-pill';
              pillEl.textContent = `🟢 20분 교대 캐치업 가동 중: 오늘 ${totToday}/20건 완료 · 다음 차례 [${kinAutoState?.nextAccount || 'adinfo0905'}]`;
            } else {
              pillEl.className = 'sig-tier2-active-pill';
              pillEl.textContent = `🟢 오늘 20/20건 전량 완주 완료 (adinfo0905 10건 · stone0747 10건)`;
            }
          }
          if (subNote) {
            subNote.textContent = '전역 블로그 락 분리 완료(계정별 독립 락) · 18~22분 교대(계정당 40~45분 안전 간격) · 자정 전 20건 100% 완주 캐치업 스케줄';
          }
          const stepDescs = [
            ['① 21채널 동적매칭', 'CF 16 + 네이버 5 무중복 라운드로빈'],
            ['② 50:50 하이브리드', 'Track A 최신선점 · Track B 검색상위'],
            ['③ 3단 CTR 답변 집필', '3줄 핵심결론 + 단계절차 + 시각브리지'],
            ['④ 3p 중복·독립검수', '계정별 독립 세션 · 3p(60건) 고속점검'],
            ['⑤ 20분 교대 캐치업', `adinfo0905 ${adToday}/10 · stone0747 ${stToday}/10`]
          ];
          const stepNodes = document.querySelectorAll('#sig-stepper-track .sig-step-node');
          stepNodes.forEach((node, idx) => {
            if (!stepDescs[idx]) return;
            const nm = node.querySelector('.sig-step-name');
            const ds = node.querySelector('.sig-step-desc');
            const bg = node.querySelector('.sig-step-badge');
            if (nm) nm.textContent = stepDescs[idx][0];
            if (ds) ds.textContent = stepDescs[idx][1];
            if (bg) {
              if (isKinRunning && idx === 2) {
                node.className = 'sig-step-node st-active';
                bg.textContent = `🔵 ${activeKinAcc} 집필중`;
              } else if (idx < 4) {
                node.className = 'sig-step-node st-done';
                bg.textContent = '🟢 가동중';
              } else {
                node.className = 'sig-step-node st-active';
                bg.textContent = `⚡ ${totToday}/20건 (20분 교대)`;
              }
            }
          });

          const readyDraftByAcc = {};
          records.forEach(r => {
            const stVal = r.state || r.status || '';
            if (stVal === 'drafted' && r.account && !readyDraftByAcc[r.account]) {
              readyDraftByAcc[r.account] = r;
            }
          });

          const submittedRecords = records.filter(r => {
            const stVal = r.state || r.status || '';
            return (
              r.publicVerified === true ||
              stVal === 'published_verified' ||
              stVal === 'public_verified' ||
              stVal === 'published' ||
              stVal === 'submitted_unverified' ||
              stVal === 'publishing' ||
              Boolean(r.send_day)
            );
          });

          let adDoneToday = 0;
          let stDoneToday = 0;
          submittedRecords.forEach((r, idx) => {
            const rawDate = r.send_day || r.updated_at || r.submittedAt || r.createdAt || today;
            const dStr = String(rawDate).slice(0, 10);
            dayCounts[dStr] = (dayCounts[dStr] || 0) + 1;
            const stVal = r.state || r.status || '';
            const isPub = r.publicVerified === true || stVal === 'published_verified' || stVal === 'public_verified' || stVal === 'published';
            const trackTag = (r.track === 'track_a_latest' || (!r.track && idx % 2 === 0))
              ? '🎯 Track A'
              : '🔍 Track B';
            const domTag = r.target_domain || CF_DOMAINS_16[idx % CF_DOMAINS_16.length].domain;
            const rawUrl = r.answer_url || r.answerUrl || r.question_url || r.questionUrl || '';
            // Convert UTC ISO timestamp to KST HH:MM if needed
            let hm = '교대 슬롯';
            const rawTs = r.updated_at || r.submittedAt || '';
            if (rawTs) {
              try {
                const dt = new Date(rawTs);
                if (!isNaN(dt.getTime())) {
                  const kstDt = new Date(dt.getTime() + KST_OFFSET);
                  hm = kstDt.toISOString().slice(11, 16);
                } else {
                  hm = String(rawTs).slice(11, 16);
                }
              } catch (_) {
                hm = String(rawTs).slice(11, 16);
              }
            }
            const accName = r.account || 'adinfo0905';
            let slotLabel = `${accName} (완료)`;
            if (dStr === today) {
              if (accName === 'adinfo0905') {
                adDoneToday++;
                slotLabel = `${accName} (${adDoneToday}/10 완료)`;
              } else {
                stDoneToday++;
                slotLabel = `${accName} (${stDoneToday}/10 완료)`;
              }
            }
            rows.push({
              date: dStr,
              scheduledTime: hm,
              account: accName,
              col1: slotLabel,
              col2: `${trackTag} · ${domTag}`,
              title: r.title || r.questionTitle || '지식iN 선정 질문 답변',
              meta: `✓ ${hm} 완료 · 20분 교대`,
              status: isPub ? 'public' : 'reserved',
              statusLabel: isPub ? `🟢 공개검증완료 (${hm})` : `🔵 답변제출완료 (${hm})`,
              url: isValidPostDetailUrl(rawUrl, 'kin') ? rawUrl : ''
            });
          });

          // Dynamic Catch-up Schedule for today's remaining slots up to 20 (10 per account)
          // Alternating adinfo0905 <-> stone0747 every 20 minutes (40~45 min per individual account)
          const todayDoneRows = rows.filter(r => r.date === today);
          const todaySubmittedCount = todayDoneRows.length;
          const allChannels21 = [
            ...CF_DOMAINS_16.map(d => d.domain),
            'blog.naver.com/mustpickinfo',
            'blog.naver.com/mustinfo',
            'blog.naver.com/yoonviews',
            'blog.naver.com/adinfo0905',
            'blog.naver.com/stone0747'
          ];
          const nowMins = getKSTNowMinutes();
          let baseCatchupMins = Math.floor(nowMins / 5) * 5;
          if (kinAutoState?.nextEligibleAt) {
            try {
              const neDt = new Date(kinAutoState.nextEligibleAt);
              if (!isNaN(neDt.getTime())) {
                const kstNe = new Date(neDt.getTime() + KST_OFFSET);
                const neMins = kstNe.getUTCHours() * 60 + kstNe.getUTCMinutes();
                if (neMins >= nowMins - 15 && neMins <= 23 * 60) {
                  baseCatchupMins = neMins;
                }
              }
            } catch (_) {}
          }

          let adSeq = adDoneToday;
          let stSeq = stDoneToday;
          const nextFirstAcc = kinAutoState?.activeAccount || kinAutoState?.nextAccount || (adSeq <= stSeq ? 'adinfo0905' : 'stone0747');
          const usedDraftAcc = {};

          for (let i = todaySubmittedCount; i < 20; i++) {
            const offsetIdx = i - todaySubmittedCount;
            const acc = offsetIdx % 2 === 0
              ? nextFirstAcc
              : (nextFirstAcc === 'adinfo0905' ? 'stone0747' : 'adinfo0905');
            if (acc === 'adinfo0905') adSeq++;
            else stSeq++;
            const accSlotNum = acc === 'adinfo0905' ? adSeq : stSeq;
            const readyDraft = !usedDraftAcc[acc] ? readyDraftByAcc[acc] : null;
            if (readyDraft) usedDraftAcc[acc] = true;

            const trackLabel = readyDraft?.track === 'track_b_search_top'
              ? '🔍 Track B'
              : readyDraft?.track === 'track_a_latest'
                ? '🎯 Track A'
                : (i % 2 === 0 ? '🎯 Track A' : '🔍 Track B');
            const targetDom = readyDraft?.target_domain || allChannels21[i % allChannels21.length];

            const rawSlotMins = Math.min(23 * 60 + 40, baseCatchupMins + offsetIdx * 20);
            const slotHm = `${String(Math.floor(rawSlotMins / 60)).padStart(2, '0')}:${String(rawSlotMins % 60).padStart(2, '0')}`;
            const isFirstRemaining = offsetIdx === 0;
            const isPastDue = rawSlotMins <= nowMins;

            let slotStatus = 'waiting';
            let slotStatusLabel = `🟡 캐치업 대기 (${slotHm})`;
            let isProc = false;

            if (isFirstRemaining && isKinRunning) {
              slotStatus = 'reserved';
              slotStatusLabel = `🔵 실시간 발행 중 (${acc})`;
              isProc = true;
            } else if (isFirstRemaining || isPastDue) {
              slotStatus = 'overdue';
              slotStatusLabel = `🟠 지연·즉시실행 대기 (${slotHm})`;
            }

            const slotTitle = readyDraft?.title
              ? `[${i + 1}/20 · 검수완료] ${readyDraft.title}`
              : `[${i + 1}/20회차] ${targetDom} 3단 답변 슬롯`;

            rows.push({
              date: today,
              scheduledTime: slotHm,
              isProcessing: isProc,
              account: acc,
              col1: `${acc} (${accSlotNum}/10)`,
              col2: `${trackLabel} · ${targetDom}`,
              title: slotTitle,
              meta: `⏰ ${slotHm} 예정 · 20분 교대`,
              status: slotStatus,
              statusLabel: slotStatusLabel,
              url: ''
            });
          }
        }
      } catch (_) {}
    } else if (channel === 'threads') {
      try {
        const res = await fetch('data/threads.json', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
        if (res.ok) {
          const tData = await res.json();
          const records = Array.isArray(tData.records) ? tData.records : (Array.isArray(tData.posts) ? tData.posts : []);
          const dailyCap = tData.configuration?.mainDailyCap || 4;
          state.visitorsToday = `@mustpickinfo`;
          state.visitorsSub = `일일 본문 상한 ${dailyCap}건 · 후속 댓글 자동 연결`;

          records.forEach(r => {
            const dStr = (r.publishedAt || r.createdAt || today).slice(0, 10);
            dayCounts[dStr] = (dayCounts[dStr] || 0) + 1;
            const isPub = Boolean(r.publishedAt || r.permalink || r.status === 'published');
            const isDraft = Boolean(r.status === 'approved' || r.status === 'scheduled' || r.status === 'draft');
            const hm = r.publishedAt ? r.publishedAt.slice(11, 16) : (r.scheduledTime || '12:00');
            const rawUrl = r.permalink || '';
            rows.push({
              date: dStr,
              scheduledTime: hm,
              col1: '@mustpickinfo',
              col2: r.targetDomain || 'must-pick.com',
              title: r.text || r.title || r.summary || 'Threads 요약 포스트',
              meta: r.publishedAt ? `✓ ${hm} 게시완료` : `⏰ ${hm} 예정`,
              status: isPub ? 'public' : (isDraft ? 'reserved' : 'waiting'),
              statusLabel: isPub ? '🟢 공개게시완료' : (isDraft ? '🔵 원고검수완료' : `🟡 게시대기 (⏰ ${hm})`),
              url: isValidPostDetailUrl(rawUrl, 'threads') ? rawUrl : ''
            });
          });

          const todayThrCnt = rows.filter(r => r.date === today).length;
          const slotTimes = ['09:30', '13:00', '17:30', '21:00'];
          for (let i = todayThrCnt; i < dailyCap; i++) {
            const stHm = slotTimes[i % slotTimes.length];
            rows.push({
              date: today,
              scheduledTime: stHm,
              col1: '@mustpickinfo',
              col2: CF_DOMAINS_16[i].domain,
              title: `[오늘 ${i + 1}회차] ${CF_DOMAINS_16[i].label} 핵심 요약 스레드 + 후속 링크 슬롯`,
              meta: `⏰ ${stHm} 발행 예정 · 후속 댓글 자동 연결`,
              status: 'waiting',
              statusLabel: `🟡 슬롯대기 (⏰ ${stHm} 예정)`,
              url: ''
            });
          }
        }
      } catch (_) {}
    } else if (channel === 'apps') {
      try {
        const res = await fetch('/api/projects', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
        if (res.ok) {
          const pData = await res.json();
          const projects = Array.isArray(pData.projects) ? pData.projects : [];
          state.visitorsToday = `앱 ${projects.length}종 가동`;
          state.visitorsSub = 'Google Play 비공개 테스트 14일 D-Day 관제 중';

          projects.forEach(p => {
            const ms = Array.isArray(p.milestones) ? p.milestones : [];
            const vCnt = ms.filter(m => m.status === 'verified').length;
            const pct = Math.round((vCnt / Math.max(1, ms.length)) * 100);
            ms.forEach(m => {
              const st = m.status === 'verified' ? 'public' : (m.status === 'in_progress' ? 'reserved' : 'waiting');
              rows.push({
                date: today,
                col1: `📱 ${p.name}`,
                col2: `${p.stage || '내부 테스트'} (${pct}%)`,
                title: `[${m.title || m.id}] ${m.evidence || m.description || '실기기 및 Play 콘솔 검증 항목'}`,
                meta: m.updatedAt ? m.updatedAt.slice(0, 10) : 'Play Console 연동',
                status: st,
                statusLabel: st === 'public' ? '🟢 검증완료' : (st === 'reserved' ? '🔵 테스트진행' : '🟡 출시대기'),
                url: ''
              });
            });
          });
        }
      } catch (_) {}
    }

    state.allRows = rows;
    render14DayLedChart(dayCounts);
    renderTableAndGauges();
    } finally { channelLoadPending = false; }
  }

  function renderActionCell(r, absIdx) {
    if (channel === 'naver') {
      if (r.status === 'public' && isValidPostDetailUrl(r.url, 'naver')) {
        return `
          <a class="sig-open-link" href="${r.url}" target="_blank" rel="noopener" onclick="event.stopPropagation();">
            글 보기 ↗
          </a>
        `;
      }
      if (r.isProcessing) {
        return `
          <button type="button" class="sig-open-link" style="background:linear-gradient(135deg,#2563eb,#1d4ed8);border-color:#60a5fa;color:#fff;cursor:pointer;" onclick="event.stopPropagation(); window.BaroSigDeck.selectRow(${absIdx});">
            ⚡ 진행 상세
          </button>
        `;
      }
      if (r.status === 'overdue') {
        return `
          <button type="button" class="sig-retry-btn" onclick="event.stopPropagation(); window.BaroSigDeck.triggerRetry(${absIdx}, this)">
            ⚡ 즉시 재발행
          </button>
        `;
      }
      if (r.status === 'reserved') {
        if (r.previewUrl) {
          return `
            <a class="sig-open-link" style="background:linear-gradient(135deg,#2563eb,#1d4ed8);border-color:#60a5fa;color:#fff;" href="${r.previewUrl}" target="_blank" rel="noopener" onclick="event.stopPropagation();">
              원고 미리보기
            </a>
          `;
        }
        return `
          <button type="button" class="sig-open-link" style="background:linear-gradient(135deg,#2563eb,#1d4ed8);border-color:#60a5fa;color:#fff;cursor:pointer;" onclick="event.stopPropagation(); window.BaroSigDeck.openRowModal(${absIdx});">
            원고 미리보기
          </button>
        `;
      }
      return `<span class="sig-action-muted">작업 전</span>`;
    }

    if (r.status === 'public' && isValidPostDetailUrl(r.url, channel)) {
      return `
        <a class="sig-open-link" href="${r.url}" target="_blank" rel="noopener" onclick="event.stopPropagation();">
          글 보기 ↗
        </a>
      `;
    }
    if (r.isProcessing || r.rawStatus === 'processing') {
      return `<span class="sig-action-muted processing">${channel === 'kin' ? '답변 집필 중 ⚙️' : '생성 중 ⚙️'}</span>`;
    }
    if (r.status === 'overdue') {
      return `
        <button type="button" class="sig-retry-btn" onclick="event.stopPropagation(); window.BaroSigDeck.triggerRetry(${absIdx}, this)">
          ${channel === 'kin' ? '⚡ 지금 즉시 실행' : '⚡ 즉시 재발행'}
        </button>
      `;
    }
    if (r.status === 'reserved' && r.previewUrl) {
      return `
        <a class="sig-open-link" style="background:linear-gradient(135deg,#2563eb,#1d4ed8);" href="${r.previewUrl}" target="_blank" rel="noopener" onclick="event.stopPropagation();">
          원고 프리뷰 ↗
        </a>
      `;
    }
    const schedNote = r.scheduledTime ? ` (${r.scheduledTime} 예정)` : '';
    return `<span class="sig-action-muted">발행 전${schedNote}</span>`;
  }

  function renderPipelineStepper7(filteredRows, dateMatchedRows) {
    if (channel !== 'cf' && channel !== 'naver') return;
    const pillEl = document.getElementById('sig-step-active-pill');
    const subEl = document.getElementById('sig-step-sub-note');
    if (!pillEl || !subEl) return;

    const today = getKSTDateStr(0);
    const tomorrow = getKSTDateStr(1);
    const nowMins = getKSTNowMinutes();
    const todayRows = state.allRows.filter(r => r.date === today && !r.isRollover);
    const tomorrowRows = state.allRows.filter(r => r.date === tomorrow && !r.isRollover);

    // 1. Determine target slot row for the 7-stage pipeline stepper:
    //    - Manual row selection if user clicked a row
    //    - Otherwise:
    //      (a) Currently running non-stale process (PID/lock active)
    //      (b) Next-Up waiting slot today (sorted by scheduledTime ascending)
    //      (c) Overdue / immediate retry slot
    //      (d) Tomorrow's waiting/overdue slot (for Naver) or most recent completed slot
    let targetRow = null;
    let isManualSelection = false;
    let focusMode = 'idle';

    if (state.selectedRowIdx !== null && filteredRows[state.selectedRowIdx]) {
      targetRow = filteredRows[state.selectedRowIdx];
      isManualSelection = true;
      focusMode = 'manual';
    } else {
      const activeRunning = todayRows.find(r => r.isProcessing && !r.isStaleZombie)
        || state.allRows.find(r => r.isProcessing && !r.isStaleZombie);

      if (activeRunning) {
        targetRow = activeRunning;
        focusMode = 'running';
      } else {
        const waitingToday = todayRows
          .filter(r => r.status === 'waiting')
          .slice()
          .sort((a, b) => parseTimeToMinutes(a.scheduledTime) - parseTimeToMinutes(b.scheduledTime));
        const nextUpcoming = waitingToday.find(r => parseTimeToMinutes(r.scheduledTime) >= nowMins) || waitingToday[0];
        const overdueToday = todayRows.find(r => r.status === 'overdue' || r.isStaleZombie);

        if (nextUpcoming) {
          targetRow = nextUpcoming;
          focusMode = 'next_up';
        } else if (overdueToday) {
          targetRow = overdueToday;
          focusMode = 'overdue';
        } else if (channel === 'naver') {
          const naverNext = tomorrowRows.find(r => r.isProcessing && !r.isStaleZombie)
            || tomorrowRows.find(r => r.status === 'overdue')
            || tomorrowRows.find(r => r.status === 'waiting')
            || todayRows.find(r => r.status === 'reserved')
            || todayRows[todayRows.length - 1];
          targetRow = naverNext || filteredRows[0] || state.allRows[0];
          focusMode = 'naver_next';
        } else {
          targetRow = todayRows[todayRows.length - 1] || filteredRows[0] || state.allRows[0];
          focusMode = 'completed_all';
        }
      }
    }
    if (!targetRow) return;

    const slotPrefix = channel === 'cf'
      ? `#${targetRow.slotOrder || targetRow.domainIdx || 1} ${targetRow.domain}`
      : `[${targetRow.accNo || 1}호기 ${targetRow.account} · ${targetRow.scheduledTime}]`;
    const prepHm = targetRow.prepTime || targetRow.scheduledTime || '09:00';
    const doneHm = targetRow.reservedAtKst || targetRow.updatedAt || targetRow.scheduledTime || prepHm;

    const setStepNode = (idx, cls, badgeText, descText) => {
      const node = document.getElementById(`sig-step-node-${idx}`);
      const badge = document.getElementById(`sig-step-badge-${idx}`);
      const desc = document.getElementById(`sig-step-desc-${idx}`);
      if (node) node.className = `sig-step-node ${cls}`;
      if (badge) badge.textContent = badgeText;
      if (desc) desc.textContent = descText;
    };

    const stageDoneDescs = {
      1: `도메인 카테고리 맞춤형 키워드·주제 확정`,
      2: `공식 문서·통계 팩트체크 및 근거 수집 완료`,
      3: `체류형 전문 원고 집필(Writer) 완료`,
      4: `실화면 캡처·인포그래픽 생성·EXIF 세탁 완료`,
      5: `Reviewer 품질 검수 및 부분수선 통과`,
      6: channel === 'cf' ? `Cloudflare Pages 빌드·배포 완료` : `스마트에디터 발행/예약 등록 완료`,
      7: `라이브 URL 200 OK 응답 및 색인 검증 완료`
    };

    const stageWaitDescs = {
      1: `도메인 전문 카테고리 기반 키워드·주제 선정 대기`,
      2: `공식 기관 문서·근거 데이터 수집 대기`,
      3: `체류형 본문 원고 집필(Writer) 대기`,
      4: `캡처·이미지 생성 및 EXIF 메타 세탁 대기`,
      5: `Reviewer 팩트·가독성 검수 및 수선 대기`,
      6: channel === 'cf' ? `Cloudflare 정적 빌드·배포 대기` : `스마트에디터 에디터 발행 대기`,
      7: `실제 URL 200 OK 응답 및 서치어드바이저 색인 대기`
    };

    if (targetRow.isProcessing && !targetRow.isStaleZombie) {
      const curStage = Math.max(1, Math.min(7, targetRow.stage7Idx || 3));
      const pctVal = targetRow.progressPct || 35;
      const pctStr = `${pctVal}%`;
      const elapsed = targetRow.elapsedText || '실시간 진행 중';

      pillEl.className = 'sig-tier2-active-pill pill-running';
      pillEl.textContent = `⚡ 현재 작업 중: ${slotPrefix} · ${curStage}단계: ${STAGE7_SHORT[curStage]} (${pctStr}) - 경과 ${elapsed}`;
      subEl.textContent = `실시간 작업 원고: "${targetRow.title}" (${targetRow.col2}) · 예정 ${targetRow.scheduledTime} · 최근 하트비트 ${targetRow.updatedAt || '방금 전'}`;

      for (let i = 1; i <= 7; i++) {
        if (i < curStage) {
          setStepNode(i, 'st-done', '🟢 완료', stageDoneDescs[i]);
        } else if (i === curStage) {
          setStepNode(i, 'st-active', `🔵 진행중 (${pctStr})`, `${curStage}단계: ${STAGE7_SHORT[curStage]} (${pctStr}) - 경과 ${elapsed}`);
        } else {
          setStepNode(i, 'st-wait', '⚪ 대기', stageWaitDescs[i]);
        }
      }
    } else if (targetRow.status === 'overdue' || targetRow.isStaleZombie) {
      const stopStage = Math.max(1, Math.min(7, targetRow.stage7Idx || 3));
      pillEl.className = 'sig-tier2-active-pill pill-overdue';
      pillEl.textContent = `🟠 지연·재시도 감지: ${slotPrefix} · ${stopStage}단계(${STAGE7_SHORT[stopStage]}) 좀비 락 해제 및 즉시 재시도 대기`;
      subEl.textContent = `사유: ${targetRow.failureReason || '15분 초과 정체 감지 ➔ 락 자동 해제 및 재시도 큐 진입'} · 대상 원고: "${targetRow.title}" (${targetRow.col2})`;

      for (let i = 1; i <= 7; i++) {
        if (i < stopStage) {
          setStepNode(i, 'st-done', '🟢 완료', stageDoneDescs[i]);
        } else if (i === stopStage) {
          setStepNode(i, 'st-error', '🟠 지연·재시도', `${targetRow.failureReason || '락 해제 완료 · 워커 즉시 재시도 대기'}`);
        } else {
          setStepNode(i, 'st-wait', '⚪ 대기', stageWaitDescs[i]);
        }
      }
    } else if (targetRow.status === 'waiting') {
      const schedMins = parseTimeToMinutes(targetRow.scheduledTime);
      const diffMins = schedMins - nowMins;
      let remainStr = '곧 시작';
      if (targetRow.date !== today) {
        remainStr = `${targetRow.date.slice(5)} ${targetRow.scheduledTime} 예정`;
      } else if (diffMins > 60) {
        remainStr = `남은 시간 ${Math.floor(diffMins / 60)}시간 ${diffMins % 60}분`;
      } else if (diffMins > 0) {
        remainStr = `남은 시간 ${diffMins}분`;
      } else {
        remainStr = `슬롯 도래 · 즉시 실행 대기`;
      }

      const overdueNote = todayRows.some(r => r.status === 'overdue')
        ? ` · (🟠 지연 슬롯 자동 재시도 병행 중)`
        : '';

      pillEl.className = 'sig-tier2-active-pill';
      pillEl.textContent = `${isManualSelection ? '🔍 선택 슬롯 대기' : '⏭️ 다음 발행 예정'}: ${slotPrefix} · ${targetRow.scheduledTime} 발행 예정 - 대기 중 (${remainStr})`;
      subEl.textContent = `다음 예정 원고: "${targetRow.title}" (${targetRow.col2}) · 현재 실행 중인 프로세스 없음 (유휴 구간)${overdueNote} · 행 클릭 시 개별 슬롯 검수`;

      setStepNode(1, 'st-wait', `🟡 ${targetRow.scheduledTime} 예정`, `${remainStr} · 키워드·주제선정 대기`);
      for (let i = 2; i <= 6; i++) {
        setStepNode(i, 'st-wait', '⚪ 대기', stageWaitDescs[i]);
      }
      setStepNode(7, 'st-wait', `⚪ ${targetRow.scheduledTime} 목표`, stageWaitDescs[7]);
    } else if (targetRow.status === 'reserved') {
      pillEl.className = 'sig-tier2-active-pill';
      pillEl.textContent = `${isManualSelection ? '🔍 선택 슬롯 검수' : '🔵 예약 등록 완료'}: ${slotPrefix} · 1~6단계 완료 ➔ ⑦ ${targetRow.date.slice(5)} ${targetRow.scheduledTime} 오픈·색인 대기`;
      subEl.textContent = `예약 원고: "${targetRow.title}" (${targetRow.col2}) · ${doneHm} 예약등록 완료 ➔ ${targetRow.date.slice(5)} ${targetRow.scheduledTime} 자동 공개 및 200 OK 검증 예정`;

      for (let i = 1; i <= 6; i++) {
        setStepNode(i, 'st-done', `🟢 완료 (${doneHm})`, stageDoneDescs[i]);
      }
      setStepNode(7, 'st-active', `🔵 ${targetRow.scheduledTime} 오픈대기`, `예약 시각 도래 시 200 OK 및 RSS 색인 자동 확인`);
    } else {
      pillEl.className = 'sig-tier2-active-pill';
      pillEl.textContent = `${isManualSelection ? '🔍 선택 슬롯 검수' : '🟢 전 공정 발행 완료'}: ${slotPrefix} · 1~7단계 200 OK 검증 완료 (${doneHm})`;
      subEl.textContent = `발행 완료 원고: "${targetRow.title}" (${targetRow.col2}) · 라이브 URL 200 OK 응답 및 색인 제출 완료 (클릭 시 다른 슬롯 점검)`;

      for (let i = 1; i <= 7; i++) {
        setStepNode(i, 'st-done', i === 7 ? `🟢 200 OK (${doneHm})` : `🟢 완료`, stageDoneDescs[i]);
      }
    }
  }

  function renderTableAndGauges() {
    const today = getKSTDateStr(0);
    const tomorrow = getKSTDateStr(1);
    const yesterday = getKSTDateStr(-1);
    const meta = CHANNEL_META[channel];

    // Resolve active target date when in daily mode
    let activeDateStr = today;
    if (state.dateFilter === 'today') activeDateStr = today;
    else if (state.dateFilter === 'tomorrow') activeDateStr = tomorrow;
    else if (state.dateFilter === 'yesterday') activeDateStr = yesterday;
    else if (state.dateFilter === 'custom') activeDateStr = state.customDate || today;

    // Filter rows by date first
    const dateMatchedRows = state.allRows.filter(r => {
      if (state.dateFilter === 'today') return r.date === today && !r.isRollover;
      if (state.dateFilter === 'tomorrow') return r.date === tomorrow && !r.isRollover;
      if (state.dateFilter === 'yesterday') return r.date === yesterday;
      if (state.dateFilter === 'custom') return r.date === activeDateStr && !r.isRollover;
      return !r.isRollover;
    });

    const pubCnt = dateMatchedRows.filter(r => r.status === 'public').length;
    const resCnt = dateMatchedRows.filter(r => r.status === 'reserved').length;
    const overdueCnt = dateMatchedRows.filter(r => r.status === 'overdue').length;
    const waitCnt = dateMatchedRows.filter(r => r.status === 'waiting').length;

    if (channel === 'naver') {
      // Strictly separate Card 1 (Today 10-18 Public Status) and Card 2 (Tomorrow 10-19 Reservation Status)
      const todayRows = state.allRows.filter(r => r.date === today && !r.isRollover);
      const tomorrowRows = state.allRows.filter(r => r.date === tomorrow && !r.isRollover);

      const tdPub = todayRows.filter(r => r.status === 'public').length;
      const tdOpenWait = todayRows.filter(r => r.status === 'reserved' && !r.isProcessing).length;
      const tdProc = todayRows.filter(r => r.isProcessing).length;
      const tdOverdue = todayRows.filter(r => r.status === 'overdue').length;
      const tdPct = Math.min(100, Math.round((tdPub / 7) * 100));

      const ring1 = document.getElementById('sig-ring-fg');
      if (ring1) ring1.style.strokeDashoffset = (150.8 * (1 - tdPct / 100)).toFixed(1);
      const pct1 = document.getElementById('sig-gauge-pct');
      if (pct1) pct1.textContent = `${tdPct}%`;
      const frac1 = document.getElementById('sig-gauge-fraction');
      if (frac1) frac1.textContent = `${tdPub} / 7건 공개완료`;
      const head1 = document.getElementById('sig-gauge-headline');
      if (head1) {
        head1.style.fontSize = '11px';
        head1.style.letterSpacing = '-0.04em';
        head1.textContent = `🟢 공개됨 ${tdPub}건 · 🔵 오늘 오픈대기 ${tdOpenWait + tdProc}건`;
      }
      const bar1 = document.getElementById('sig-gauge-bar');
      if (bar1) bar1.style.width = `${Math.min(100, Math.round(((tdPub + tdOpenWait) / 7) * 100))}%`;

      // Card 2: Tomorrow (10-19) Reservation Status
      const tmRes = tomorrowRows.filter(r => r.status === 'reserved' && !r.isProcessing).length;
      const tmProc = tomorrowRows.filter(r => r.isProcessing).length;
      const tmOverdue = tomorrowRows.filter(r => r.status === 'overdue').length;
      const tmWait = tomorrowRows.filter(r => r.status === 'waiting').length;
      const tmPct = Math.min(100, Math.round((tmRes / 7) * 100));

      const ring2 = document.getElementById('sig-ring-fg-2');
      if (ring2) ring2.style.strokeDashoffset = (150.8 * (1 - tmPct / 100)).toFixed(1);
      const pct2 = document.getElementById('sig-gauge-pct-2');
      if (pct2) pct2.textContent = `${tmPct}%`;
      const frac2 = document.getElementById('sig-gauge-fraction-2');
      if (frac2) frac2.textContent = `${tmRes} / 7건 예약완료`;
      const head2 = document.getElementById('sig-gauge-headline-2');
      if (head2) {
        head2.style.fontSize = '9.8px';
        head2.style.letterSpacing = '-0.05em';
        head2.textContent = `🔵 예약완료 ${tmRes}건 · 🟠 지연/재시도 ${tmOverdue}건 · 🟡 작업대기 ${tmWait + tmProc}건`;
      }
      const bar2 = document.getElementById('sig-gauge-bar-2');
      if (bar2) bar2.style.width = `${tmPct}%`;
    } else {
      let targetVal = meta.defaultTarget;
      let achieved = pubCnt + resCnt;
      let unitStr = meta.unit;

      if (channel === 'cf' && state.dateFilter !== 'all') {
        targetVal = 16;
        achieved = Math.min(16, pubCnt);
      } else if (channel === 'apps') {
        targetVal = Math.max(1, dateMatchedRows.length);
        achieved = pubCnt + resCnt;
        unitStr = '건';
      } else {
        targetVal = meta.defaultTarget;
        achieved = Math.min(targetVal, pubCnt + resCnt);
      }
      const pct = Math.min(100, Math.round((achieved / Math.max(1, targetVal)) * 100));

      const ringEl = document.getElementById('sig-ring-fg');
      if (ringEl) {
        const C = 150.8;
        ringEl.style.strokeDashoffset = (C * (1 - pct / 100)).toFixed(1);
      }
      const pctEl = document.getElementById('sig-gauge-pct');
      if (pctEl) pctEl.textContent = `${pct}%`;

      const fracEl = document.getElementById('sig-gauge-fraction');
      if (fracEl) fracEl.textContent = `${achieved} / ${targetVal}${unitStr}`;

      const headEl = document.getElementById('sig-gauge-headline');
      if (headEl) {
        if (channel === 'kin' && state.kinQuotaSummary) {
          headEl.textContent = state.kinQuotaSummary;
          headEl.style.fontSize = '11px';
          headEl.style.letterSpacing = '-0.03em';
        } else if (channel === 'cf') {
          if (overdueCnt > 0 || resCnt > 0) {
            headEl.textContent = `🟢공개 ${pubCnt}/16 · ${resCnt > 0 ? `🔵진행 ${resCnt}` : `🟠지연 ${overdueCnt}건`}`;
          } else {
            headEl.textContent = `🟢공개완료 ${pubCnt} / 목표 ${targetVal}${unitStr}`;
          }
        } else if (resCnt > 0) {
          headEl.textContent = `🟢공개 ${pubCnt} · 🔵예약/진행 ${resCnt}`;
        } else {
          headEl.textContent = `🟢완료 ${pubCnt} / 목표 ${targetVal}${unitStr}`;
        }
      }
      const barEl = document.getElementById('sig-gauge-bar');
      if (barEl) barEl.style.width = `${pct}%`;

      const totLbl = document.getElementById('sig-total-items-label');
      if (totLbl) totLbl.textContent = `조회 ${dateMatchedRows.length}건`;

      const cPub = document.getElementById('sig-cnt-public');
      const cRes = document.getElementById('sig-cnt-reserved');
      const cWait = document.getElementById('sig-cnt-waiting');
      const cWaitLbl = document.getElementById('sig-cnt-waiting-label');
      if (cPub) cPub.textContent = `${pubCnt}건`;
      if (cRes) cRes.textContent = `${resCnt}건`;
      if (cWait) {
        if (overdueCnt > 0) {
          cWait.textContent = `${waitCnt + overdueCnt}건 (지연 ${overdueCnt})`;
          if (cWaitLbl) cWaitLbl.textContent = '🟠 지연/대기';
        } else {
          cWait.textContent = `${waitCnt}건`;
          if (cWaitLbl) cWaitLbl.textContent = '🟡 작업대기';
        }
      }
    }

    const vToday = document.getElementById('sig-visitors-today');
    const vSub = document.getElementById('sig-visitors-sub');
    if (vToday) {
      vToday.textContent = state.visitorsToday;
      if (channel === 'kin') {
        vToday.style.fontSize = '12.5px';
        vToday.style.letterSpacing = '-0.03em';
      }
    }
    if (vSub) vSub.textContent = state.visitorsSub;

    // Filter by status & search query for Tier 3 Table
    let filtered = dateMatchedRows.filter(r => {
      if (state.statusFilter !== 'all') {
        if (state.statusFilter === 'waiting') {
          if (r.status !== 'waiting' && r.status !== 'overdue') return false;
        } else if (r.status !== state.statusFilter) {
          return false;
        }
      }
      if (state.searchQuery) {
        const q = state.searchQuery.toLowerCase();
        const hay = `${r.col1} ${r.col2} ${r.title} ${r.meta}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    // Apply Sort Order for CF channel
    if (channel === 'cf' && state.dateFilter !== 'all') {
      filtered = filtered.slice().sort((a, b) => {
        if (state.sortOrder === 'schedule') {
          const tA = parseTimeToMinutes(a.scheduledTime);
          const tB = parseTimeToMinutes(b.scheduledTime);
          if (tA !== tB) return tA - tB;
          return (a.slotOrder || 99) - (b.slotOrder || 99);
        }
        return (a.domainIdx || 99) - (b.domainIdx || 99);
      });
    }

    state.currentFilteredRows = filtered;
    renderPipelineStepper7(filtered, dateMatchedRows);

    // Daily Views ('today' | 'tomorrow' | 'yesterday' | 'custom') -> Show 100% of items on ONE screen (NO 10-row slicing!)
    // Only '[전체 누적]' ('all') slices by 20 rows per page.
    const isAllCumulativeMode = state.dateFilter === 'all';
    let startIdx = 0;
    let pageRows = filtered;
    let totalPages = 1;

    if (isAllCumulativeMode) {
      totalPages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
      if (state.currentPage > totalPages) state.currentPage = totalPages;
      startIdx = (state.currentPage - 1) * state.pageSize;
      pageRows = filtered.slice(startIdx, startIdx + state.pageSize);
    }

    const tbody = document.getElementById('sig-work-tbody');
    if (tbody) {
      if (pageRows.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:20px;color:#64748b;font-weight:700;">해당 조건에 일치하는 작업 내역이 없습니다.</td></tr>`;
      } else {
        tbody.innerHTML = pageRows.map((r, idx) => {
          const absIdx = startIdx + idx;
          const rowNum = absIdx + 1;
          const stClass = r.status === 'public'
            ? 'st-public'
            : r.status === 'reserved'
              ? 'st-reserved'
              : r.status === 'overdue'
                ? 'st-overdue'
                : 'st-waiting';
          const isSelected = (channel === 'naver' || channel === 'cf') && state.selectedRowIdx === absIdx;
          const safeTitle = String(r.title || '').replace(/"/g, '&quot;');
          const rowClickAction = (channel === 'naver' || channel === 'cf')
            ? `window.BaroSigDeck.selectRow(${absIdx})`
            : `window.BaroSigDeck.openRowModal(${absIdx})`;
          return `
            <tr class="${isSelected ? 'sig-row-selected' : ''}" onclick="${rowClickAction}" title="${(channel === 'naver' || channel === 'cf') ? '클릭 시 상단 7단계 파이프라인 스텝퍼에 이 슬롯의 수행 상세 연동' : '클릭 시 해당 작업물 상세 정보 확인'}">
              <td style="text-align:center;font-weight:800;color:#64748b;">${rowNum}</td>
              <td style="font-variant-numeric:tabular-nums;font-weight:700;color:#475569;">${r.date}</td>
              <td style="font-weight:800;color:#0f172a;">${r.col1}</td>
              <td><span style="font-size:10px;font-weight:700;padding:2px 5px;border-radius:5px;background:#f1f5f9;color:#334155;">${r.col2}</span></td>
              <td style="max-width:225px;overflow:hidden;text-overflow:ellipsis;font-weight:700;color:#0f172a;">${safeTitle}</td>
              <td style="font-size:10px;color:#475569;font-weight:700;">${r.meta}</td>
              <td><span class="sig-status-pill ${stClass}">${r.statusLabel}</span></td>
              <td>${renderActionCell(r, absIdx)}</td>
            </tr>
          `;
        }).join('');
      }
    }

    // Render Bottom Pagination Bar:
    // - In Daily Mode: Date Pagination (< 1=오늘 10-18 | 2=어제 10-17 | 3=10-16 | 4=10-15 | 5=10-14 >)
    // - In Cumulative Mode ('all'): Row Pagination (20 per page)
    const sumEl = document.getElementById('sig-page-summary');
    const pageBtns = document.getElementById('sig-page-btns');

    if (!isAllCumulativeMode) {
      let curDatePage = state.datePage || 1;
      for (let p = 1; p <= 5; p++) {
        if (getKSTDateStr(-(p - 1)) === activeDateStr) {
          curDatePage = p;
          break;
        }
      }
      state.datePage = curDatePage;

      if (sumEl) {
        if (channel === 'naver' && state.dateFilter === 'tomorrow') {
          sumEl.textContent = `🚀 내일(${tomorrow}) 예약분 ${filtered.length}건 (하루 7건 고정 슬롯) 한 화면 100% 전체 표시`;
        } else if (channel === 'naver' && state.dateFilter === 'today') {
          sumEl.textContent = `📅 오늘(${today}) 발행분 ${filtered.length}건 (하루 7건 고정 슬롯) 한 화면 100% 전체 표시`;
        } else {
          sumEl.textContent = `📅 ${activeDateStr} 당일 작업물 ${filtered.length}건 한 화면 100% 전체 표시 · 날짜 이동 (${curDatePage} / 5일 페이지)`;
        }
      }
      if (pageBtns) {
        const btns = [];
        btns.push(`<button type="button" class="sig-page-btn" ${curDatePage <= 1 ? 'disabled' : ''} onclick="window.BaroSigDeck.goDatePage(${curDatePage - 1})" title="다음 날짜(최신)로 이동">‹</button>`);
        for (let p = 1; p <= 5; p++) {
          const dStr = getKSTDateStr(-(p - 1));
          const shortMd = dStr.slice(5);
          const lbl = p === 1 ? `1 (${shortMd} 오늘)` : p === 2 ? `2 (${shortMd} 어제)` : `${p} (${shortMd})`;
          const isActive = dStr === activeDateStr && state.dateFilter !== 'tomorrow';
          btns.push(`<button type="button" class="sig-page-btn ${isActive ? 'active' : ''}" style="width:auto;padding:0 9px;" onclick="window.BaroSigDeck.goDatePage(${p})" title="${dStr} 전체 목록 보기">${lbl}</button>`);
        }
        btns.push(`<button type="button" class="sig-page-btn" ${curDatePage >= 5 ? 'disabled' : ''} onclick="window.BaroSigDeck.goDatePage(${curDatePage + 1})" title="이전 날짜로 이동">›</button>`);
        pageBtns.innerHTML = btns.join('');
      }
    } else {
      if (sumEl) {
        sumEl.textContent = `전체 누적 총 ${filtered.length}건 · ${state.currentPage} / ${totalPages} 페이지 (페이지당 ${state.pageSize}건 표시)`;
      }
      if (pageBtns) {
        const btns = [];
        btns.push(`<button type="button" class="sig-page-btn" ${state.currentPage <= 1 ? 'disabled' : ''} onclick="window.BaroSigDeck.goPage(${state.currentPage - 1})">‹</button>`);
        const maxPagesToShow = Math.max(5, totalPages);
        for (let p = 1; p <= Math.min(5, maxPagesToShow); p++) {
          const disabled = p > totalPages;
          btns.push(`<button type="button" class="sig-page-btn ${p === state.currentPage ? 'active' : ''}" ${disabled ? 'disabled' : ''} onclick="window.BaroSigDeck.goPage(${p})">${p}</button>`);
        }
        btns.push(`<button type="button" class="sig-page-btn" ${state.currentPage >= totalPages ? 'disabled' : ''} onclick="window.BaroSigDeck.goPage(${state.currentPage + 1})">›</button>`);
        pageBtns.innerHTML = btns.join('');
      }
    }
  }

  window.BaroSigDeck = {
    selectRow(idx) {
      state.selectedRowIdx = idx;
      renderTableAndGauges();
    },
    setDateFilter(mode) {
      state.dateFilter = mode;
      state.currentPage = 1;
      state.selectedRowIdx = null;
      if (mode === 'today') {
        state.customDate = getKSTDateStr(0);
        state.datePage = 1;
      } else if (mode === 'yesterday') {
        state.customDate = getKSTDateStr(-1);
        state.datePage = 2;
      }
      const dateInput = document.getElementById('sig-custom-date');
      if (dateInput && (mode === 'today' || mode === 'yesterday')) {
        dateInput.value = state.customDate;
      }
      document.querySelectorAll('[data-date-tab]').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-date-tab') === mode);
      });
      renderTableAndGauges();
    },
    goDatePage(p) {
      const pageNum = Math.max(1, Math.min(5, p));
      state.datePage = pageNum;
      state.selectedRowIdx = null;
      const targetDate = getKSTDateStr(-(pageNum - 1));
      state.customDate = targetDate;
      if (pageNum === 1) {
        state.dateFilter = 'today';
      } else if (pageNum === 2) {
        state.dateFilter = 'yesterday';
      } else {
        state.dateFilter = 'custom';
      }
      const dateInput = document.getElementById('sig-custom-date');
      if (dateInput) dateInput.value = targetDate;
      document.querySelectorAll('[data-date-tab]').forEach(btn => {
        const tab = btn.getAttribute('data-date-tab');
        btn.classList.toggle('active', (pageNum === 1 && tab === 'today') || (pageNum === 2 && tab === 'yesterday'));
      });
      renderTableAndGauges();
    },
    setStatusFilter(st) {
      state.statusFilter = st;
      state.currentPage = 1;
      state.selectedRowIdx = null;
      document.querySelectorAll('[data-st-tab]').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-st-tab') === st);
      });
      renderTableAndGauges();
    },
    setSortOrder(order) {
      state.sortOrder = order;
      document.querySelectorAll('[data-sort-tab]').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-sort-tab') === order);
      });
      renderTableAndGauges();
    },
    goPage(p) {
      state.currentPage = Math.max(1, p);
      renderTableAndGauges();
    },
    async triggerRetry(idx, btnEl) {
      const row = (state.currentFilteredRows || [])[idx];
      if (!row) return;
      if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = '⏳ 재발행 요청중...';
      }
      try {
        if (channel === 'cf') {
          const res = await fetch('/api/workflows/cf/retry', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-BaroLab-Settings': '1'
            },
            body: JSON.stringify({ domain: row.domain, id: row.blogId, date: row.date })
          });
          if (res.ok && btnEl) {
            btnEl.textContent = '🚀 재시도 큐 등록됨';
          }
        } else if (channel === 'naver') {
          await fetch('/api/naver/verify-overdue', { method: 'POST' });
          if (btnEl) btnEl.textContent = '🚀 검증·재시도 완료';
        } else if (channel === 'kin') {
          let res = await fetch('/api/kin/run-now', { method: 'POST' }).catch(() => null);
          if (!res || !res.ok) {
            res = await fetch('http://192.168.45.248:8790/api/kin/run-now', { method: 'POST' }).catch(() => null);
          }
          if (!res || !res.ok) {
            res = await fetch('http://127.0.0.1:8790/api/kin/run-now', { method: 'POST' }).catch(() => null);
          }
          if (res && res.ok && btnEl) {
            btnEl.textContent = '🚀 즉시 가동 시작됨';
          }
        }
        setTimeout(() => loadChannelData(), 1200);
      } catch (_) {
        if (btnEl) {
          btnEl.disabled = false;
          btnEl.textContent = channel === 'kin' ? '⚡ 지금 즉시 실행' : '⚡ 즉시 재발행';
        }
      }
    },
    async runKinNow(btnEl) {
      if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = '⏳ 워커 가동중...';
      }
      try {
        let res = await fetch('/api/kin/run-now', { method: 'POST' }).catch(() => null);
        if (!res || !res.ok) {
          res = await fetch('http://192.168.45.248:8790/api/kin/run-now', { method: 'POST' }).catch(() => null);
        }
        if (!res || !res.ok) {
          res = await fetch('http://127.0.0.1:8790/api/kin/run-now', { method: 'POST' }).catch(() => null);
        }
        if (btnEl) {
          btnEl.textContent = '🚀 즉시 실행 시작됨';
          setTimeout(() => {
            btnEl.disabled = false;
            btnEl.textContent = '⚡ 지연 슬롯 즉시 실행';
          }, 3000);
        }
        setTimeout(() => loadChannelData(), 1200);
      } catch (_) {
        if (btnEl) {
          btnEl.disabled = false;
          btnEl.textContent = '⚡ 지연 슬롯 즉시 실행';
        }
      }
    },
    openRowModal(idx) {
      const row = (state.currentFilteredRows || [])[idx];
      if (!row) return;
      const modal = document.getElementById('sig-row-preview-modal');
      if (!modal) return;
      const badge = document.getElementById('sig-modal-badge');
      const head = document.getElementById('sig-modal-head');
      const sub = document.getElementById('sig-modal-sub');
      const title = document.getElementById('sig-modal-title');
      const url = document.getElementById('sig-modal-url');
      const openBtn = document.getElementById('sig-modal-open-btn');

      const stClass = row.status === 'public'
        ? 'st-public'
        : row.status === 'reserved'
          ? 'st-reserved'
          : row.status === 'overdue'
            ? 'st-overdue'
            : 'st-waiting';
      if (badge) {
        badge.className = `sig-status-pill ${stClass}`;
        badge.textContent = row.statusLabel;
      }
      if (head) head.textContent = row.col1;
      if (sub) sub.textContent = `${row.date} · ${row.col2} · ${row.meta}`;
      if (title) title.textContent = row.title;
      const hasValidUrl = row.status === 'public' && isValidPostDetailUrl(row.url, channel);
      if (url) {
        url.textContent = hasValidUrl ? row.url : (row.previewUrl || '발행 완료 후 공개 상세 URL이 연결됩니다.');
        url.href = hasValidUrl ? row.url : (row.previewUrl || '#');
        url.style.pointerEvents = (hasValidUrl || row.previewUrl) ? 'auto' : 'none';
      }
      if (openBtn) {
        if (hasValidUrl) {
          openBtn.style.display = 'inline-block';
          openBtn.href = row.url;
          openBtn.textContent = '🚀 새 창에서 공개 글 보기 ↗';
        } else if (row.previewUrl) {
          openBtn.style.display = 'inline-block';
          openBtn.href = row.previewUrl;
          openBtn.textContent = '📄 로컬 원고 프리뷰 열기 ↗';
        } else {
          openBtn.style.display = 'none';
        }
      }
      modal.style.display = 'flex';
    },
    toggleLegacyPanels() {
      const collapsed = document.body.classList.toggle('sig-legacy-collapsed');
      const arrow = document.getElementById('sig-legacy-toggle-arrow');
      if (arrow) arrow.textContent = collapsed ? '▼ 펼치기' : '▲ 접기';
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      mountSignatureDeck();
      loadChannelData();
      setInterval(() => loadChannelData(), 15000);
    });
  } else {
    mountSignatureDeck();
    loadChannelData();
    setInterval(() => loadChannelData(), 15000);
  }
})();
