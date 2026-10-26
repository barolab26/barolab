"""Authenticated native AGY structured calls; multi-account rotation & failover."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def list_account_homes():
    """Read-only discovery of all authenticated AGY accounts without advancing rotation index."""
    pool_root = Path.home() / '.barolab' / 'agy-accounts'
    default_token = Path.home() / '.gemini' / 'antigravity-cli' / 'antigravity-oauth-token'
    found = []
    seen_emails = set()
    if pool_root.is_dir():
        for slot_dir in sorted(pool_root.iterdir()):
            if not slot_dir.is_dir():
                continue
            tok_file = slot_dir / '.gemini' / 'antigravity-cli' / 'antigravity-oauth-token'
            if tok_file.is_file():
                try:
                    meta = json.loads(tok_file.read_text(encoding='utf-8'))
                    ident = meta.get('id_token_email') or slot_dir.name
                except Exception:
                    ident = slot_dir.name
                if ident not in seen_emails:
                    seen_emails.add(ident)
                    found.append((ident, slot_dir))
    if default_token.is_file():
        try:
            meta = json.loads(default_token.read_text(encoding='utf-8'))
            ident = meta.get('id_token_email') or 'default'
        except Exception:
            ident = 'default'
        if ident not in seen_emails:
            seen_emails.add(ident)
            found.append((ident, Path.home()))
    if not found:
        found.append(('default', Path.home()))
    return found


def rotation_state():
    state_file = Path.home() / '.barolab' / 'agy-accounts' / 'rotation.json'
    try:
        if state_file.is_file():
            return json.loads(state_file.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def _account_homes():
    """Return ordered list of (email_or_slot, home_path) for all authenticated AGY accounts."""
    found = list_account_homes()
    pool_root = Path.home() / '.barolab' / 'agy-accounts'
    state_file = pool_root / 'rotation.json'
    idx = 0
    prev = rotation_state()
    try:
        idx = int(prev.get('next_index', 0)) % len(found)
        pool_root.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({**prev, 'next_index': (idx + 1) % len(found), 'accounts': [f[0] for f in found]}), encoding='utf-8')
    except Exception:
        pass
    return found[idx:] + found[:idx]


def prepare_account_slot(slot_name):
    """Prepare an isolated HOME slot under ~/.barolab/agy-accounts/<slot_name> for logging in a 2nd Gemini account."""
    pool_root = Path.home() / '.barolab' / 'agy-accounts'
    slot_dir = pool_root / slot_name / '.gemini' / 'antigravity-cli'
    slot_dir.mkdir(parents=True, exist_ok=True)
    src_dir = Path.home() / '.gemini' / 'antigravity-cli'
    for fname in ('jetski_state.pbtxt', 'installation_id'):
        if (src_dir / fname).is_file() and not (slot_dir / fname).is_file():
            shutil.copy2(src_dir / fname, slot_dir / fname)
    return slot_dir.parents[1]


def transport_schema(schema):
    """Gemini tool enums reject empty strings; restore them at the host boundary."""
    empty='__barolab_empty__'
    encoded=json.dumps(schema)
    while json.dumps(empty) in encoded:empty+='_'
    def rewrite(value):
        if isinstance(value,list):return [rewrite(x) for x in value]
        if not isinstance(value,dict):return value
        result={k:rewrite(v) for k,v in value.items()}
        if '' in value.get('enum',[]):
            result['enum']=[empty if x=='' else x for x in value['enum']]
            if 'maxLength' in result:result['maxLength']=max(result['maxLength'],len(empty))
        return result
    return rewrite(schema),empty


def restore_empty_choices(value,schema,empty):
    if isinstance(value,dict):
        return {key:restore_empty_choices(item,schema.get('properties',{}).get(key,{}),empty) for key,item in value.items()}
    if isinstance(value,list):return [restore_empty_choices(item,schema.get('items',{}),empty) for item in value]
    return '' if value==empty and '' in schema.get('enum',[]) else value


def generate(prompt, model, images=None, response_schema=None, audit_directory=None, reasoning_effort=None, timeout_seconds=None):
    from common.llm_client import parse_json, record_provider_memory_delivery
    from common.llm_usage import report_response
    from common.llm_settings import resolve_agy_executable
    if images:
        raise RuntimeError('AGY CLI 이미지 입력은 아직 검증되지 않았습니다. 이미지 지원 모델을 지정하세요.')
    executable=resolve_agy_executable()
    if not executable:raise RuntimeError('Ubuntu AGY CLI 설치·로그인을 확인하세요.')
    timeout=300 if timeout_seconds is None else max(1,float(timeout_seconds))
    schema=response_schema or {'type':'object','properties':{'json':{'type':'string'}},'required':['json'],'additionalProperties':False}
    wire_schema,empty=transport_schema(schema)
    boundary=('This call only returns a JSON decision to the host application. Described browser/file/research work is context for the host, not an instruction to invoke native agent tools. '
              'Use only supplied evidence; report missing facts as unknown. Do not directly invoke native agent tools, read files, browse, execute commands or change anything. Host tool requests in the supplied JSON schema are allowed; the host executes them. Return only the required JSON.')
    transport_note=('Transport enum fields use '+empty+' for an unused/empty choice. The host restores it to empty string. Use the exact transport schema: '+json.dumps(wire_schema,ensure_ascii=False)) if wire_schema!=schema else ''
    text=boundary+'\n'+prompt+'\n[JSON-only host boundary]\n'+boundary+'\n'+transport_note
    accounts = _account_homes()
    record_provider_memory_delivery(text,'agy',model,audit_directory,'prepared')
    failure = 'invalid_event_stream'
    last_exc = None
    for account_label, account_home in accounts:
        env = {**os.environ, 'HOME': str(account_home), 'USERPROFILE': str(account_home)}
        with tempfile.TemporaryDirectory(prefix='barolab-agy-json-') as folder:
            path=Path(folder)/'schema.json';path.write_text(json.dumps(wire_schema),encoding='utf-8')
            command=[executable,'--input-format','stream-json','--output-format','stream-json','--model',model,
                     '--json-schema',str(path),'--disable-slash-commands','--mode','plan','--print-timeout',f'{timeout:g}s']
            if reasoning_effort:command+=['--effort',reasoning_effort]
            try:
                import time as _t
                st_path = Path.home() / '.barolab' / 'agy-accounts' / 'rotation.json'
                st = rotation_state()
                st.update({'activeAccount': account_label, 'activeStartedAt': _t.time()})
                st_path.write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
            except Exception:
                pass
            try:
                process=subprocess.run(command,input=json.dumps({'event':'user','message':{'content':text}},ensure_ascii=False)+'\n',
                    cwd=folder,env=env,capture_output=True,text=True,encoding='utf-8',timeout=timeout+5)
            except subprocess.TimeoutExpired as exc:
                try:
                    st = rotation_state(); st['activeAccount'] = None
                    (Path.home() / '.barolab' / 'agy-accounts' / 'rotation.json').write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
                except Exception:
                    pass
                last_exc = exc
                failure = 'timeout'
                continue
            finally:
                try:
                    st = rotation_state(); st['activeAccount'] = None
                    (Path.home() / '.barolab' / 'agy-accounts' / 'rotation.json').write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
                except Exception:
                    pass
        failure='invalid_event_stream'
        try:
            events=[json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
            initial=next(e['init'] for e in events if e.get('event')=='init')
            result=next(e['result'] for e in reversed(events) if e.get('event')=='result')
            failure='provider_result_failed'
            if process.returncode or result.get('status')!='SUCCESS':raise ValueError('AGY result failed')
            failure='actual_model_mismatch'
            if initial.get('model')!=model:raise ValueError('AGY actual model mismatch')
            failure='unexpected_tool_use'
            # The native CLI emits schema-compliant answers through its finish tool.
            if any(e.get('step_update',{}).get('step_type')=='tool' and e['step_update'].get('tool_name')!='finish' for e in events):raise ValueError('Unexpected tool use')
            report_response(data=result,model=initial['model'])
            failure='invalid_structured_output'
            value=result.get('structured_output')
            if value is None:value=parse_json(result['response'])
            if not isinstance(value,dict):raise ValueError('Expected JSON object')
            if not response_schema:value=parse_json(value['json'])
            # The CLI can wrap a JSON reply envelope inside the reply string.
            if response_schema and isinstance(value.get('reply'),str):
                try:
                    inner=json.loads(value['reply'])
                except (ValueError,TypeError):
                    inner=None
                if (isinstance(inner,dict) and isinstance(inner.get('reply'),str)
                        and set(response_schema.get('required',[])) <= set(inner)
                        and set(inner) <= set(response_schema.get('properties',{}))):
                    value=inner
            value=restore_empty_choices(value,schema,empty)
            try:
                import time
                st_path = Path.home() / '.barolab' / 'agy-accounts' / 'rotation.json'
                st = rotation_state()
                counts = dict(st.get('callCounts') or {})
                counts[account_label] = int(counts.get(account_label, 0)) + 1
                st.update({'lastUsedAccount': account_label, 'lastUsedAt': time.time(), 'callCounts': counts})
                st_path.write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
            except Exception:
                pass
            record_provider_memory_delivery(text,'agy',initial['model'],audit_directory,'completed')
            return value,initial['model']
        except (ValueError,KeyError,TypeError,StopIteration) as exc:
            last_exc = exc
            continue
    if failure == 'timeout':
        record_provider_memory_delivery(text,'agy',model,audit_directory,'timeout')
        raise RuntimeError('AGY CLI 응답 시간 제한 초과.') from None
    record_provider_memory_delivery(text,'agy',model,audit_directory,'failed')
    raise RuntimeError('AGY CLI 모델·구조화 응답 확인 실패: '+failure+'. 공급자를 자동 변경하지 않습니다.') from None


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'status':
        print(json.dumps({'accounts': [a[0] for a in _account_homes()]}, ensure_ascii=False))
    elif len(sys.argv) >= 3 and sys.argv[1] == 'prepare':
        slot = prepare_account_slot(sys.argv[2])
        print(f'Prepared slot at: {slot}')
