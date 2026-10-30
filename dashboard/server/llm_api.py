"""Local-only settings routes. No key values in GET, errors, logs, or test output."""
import sys
import os
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import llm_settings as settings
from common.llm_client import generate_json
from common import dashboard_jobs as jobs

router = APIRouter(prefix='/api/llm')
workflow_router = APIRouter(prefix='/api/workflows')


def trusted_settings_client(client):
    if client == 'testclient':
        return True
    try:
        address = ipaddress.ip_address(client)
        networks = os.getenv('BAROLAB_TRUSTED_CLIENTS', '127.0.0.0/8,::1/128,192.168.45.0/24,172.16.0.0/12').split(',')
        return any(address in ipaddress.ip_network(network.strip()) for network in networks)
    except ValueError:
        return False


async def guard(request: Request, call_next):
    # Public status/preview mounts must never serve account keys or dotfiles.
    if any(part.casefold() in ('secure', 'data-secret') or part.startswith('.')
           for part in request.url.path.split('/') if part):
        return JSONResponse({'detail': 'Not found'}, status_code=404)
    if request.method == 'OPTIONS' or not request.url.path.startswith(('/api/llm', '/api/workflows')):
        return await call_next(request)
    host = request.url.hostname
    client = request.client.host if request.client else ''
    allowed_hosts = os.getenv('BAROLAB_ALLOWED_HOSTS', '127.0.0.1,localhost,::1,192.168.45.190,192.168.45.248,otns,otns.local').split(',')
    if host not in allowed_hosts or not trusted_settings_client(client):
        return JSONResponse({'detail': '로컬 대시보드에서만 설정할 수 있습니다.'}, status_code=403)
    if request.method == 'POST' and (request.headers.get('x-barolab-settings') != '1'
            or request.headers.get('content-type', '').split(';')[0] != 'application/json'):
        return JSONResponse({'detail': '올바른 설정 요청이 아닙니다.'}, status_code=403)
    try:
        response = await call_next(request)
    except Exception:
        return JSONResponse({'detail': '설정 처리 실패. 서버 상태를 확인하세요.'}, status_code=500)
    response.headers['Cache-Control'] = 'no-store'
    return response


@router.get('/settings')
def get_settings():
    try:
        return settings.public()
    except settings.SettingsError as e:
        return JSONResponse({'detail': str(e)}, status_code=503)


@router.post('/settings')
async def set_settings(request: Request):
    raw = await request.body()
    if len(raw) > 32768:
        return JSONResponse({'detail': '요청이 너무 큽니다.'}, status_code=413)
    try:
        import json
        return await run_in_threadpool(settings.save, json.loads(raw))
    except (ValueError, TypeError) as e:
        message = str(e) if isinstance(e, settings.SettingsError) else '잘못된 JSON 요청입니다.'
        return JSONResponse({'detail': message}, status_code=400)


@router.post('/agent-brains')
async def set_agent_brains(request: Request):
    raw = await request.body()
    if len(raw) > 32768:
        return JSONResponse({'detail': '요청이 너무 큽니다.'}, status_code=413)
    try:
        import json
        return await run_in_threadpool(settings.save_agent_brains, json.loads(raw))
    except (ValueError, TypeError) as e:
        message = str(e) if isinstance(e, settings.SettingsError) else '잘못된 JSON 요청입니다.'
        return JSONResponse({'detail': message}, status_code=400)


@router.post('/test')
async def test_connection(request: Request):
    try:
        body = await request.json()
        provider = body.get('provider')
        if provider not in settings.PROVIDERS:
            raise settings.SettingsError('공급자를 선택하세요.')
        result = await run_in_threadpool(generate_json, 'Return JSON {"ok":true}.', provider)
        if result.get('ok') is not True:
            raise RuntimeError('테스트 응답 검증 실패.')
        return {'ok': True, 'provider': provider, 'message': '실제 JSON 생성 성공. 원고·이미지·발행 검증은 별도입니다.'}
    except (settings.SettingsError, RuntimeError) as e:
        return JSONResponse({'ok': False, 'detail': str(e)}, status_code=400)
    except Exception:
        return JSONResponse({'ok': False, 'detail': '연결 확인 실패.'}, status_code=400)


@workflow_router.post('/cf/retry')
async def retry_cf(request: Request):
    try:
        import json
        body = await request.json()
        schedule_path = jobs.ROOT / 'dashboard' / 'data' / 'cf' / 'daily_schedule.json'
        schedule = json.loads(schedule_path.read_text(encoding='utf-8'))
        req_date = body.get('date') or schedule.get('date')
        if req_date != schedule.get('date'):
            raise ValueError('발행 날짜가 변경되었습니다. 화면을 새로고침하세요.')
        item = next((row for row in schedule['items'] if row['domain'] == body.get('domain')), None)
        if not item or item.get('status') == 'published':
            raise ValueError('이미 발행 완료된 도메인이거나 대상을 찾을 수 없습니다.')
        if item.get('status') in ('processing', 'publishing'):
            raise ValueError('현재 실시간 발행이 진행 중인 도메인입니다.')
        if item.get('status') not in ('failed', 'retry_wait', 'review_required', 'interrupted', 'waiting', 'pending', 'prepared'):
            raise ValueError('재실행 가능한 상태가 아닙니다.')
        job = jobs.enqueue('cf-retry', {'domain': item['domain'], 'date': schedule['date']})
        return JSONResponse({**jobs.public(job), 'message': f"[{item.get('name', item['domain'])}] 즉시 재발행 요청을 접수했습니다. 중복 발행 여부를 확인한 뒤 파이프라인을 가동합니다."}, status_code=202)
    except (ValueError, OSError) as exc:
        return JSONResponse({'detail': str(exc) if isinstance(exc, ValueError) else '발행 일정 정보를 읽지 못했습니다.'}, status_code=409)


@workflow_router.get('/jobs/{job_id}')
def workflow_job(job_id: str):
    try:
        return jobs.public(jobs.load(job_id))
    except (ValueError, OSError):
        return JSONResponse({'detail': '작업 요청을 찾을 수 없습니다.'}, status_code=404)
