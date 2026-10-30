'use strict';
const $ = id => document.getElementById(id);
let config, busy = false;

const DEFAULT_AGY_MODELS = [
  { id: 'gemini-4-argon-high', label: 'Gemini 4 Argon (High) · 최고 추론' },
  { id: 'gemini-4-argon-medium', label: 'Gemini 4 Argon (Medium) · 표준' },
  { id: 'gemini-4-argon-low', label: 'Gemini 4 Argon (Low) · 고속' },
  { id: 'gemini-3.8-flash-high', label: 'Gemini 3.8 Flash (High)' },
  { id: 'gemini-3.8-flash-medium', label: 'Gemini 3.8 Flash (Medium) · 고속 검진' },
  { id: 'gemini-3.8-flash-low', label: 'Gemini 3.8 Flash (Low)' },
  { id: 'gpt-6.1-sol', label: 'gpt-6.1-sol (High · 원고/코드 특화)' },
  { id: 'claude-opus-5-5-high', label: 'Claude Opus 5.5 (High)' },
  { id: 'claude-opus-5-5-medium', label: 'Claude Opus 5.5 (Medium)' },
  { id: 'claude-sonnet-5-5-high', label: 'Claude Sonnet 5.5 (High)' },
  { id: 'claude-sonnet-5-5-medium', label: 'Claude Sonnet 5.5 (Medium)' },
  { id: 'gpt-oss-120b-medium', label: 'GPT-OSS 120B (Medium)' },
];

const PROVIDER_OPTIONS = [
  { id: 'agy', label: 'AGY CLI (Argon/Flash)' },
  { id: 'codex', label: 'Codex CLI (ChatGPT 구독)' },
  { id: 'gemini', label: 'Gemini API' },
  { id: 'openai', label: 'OpenAI API' },
  { id: 'claude', label: 'Claude API' },
  { id: 'deepseek', label: 'DeepSeek API' },
];

const PROVIDER_MODELS_MAP = {
  agy: DEFAULT_AGY_MODELS,
  codex: [
    { id: 'gpt-6.1-sol', label: 'gpt-6.1-sol (Codex 최고성능 · 추천)' },
    { id: 'gemini-4-argon-high', label: 'Gemini 4 Argon (High · 대체 호환)' },
    { id: 'gpt-5.4', label: 'gpt-5.4 (Codex 표준 추론)' },
    { id: 'gpt-5.3-codex', label: 'gpt-5.3-codex (Codex 고속 코딩)' },
    { id: 'o3-pro', label: 'o3-pro (심층 검증)' },
  ],
  gemini: [
    { id: 'gemini-2.5-pro', label: 'gemini-2.5-pro (고성능 추론)' },
    { id: 'gemini-2.5-flash', label: 'gemini-2.5-flash (고속·대량)' },
    { id: 'gemini-4-argon-high', label: 'gemini-4-argon-high' },
  ],
  openai: [
    { id: 'gpt-6.1-sol', label: 'gpt-6.1-sol' },
    { id: 'gpt-5.4', label: 'gpt-5.4' },
    { id: 'gpt-4.1', label: 'gpt-4.1' },
    { id: 'o3-mini', label: 'o3-mini' },
  ],
  claude: [
    { id: 'claude-opus-5-5-high', label: 'Claude Opus 5.5 (High)' },
    { id: 'claude-sonnet-5-5-high', label: 'Claude Sonnet 5.5 (High)' },
    { id: 'claude-3-7-sonnet-latest', label: 'claude-3-7-sonnet-latest' },
  ],
  deepseek: [
    { id: 'deepseek-chat', label: 'deepseek-chat (V3)' },
    { id: 'deepseek-reasoner', label: 'deepseek-reasoner (R1)' },
  ],
};

