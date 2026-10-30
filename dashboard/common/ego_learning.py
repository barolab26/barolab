"""Reuse verified screen interactions; keep hypotheses and measured outcomes separate."""
from common import runtime_locks as fcntl
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from common.collection_observability import load, write
from common.runtime_locks import runtime_lock_path

ROOT = Path(__file__).resolve().parents[2]


def remember_success(problem, turns, before_screen, after_screen, elapsed_seconds, *, root=ROOT,
                     verification='same approved prefix passed native text/style/component checks'):
    """Called only after the same approved input prefix passes its host checks."""
    from dashboard.agents.synapse import build_index, edge
    if not Path(before_screen).is_file() or not Path(after_screen).is_file():
        raise ValueError('Verified screen learning requires both actual screenshots')
    signature = problem.split(':', 1)[0] if problem.startswith('Visible ') else problem.split('):', 1)[-1]
    identity = 'screen-lesson:' + hashlib.sha256(signature.encode()).hexdigest()[:24]
    data = Path(root) / 'dashboard/data'
    data.mkdir(parents=True, exist_ok=True)
    lock = runtime_lock_path(data / 'synapse.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    messages = [row['message'] for row in turns[-5:]]
    measurement = {'actionCount': sum(row.get('completedActions', 0) for row in turns),
                   'elapsedSeconds': round(elapsed_seconds, 3), 'checkedAt': datetime.now(timezone.utc).isoformat()}
    with lock.open('a+b') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        graph = load(data / 'memory_graph.json', {'schema': 'synapse-memory-v1', 'nodes': {}, 'edges': []})
        graph['nodes'].setdefault('memory:hub', {'type': 'MemoryHub'})
        node = graph['nodes'].setdefault(identity, {'type': 'ScreenInteractionLesson', 'title': signature,
                                                   'domain': 'naver-smarteditor', 'measurements': []})
        node.update(status='verified_success', recordedAt=measurement['checkedAt'],
                    guidance='호스트의 실제 검사를 통과한 조작 사례다. 현재 화면 조건을 확인하고 의미 단위 조작을 재사용한다. 좌표는 복사하지 않는다. 상황: ' + problem[:300] + ' 마지막 조작: ' + ' / '.join(messages),
                    evidence={'beforeScreen': str(before_screen), 'afterScreen': str(after_screen),
                              'verification': verification},
                    causalClaim=False, successCount=node.get('successCount', 0) + 1)
        node['measurements'] = (node['measurements'] + [measurement])[-8:]
        edge(graph, 'memory:hub', identity, 'contains')
        write(data / 'memory_graph.json', graph)
        write(data / 'synapse-recipes.json', build_index(graph))
    return identity


def consult_problem(problem, page_image, goal, turns, folder):
    """One bounded team-lead consultation; advice is not a verified skill."""
    from common.llm_client import generate_json
    return generate_json('당신은 EGO Lite를 지휘하는 팀장이다. 같은 오류가 반복됐다. 첨부 실제 화면과 '
                         '행동 기록을 보고 반복 중인 잘못된 접근을 중단시키고 다른 조작 방법을 한국어로 지시하라. '
                         '화면에 없는 메뉴를 있다고 만들지 말고 현재 도구로 불가능하면 필요한 능력 보완을 구체적으로 보고하라. '
                         '이미 승인된 원고·탭·로그인은 보존한다. DOM 주입·가짜 검수·발행 재클릭은 금지다. '
                         '현재 도구는 좌표 클릭·드래그·키보드·승인 원고 입력·승인된 짧은 trial·이 문서 내부의 Ctrl+C/X/V/Z/A를 지원한다. '
                         '아직 실행 검증 전인 조언을 성공 지식이라고 하지 않는다.\n' + json.dumps({
                             'problem': problem, 'goal': goal, 'recentTurns': turns[-8:]}, ensure_ascii=False),
                         images=[str(Path(page_image).resolve())], agent_slot='jarvis',
                         response_schema={'type': 'object', 'properties': {
                             'message': {'type': 'string'}, 'instruction': {'type': 'string'},
                             'needsToolUpgrade': {'type': 'boolean'}, 'requiredCapability': {'type': 'string'}},
                             'required': ['message', 'instruction', 'needsToolUpgrade', 'requiredCapability'],
                             'additionalProperties': False}, audit_directory=Path(folder) / 'model-audit', timeout_seconds=120)
