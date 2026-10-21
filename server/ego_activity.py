"""Read-only, bounded stage observations; never replay historical browser actions."""
import json
import hashlib
import re
import math
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parent.parent


def read_json(path):
    if path.stat().st_size > 4_000_000:
        raise ValueError('Activity source too large')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Activity source not object')
    return value


def lock_busy(path):
    if not path.exists():
        return False
    if os.name != 'posix':
        raise ValueError('Passive OS lock observation unavailable')
    stat = path.stat()
    identity = (os.major(stat.st_dev), os.minor(stat.st_dev), stat.st_ino)
    for line in Path('/proc/locks').read_text().splitlines():
        fields = line.split()
        if '->' in fields:
            continue
        for field in fields:
            parts = field.split(':')
            if len(parts) == 3:
                try:
                    key = (int(parts[0],16), int(parts[1],16), int(parts[2]))
                except ValueError:
                    continue
                if key == identity:
                    return True
    return False


def stamp(value):
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timestamp lacks timezone')
    return dt.timestamp()


def active_folder(value, account, base):
    candidate = Path(value)
    win = PureWindowsPath(value)
    if os.name == 'posix' and win.is_absolute():
        suffix = win.relative_to(PureWindowsPath(r'C:\10_Project\BaroLab\naver_blog_posting\output'))
        candidate = base/'output'/Path(*suffix.parts)
    folder = candidate.resolve()
    folder.relative_to((base/'output'/account).resolve())
    if folder == (base/'output'/account).resolve():
        raise ValueError('Account root is not a run folder')
    return folder


def read_activity(root=ROOT, now=None):
    root = Path(root)
    now = time.time() if now is None else now
    result = {'observedAt': datetime.fromtimestamp(now, timezone.utc).isoformat(),
              'coverage': '연결된 자동화 입력·단계 관측 · 사용자 수동 입력/미연결 외부 앱은 수집하지 않음'}
    for channel, base, lock in [('cf', root/'cf_posting', 'cleaner.lock'),
                                ('naver', root/'naver_blog_posting', 'pipeline-run.lock')]:
        row = {'state': 'unknown', 'stage': None, 'lastActionAt': None,
               'source': 'OS lock and channel stage records'}
        result[channel] = row
        try:
            if not lock_busy(base/'data'/lock):
                row['state'] = 'registered_idle'
                continue
            row['state'] = 'active_unobserved'
            if channel == 'cf':
                state = read_json(base/'data/pipeline_state.json')
                schedule = read_json(base/'data/daily_schedule.json')
                domain = state.get('activeDomain') or state.get('domain')
                item = next((x for x in schedule.get('items', []) if x.get('domain') == domain and x.get('status') == 'processing'), None)
                at = state.get('timestamp')
                today = datetime.fromtimestamp(now, timezone(timedelta(hours=9))).date().isoformat()
                if schedule.get('date') != today or not item or not isinstance(at, (float, int)) or not 0 <= now-at <= 120:
                    continue
                row.update(state='active', stage=state.get('stageName') or str(state.get('currentStage')),
                           lastActionAt=datetime.fromtimestamp(at, timezone.utc).isoformat(), domain=domain)
            else:
                attempts = read_json(base/'data/automation-journal.json').get('attempts', [])
                active = [a for a in attempts if a.get('phase') in ('started', 'submitting')]
                if not active:
                    continue
                attempt = max(active, key=lambda a: stamp(a['startedAt']))
                started = stamp(attempt['startedAt'])
                account = attempt['account']
                if not isinstance(account, str) or Path(account).name != account or account in ('.', '..'):
                    raise ValueError('Invalid account')
                folder = active_folder(attempt['artifactFolder'], account, base)
                event = read_json(folder/'visible-editor-progress.json').get('events', [])[-1]
                at = stamp(event['at'])
                if at < started or not 0 <= now-at <= 120:
                    continue
                stage = event.get('stage')
                if stage not in ('start', 'title', 'block', 'image', 'sticker', 'content-mismatch', 'verified'):
                    continue
                row.update(state='active', stage=stage, lastActionAt=event['at'], account=account,
                           source='active journal + visible-editor-progress')
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            row['errorType'] = type(exc).__name__
    return result


def read_input_activity(directory=None, now=None):
    """Reproject only bounded host action fields; no input text or arbitrary labels."""
    from common.ego_telemetry import DIRECTORY, ACTIONS, TARGETS
    directory = Path(directory) if directory is not None else DIRECTORY
    now = time.time() if now is None else now
    rows = []
    candidates = sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)[:64]
    for path in candidates:
        try:
            if path.is_symlink() or path.stat().st_size > 100000:
                continue
            doc = read_json(path); context = doc['context']; pid = doc['processId']
            if not isinstance(context,dict) or type(pid) is not int or pid <= 0:
                continue
            allowed = ('taskId','requestId','requester','actor','project','parentRequestId','source','tool')
            if set(context)-set(allowed) or any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_:.-]{1,180}',v) for v in context.values()):
                continue
            key = hashlib.sha256((context['taskId']+':'+str(pid)).encode()).hexdigest()
            if path.name != key+'.json':
                continue
            events = []
            for event in doc.get('recent', [])[-16:]:
                if not isinstance(event,dict) or event.get('action') not in ACTIONS or event.get('target') not in TARGETS or event.get('phase') not in ('before','after','failed'):
                    continue
                if not re.fullmatch(r'[0-9a-f]{32}',str(event.get('actionId',''))):
                    continue
                at = stamp(event.get('at'))
                if not math.isfinite(at) or at > now:
                    continue
                row = {k:event[k] for k in ('actionId','action','target','phase','at')}
                if type(event.get('count')) is int and 0 <= event['count'] <= 1000000:
                    row['count'] = event['count']
                events.append(row)
            if not events:
                continue
            latest = events[-1]; age = now-stamp(latest['at'])
            distinct = {}
            for event in events:
                distinct[event['actionId']] = event
            recent = sorted(distinct.values(),key=lambda e: stamp(e['at']))[-4:]
            rows.append({'context':context,'latest':latest,'recent':recent,
                         'fresh':0 <= age <= 120, 'processObserved':os.name=='posix' and Path('/proc',str(pid)).exists()})
        except (OSError,ValueError,TypeError,KeyError,IndexError):
            continue
    rows = sorted(rows,key=lambda r:(r['fresh'] and r['latest']['phase']=='before',stamp(r['latest']['at'])),reverse=True)
    if rows:
        rows[0]['additionalRecords'] = max(0,len(rows)-1)
        rows[0]['scanLimited'] = len(candidates)==64
    return rows[:3]
