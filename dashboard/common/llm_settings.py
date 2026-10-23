"""Shared LLM configuration. Encrypted keys are never returned by the API."""
import base64
import copy
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'dashboard' / 'data' / 'llm-settings.json'
PROVIDERS = {
    'gemini': ('Gemini', 'GEMINI_API_KEY'),
    'deepseek': ('DeepSeek', 'DEEPSEEK_API_KEY'),
    'openai': ('ChatGPT / OpenAI API', 'OPENAI_API_KEY'),
    'claude': ('Claude', 'ANTHROPIC_API_KEY'),
    'agy': ('Antigravity AGY CLI', ''),
    'codex': ('Codex CLI · ChatGPT 구독', ''),
}
LOCK = threading.RLock()


class SettingsError(ValueError):
    pass


def crypt(value, decrypt=False):
    prefix = 'fernet:v1:'
    key_path = Path(os.getenv('BAROLAB_CONFIG_KEY_FILE',
                            str(ROOT / 'dashboard' / 'data' / 'secure' / 'runtime' / 'llm-settings.key')))
    portable = decrypt and value.startswith(prefix)
    if portable or (not decrypt and key_path.is_file()):
        from cryptography.fernet import Fernet, InvalidToken
        try:
            cipher = Fernet(key_path.read_bytes().strip())
            if decrypt:
                return cipher.decrypt(value[len(prefix):].encode('ascii')).decode('utf-8')
            return prefix + cipher.encrypt(value.encode('utf-8')).decode('ascii')
        except (OSError, ValueError, InvalidToken):
            raise SettingsError('설정 암호화 키를 읽을 수 없거나 암호문이 유효하지 않습니다.') from None
    if os.name != 'nt':
        raise SettingsError('Windows DPAPI 암호화가 필요합니다.')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]
    raw = base64.b64decode(value) if decrypt else value.encode('utf-8')
    buf = ctypes.create_string_buffer(raw)
    src = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    dst = Blob()
    dll = ctypes.WinDLL('crypt32', use_last_error=True)
    fn = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst)):
        raise SettingsError('키 암호화/복호화 실패: 저장한 Windows 사용자로 실행하세요.')
    try:
        result = ctypes.string_at(dst.data, dst.size)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        free = ctypes.WinDLL('kernel32').LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(ctypes.cast(dst.data, ctypes.c_void_p))


def load():
    if not CONFIG.exists():
        return {'active': 'legacy', 'providers': {p: {'model': ''} for p in PROVIDERS}}
    try:
        data = json.loads(CONFIG.read_text(encoding='utf-8'))
        if data['active'] not in ('legacy', *PROVIDERS) or not isinstance(data['providers'], dict):
            raise ValueError()
        return data
    except (ValueError, KeyError, TypeError, OSError):
        raise SettingsError('LLM 설정을 읽을 수 없습니다. 기존 파일을 확인하세요.') from None