const DEFAULT_SLOTS = [
  { slot: 'jarvis', kind: 'agent', name: '팀장 (@jarvis)', role: '총괄 · 전략판단 · 회의실 의사결정', icon: '🧭', color: '#2563eb', recommendedProvider: 'agy', recommendedModel: 'gemini-4-argon-high', recommendedReason: '전사 데이터 종합 및 고차원 전략 판단용 최고 추론 모델' },
  { slot: 'publi', kind: 'agent', name: '퍼블리 (@publi)', role: '원고집필 · 최종검수 · 지식iN 총괄', icon: '🤖', color: '#059669', recommendedProvider: 'codex', recommendedModel: 'gpt-6.1-sol', recommendedReason: '장문 구조화 원고 집필·HTML 테이블 조립·엄격한 스키마 검수 특화' },
  { slot: 'patch', kind: 'agent', name: '패치 (@patch)', role: '시스템 · 코드수선 · CDP/스케줄러', icon: '⚙️', color: '#d97706', recommendedProvider: 'codex', recommendedModel: 'gpt-6.1-sol', recommendedReason: '파이프라인 디버깅·DOM/코드 부분수선(Surgical Repair) 최적 모델' },
  { slot: 'radar', kind: 'agent', name: '레이더 (@radar)', role: '유튜브 자막분석 · 트렌드 · 고단가 R&D', icon: '🎯', color: '#e11d48', recommendedProvider: 'agy', recommendedModel: 'gemini-4-argon-medium', recommendedReason: '대용량 유튜브 자막(1,400+ 구간) 고속 독해 및 핵심 전략 추출' },
  { slot: 'doctor', kind: 'agent', name: '닥터 (@doctor)', role: '24시간 기존 글 고속 검진 · 세탁 · 격리', icon: '🩺', color: '#0d9488', recommendedProvider: 'agy', recommendedModel: 'gemini-3.8-flash-medium', recommendedReason: '1,960+ 기발행 글 24시간 무중단 고속 순찰 및 저비용 대량 검진' },
  { slot: 'trace', kind: 'agent', name: '트레이스 (@trace)', role: '색인 · 트래픽 · 애드센스 수익 집계', icon: '📊', color: '#7c3aed', recommendedProvider: 'agy', recommendedModel: 'gemini-3.8-flash-medium', recommendedReason: 'GSC/GA4/IndexNow/애드센스 정량 지표 고속 대조 및 진단' },
  { slot: 'cf_pipeline', kind: 'pipeline', name: 'CF 16개 블로그 파이프라인', role: 'CF 워드프레스/커스텀 원고 작성 · 비주얼 검수', icon: '🌐', color: '#0284c7', recommendedProvider: 'codex', recommendedModel: 'gpt-6.1-sol', recommendedReason: '16개 도메인 장문 HTML 원고 및 이미지 픽셀 정합성 검수' },
  { slot: 'naver_pipeline', kind: 'pipeline', name: '네이버 5계정 블로그 파이프라인', role: '스마트블록 · 롱테일 원고 작성 및 예약발행', icon: '🟢', color: '#16a34a', recommendedProvider: 'codex', recommendedModel: 'gpt-6.1-sol', recommendedReason: '네이버 에디터 맞춤형 체류시간 최적화 원고 생성' },
  { slot: 'kin_pipeline', kind: 'pipeline', name: '지식iN 자동 답변 파이프라인', role: 'adinfo0905 · stone0747 질문 매칭 및 답변 검수', icon: '💡', color: '#ca8a04', recommendedProvider: 'codex', recommendedModel: 'gpt-6.1-sol', recommendedReason: '질문자 의도 직결 답변 작성 및 브릿지 링크 자연 삽입' },
  { slot: 'threads_pipeline', kind: 'pipeline', name: 'Threads 4슬롯 바이럴 파이프라인', role: '초반 3초 후킹 카피 생성 및 댓글 링크 유도', icon: '🧵', color: '#4f46e5', recommendedProvider: 'agy', recommendedModel: 'gemini-4-argon-medium', recommendedReason: '짧고 강렬한 SNS 바이럴 후킹 문구 및 요약본 생성' },
];

