"""Full-height six-panel EGO cockpit; legacy text adapters remain import-compatible."""
import datetime
import json
import math
import unicodedata
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBSERVATION = ROOT / 'dashboard/data/project-monitor-observation.json'
REQUESTS = ROOT / 'dashboard/data/chats/staff-requests'
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


def activity_lines(requests, now, activity=None, has_inputs=False):
    active = [r for r in requests if r.get('status') in ('queued','acknowledged','awaiting_completion')]
    lines = ['④ EGO 현재 활동 · 최근 기록', '  EGO 직원 지시 실행: 진행·대기 요청 '+str(len(active))+'건 (기록 기반; 프로세스 생존은 별도 확인)']
    if activity:
        lines.append('  실행기 관측: '+time_label(activity.get('observedAt'),now)+' (마지막 동작 시각과 구분)')
    for channel, data in (activity or {}).items():
        if channel not in ('cf','naver') or not isinstance(data,dict):
            continue
        title = 'CF' if channel == 'cf' else '네이버'
        lines.append('  '+title+' 파이프라인: '+state_text(data.get('state','unknown'))+' · '+clean(data.get('stage') or '단계 미관측'))
        if not has_inputs:
            lines.append('    마지막 동작: '+time_label(data.get('lastActionAt'),now))
    if (activity or {}).get('coverage'):
        lines.append('  연결 범위: '+clean(activity['coverage']))
    if not active:
        lines.append('  진행 요청 없음 · 다음 요청 대기 여부는 실행기 연결 확인 필요')
    for row in active[:4]:
        action = next(iter(row.get('actions') or [{}]), {})
        lines.append('  '+'['+STAFF.get(action.get('agent'),'담당 직원')+'] · '+TOOLS.get(action.get('tool'),'등록 작업')+' · '+state_text(row.get('status','unknown')))
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
        lines.append('  최근 요청: '+'['+STAFF.get(action.get('agent'),'담당 직원')+'] · '+TOOLS.get(action.get('tool'),'등록 작업')+' · '+state_text(row.get('status','unknown'))+' · '+time_label((row.get('latestAction') or {}).get('observedAt') or row.get('executionObservedAt') or row.get('claimedAt') or row.get('createdAt'),now))
    lines.append('  연결된 자동화 동작만 표시 · 사용자 수동 입력/미연결 외부 앱은 수집하지 않음')
    return lines


STAFF = {'jarvis':'팀장','patch':'패치','publi':'퍼블리','trace':'트레이스','doctor':'닥터','radar':'레이더'}
TOOLS = {'read_agent_status':'운영 상태 확인','repair_cf_known_failure':'CF 오류 수리'}
STATES = {'queued':'요청 대기','acknowledged':'접수','running':'실행 중','started':'시작됨',
          'awaiting_completion':'결과 대기','completed':'요청 처리 완료','held':'보류','failed':'실패',
          'unknown':'미관측','review_required':'검수 대기','stale':'지난 자료','observed':'관측됨',
          'attention':'확인 필요','published':'공개됨','reserved':'예약됨','scheduled':'예약됨',
          'idle':'대기', 'active':'실행 중', 'registered_idle':'등록 파이프라인 실행 없음', 'active_unobserved':'실행 잠금 확인 · 단계 미관측', 'disconnected':'미연결', 'waiting':'대기','prepared':'준비됨','retry_wait':'재시도 대기','done':'처리됨'}


def state_text(value):
    return STATES.get(value, clean(value))