def revision(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def environment_key(provider):
    env = PROVIDERS[provider][1]
    return os.getenv(env, '') or (os.getenv('GOOGLE_API_KEY', '') if provider == 'gemini' else '')


AGY_MODELS = [
    {'id': 'gemini-4-argon-high', 'label': 'Gemini 4 Argon (High) · 최고 추론'},
    {'id': 'gemini-4-argon-medium', 'label': 'Gemini 4 Argon (Medium) · 표준'},
    {'id': 'gemini-4-argon-low', 'label': 'Gemini 4 Argon (Low) · 고속'},
    {'id': 'gemini-3.8-flash-high', 'label': 'Gemini 3.8 Flash (High)'},
    {'id': 'gemini-3.8-flash-medium', 'label': 'Gemini 3.8 Flash (Medium)'},
    {'id': 'gemini-3.8-flash-low', 'label': 'Gemini 3.8 Flash (Low)'},
    {'id': 'gpt-6.1-sol', 'label': 'GPT-6.1-Sol (High) · 에이전틱 코딩/집필'},
    {'id': 'claude-opus-5-5-high', 'label': 'Claude Opus 5.5 (High)'},
    {'id': 'claude-opus-5-5-medium', 'label': 'Claude Opus 5.5 (Medium)'},
    {'id': 'claude-sonnet-5-5-high', 'label': 'Claude Sonnet 5.5 (High)'},
    {'id': 'claude-sonnet-5-5-medium', 'label': 'Claude Sonnet 5.5 (Medium)'},
    {'id': 'gpt-oss-120b-medium', 'label': 'GPT-OSS 120B (Medium)'},
]

CODEX_DEFAULT_MODELS = [
    {'id': 'gpt-6.1-sol', 'label': 'gpt-6.1-sol (Codex 최고성능 · 원고집필/코드수선 추천)'},
    {'id': 'gpt-5.4', 'label': 'gpt-5.4 (Codex 표준 추론)'},
    {'id': 'gpt-5.3-codex', 'label': 'gpt-5.3-codex (Codex 고속 코딩)'},
    {'id': 'o3-pro', 'label': 'o3-pro (심층 검증)'},
]

# 6 Crew Agents + 4 Channel Pipelines Individual Brain Matrix
AGENT_BRAIN_SLOTS = [
    {
        'slot': 'jarvis',
        'kind': 'agent',
        'name': '팀장 (@jarvis)',
        'role': '총괄 · 전략판단 · 회의실 의사결정',
        'icon': '🧭',
        'color': '#2563eb',
        'recommendedProvider': 'agy',
        'recommendedModel': 'gemini-4-argon-high',
        'recommendedReason': '전사 데이터 종합 및 고차원 전략 판단용 최고 추론 모델',
    },
    {
        'slot': 'publi',
        'kind': 'agent',
        'name': '퍼블리 (@publi)',
        'role': '원고집필 · 최종검수 · 지식iN 총괄',
        'icon': '🤖',
        'color': '#059669',
        'recommendedProvider': 'codex',
        'recommendedModel': 'gpt-6.1-sol',
        'recommendedReason': '장문 구조화 원고 집필·HTML 테이블 조립·엄격한 스키마 검수 특화',
    },
    {
        'slot': 'patch',
        'kind': 'agent',
        'name': '패치 (@patch)',
        'role': '시스템 · 코드수선 · CDP/스케줄러',
        'icon': '⚙️',
        'color': '#d97706',
        'recommendedProvider': 'codex',
        'recommendedModel': 'gpt-6.1-sol',
        'recommendedReason': '파이프라인 디버깅·DOM/코드 부분수선(Surgical Repair) 최적 모델',
    },
    {
        'slot': 'radar',
        'kind': 'agent',
        'name': '레이더 (@radar)',
        'role': '유튜브 자막분석 · 트렌드 · 고단가 R&D',
        'icon': '🎯',
        'color': '#e11d48',
        'recommendedProvider': 'agy',
        'recommendedModel': 'gemini-4-argon-medium',
        'recommendedReason': '대용량 유튜브 자막(1,400+ 구간) 고속 독해 및 핵심 전략 추출',
    },
    {
        'slot': 'doctor',
        'kind': 'agent',
        'name': '닥터 (@doctor)',
        'role': '24시간 기존 글 고속 검진 · 세탁 · 격리',
        'icon': '🩺',
        'color': '#0d9488',
        'recommendedProvider': 'agy',
        'recommendedModel': 'gemini-3.8-flash-medium',
        'recommendedReason': '1,960+ 기발행 글 24시간 무중단 고속 순찰 및 저비용 대량 검진',
    },
    {
        'slot': 'trace',
        'kind': 'agent',
        'name': '트레이스 (@trace)',
        'role': '색인 · 트래픽 · 애드센스 수익 집계',
        'icon': '📊',
        'color': '#7c3aed',
        'recommendedProvider': 'agy',
        'recommendedModel': 'gemini-3.8-flash-medium',
        'recommendedReason': 'GSC/GA4/IndexNow/애드센스 정량 지표 고속 대조 및 진단',
    },
    {
        'slot': 'cf_pipeline',
        'kind': 'pipeline',
        'name': 'CF 16개 블로그 파이프라인',
        'role': 'CF 워드프레스/커스텀 원고 작성 · 비주얼 검수',
        'icon': '🌐',
        'color': '#0284c7',
        'recommendedProvider': 'codex',
        'recommendedModel': 'gpt-6.1-sol',
        'recommendedReason': '16개 도메인 장문 HTML 원고 및 이미지 픽셀 정합성 검수',
    },
    {
        'slot': 'naver_pipeline',
        'kind': 'pipeline',
        'name': '네이버 5계정 블로그 파이프라인',
        'role': '스마트블록 · 롱테일 원고 작성 및 예약발행',
        'icon': '🟢',
        'color': '#16a34a',
        'recommendedProvider': 'codex',
        'recommendedModel': 'gpt-6.1-sol',
        'recommendedReason': '네이버 에디터 맞춤형 체류시간 최적화 원고 생성',
    },
    {
        'slot': 'kin_pipeline',
        'kind': 'pipeline',
        'name': '지식iN 자동 답변 파이프라인',
        'role': 'adinfo0905 · stone0747 질문 매칭 및 답변 검수',
        'icon': '💡',
        'color': '#ca8a04',
        'recommendedProvider': 'codex',
        'recommendedModel': 'gpt-6.1-sol',
        'recommendedReason': '질문자 의도 직결 답변 작성 및 브릿지 링크 자연 삽입',
    },
    {
        'slot': 'threads_pipeline',
        'kind': 'pipeline',
        'name': 'Threads 4슬롯 바이럴 파이프라인',
        'role': '초반 3초 후킹 카피 생성 및 댓글 링크 유도',
        'icon': '🧵',
        'color': '#4f46e5',
        'recommendedProvider': 'agy',
        'recommendedModel': 'gemini-4-argon-medium',
        'recommendedReason': '짧고 강렬한 SNS 바이럴 후킹 문구 및 요약본 생성',
    },
]

DEFAULT_OPTIMAL_BRAINS = {
    item['slot']: {
        'provider': item['recommendedProvider'],
        'model': item['recommendedModel'],
    }
    for item in AGENT_BRAIN_SLOTS
}


def format_brain_badge(provider: str, model: str) -> str:
    """Return a compact, human-readable badge for chat.html and settings.html (e.g. 'Argon High', 'gpt-6.1-sol', '3.8 Flash')."""
    m = (model or '').strip()
    ml = m.lower()
    if 'argon-high' in ml:
        return 'Argon High'
    if 'argon-medium' in ml:
        return 'Argon Med'
    if 'argon-low' in ml:
        return 'Argon Low'
    if '3.8-flash-high' in ml:
        return '3.8 Flash High'
    if '3.8-flash-medium' in ml or '3.8-flash' in ml:
        return '3.8 Flash'
    if 'gpt-6.1-sol' in ml:
        return 'gpt-6.1-sol'
    if 'claude-opus-5-5' in ml:
        return 'Opus 5.5'
    if 'claude-sonnet-5-5' in ml:
        return 'Sonnet 5.5'
    if m:
        return m[:18]
    return 'Argon High' if provider == 'agy' else 'gpt-6.1-sol'


REASONING_EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')


def validate_reasoning_effort(provider, model, value):
    if value in (None, '', 'default'):
        return None
    if not isinstance(value, str) or value not in REASONING_EFFORTS:
        raise SettingsError('유효한 추론 강도를 선택하세요.')
    if provider != 'codex':
        raise SettingsError('선택한 공급자는 별도 추론 강도 설정을 지원하지 않습니다.')
    from common.codex_cli import model_catalog
    row = next((row for row in model_catalog() if row.get('id') == model), {})
    if value not in row.get('reasoningEfforts', []):
        raise SettingsError('선택 모델에서 지원이 확인된 추론 강도를 선택하세요.')
    return value


def _saved_reasoning_effort(cfg, previous):
    same_route = all(cfg.get(key) == previous.get(key) for key in ('provider', 'model'))
    value = cfg.get('reasoningEffort', previous.get('reasoningEffort') if same_route else None)
    return validate_reasoning_effort(cfg['provider'], cfg['model'], value)


def reasoning_effort_for_call(provider, model, slot=None, data=None):
    """Inherit only the caller's exact configured route; never another employee."""
    if provider != 'codex':
        return None
    if slot is None:
        from common.crew_chat_bridge import current_model_identity
        actor, owner = current_model_identity()
        slots = {row['slot'] for row in AGENT_BRAIN_SLOTS}
        slot = actor if actor in slots else next((target for prefix, target in
            (('cf-', 'cf_pipeline'), ('naver-', 'naver_pipeline'), ('kin-', 'kin_pipeline'),
             ('threads-', 'threads_pipeline')) if actor.startswith(prefix)), owner)
    if slot not in {row['slot'] for row in AGENT_BRAIN_SLOTS}:
        return None
    brain = get_agent_brain(slot, data)
    if brain['provider'] == provider and brain['model'] == model:
        return brain.get('reasoningEffort')
    return None


def ensure_agent_brains(data: dict) -> dict:
    """Ensure `data['agentBrains']` has valid entries for all 6 agents + 4 pipelines."""
    raw = data.get('agentBrains')
    if not isinstance(raw, dict):
        raw = {}
    out = {}
    for slot_meta in AGENT_BRAIN_SLOTS:
        slot = slot_meta['slot']
        cur = raw.get(slot) if isinstance(raw.get(slot), dict) else {}
        prov = cur.get('provider') if cur.get('provider') in PROVIDERS else slot_meta['recommendedProvider']
        mod = str(cur.get('model') or '').strip() or slot_meta['recommendedModel']
        out[slot] = {
            'provider': prov,
            'model': mod,
            'reasoningEffort': cur.get('reasoningEffort') if prov == 'codex' and cur.get('reasoningEffort') in REASONING_EFFORTS else None,
            'badge': format_brain_badge(prov, mod),
            'providerLabel': PROVIDERS.get(prov, (prov, ''))[0],
        }
    data['agentBrains'] = out
    return out


def get_agent_brain(slug_or_slot: str, data: dict = None) -> dict:
    """Return the configured brain (`provider`, `model`, `badge`, `providerLabel`) for a given agent slug or pipeline slot."""
    d = load() if data is None else data
    brains = ensure_agent_brains(d)
    key = (slug_or_slot or 'jarvis').strip().lower()
    if key in brains:
        return brains[key]
    return brains.get('jarvis', {
        'provider': 'agy',
        'model': 'gemini-4-argon-high',
        'badge': 'Argon High',
        'providerLabel': 'Antigravity AGY CLI',
    })


def resolve_agy_executable():
    found = shutil.which('agy')
    if found:
        return found
    win_candidate = Path.home() / 'AppData/Local/agy/bin/agy.exe'
    if win_candidate.is_file():
        return str(win_candidate)
    return None


def is_agy_available():
    if resolve_agy_executable():
        return True
    # Check shared codex-runtime.json to see if Windows worker host is online
    rt = ROOT / 'dashboard' / 'data' / 'codex-runtime.json'
    if rt.is_file():
        return True
    return False


def public(data=None):
    data = load() if data is None else data
    brains = ensure_agent_brains(data)
    providers = {}
    from common.codex_cli import runtime, model_catalog
    codex = runtime()
    capabilities = {row["id"]: row for row in model_catalog() if row.get("id")}
    for name, (label, _) in PROVIDERS.items():
        row = data['providers'].get(name, {})
        model_val = row.get('model', '') or ('gemini-4-argon-high' if name == 'agy' else ('gpt-6.1-sol' if name == 'codex' else ''))
        providers[name] = {'label': label, 'model': model_val,
                           'key_set': bool(row.get('encrypted_key')),
                           'environment_key': bool(environment_key(name)),
                           'installed': is_agy_available() if name == 'agy' else None}
        if name == 'agy':
            providers[name]['models'] = AGY_MODELS
        if name == 'codex':
            raw_codex_models = list(codex.get('models') or [])
            existing_ids = {m.get('id') for m in raw_codex_models if isinstance(m, dict)}
            merged_codex_models = list(CODEX_DEFAULT_MODELS)
            for cm in raw_codex_models:
                if isinstance(cm, dict) and cm.get('id') not in {x['id'] for x in merged_codex_models}:
                    merged_codex_models.append(cm)
            merged_codex_models = [{**row, **capabilities.get(row['id'], {})} for row in merged_codex_models]
            providers[name].update(installed=codex.get('installed', True), online=codex.get('online', True),
                                   authenticated=codex.get('authenticated', True), models=merged_codex_models,
                                   modelsFetchedAt=codex.get('modelsFetchedAt'), checkedAt=codex.get('checkedAt'))
    return {
        'active': data['active'],
        'revision': revision(data),
        'providers': providers,
        'agentBrains': brains,
        'agentBrainSlots': AGENT_BRAIN_SLOTS,
        'optimalPreset': DEFAULT_OPTIMAL_BRAINS,
    }


def _atomic_write_config(updated: dict):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='llm-settings-', suffix='.tmp', dir=CONFIG.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(updated, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, CONFIG)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_agent_brains(body: dict):
    """Save individual or preset 6-agent + 4-pipeline brain assignments to `llm-settings.json`."""
    with LOCK:
        current = load()
        updated = copy.deepcopy(current)
        ensure_agent_brains(updated)

        if body.get('preset') == 'optimal':
            for slot, cfg in DEFAULT_OPTIMAL_BRAINS.items():
                updated['agentBrains'][slot] = {
                    'provider': cfg['provider'],
                    'model': cfg['model'],
                    'reasoningEffort': None,
                    'badge': format_brain_badge(cfg['provider'], cfg['model']),
                    'providerLabel': PROVIDERS.get(cfg['provider'], (cfg['provider'], ''))[0],
                }
        else:
            incoming = body.get('agentBrains')
            if not isinstance(incoming, dict):
                raise SettingsError('저장할 에이전트 두뇌 설정(agentBrains)이 없습니다.')
            valid_slots = {s['slot'] for s in AGENT_BRAIN_SLOTS}
            for slot, cfg in incoming.items():
                if slot not in valid_slots or not isinstance(cfg, dict):
                    continue
                prov = str(cfg.get('provider') or '').strip()
                mod = str(cfg.get('model') or '').strip()
                if prov not in PROVIDERS:
                    raise SettingsError(f'[{slot}] 지원하지 않는 공급자입니다: {prov}')
                if not mod or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}', mod):
                    raise SettingsError(f'[{slot}] 유효한 모델 ID를 입력하세요.')
                updated['agentBrains'][slot] = {
                    'provider': prov,
                    'model': mod,
                    'reasoningEffort': _saved_reasoning_effort({**cfg, 'provider': prov, 'model': mod}, updated['agentBrains'][slot]),
                    'badge': format_brain_badge(prov, mod),
                    'providerLabel': PROVIDERS.get(prov, (prov, ''))[0],
                }

        _atomic_write_config(updated)
        return public(updated)


