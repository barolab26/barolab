"""Provider adapters for JSON article generation; no silent provider fallback."""
import json
import re
import time
from pathlib import Path
import requests
from common import llm_settings as settings


def parse_json(text):
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError('LLM 응답이 비어 있습니다.')
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I)
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data:
            return data
    except (ValueError, TypeError):
        pass
    match = re.search(r'(\{[\s\S]*\})', text)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and data:
                return data
        except Exception:
            pass
    raise RuntimeError('LLM 응답이 유효한 JSON 객체가 아닙니다.')


FREELLM_CIRCUIT_FILE = Path.home() / '.barolab' / 'scratch' / 'freellm_circuit.json'
AGY_COOLDOWN_FILE = Path.home() / '.barolab' / 'scratch' / 'agy_cooldown.json'
AGY_MIN_COOLDOWN_SEC = 20.0
FREELLM_MAX_FAILURES = 2
FREELLM_COOLDOWN_SEC = 600.0  # 10 minutes


def check_freellm_circuit():
    """Return True if freellm circuit breaker is open (skip for 10m after 2 consecutive failures)."""
    try:
        if FREELLM_CIRCUIT_FILE.is_file():
            data = json.loads(FREELLM_CIRCUIT_FILE.read_text(encoding='utf-8'))
            if float(data.get('until', 0.0)) > time.time():
                return True
    except Exception:
        pass
    return False


def record_freellm_result(success: bool):
    """Record freellm call outcome; trip 10-minute circuit breaker on 2 consecutive failures."""
    try:
        FREELLM_CIRCUIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {'failures': 0, 'until': 0.0}
        if FREELLM_CIRCUIT_FILE.is_file():
            try:
                data = json.loads(FREELLM_CIRCUIT_FILE.read_text(encoding='utf-8'))
            except Exception:
                pass
        if success:
            data = {'failures': 0, 'until': 0.0, 'updatedAt': time.time()}
        else:
            failures = int(data.get('failures', 0)) + 1
            until = time.time() + FREELLM_COOLDOWN_SEC if failures >= FREELLM_MAX_FAILURES else 0.0
            data = {'failures': failures, 'until': until, 'updatedAt': time.time()}
        FREELLM_CIRCUIT_FILE.write_text(json.dumps(data), encoding='utf-8')
    except Exception:
        pass


def enforce_agy_cooldown(min_interval=AGY_MIN_COOLDOWN_SEC):
    """Enforce minimum 15~20s cooldown between agy CLI calls to prevent Google account lockouts."""
    try:
        AGY_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        if AGY_COOLDOWN_FILE.is_file():
            last_call = float(json.loads(AGY_COOLDOWN_FILE.read_text(encoding='utf-8')).get('last_call_epoch', 0.0))
            elapsed = time.time() - last_call
            if 0 <= elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        AGY_COOLDOWN_FILE.write_text(json.dumps({'last_call_epoch': time.time()}), encoding='utf-8')
    except Exception:
        pass


def _field_type_hint(spec, depth=0):
    if not isinstance(spec, dict):
        return 'any'
    t = spec.get('type', 'any')
    if 'enum' in spec and isinstance(spec['enum'], list) and spec['enum']:
        vals = spec['enum']
        if len(vals) == 1:
            return f"{t} (exact value: {json.dumps(vals[0], ensure_ascii=False)})"
        joined = ' | '.join(json.dumps(x, ensure_ascii=False) for x in vals[:6])
        return f"{t} (one of: {joined})"
    if t == 'array' and isinstance(spec.get('items'), dict):
        if depth < 2:
            return [_field_type_hint(spec['items'], depth + 1)]
        return [spec['items'].get('type', 'string')]
    if t == 'object' and isinstance(spec.get('properties'), dict):
        if depth < 2:
            return {ik: _field_type_hint(iv, depth + 1) for ik, iv in spec['properties'].items()}
        return {ik: iv.get('type', 'string') if isinstance(iv, dict) else 'any' for ik, iv in spec['properties'].items()}
    return t


def _compact_schema_hint(schema):
    """Build a concise JSON structure hint for AGY without representing scalar enums as arrays."""
    if not isinstance(schema, dict):
        return ''
    props = schema.get('properties')
    if not isinstance(props, dict):
        return ''
    summary = {k: _field_type_hint(v, 0) for k, v in props.items()}
    return json.dumps(summary, ensure_ascii=False)


def _enabled_route(config, provider=None, model_override=None):
    """AGY is disabled after weekly quota exhaustion (2026-10-19)."""
    provider = provider or config['active']
    if provider == 'agy':
        # AGY model IDs are not valid Codex model overrides.
        return 'codex', config['providers'].get('codex', {}).get('model') or 'gpt-6.1-sol'
    return provider, model_override


def agy_generate(prompt, model, response_schema=None):
    """Compatibility entry point; never start AGY, even for direct callers."""
    result, _ = _generate_json(prompt, provider='agy', response_schema=response_schema)
    return result