PROJECT_NAMES = {'cf_blog':'CF 블로그','cf':'CF 블로그','naver_blog':'네이버 블로그','naver':'네이버 블로그','naver_kin':'지식iN','threads':'Threads','naver_search':'네이버 검색 검증','project':'공통 작업','metrics':'운영 지표','content_maintenance':'콘텐츠 유지보수','mobile_apps':'앱 프로젝트'}
INPUT_ACTIONS = {'click':'클릭','type':'타이핑','press':'키 입력','insert_text':'문자 삽입','navigate':'화면 이동','download':'다운로드','upload':'업로드','api_request':'API 요청','tool':'등록 도구 실행'}
INPUT_TARGETS = {'registered-tool':'업무 도구','naver-title':'제목','naver-body':'본문','naver-toolbar':'서식','naver-link':'링크','naver-image':'사진','naver-caption':'사진 설명','naver-sticker':'스티커','naver-editor':'편집기','naver-editor-key':'편집기 키','kin-editor':'답변 편집기','kin-answer':'답변','kin-submit':'답변 등록','kin-editor-key':'답변 키','flow-home':'Flow 시작 화면','flow-settings':'Flow 설정','flow-single-output':'Flow 1장 설정','flow-new-project':'Flow 새 프로젝트','flow-project-tile':'Flow 프로젝트','flow-generate':'Flow 생성 버튼','flow-dismiss':'Flow 팝업 닫기','flow-prompt':'Flow 생성 문구','flow-image':'Flow 이미지','cf-image-upload':'CF 이미지 전송','cf-post-submit':'CF 글 제출','search-results':'검색 결과','official-source':'공식 자료','naver-search':'네이버 검색','naver-search-query':'검색어 입력란','naver-search-submit':'검색 버튼','threads-scheduler':'Threads 일정 확인','threads-publish':'Threads 게시 작업','threads-api-read':'Threads API 조회','threads-api-write':'Threads API 쓰기','threads-reconcile':'Threads 실제 게시 대조','threads-recovery':'Threads 복구 검토','threads-measurement':'Threads 측정','threads-authoring':'Threads 원고 제작','metrics-collection':'운영 지표 수집','revenue-collection':'수익 자료 수집','traffic-collection':'유입 자료 수집','maintenance-audit':'콘텐츠 점검','maintenance-prepare':'콘텐츠 수정 준비','maintenance-apply':'검토된 콘텐츠 적용','maintenance-run':'콘텐츠 유지보수 실행','metrics-browser':'지표 수집 화면','metrics-auth':'인증 화면'}


def input_lines(inputs, requests, now):
    lines = ['◆ 현재 입력 동작 · 지시 연결']
    if not inputs:
        return lines+['  연결된 클릭·타이핑 기록 미관측']
    for index,row in enumerate(inputs[:3]):
        context = row['context']; event = row['latest']
        matched = next((r for r in requests if r.get('taskId')==context.get('taskId') and r.get('requestId')==context.get('requestId')),None)
        if context.get('source')=='staff_queue' and matched:
            requester=STAFF.get(context.get('requester'),'지시자 미관측')
            actor=STAFF.get(context.get('actor'),'담당 미관측')
        elif context.get('source')=='direct':
            requester={'user':'사용자','scheduler':'등록 스케줄러'}.get(context.get('requester'),'지시자 미관측')
            actor='Codex(실행 검증)' if context.get('actor')=='codex' else '직접 실행'
        else:
            requester,actor='지시 연결 미확인','실행자 미관측'
        project=PROJECT_NAMES.get(context.get('project'),'등록 작업')
        lines.append(f'  [{project}] {requester} → [{actor}]')
        phase={'before':'입력 시작 관측 · 반환 미관측','after':'호출 반환','failed':'입력 실패'}[event['phase']]
        if not row['fresh'] or (event['phase']=='before' and not row['processObserved']):
            phase='마지막 기록 '+phase+' · 현재 지속 미확인'
        target=INPUT_TARGETS.get(event['target'],'등록 대상'); action=INPUT_ACTIONS[event['action']]
        count=f" · {event['count']}자" if 'count' in event and event['action'] in ('type','insert_text') else ''
        lines.append(f'    {target} {action}{count} — {phase}')
        lines.append('    실제 동작: '+time_label(event['at'],now)+' · 반환은 업무 성공 판정 아님')
        history=[]
        for previous in row.get('recent', [])[-4:]:
            suffix={'before':'시작','after':'반환','failed':'실패'}[previous['phase']]
            history.append(INPUT_TARGETS.get(previous['target'],'등록 대상')+' '+INPUT_ACTIONS[previous['action']]+'('+suffix+')')
        for start in range(0,len(history),2):
            lines.append('    최근 동작: '+' → '.join(history[start:start+2]))
        if index==0 and row.get('additionalRecords',0)>=3:
            lines.append('    다른 입력 기록 '+str(row['additionalRecords']-2)+'건 · 가장 최근 진행 관측 우선')
        if row.get('scanLimited'):
            lines.append('    최근 64개 기록 범위 · 그 이전 입력은 미관측')
    return lines


