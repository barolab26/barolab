"""Read-only EGO terminal HUD backed by the existing project and staff ledgers."""
import datetime
import json
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
    return sorted(rows, key=lambda row: str(row.get('updatedAt') or row.get('createdAt') or ''), reverse=True)[:4]


def clean(value):
    return ''.join(c for c in str(value) if c.isprintable())[:220]


STAFF = {'jarvis':'자비스','patch':'패치','publi':'퍼블리','trace':'트레이스','doctor':'닥터','radar':'레이더'}
TOOLS = {'read_agent_status':'운영 상태 확인','repair_cf_known_failure':'CF 오류 수리'}
STATES = {'queued':'요청 대기','acknowledged':'접수','running':'실행 중','started':'시작됨',
          'awaiting_completion':'결과 대기','completed':'요청 처리 완료','held':'보류','failed':'실패',
          'unknown':'미관측','review_required':'검수 대기','stale':'지난 자료','observed':'관측됨',
          'attention':'확인 필요','published':'공개됨','reserved':'예약됨','scheduled':'예약됨',
          'waiting':'대기','prepared':'준비됨','retry_wait':'재시도 대기','done':'처리됨'}


def state_text(value):
    return STATES.get(value, clean(value))


def render_lines(snapshot, requests, *, now, columns=120):
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
    lines += [f'③ 전체 프로젝트 진행: {label}']
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
            lines.append('    원천 날짜: '+clean(source.get('sourceDate') or '미상')+' / 확인: '+clean(source.get('sourceCheckedAt') or '미상'))
    return [line[:max(20, columns-1)] for line in lines]


def main():
    print('\033]0;EGO LITE Live Monitor\007\033[?25l', end='')
    try:
        while True:
            width = shutil.get_terminal_size((140, 45)).columns
            lines = render_lines(load(OBSERVATION), request_rows(REQUESTS), now=datetime.datetime.now(KST), columns=width)
            styled = [('\033[1;36m'+line+'\033[0m') if line.startswith(('EGO','①','②','③')) else line for line in lines]
            print('\033[H\033[2J'+'\n'.join(styled), end='', flush=True)
            time.sleep(1)
    finally:
        print('\033[?25h', end='', flush=True)


if __name__ == '__main__':
    main()