function formatBrainBadge(provider, model, reasoningEffort = null) {
  const m = String(model || '').trim();
  const ml = m.toLowerCase();
  if (provider === 'codex') { const effort=reasoningEffort || 'low'; return (m || 'Codex')+' · '+effort[0].toUpperCase()+effort.slice(1); }
  if (ml.includes('argon-high')) return 'Argon High';
  if (ml.includes('argon-medium')) return 'Argon Med';
  if (ml.includes('argon-low')) return 'Argon Low';
  if (ml.includes('3.8-flash-high')) return '3.8 Flash High';
  if (ml.includes('3.8-flash-medium')) return '3.8 Flash Med';
  if (ml.includes('3.8-flash-low')) return '3.8 Flash Low';
  if (ml.includes('3.8-flash')) return '3.8 Flash';
  if (ml.includes('gpt-6.1-sol')) return 'gpt-6.1-sol';
  if (ml.includes('opus-5-5')) return 'Opus 5.5';
  if (ml.includes('sonnet-5-5')) return 'Sonnet 5.5';
  return m ? m.slice(0, 18) : (provider === 'codex' ? 'gpt-6.1-sol' : 'Argon High');
}

function badgeClassFor(provider, model) {
  const ml = String(model || '').toLowerCase();
  if (provider === 'codex' || ml.includes('gpt-6.1-sol')) return 'is-codex';
  if (ml.includes('flash')) return 'is-flash';
  return '';
}

function normalizeConfig(d) {
  if (!d || !d.providers) return d;
  if (d.providers.agy) {
    if (!d.providers.agy.model) d.providers.agy.model = 'gemini-4-argon-high';
    if (!d.providers.agy.models || !d.providers.agy.models.length) d.providers.agy.models = DEFAULT_AGY_MODELS;
  }
  if (!d.agentBrainSlots || !d.agentBrainSlots.length) {
    d.agentBrainSlots = DEFAULT_SLOTS;
  }
  if (!d.agentBrains) {
    d.agentBrains = {};
    for (const s of d.agentBrainSlots) {
      d.agentBrains[s.slot] = {
        provider: s.recommendedProvider,
        model: s.recommendedModel,
        badge: formatBrainBadge(s.recommendedProvider, s.recommendedModel),
      };
    }
  }
  return d;
}

function message(text, error = false) {
  if (!$('message')) return;
  $('message').textContent = text;
  $('message').className = error ? 'error' : '';
}

function matrixMessage(text, error = false) {
  const el = $('brain-matrix-message');
  if (!el) return;
  if (!text) {
    el.className = '';
    el.textContent = '';
    return;
  }
  el.textContent = text;
  el.className = error ? 'error' : 'visible';
}

function getModelsForProvider(provider) {
  if (provider === 'codex' && config?.providers?.codex?.models?.length) {
    const base = [...PROVIDER_MODELS_MAP.codex];
    for (const m of config.providers.codex.models) {
      if (m?.id && !base.some(b => b.id === m.id)) {
        base.push({ id: m.id, label: m.label || m.id });
      }
    }
    return base.map(m => ({ ...m, ...(config.providers.codex.models.find(row => row.id === m.id) || {}) }));
  }
  if (provider === 'agy' && config?.providers?.agy?.models?.length) {
    return config.providers.agy.models;
  }
  return PROVIDER_MODELS_MAP[provider] || DEFAULT_AGY_MODELS;
}

const EFFORT_LABELS = { none: '없음 (None)', minimal: '최소 (Minimal)', low: '낮음 (Low)',
  medium: '보통 (Medium)', high: '높음 (High)', xhigh: '매우 높음 (XHigh)',
  max: '최대 (Max)', ultra: '최상 (Ultra)' };

function reasoningEfforts(provider, model) {
  if (provider !== 'codex') return [];
  const row = getModelsForProvider(provider).find(row => row.id === model);
  return (row?.reasoningEfforts || []).filter(effort => Object.hasOwn(EFFORT_LABELS, effort));
}

function effortOptions(provider, model, current) {
  const efforts = reasoningEfforts(provider, model);
  const selected = efforts.includes(current) ? current : '';
  return `<option value="" ${selected ? '' : 'selected'}>${provider === 'codex' ? '기본값 (Low)' : '공급자 기본값'}</option>` +
    efforts.map(effort => `<option value="${effort}" ${effort === selected ? 'selected' : ''}>${EFFORT_LABELS[effort]}</option>`).join('');
}