def render_lines(snapshot, requests, *, now, columns=120, activity=None, inputs=None, rows=70):
    """Pure rendering: no observation is promoted into execution or success."""
    observed = snapshot.get('observedAt')
    fresh = isinstance(observed, (int, float)) and 0 <= now.timestamp()-observed <= 90
    label = '최근 관측' if fresh else '관측 지연 / 미관측'
    lines = ['EGO LITE 프로젝트 모니터', f'① 현재 시각: {now.astimezone(KST):%Y-%m-%d %H:%M:%S} KST',
             '화면 시계와 업무·원천 자료의 갱신 시각은 다릅니다.']
    lines += ['직원 색상: [팀장] [퍼블리] [트레이스] [패치] [레이더] [닥터]']
    lines += input_lines(inputs or [],requests,now)
    lines += ['─'*min(columns-1,70),'② 직원 실행 요청 · 실제 결과']
    if not requests:
        lines.append('  실행 요청 기록 미관측')
    for row in requests[:2]:
        action = next(iter(row.get('actions') or row.get('results') or [{}]), {})
        lines.append('  '+'['+STAFF.get(action.get('agent'),'담당 직원')+'] · '+TOOLS.get(action.get('tool'),'등록 작업')+' · '+state_text(row.get('status','unknown')))
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
            app_note = ' · 등록된 자동작업 없음 / 상태자료 관측' if project.get('id')=='mobile_apps' else ''
            state = project.get('status') or 'unknown'
            lines.append('  '+clean(project.get('title') or project.get('id'))+' | '+state_text(state)+
                         ('' if fresh else ' (지난 관측)')+app_note)
            counts = project.get('counts') or {}
            progress = ', '.join(state_text(k)+':'+clean(v) for k,v in counts.items()) if isinstance(counts,dict) and counts else clean(project.get('observedState') or '미관측')
            lines.append('    '+progress+' | 공개 확인:'+clean(project.get('verifiedPublicCount') if project.get('verifiedPublicCount') is not None else '미관측')+
                         ' | 예약:'+clean(project.get('reservedCount') if project.get('reservedCount') is not None else '미관측'))
            source_label = '관측 기준 충족' if source.get('fresh') is True else '원천 오래됨 / 미확인'
            lines.append('    '+source_label+' · 날짜: '+clean(source.get('sourceDate') or '미상')+' / 확인: '+time_label(source.get('sourceCheckedAt'),now))
    lines += activity_lines(requests, now, activity, bool(inputs))
    lines.append('  화면은 1초마다 갱신 · 업무 실행 및 원천 데이터 갱신을 의미하지 않음')
    limit=max(8,rows-1)
    if len(lines)>limit:
        hidden=len(lines)-limit+1
        lines=lines[:limit-1]+[f'… 화면 높이 제한: 아래 {hidden}줄 추가 기록 있음']
    return [clip_cells(line,max(20,columns-1)) for line in lines]




def clip_cells(text, width):
    used=0; result=''
    for char in text:
        size=0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in ('W','F') else 1
        if used+size>width-1:
            return result+'…'
        result+=char;used+=size
    return result

def color_line(line):
    reset='\033[0m'
    if line.startswith(('EGO','①','②','③','④','◆','─')):
        return '\033[1;36m'+line+reset
    for title,color in [('CF','94'),('네이버 지식','95'),('네이버','96'),('지식','95'),('Threads','93'),('앱','92'),('콘텐츠','95')]:
        if line.lstrip().startswith((title,'['+title)):
            line='\033[1;'+color+'m'+line+reset
            break
    for status,color in [('입력 실패','31'),('실패','31'),('미확인','33'),('미관측','33'),('보류','33'),('대기','33'),('시도 중','36'),('실행 중','36'),('요청 처리 완료','32'),('호출 반환','32')]:
        line=line.replace(status,'\033[1;'+color+'m'+status+reset)
    for name,color in {'팀장':'94','퍼블리':'92','트레이스':'95','패치':'38;5;208','레이더':'38;5;213','닥터':'96','Codex(실행 검증)':'97'}.items():
        line=line.replace('['+name+']','\033[1;'+color+'m['+name+']'+reset)
    return line

def main():
    from server.mission_control import main as cockpit_main
    import sys
    return cockpit_main(sys.argv[1:])


if __name__ == '__main__':
    import sys
    sys.path.insert(0,str(ROOT))
    main()