def generate_json(prompt, provider=None, observer=None, images=None, model_override=None, response_schema=None, audit_directory=None, reasoning_effort=None, agent_slot=None):
    config = settings.load()
    if agent_slot and not provider and not model_override:
        brain = settings.get_agent_brain(agent_slot, config)
        provider = brain.get('provider') or config['active']
        model_override = brain.get('model') or None
    provider, model_override = _enabled_route(config, provider, model_override)
    model = model_override or config['providers'].get(provider, {}).get('model', '')
    if observer:
        observer(provider, model, 'calling')
    try:
        result, actual_model = _generate_json(prompt, provider, images, model_override, response_schema, audit_directory, reasoning_effort)
    except Exception as exc:
        if observer:
            match = re.search(r'HTTP (\d{3})', str(exc))
            observer(provider, model, 'failed', reason=str(exc)[:400],
                     http_status=int(match.group(1)) if match else None)
        raise
    if observer:
        observer(provider, model, 'returned', actual_model=actual_model)
    return result


def _generate_json(prompt, provider=None, images=None, model_override=None, response_schema=None, audit_directory=None, reasoning_effort=None):
    config = settings.load()
    provider, model_override = _enabled_route(config, provider, model_override)
    if provider not in settings.PROVIDERS:
        raise RuntimeError('기존 연결 모드는 각 워크플로우에서 검증하세요.')
    row = config['providers'].get(provider, {})
    model = model_override or row.get('model', '')
    if not model and provider == 'codex':
        model = 'gpt-6.1-sol'
    if not model:
        raise RuntimeError('모델 ID가 설정되지 않았습니다.')
    if provider == 'codex':
        from common.codex_cli import generate
        # Map gpt-6.1-sol gracefully if local codex CLI requires an installed alias or pass directly
        return generate(prompt, model, images, response_schema, audit_directory=audit_directory,
                        reasoning_effort=reasoning_effort)
    if reasoning_effort is not None:
        raise RuntimeError('선택한 공급자 어댑터는 명시적 추론 강도 전달을 지원하지 않습니다.')
    prompt = 'Return only a complete JSON object. Do not use tools or access files.\n'+prompt
    key = settings.crypt(row['encrypted_key'], decrypt=True) if row.get('encrypted_key') else settings.environment_key(provider)
    if not key:
        raise RuntimeError('선택한 공급자의 API 키가 없습니다.')
    headers = {'Content-Type': 'application/json'}
    if provider == 'gemini':
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        headers['x-goog-api-key'] = key
        body = {'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'responseMimeType': 'application/json'}}
    elif provider == 'openai':
        url = 'https://api.openai.com/v1/responses'
        headers['Authorization'] = 'Bearer '+key
        body = {'model': model, 'input': prompt, 'store': False,
                'text': {'format': {'type': 'json_object'}}}
    elif provider == 'deepseek':
        url = 'https://api.deepseek.com/chat/completions'
        headers['Authorization'] = 'Bearer '+key
        body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                'response_format': {'type': 'json_object'}}
    else:
        url = 'https://api.anthropic.com/v1/messages'
        headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
        body = {'model': model, 'max_tokens': 8192, 'messages': [{'role': 'user', 'content': prompt}]}
    try:
        response = requests.post(url, headers=headers, json=body, timeout=120, allow_redirects=False)
    except requests.RequestException:
        raise RuntimeError('LLM 네트워크 연결 실패 또는 시간 초과.') from None
    if response.status_code != 200:
        labels = {401: '인증 실패', 403: '접근 거절', 402: '잔액 부족', 404: '모델 또는 경로 없음', 429: '요청 한도 초과'}
        raise RuntimeError(f'LLM HTTP {response.status_code}: {labels.get(response.status_code, "공급자 요청 실패")}')
    try:
        data = response.json()
        if provider == 'gemini':
            if data['candidates'][0].get('finishReason') not in (None, 'STOP'):
                raise ValueError()
            text = ''.join(p.get('text', '') for p in data['candidates'][0]['content']['parts'] if not p.get('thought'))
        elif provider == 'openai':
            if data.get('status') != 'completed':
                raise ValueError()
            text = ''.join(c.get('text', '') for item in data['output'] if item.get('type') == 'message'
                           for c in item.get('content', []) if c.get('type') == 'output_text')
        elif provider == 'deepseek':
            if data['choices'][0].get('finish_reason') != 'stop':
                raise ValueError()
            text = data['choices'][0]['message']['content']
        else:
            if data.get('stop_reason') != 'end_turn':
                raise ValueError()
            text = ''.join(c.get('text', '') for c in data['content'] if c.get('type') == 'text')
    except (ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError('LLM 응답이 불완전하거나 형식이 잘못되었습니다.') from None
    return parse_json(text), data.get('modelVersion') or data.get('model')