function updateEffortSelect(slot) {
  const provider = document.querySelector(`.brain-provider-select[data-slot="${slot}"]`)?.value;
  const model = document.querySelector(`.brain-model-select[data-slot="${slot}"]`)?.value;
  const select = document.querySelector(`.brain-effort-select[data-slot="${slot}"]`);
  if (!select) return;
  const current = select.value;
  select.innerHTML = effortOptions(provider, model, current);
  select.disabled = reasoningEfforts(provider, model).length === 0;
  select.title = select.disabled ? '선택 가능한 추론 강도 정보가 없습니다.' : '높을수록 응답 시간이 길어질 수 있습니다.';
}


function buildBrainCardHtml(slotMeta, currentBrain) {
  const prov = currentBrain?.provider || slotMeta.recommendedProvider;
  const mod = currentBrain?.model || slotMeta.recommendedModel;
  const badgeText = formatBrainBadge(prov, mod, currentBrain?.reasoningEffort);
  const badgeCls = badgeClassFor(prov, mod);
  const models = getModelsForProvider(prov);
  const hasModInList = models.some(m => m.id === mod);
  const modelOptions = [...models];
  if (mod && !hasModInList) {
    modelOptions.unshift({ id: mod, label: `${mod} (직접 지정)` });
  }

  return `
    <div class="brain-card" data-slot="${slotMeta.slot}">
      <div class="brain-card-top">
        <div class="brain-agent-id">
          <div class="brain-avatar" style="background:${slotMeta.color};">${slotMeta.icon}</div>
          <div class="brain-title-wrap">
            <strong>${slotMeta.name}</strong>
            <span title="${slotMeta.role}">${slotMeta.role}</span>
          </div>
        </div>
        <span class="brain-live-badge ${badgeCls}" data-badge-for="${slotMeta.slot}">🧠 ${badgeText}</span>
      </div>
      <div class="brain-controls">
        <div class="brain-field">
          <label>AI 공급자</label>
          <select class="brain-provider-select" data-slot="${slotMeta.slot}">
            ${PROVIDER_OPTIONS.map(p => `<option value="${p.id}" ${p.id === prov ? 'selected' : ''}>${p.label}</option>`).join('')}
          </select>
        </div>
        <div class="brain-field">
          <label>전용 모델 ID</label>
          <select class="brain-model-select" data-slot="${slotMeta.slot}">
            ${modelOptions.map(m => `<option value="${m.id}" ${m.id === mod ? 'selected' : ''}>${m.label}</option>`).join('')}
          </select>
        </div>
        <div class="brain-field brain-effort-field">
          <label for="brain-effort-${slotMeta.slot}">추론 강도</label>
          <select id="brain-effort-${slotMeta.slot}" class="brain-effort-select" data-slot="${slotMeta.slot}"
            ${reasoningEfforts(prov, mod).length ? '' : 'disabled'}
            title="${reasoningEfforts(prov, mod).length ? '높을수록 응답 시간이 길어질 수 있습니다.' : '선택 가능한 추론 강도 정보가 없습니다.'}">
            ${effortOptions(prov, mod, currentBrain?.reasoningEffort)}
          </select>
        </div>
      </div>
      <div class="brain-rec-note">
        <span>권장: <code>${slotMeta.recommendedProvider.toUpperCase()} · ${formatBrainBadge(slotMeta.recommendedProvider, slotMeta.recommendedModel)}</code></span>
        <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${slotMeta.recommendedReason}">${slotMeta.recommendedReason}</span>
      </div>
    </div>
  `;
}

