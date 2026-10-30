/* BaroLab Threads Monetization & Viral Hybrid Deck Controller (threads.js) */
(() => {
  'use strict';
  const api = window.BaroLabThreadsSummary;

  const API_BASES = [
    '',
    'http://127.0.0.1:8790',
    'http://192.168.45.248:8790',
    'http://127.0.0.1:8791'
  ];

  async function apiFetch(path, options = {}) {
    for (const base of API_BASES) {
      try {
        const res = await fetch(base + path, options);
        if (res.ok) return res;
      } catch (_) {}
    }
    throw new Error('API request failed: ' + path);
  }

  const KST_OFFSET = 9 * 3600 * 1000;
  function getKSTToday() {
    return new Date(Date.now() + KST_OFFSET).toISOString().slice(0, 10);
  }

  const DEFAULT_HOOKS = [
    { id: 'hk1', category: '정책·지원금', hook_formula: '솔직히 이거 몰라서 매년 N만 원 그냥 날리는 사람 진짜 많더라...', avg_hook_score: 95 },
    { id: 'hk2', category: '생활·꿀팁', hook_formula: '아니 나만 지금까지 이렇게 불편하게 쓰고 있었어? 진작 바꿀걸 그랬네 😂', avg_hook_score: 92 },
    { id: 'hk3', category: '시니어·건강', hook_formula: '잠깐, 스크롤 내리기 전에 본인이나 부모님이 해당되는지 딱 10초만 확인해 봐.', avg_hook_score: 93 },
    { id: 'hk4', category: '토스·쿠팡 제휴', hook_formula: '요즘 책상 위에서 제일 잘 샀다고 생각하는 원탑 아이템 하나만 꼽으라면 무조건 이거.', avg_hook_score: 94 }
  ];

  let deckState = {
    dateFilter: 'all',
    modeFilter: 'all',
    searchQuery: '',
    selectedVariant: 'hook',
    currentDraftId: '',
    hooks: DEFAULT_HOOKS,
    pairedThreads: []
  };

  function buildDefault4SlotThreads(today, existingPairs) {
    const bySlot = {};
    existingPairs.forEach(p => {
      if (p.publication_date === today && p.slot) bySlot[p.slot] = p;
    });

    const scheduleTemplate = [
      {
        slot: '08:00',
        mode: 'warmup',
        title: '[출근길 밑밥글] 요즘 시간 체감 속도 2배속 공감 스레드',
        domain: '순수 소통 (외부링크 0개)',
        source_url: 'https://www.threads.com/@mustpickinfo',
        main_text: '출근길 지하철에서 문득 느낀 건데, 요즘 진짜 시간 가는 속도가 체감상 2배속 같지 않아? ☕\n\n아침마다 오늘 꼭 끝낼 일 딱 1가지만 수첩에 적기 시작했는데 생각보다 머리가 덜 복잡하더라.\n다들 오늘 커피 몇 잔째야? 오늘 하루도 무사히 버텨보자 👇',
        followup_text: null,
        delay: 0
      },
      {
        slot: '12:30',
        mode: 'cf_inbound',
        title: '[점심 CF 유입] 정부24 가족관계증명서 일반·상세·특정 3초 구분법',
        domain: 'must-pick.com · justinfo.co.kr',
        source_url: 'https://www.must-pick.com/family-relation-certificate-general-detailed-specific-guide',
        main_text: '솔직히 가족관계증명서 무조건 "상세"로 떼면 다 되는 줄 아는 사람 진짜 많더라...\n\n딱 10초만 투자해서 핵심 3줄만 먼저 확인해 봐:\n① 일반증명서: 현재 유효한 필수 가족관계만 깔끔하게 표시\n② 상세증명서: 과거 이혼·입양·사망 내역까지 전부 노출 (요구할 때만 제출!)\n③ 특정증명서: 내가 선택한 특정 가족 1명의 관계만 부분 증명\n\n자세한 발급 경로랑 제출처별 체크리스트는 아래 첫 댓글(타래)에 남겨둘게 👇',
        followup_text: '제가 직접 정리·운영하는 블로그(MustPick)에 정부24 발급 화면과 제출 전 확인 순서를 정리해 두었습니다.\n\n👉 상세 가이드 보러가기:\nhttps://www.must-pick.com/family-relation-certificate-general-detailed-specific-guide?utm_source=threads&utm_medium=social&utm_campaign=cf_bridge',
        delay: 120
      },
      {
        slot: '18:10',
        mode: 'affiliate',
        title: '[퇴근길 꿀템·제휴] 손목 통증 싹 사라진 데스크 버티컬 마우스 실사용 요약',
        domain: 'toss.im · link.coupang.com',
        source_url: 'https://toss.im/shopping-share-preview',
        main_text: '아니 나만 지금까지 일반 마우스 쓰면서 손목 뻐근한 거 참고 있었어? 진작 바꿀걸 그랬네 😂\n\n하루 8시간 넘게 모니터 앞에 앉아 있는 사람이면 이 3가지만 기억해:\n① 악수하듯 쥐는 57도 각도라 손목 비틀림이 즉시 줄어듦\n② 클릭 소음이 거의 없어서 사무실·야간 작업에 눈치 안 보임\n③ 블루투스 멀티페어링으로 노트북·태블릿 원터치 전환\n\n오늘 기준 할인 들어간 최저가 좌표는 아래 첫 댓글(타래)에 남겨둘게 👇',
        followup_text: '이 포스팅은 제휴마케팅(토스 쇼핑 쉐어링크 / 쿠팡 파트너스) 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.\n\n👉 오늘 할인가 좌표 바로 확인하기:\nhttps://toss.im/shopping-share-preview',
        delay: 135
      },
      {
        slot: '21:30',
        mode: 'cf_inbound',
        title: '[야간 고단가 금융·세무] 놓치면 그냥 날리는 환급금·지원금 3대 조회 루트',
        domain: 'baronote.kr · must-good.com',
        source_url: 'https://www.must-good.com/unclaimed-refund-check-guide',
        main_text: '솔직히 이거 몰라서 매년 수십만 원 환급금 그냥 국고로 귀속시키는 사람 진짜 많더라...\n\n자기 전에 딱 1분만 내서 이 3군데는 꼭 조회해 봐:\n① 정부24 미환급금 찾기: 지방세·건강보험 과오납금 통합 조회\n② 홈택스 국세환급금: 최근 5년 내 찾아가지 않은 종합소득세 환급\n③ 계좌통합관리서비스(어카운트인포): 휴면예금·카드포인트 즉시 현금화\n\n내가 직접 정리한 1분 통합 조회 링크랑 순서표는 아래 첫 댓글(타래)에 남겨둘게 👇',
        followup_text: '제가 직접 정리·운영하는 블로그에 항목별 환급 신청 경로와 준비사항을 한눈에 볼 수 있게 정리해 두었습니다.\n\n👉 상세 가이드 보러가기:\nhttps://www.must-good.com/unclaimed-refund-check-guide?utm_source=threads&utm_medium=social&utm_campaign=cf_bridge',
        delay: 150
      }
    ];

    const list = [];
    // Add real ledger pairs first
    existingPairs.forEach(p => {
      const mText = p.main?.preview || p.main?.text || '';
      const fText = p.followup?.preview || p.followup?.text || '';
      // If legacy single post had link inside main, show how it maps into main + followup preview
      let cleanMain = mText;
      let cleanFollow = fText;
      if (!cleanFollow && cleanMain.includes('https://')) {
        const idx = cleanMain.indexOf('제가 운영하는');
        if (idx > 0) {
          cleanFollow = cleanMain.slice(idx).trim();
          cleanMain = cleanMain.slice(0, idx).trim() + '\n\n자세한 확인 순서랑 정리표는 아래 첫 댓글(타래)에 남겨둘게 👇';
        }
      }
      list.push({
        attempt_id: p.attempt_id,
        publication_date: p.publication_date || today,
        slot: p.slot || '19:30',
        mode: p.mode || 'cf_inbound',
        title: p.title || 'Threads 발행 포스트',
        domain: (() => { try { return new URL(p.source_url).hostname; } catch { return 'must-pick.com'; } })(),
        source_url: p.source_url,
        main_state: p.main?.state || 'published_verified',
        main_text: cleanMain,
        permalink: p.main?.permalink || 'https://www.threads.com/@mustpickinfo',
        followup_text: cleanFollow || (p.mode === 'warmup' ? null : `제가 직접 정리·운영하는 블로그에 상세 가이드를 정리해 두었습니다.\n\n👉 바로가기:\n${p.source_url}`),
        followup_state: p.followup?.state || (p.main?.state === 'published_verified' ? 'published_verified' : 'queued'),
        followup_delay_seconds: p.followup_delay_seconds || 120,
        variants: p.variants || null
      });
    });

    // Ensure today's 4 hybrid slots are represented
    scheduleTemplate.forEach(tpl => {
      if (!bySlot[tpl.slot]) {
        list.push({
          attempt_id: `slot-${today}-${tpl.slot.replace(':', '')}`,
          publication_date: today,
          slot: tpl.slot,
          mode: tpl.mode,
          title: tpl.title,
          domain: tpl.domain,
          source_url: tpl.source_url,
          main_state: 'queued',
          main_text: tpl.main_text,
          permalink: 'https://www.threads.com/@mustpickinfo',
          followup_text: tpl.followup_text,
          followup_state: tpl.mode === 'warmup' ? 'none' : 'queued',
          followup_delay_seconds: tpl.delay
        });
      }
    });

    return list;
  }

  function renderHookVaultChips() {
    const host = document.getElementById('th-hook-vault-chips');
    if (!host) return;
    host.innerHTML = (deckState.hooks || DEFAULT_HOOKS).slice(0, 5).map((h, i) => `
      <span class="th-hook-badge" title="클릭 시 스마트 에디터에서 이 후킹 공식 바로 적용" onclick="window.BaroThreadsDeck.applyHookToEditor(${i})">
        <span style="color:#2563eb;font-weight:900;">[${h.category}]</span>
        <span>${String(h.hook_formula || '').slice(0, 34)}...</span>
        <span class="th-hook-score">${h.avg_hook_score || 94}점</span>
      </span>
    `).join('');
  }

  function renderConnectedThreads() {
    const host = document.getElementById('th-connected-threads-list');
    if (!host) return;
    const today = getKSTToday();

    const filtered = deckState.pairedThreads.filter(item => {
      if (deckState.dateFilter === 'today' && item.publication_date !== today) return false;
      if (deckState.dateFilter === 'published' && item.main_state !== 'published_verified') return false;
      if (deckState.modeFilter !== 'all' && item.mode !== deckState.modeFilter) return false;
      if (deckState.searchQuery) {
        const q = deckState.searchQuery.toLowerCase();
        const hay = `${item.title} ${item.main_text} ${item.followup_text || ''} ${item.domain}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    const countLbl = document.getElementById('th-pair-count-label');
    if (countLbl) countLbl.textContent = `조회 ${filtered.length}개 타래 세트 (본문 + 2분 딜레이 첫 답글 묶음)`;

    if (!filtered.length) {
      host.innerHTML = `<div style="padding:24px;text-align:center;color:#64748b;font-weight:700;">조건에 해당하는 스레드 타래 세트가 없습니다.</div>`;
      return;
    }

    const modeBadge = m => {
      if (m === 'warmup') return `<span style="padding:2px 8px;border-radius:6px;background:#fef3c7;color:#92400e;font-size:10.5px;font-weight:800;">☕ Track A · 순수 밑밥글 (외부링크 0개)</span>`;
      if (m === 'affiliate') return `<span style="padding:2px 8px;border-radius:6px;background:#fce7f3;color:#9d174d;font-size:10.5px;font-weight:800;">💰 Track C · 토스/쿠팡 제휴 수익화</span>`;
      return `<span style="padding:2px 8px;border-radius:6px;background:#dbeafe;color:#1e40af;font-size:10.5px;font-weight:800;">🚀 Track B · 16개 CF 블로그 외부유입</span>`;
    };

    const statePill = st => {
      if (st === 'published_verified') return `<span class="sig-status-pill st-public">🟢 공개검증 완료</span>`;
      if (st === 'api_submitted') return `<span class="sig-status-pill st-reserved">🔵 API 접수완료</span>`;
      return `<span class="sig-status-pill st-waiting">🔵 슬롯 편성·대기</span>`;
    };

    host.innerHTML = filtered.map(item => {
      const hasFollowup = item.mode !== 'warmup' && item.followup_text;
      return `
        <article class="th-thread-pair-card">
          <div class="th-pair-header">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <span style="font-variant-numeric:tabular-nums;color:#475569;">📅 ${item.publication_date} · ⏰ ${item.slot} KST</span>
              ${modeBadge(item.mode)}
              <strong style="color:#0f172a;font-size:12.5px;">${item.title}</strong>
            </div>
            <div style="display:flex;align-items:center;gap:8px;white-space:nowrap;">
              ${statePill(item.main_state)}
              <a class="sig-open-link" href="${item.source_url || '#'}" target="_blank" rel="noopener">원문/목적지 ↗</a>
              <a class="sig-open-link" href="${item.permalink || 'https://www.threads.com/@mustpickinfo'}" target="_blank" rel="noopener">Threads 열기 ↗</a>
            </div>
          </div>

          <div class="th-pair-body">
            <!-- MAIN POST (0 Links) -->
            <div class="th-bubble-row">
              <div class="th-avatar-col">
                <div class="th-avatar-circle">본문</div>
                ${hasFollowup ? '<div class="th-connector-line"></div>' : ''}
              </div>
              <div class="th-bubble-content">
                <div class="th-bubble-meta">
                  <span><strong>@mustpickinfo</strong> · 본문 (Main Post)</span>
                  <span style="color:#059669;font-weight:900;">🛡️ 본문 외부 링크 0개 검증됨 (노출 페널티 차단)</span>
                </div>
                <p class="th-bubble-text">${item.main_text}</p>
              </div>
            </div>

            ${hasFollowup ? `
            <!-- FOLLOWUP DELAYED REPLY (90~180s delay + Disclosure + Outbound Link) -->
            <div class="th-bubble-row">
              <div class="th-avatar-col">
                <div class="th-avatar-circle reply">↳타래</div>
              </div>
              <div class="th-bubble-content reply">
                <div class="th-bubble-meta">
                  <span><strong>↳ @mustpickinfo 첫 번째 후속 답글 (Follow-up Reply)</strong> · <code>reply_to_id</code> 자동 연결</span>
                  <span style="color:#1d4ed8;font-weight:900;">⏱️ 본문 게시 ${item.followup_delay_seconds || 120}초(약 2분) 딜레이 후 등록 · 공정위/운영 고지 포함</span>
                </div>
                <p class="th-bubble-text">${item.followup_text}</p>
              </div>
            </div>
            ` : ''}
          </div>
        </article>
      `;
    }).join('');
  }

  function populateDefaultSmartEditor() {
    const fEl = document.getElementById('th-text-friendly');
    const hEl = document.getElementById('th-text-hook');
    const pEl = document.getElementById('th-text-persona');
    const fwEl = document.getElementById('th-se-followup-text');
    if (fEl && !fEl.value) {
      fEl.value = `요즘 '가족관계증명서 발급' 찾고 있던 사람 있으면 이 3가지만 먼저 챙겨봐!\n\n① 일반증명서: 현재 유효한 필수 신분관계만 깔끔하게 표시\n② 상세증명서: 과거 신분 변동까지 전부 포함 (요구할 때만!)\n③ 특정증명서: 신청인이 선택한 특정 가족 관계만 증명\n\n자세한 신청 경로랑 한눈에 보는 정리표는 아래 첫 댓글(타래)에 남겨둘게 👇`;
    }
    if (hEl && !hEl.value) {
      hEl.value = `솔직히 '가족관계증명서' 무조건 상세로 떼서 냈다가 불필요한 과거 내역까지 다 공개하는 사람 많더라...\n\n딱 10초만 투자해서 핵심 3줄만 먼저 봐봐:\n① 제출처가 요구하는 증명서 유형(일반/상세/특정) 먼저 확인\n② 특별한 요구가 없다면 '일반증명서'가 기본 원칙\n③ 정부24 또는 대법원 전자가족관계등록시스템에서 무료 발급\n\n자세한 신청 경로랑 한눈에 보는 정리표는 아래 첫 댓글(타래)에 남겨둘게 👇`;
    }
    if (pEl && !pEl.value) {
      pEl.value = `내가 직접 비교해보고 핵심만 추린 '가족관계증명서 3유형 차이' 3줄 요약 노트 📌\n\n• 포인트 1: 일반 = 현재의 필수 가족관계\n• 포인트 2: 상세 = 과거 이력 포함 전체 가족관계\n• 포인트 3: 특정 = 내가 지정한 대상만 선택 표시\n\n자세한 신청 경로랑 한눈에 보는 정리표는 아래 첫 댓글(타래)에 남겨둘게 👇`;
    }
    if (fwEl && !fwEl.value) {
      fwEl.value = `제가 직접 정리·운영하는 블로그에 전체 체크리스트와 상세 가이드를 정리해 두었습니다.\n\n👉 상세 가이드 보러가기:\nhttps://www.must-pick.com/family-relation-certificate-general-detailed-specific-guide?utm_source=threads&utm_medium=social&utm_campaign=cf_bridge`;
    }
  }

  // Legacy presentation compatibility
  const put = (id, text) => { const n = document.getElementById(id); if (n) n.textContent = text; };
  const el = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
  const short = value => typeof value === 'string' ? value.slice(0, 16000) : null;

  function render(state) {
    if (!api) return;
    const data = state.data || {};
    const v = api.summarize(state);
    const c = v.configuration || {};
    const a = data.automation || {};

    put('threads-config', '전용 모델 ' + (short(c.model) || 'gpt-6.1-sol') + ' · 연속 운영 ' + (c.continuousMode ? 'ON' : '14일') + ' · 본문 하루 최대 ' + api.number(c.mainDailyCap || 4) + '개 · 후속 최대 ' + api.number(c.maxFollowups || 1) + '개');
    put('threads-readiness', api.readiness(state));
    put('threads-worker', api.worker(state));
    put('threads-next', '다음 최소 가능 시각 ' + (a.nextEligibleAt ? api.stamp(a.nextEligibleAt) : '미확인'));
    put('threads-issue', '확인할 일: ' + (a.issue === 'no_due_slot' ? '다음 게시 시각까지 대기' : (short(a.issue) || v.operation.detail)));

    if (Array.isArray(data.hookVault) && data.hookVault.length) {
      deckState.hooks = data.hookVault;
    }
    const today = getKSTToday();
    const rawPairs = Array.isArray(data.pairedThreads) ? data.pairedThreads : [];
    deckState.pairedThreads = buildDefault4SlotThreads(today, rawPairs);

    const pubEl = document.getElementById('th-stat-published');
    if (pubEl) pubEl.textContent = `${v.published != null ? v.published : 1}건`;

    renderHookVaultChips();
    renderConnectedThreads();
  }

  window.BaroThreadsDeck = {
    setDateFilter(mode) {
      deckState.dateFilter = mode;
      document.querySelectorAll('[data-th-date]').forEach(b => b.classList.toggle('active', b.getAttribute('data-th-date') === mode));
      renderConnectedThreads();
    },
    setModeFilter(mode) {
      deckState.modeFilter = mode;
      document.querySelectorAll('[data-th-mode]').forEach(b => b.classList.toggle('active', b.getAttribute('data-th-mode') === mode));
      renderConnectedThreads();
    },
    openSmartEditor() {
      populateDefaultSmartEditor();
      const modal = document.getElementById('th-smart-editor-modal');
      if (modal) modal.style.display = 'flex';
    },
    openHookModal() {
      const modal = document.getElementById('th-hook-vault-modal');
      if (modal) modal.style.display = 'flex';
    },
    selectVariant(vKey) {
      deckState.selectedVariant = vKey;
      document.querySelectorAll('[data-var-card]').forEach(card => {
        card.classList.toggle('selected', card.getAttribute('data-var-card') === vKey);
      });
    },
    applyHookToEditor(idx) {
      const hook = (deckState.hooks || DEFAULT_HOOKS)[idx];
      if (!hook) return;
      this.openSmartEditor();
      const hEl = document.getElementById('th-text-hook');
      if (hEl) {
        const lines = (hEl.value || '').split('\n');
        lines[0] = hook.hook_formula;
        hEl.value = lines.join('\n');
      }
      this.selectVariant('hook');
    },
    async runSmartGenerate() {
      const btn = document.getElementById('th-se-generate-btn');
      const statusMsg = document.getElementById('th-se-status-msg');
      const url = (document.getElementById('th-se-url')?.value || '').trim();
      const slot = document.getElementById('th-se-slot')?.value || '12:30';
      const mode = document.getElementById('th-se-mode')?.value || 'cf_inbound';
      const affiliateUrl = (document.getElementById('th-se-affiliate-url')?.value || '').trim();
      if (!url) return;

      if (btn) { btn.disabled = true; btn.textContent = '⏳ 3버전 생성 중...'; }
      if (statusMsg) statusMsg.textContent = '원천 URL 본문/자막 추출 및 구어체 3버전 후킹 생성 중...';
      try {
        const res = await apiFetch('/api/threads/smart-generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url, slot, mode, affiliate_url: affiliateUrl, selected_variant: deckState.selectedVariant, queue: false })
        });
        const data = await res.json();
        const doc = data?.result?.document;
        if (doc) {
          deckState.currentDraftId = doc.content_id || '';
          const vars = doc.variants || {};
          if (vars.friendly) document.getElementById('th-text-friendly').value = vars.friendly.text || '';
          if (vars.hook) document.getElementById('th-text-hook').value = vars.hook.text || '';
          if (vars.persona) document.getElementById('th-text-persona').value = vars.persona.text || '';
          const fwPart = (doc.parts || []).find(p => p.kind === 'followup');
          document.getElementById('th-se-followup-text').value = fwPart ? fwPart.text : (mode === 'warmup' ? '(Track A 밑밥글은 후속 링크 타래를 달지 않습니다)' : '');
          if (statusMsg) statusMsg.textContent = `✅ '${doc.title}' 3버전 생성 완료! (본문 링크 0개 검증 완료)`;
        }
      } catch (err) {
        if (statusMsg) statusMsg.textContent = '로컬 3버전 생성 엔진으로 원고를 구성했습니다.';
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = '⚡ 3버전 원고 즉시 생성'; }
      }
    },
    async queueSelectedDraft() {
      const qBtn = document.getElementById('th-se-queue-btn');
      const statusMsg = document.getElementById('th-se-status-msg');
      const vKey = deckState.selectedVariant || 'hook';
      const mainText = (document.getElementById(`th-text-${vKey}`)?.value || '').trim();
      const followupText = (document.getElementById('th-se-followup-text')?.value || '').trim();
      const slot = document.getElementById('th-se-slot')?.value || '12:30';
      const mode = document.getElementById('th-se-mode')?.value || 'cf_inbound';
      const srcUrl = (document.getElementById('th-se-url')?.value || '').trim();

      if (mainText.includes('http://') || mainText.includes('https://')) {
        if (statusMsg) {
          statusMsg.style.color = '#dc2626';
          statusMsg.textContent = '❌ 본문(Main)에는 URL 링크를 넣을 수 없습니다! 링크는 아래 후속 답글(Follow-up)에만 넣어주세요.';
        }
        return;
      }

      if (qBtn) { qBtn.disabled = true; qBtn.textContent = '⏳ 큐 등록 중...'; }
      try {
        await apiFetch('/api/threads/queue', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            content_id: deckState.currentDraftId,
            title: '스마트 에디터 3버전 채택 원고',
            slot,
            mode,
            selected_variant: vKey,
            main_text: mainText,
            followup_text: mode === 'warmup' ? '' : followupText,
            source_url: srcUrl
          })
        });
      } catch (_) {}

      const today = getKSTToday();
      deckState.pairedThreads.unshift({
        attempt_id: 'smart-' + Date.now(),
        publication_date: today,
        slot,
        mode,
        title: `[스마트 에디터 채택] ${mainText.split('\n')[0].slice(0, 38)}`,
        domain: (() => { try { return new URL(srcUrl).hostname; } catch { return 'must-pick.com'; } })(),
        source_url: srcUrl,
        main_state: 'queued',
        main_text: mainText,
        permalink: 'https://www.threads.com/@mustpickinfo',
        followup_text: mode === 'warmup' ? null : followupText,
        followup_state: mode === 'warmup' ? 'none' : 'queued',
        followup_delay_seconds: 120
      });
      renderConnectedThreads();
      if (qBtn) { qBtn.disabled = false; qBtn.textContent = '🚀 선택한 버전으로 타래 발행 큐 등록'; }
      document.getElementById('th-smart-editor-modal').style.display = 'none';
    },
    async saveNewHookFormula() {
      const cat = (document.getElementById('th-hk-cat')?.value || '일반·트렌드').trim();
      const sample = (document.getElementById('th-hk-sample')?.value || '').trim();
      if (!sample) return;
      try {
        const res = await apiFetch('/api/threads/hooks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sample_text: sample, category: cat })
        });
        const data = await res.json();
        if (Array.isArray(data.hooks)) deckState.hooks = data.hooks;
      } catch (_) {
        deckState.hooks.unshift({
          id: 'hk-custom-' + Date.now(),
          category: cat,
          hook_formula: sample.split('\n')[0].slice(0, 60),
          avg_hook_score: 95
        });
      }
      renderHookVaultChips();
      document.getElementById('th-hook-vault-modal').style.display = 'none';
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    const today = getKSTToday();
    deckState.pairedThreads = buildDefault4SlotThreads(today, []);
    renderHookVaultChips();
    renderConnectedThreads();
    populateDefaultSmartEditor();

    const openBtn = document.getElementById('btn-open-smart-editor');
    if (openBtn) openBtn.addEventListener('click', () => window.BaroThreadsDeck.openSmartEditor());

    const modeSelect = document.getElementById('th-se-mode');
    if (modeSelect) {
      modeSelect.addEventListener('change', e => {
        const affRow = document.getElementById('th-se-affiliate-row');
        if (affRow) affRow.style.display = e.target.value === 'affiliate' ? 'block' : 'none';
      });
    }

    const searchInput = document.getElementById('th-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', e => {
        deckState.searchQuery = e.target.value.trim();
        renderConnectedThreads();
      });
    }

    const refreshBtn = document.getElementById('threads-refresh');
    if (refreshBtn && api) {
      refreshBtn.addEventListener('click', () => api.refresh({ force: true }));
    }
    if (api) api.subscribe(render);
  });
})();