def save(body):
    with LOCK:
        current = load()
        ensure_agent_brains(current)
        if not isinstance(body, dict):
            raise SettingsError('잘못된 설정 요청입니다.')
        if body.get('preset') == 'optimal' or ('agentBrains' in body and 'provider' not in body):
            return save_agent_brains(body)
        if body.get('revision') and body.get('revision') != revision(current):
            # Allow saving even if agentBrains was enriched in memory
            pass
        provider = body.get('provider')
        if provider not in PROVIDERS and provider != 'legacy':
            raise SettingsError('지원하지 않는 공급자입니다.')
        updated = copy.deepcopy(current)
        if provider != 'legacy':
            model = body.get('model', '')
            if provider == 'agy' and model.lower() in ('argon', '아르곤', 'gemini-4-argon'):
                model = 'gemini-4-argon-high'
            if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}', model):
                raise SettingsError('유효한 모델 ID를 입력하세요.')
            key = body.get('api_key', '')
            if not isinstance(key, str) or len(key) > 4096 or (key and (not key.isascii() or any(c.isspace() for c in key))):
                raise SettingsError('API 키 형식을 확인하세요.')
            row = updated['providers'].setdefault(provider, {})
            row['model'] = model
            if key and provider not in ('agy', 'codex'):
                row['encrypted_key'] = crypt(key)
            if body.get('activate') is True:
                if provider == 'agy' and not is_agy_available():
                    raise SettingsError('AGY CLI를 찾을 수 없습니다.')
                if provider not in ('agy', 'codex') and not row.get('encrypted_key') and not environment_key(provider):
                    raise SettingsError('API 키를 입력한 뒤 적용하세요.')
        if body.get('activate') is True:
            updated['active'] = provider
        if isinstance(body.get('agentBrains'), dict):
            for slot, cfg in body['agentBrains'].items():
                if isinstance(cfg, dict) and cfg.get('provider') in PROVIDERS and cfg.get('model'):
                    p = cfg['provider']
                    m = str(cfg['model']).strip()
                    updated['agentBrains'][slot] = {
                        'provider': p,
                        'model': m,
                        'reasoningEffort': _saved_reasoning_effort({**cfg, 'provider': p, 'model': m}, updated['agentBrains'].get(slot, {})),
                        'badge': format_brain_badge(p, m),
                        'providerLabel': PROVIDERS.get(p, (p, ''))[0],
                    }
        _atomic_write_config(updated)
        return public(updated)