function renderBrainMatrix() {
  const crewGrid = $('crew-brain-grid');
  const pipeGrid = $('pipeline-brain-grid');
  if (!crewGrid || !pipeGrid || !config) return;

  const slots = config.agentBrainSlots || DEFAULT_SLOTS;
  const brains = config.agentBrains || {};

  const agentSlots = slots.filter(s => s.kind === 'agent');
  const pipeSlots = slots.filter(s => s.kind === 'pipeline');

  crewGrid.innerHTML = agentSlots.map(s => buildBrainCardHtml(s, brains[s.slot])).join('');
  pipeGrid.innerHTML = pipeSlots.map(s => buildBrainCardHtml(s, brains[s.slot])).join('');

  // Update KnowledgeIn summary label if present
  if ($('kin-settings-model') && brains.kin_pipeline) {
    $('kin-settings-model').textContent = brains.kin_pipeline.badge || formatBrainBadge(brains.kin_pipeline.provider,brains.kin_pipeline.model,brains.kin_pipeline.reasoningEffort);
  }

  document.querySelectorAll('.brain-effort-select').forEach(select => select.addEventListener('change', () => updateCardBadge(select.dataset.slot)));

  // Bind provider change -> repopulate model select and update badge
  document.querySelectorAll('.brain-provider-select').forEach(provSel => {
    provSel.addEventListener('change', () => {
      const slot = provSel.dataset.slot;
      const newProv = provSel.value;
      const modSel = document.querySelector(`.brain-model-select[data-slot="${slot}"]`);
      if (!modSel) return;
      const models = getModelsForProvider(newProv);
      modSel.innerHTML = models.map(m => `<option value="${m.id}">${m.label}</option>`).join('');
      const slotMeta = slots.find(s => s.slot === slot);
      if (slotMeta && slotMeta.recommendedProvider === newProv) {
        modSel.value = slotMeta.recommendedModel;
      }
      updateEffortSelect(slot);
      updateCardBadge(slot);
    });
  });

  document.querySelectorAll('.brain-model-select').forEach(modSel => {
    modSel.addEventListener('change', () => {
      updateEffortSelect(modSel.dataset.slot);
      updateCardBadge(modSel.dataset.slot);
    });
  });
}

function updateCardBadge(slot) {
  const provSel = document.querySelector(`.brain-provider-select[data-slot="${slot}"]`);
  const modSel = document.querySelector(`.brain-model-select[data-slot="${slot}"]`);
  const badgeEl = document.querySelector(`[data-badge-for="${slot}"]`);
  if (!provSel || !modSel || !badgeEl) return;
  const effort = document.querySelector(`.brain-effort-select[data-slot="${slot}"]`)?.value;
  const bText = formatBrainBadge(provSel.value, modSel.value, effort);
  const bCls = badgeClassFor(provSel.value, modSel.value);
  badgeEl.textContent = `🧠 ${bText}`;
  badgeEl.className = `brain-live-badge ${bCls}`;
}

function collectBrainMatrixPayload() {
  const out = {};
  document.querySelectorAll('.brain-card[data-slot]').forEach(card => {
    const slot = card.dataset.slot;
    const provSel = card.querySelector('.brain-provider-select');
    const modSel = card.querySelector('.brain-model-select');
    if (slot && provSel && modSel) {
      out[slot] = {
        provider: provSel.value,
        model: modSel.value,
        reasoningEffort: card.querySelector('.brain-effort-select')?.value || null,
      };
    }
  });
  return out;
}

function buttons() {
  for (const id of ['save', 'test', 'provider', 'btn-apply-optimal-preset', 'btn-save-agent-brains']) {
    if ($(id)) $(id).disabled = busy || !config;
  }
}

function selectedModel() {
  const p = $('provider') ? $('provider').value : 'openai';
  const row = config?.providers?.[p];
  if (row && row.model) return row.model;
  const fallback = PROVIDER_MODELS_MAP[p]?.[0]?.id;
  return fallback || 'gpt-6.1-sol';
}

function render() {
  renderBrainMatrix();
  if ($('cli-health-badge') && config?.providers) {
    const agyOk = config.providers.agy?.installed !== false;
    const codexOk = config.providers.codex?.installed !== false;
    $('cli-health-badge').textContent = `${agyOk ? '🟢 AGY CLI 정상' : '🟡 AGY CLI 점검'} · ${codexOk ? '🟢 Codex CLI 정상' : '🟡 Codex CLI 점검'}`;
  }
  if ($('provider') && $('api-key') && $('key-status')) {
    const p = $('provider').value || 'openai';
    $('api-key').value = '';
    const row = config?.providers?.[p] || {};
    $('key-status').textContent = row.key_set
      ? '암호화된 키 저장됨 · 빈 입력은 기존 키를 유지합니다.'
      : row.environment_key
        ? '서버 환경변수 연결 있음 · 실제 생성은 연결 테스트로 확인하세요.'
        : '저장된 키 없음 (AGY CLI / Codex CLI 사용 시 불필요)';
  }
  buttons();
}

