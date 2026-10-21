"""Read-only EGO terminal HUD backed by the existing project and staff ledgers."""
import datetime
import json
import math
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OBSERVATION = ROOT / 'server/data/project-monitor-observation.json'
REQUESTS = ROOT / 'server/data/chats/staff-requests'
KST = datetime.timezone(datetime.timedelta(hours=9))


def load(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def request_rows(directory):
    rows = []
    for path in directory.glob('*.json'):
        if path.is_symlink():
            continue
        row = load(path)
        if row.get('taskId'):
            rows.append(row)
    return sorted(rows, key=lambda row: timestamp(row.get('updatedAt') or row.get('createdAt')) or 0, reverse=True)


def clean(value):
    return ''.join(c for c in str(value) if c.isprintable())[:220]


def timestamp(value):
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        value = parsed.timestamp() if parsed.tzinfo else parsed.replace(tzinfo=KST).timestamp()
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def time_label(value, now):
    value = timestamp(value)
    if value is None:
        return '시각 미관측'
    age = int(now.timestamp()-value)
    if age < 0:
        return '미래 시각 — 확인 필요'
    return datetime.datetime.fromtimestamp(value, KST).strftime('%m-%d %H:%M:%S')+f' ({age}초 전)'


def activity_lines(requests, now, activity=None):
    active = [r for r in requests if r.get('status') in ('queued','acknowledged','awaiting_completion')]
    lines = ['④ EGO 현재 활동 · 최근 기록', '  EGO 직원 지시 실행: 진행·대기 요청 '+str(len(active))+'건 (기록 기반; 프로세스 생존은 별도 확인)']
    if activity:
        lines.append('  실행기 관측: '+time_label(activity.get('observedAt'),now)+' (마지막 동작 시각과 구분)')
    for channel, data in (activity or {}).items():
        if channel not in ('cf','naver') or not isinstance(data,dict):
            continue
        title = 'CF' if channel == 'cf' else '네이버'
        lines.append('  '+title+' 파이프라인: '+state_text(data.get('state','unknown'))+' · '+clean(data.get('stage') or '단계 미관측'))
        lines.append('    마지막 동작: '+time_label(data.get('lastActionAt'),now))
    if (activity or {}).get('coverage'):
        lines.append('  연결 범위: '+clean(activity['coverage']))
    if not active:
        lines.append('  진행 요청 없음 · 다음 요청 대기 여부는 실행기 연결 확인 필요')
    for row in active[:4]:
        action = next(iter(row.get('actions') or [{}]), {})
        lines.append('  '+STAFF.get(action.get('agent'),'담당 직원')+' · '+TOOLS.get(action.get('tool'),'등록 작업')+' · '+state_text(row.get('status','unknown')))
        execution = row.get('currentExecution') or {}
        model = row.get('latestAction') or {}
        if model.get('kind') == 'staff_model' and model.get('state') == 'calling':
            detail = '직원 모델: '+STAFF.get(model.get('agent'),'직원')+' 답변 모델 호출 중'
            observed = model.get('observedAt')
        elif execution:
            detail = 'EGO 수행: '+TOOLS.get(execution.get('tool'),'등록 작업')+' · '+state_text(execution.get('status','unknown'))
            observed = row.get('executionObservedAt') or execution.get('returnedAt') or execution.get('startedAt')
        else:
            detail = '세부 현재 단계 미연결'
            observed = row.get('claimedAt') or row.get('createdAt')
        event_time = timestamp(observed)
        ongoing = event_time is not None and 0 <= now.timestamp()-event_time <= 120
        if not ongoing:
            detail = '마지막 기록: '+detail+' / 현재 지속 여부 미확인'
        lines.append('    '+detail+' · '+time_label(observed,now))
    if len(active)>4:
        lines.append(f'  나머지 진행·대기 요청 {len(active)-4}건')
    for row in requests[:2]:
        action=next(iter(row.get('actions') or row.get('results') or [{}]),{})
        lines.append('  최근 요청: '+STAFF.get(action.get('agent'),'담당 직원')+' · '+TOOLS.get(action.get('tool'),'등록 작업')+' · '+state_text(row.get('status','unknown'))+' · '+time_label((row.get('latestAction') or {}).get('observedAt') or row.get('executionObservedAt') or row.get('claimedAt') or row.get('createdAt'),now))
    lines.append('  연결된 기록만 표시 · 미연결 작업의 클릭·타이핑·진행 여부는 미관측')
    return lines


STAFF = {'jarvis':'자비스','patch':'패치','publi':'퍼블리','trace':'트레이스','doctor':'닥터','radar':'레이더'}
TOOLS = {'read_agent_status':'운영 상태 확인','repair_cf_known_failure':'CF 오류 수리'}
STATES = {'queued':'요청 대기','acknowledged':'접수','running':'실행 중','started':'시작됨',
          'awaiting_completion':'결과 대기','completed':'요청 처리 완료','held':'보류','failed':'실패',
          'unknown':'미관측','review_required':'검수 대기','stale':'지난 자료','observed':'관측됨',
          'attention':'확인 필요','published':'공개됨','reserved':'예약됨','scheduled':'예약됨',
          'idle':'대기', 'active':'실행 중', 'registered_idle':'등록 파이프라인 실행 없음', 'active_unobserved':'실행 잠금 확인 · 단계 미관측', 'disconnected':'미연결', 'waiting':'대기','prepared':'준비됨','retry_wait':'재시도 대기','done':'처리됨'}


def state_text(value):
    return STATES.get(value, clean(value))


def render_lines(snapshot, requests, *, now, columns=120, activity=None):
    """Pure rendering: no observation is promoted into execution or success."""
    observed = snapshot.get('observedAt')
    fresh = isinstance(observed, (int, float)) and 0 <= now.timestamp()-observed <= 90
    label = '최근 관측' if fresh else '관측 지연 / 미관측'
    lines = ['EGO LITE 프로젝트 모니터', f'① 현재 시각: {now.astimezone(KST):%Y-%m-%d %H:%M:%S} KST',
             '② 직원 실행 요청 · 실제 결과']
    if not requests:
        lines.append('  실행 요청 기록 미관측')
    for row in requests[:2]:
        action = next(iter(row.get('actions') or row.get('results') or [{}]), {})
        lines.append('  '+STAFF.get(action.get('agent'),'담당 직원')+' · '+TOOLS.get(action.get('tool'),'등록 작업')+' · '+state_text(row.get('status','unknown')))
        for item in row.get('results', [])[-1:]:
            result = item.get('result') or {}
            receipt = result.get('executorReceipt') or (item.get('initialResult') or {}).get('executorReceipt') or {}
            state = result.get('status') or receipt.get('status') or 'unknown'
            lines.append('    결과: '+state_text(state)+
                         (' | EGO 실행 기록' if receipt.get('executor') == 'ego-lite' else ' | 기존 실행 기록'))
    lines += [f'③ 전체 프로젝트 진행: {label}', '  자료 다시 읽은 시각: '+time_label(observed,now)+' · 아래 원천 시각과 구분']
    projects = snapshot.get('projects')
    if not isinstance(projects, list) or not projects:
        lines.append('  프로젝트 원천 자료 미관측 — 완료로 판단하지 않음')
    else:
        for project in projects:
            if not isinstance(project, dict):
                continue
            source = project.get('source') or {}
            state = project.get('status') or 'unknown'
            lines.append('  '+clean(project.get('title') or project.get('id'))+' | '+state_text(state)+
                         ('' if fresh else ' (지난 관측)'))
            counts = project.get('counts') or {}
            progress = ', '.join(state_text(k)+':'+clean(v) for k,v in counts.items()) if isinstance(counts,dict) and counts else clean(project.get('observedState') or '미관측')
            lines.append('    '+progress+' | 공개 확인:'+clean(project.get('verifiedPublicCount') if project.get('verifiedPublicCount') is not None else '미관측')+
                         ' | 예약:'+clean(project.get('reservedCount') if project.get('reservedCount') is not None else '미관측'))
            source_label = '원천 날짜·기준 충족 (실시간 보장 아님)' if source.get('fresh') is True else '원천 오래됨 / 미확인'
            lines.append('    '+source_label+' · 날짜: '+clean(source.get('sourceDate') or '미상')+' / 확인: '+time_label(source.get('sourceCheckedAt'),now))
    lines += activity_lines(requests, now, activity)
    lines.append('  화면은 1초마다 갱신 · 업무 실행 및 원천 데이터 갱신을 의미하지 않음')
    return [line[:max(20, columns-1)] for line in lines]


def main():
    from server.ego_activity import read_activity
    print('\033]0;EGO LITE Live Monitor\007\033[?25l', end='')
    try:
        while True:
            width = shutil.get_terminal_size((140, 45)).columns
            lines = render_lines(load(OBSERVATION), request_rows(REQUESTS), now=datetime.datetime.now(KST), columns=width, activity=read_activity())
            styled = [('\033[1;36m'+line+'\033[0m') if line.startswith(('EGO','①','②','③','④')) else line for line in lines]
            print('\033[H\033[2J'+'\n'.join(styled), end='', flush=True)
            time.sleep(1)
    finally:
        print('\033[?25h', end='', flush=True)


if __name__ == '__main__':
    main()
