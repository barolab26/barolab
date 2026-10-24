"""Authenticated native AGY structured calls; no silent provider substitution."""
import json
from pathlib import Path
import subprocess
import tempfile


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
    text='Use only the supplied data. Do not use tools, read files, browse, execute commands or change anything. Return only the required JSON.\n'+prompt
    with tempfile.TemporaryDirectory(prefix='barolab-agy-json-') as folder:
        path=Path(folder)/'schema.json';path.write_text(json.dumps(schema),encoding='utf-8')
        command=[executable,'--input-format','stream-json','--output-format','stream-json','--model',model,
                 '--json-schema',str(path),'--disable-slash-commands','--mode','plan','--print-timeout',f'{timeout:g}s']
        if reasoning_effort:command+=['--effort',reasoning_effort]
        record_provider_memory_delivery(text,'agy',model,audit_directory,'prepared')
        try:
            process=subprocess.run(command,input=json.dumps({'event':'user','message':{'content':text}},ensure_ascii=False)+'\n',
                cwd=folder,capture_output=True,text=True,encoding='utf-8',timeout=timeout+5)
        except subprocess.TimeoutExpired:
            record_provider_memory_delivery(text,'agy',model,audit_directory,'timeout')
            raise RuntimeError('AGY CLI 응답 시간 제한 초과.') from None
    try:
        events=[json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
        initial=next(e['init'] for e in events if e.get('event')=='init')
        result=next(e['result'] for e in reversed(events) if e.get('event')=='result')
        if process.returncode or result.get('status')!='SUCCESS':raise ValueError('AGY result failed')
        if initial.get('model')!=model:raise ValueError('AGY actual model mismatch')
        if any(e.get('step_update',{}).get('step_type')=='tool' for e in events):raise ValueError('Unexpected tool use')
        report_response(data=result,model=initial['model'])
        value=result.get('structured_output')
        if value is None:value=parse_json(result['response'])
        if not isinstance(value,dict):raise ValueError('Expected JSON object')
        if not response_schema:value=parse_json(value['json'])
    except (ValueError,KeyError,TypeError,StopIteration):
        record_provider_memory_delivery(text,'agy',model,audit_directory,'failed')
        raise RuntimeError('AGY CLI 모델·구조화 응답 확인 실패. 공급자를 자동 변경하지 않습니다.') from None
    record_provider_memory_delivery(text,'agy',initial['model'],audit_directory,'completed')
    return value,initial['model']