async function api(path, body) {
  const bases = ['/api/llm/', 'http://127.0.0.1:8790/api/llm/', 'http://127.0.0.1:8791/api/llm/', 'http://192.168.45.248:8790/api/llm/', 'http://192.168.45.248:8791/api/llm/'];
  let lastErr = null;
  for (const base of bases) {
    try {
      const response = await fetch(
        base + path,
        body === undefined
          ? { cache: 'no-store' }
          : {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'X-Barolab-Settings': '1' },
              body: JSON.stringify(body),
            }
      );
      let data;
      try { data = await response.json(); } catch { continue; }
      if (!response.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : '설정 요청에 실패했습니다.';
        lastErr = new Error(detail);
        continue;
      }
      return normalizeConfig(data);
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error('설정 API 응답을 읽지 못했습니다. 서버 반영 상태를 확인하세요.');
}

async function saveBrainMatrix(useOptimalPreset = false) {
  if (busy) return;
  busy = true;
  buttons();
  matrixMessage(useOptimalPreset ? '⚡ 최적 효율 프리셋을 6인 크루 및 4대 채널에 배정하고 있습니다…' : '💾 6인 크루 및 채널별 두뇌 설정을 저장하고 있습니다…', false);
  try {
    const payload = useOptimalPreset
      ? { preset: 'optimal', revision: config?.revision }
      : { agentBrains: collectBrainMatrixPayload(), revision: config?.revision };
    config = await api('agent-brains', payload);
    render();
    matrixMessage(
      useOptimalPreset
        ? '✅ [최적 효율 프리셋 자동 배정 완료] 팀장(Argon High) · 퍼블리/패치(gpt-6.1-sol) · 레이더(Argon Med) · 닥터/트레이스(3.8 Flash Med)가 즉시 적용되었습니다.'
        : '✅ [저장 완료] 6인 AI 크루 및 4대 채널 파이프라인 개별 두뇌 설정이 llm-settings.json에 즉시 반영되었습니다.',
      false
    );
  } catch (e) {
    matrixMessage(`❌ 저장 실패: ${e.message}`, true);
  } finally {
    busy = false;
    buttons();
  }
}

async function save() {
  if (busy || !$('form') || !$('form').reportValidity()) return;
  busy = true;
  buttons();
  message('암호화 키 저장 중…');
  try {
    const p = $('provider').value;
    config = await api('settings', {
      provider: p,
      model: selectedModel(),
      api_key: $('api-key').value.trim(),
      activate: false,
      agentBrains: collectBrainMatrixPayload(),
      revision: config.revision,
    });
    render();
    message(`✅ ${p.toUpperCase()} API 암호화 키를 안전하게 저장했습니다.`);
  } catch (e) {
    message(e.message, true);
  } finally {
    if ($('api-key')) $('api-key').value = '';
    busy = false;
    buttons();
  }
}

if ($('form')) $('form').addEventListener('submit', e => { e.preventDefault(); save(); });
if ($('provider')) $('provider').addEventListener('change', () => { message(''); render(); });
if ($('btn-apply-optimal-preset')) {
  $('btn-apply-optimal-preset').addEventListener('click', () => saveBrainMatrix(true));
}
if ($('btn-save-agent-brains')) {
  $('btn-save-agent-brains').addEventListener('click', () => saveBrainMatrix(false));
}
if ($('test')) {
  $('test').addEventListener('click', async () => {
    if (busy) return;
    const p = $('provider').value;
    if ($('api-key') && $('api-key').value.trim()) {
      message('먼저 [암호화 키 저장]을 누른 뒤 연결 테스트를 실행하세요.', true);
      return;
    }
    busy = true;
    buttons();
    message('실제 API 연결 및 JSON 생성 확인 중…');
    try {
      const d = await api('test', { provider: p });
      message(d.message);
    } catch (e) {
      message(e.message, true);
    } finally {
      busy = false;
      buttons();
    }
  });
}

api('settings').then(d => {
  config = d;
  if ($('provider')) {
    const validPaid = ['openai', 'claude', 'gemini', 'deepseek'];
    $('provider').value = validPaid.includes(d.active) ? d.active : 'openai';
  }
  render();
}).catch(e => matrixMessage(`❌ 설정 로드 실패: ${e.message}`, true));
