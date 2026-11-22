"""Keep the existing durable Hermes review queue consumer alive."""

import logging
import hashlib
import json
import os
import signal
import sqlite3
import subprocess as _sp
import sys
import threading
import time
import traceback
from pathlib import Path

if os.name == 'nt' and not getattr(_sp.Popen, '_barolab_no_window', False):
    _orig_popen_init = _sp.Popen.__init__
    def _no_window_popen_init(self, *args, **kwargs):
        kwargs['creationflags'] = int(kwargs.get('creationflags') or 0) | getattr(_sp, 'CREATE_NO_WINDOW', 0x08000000)
        _orig_popen_init(self, *args, **kwargs)
    _sp.Popen.__init__ = _no_window_popen_init
    _sp.Popen._barolab_no_window = True

_ROOT = Path(__file__).resolve().parents[2]
_IMPORT_PATHS = (_ROOT / 'dashboard' / 'server', _ROOT / 'dashboard', _ROOT / 'dashboard' / 'agents', _ROOT / 'dashboard' / 'collectors', _ROOT)
for _p in reversed(_IMPORT_PATHS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ['PYTHONPATH'] = os.pathsep.join([*(str(p) for p in _IMPORT_PATHS), os.environ.get('PYTHONPATH', '')])
os.environ['PYTHONUTF8'] = '1'


def has_active_jobs(proc=Path('/proc'), parent=None):
    """Preserve every non-browser descendant before recovering this supervisor."""
    parent = os.getpid() if parent is None else parent
    if os.name == 'nt' and proc == Path('/proc'):
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [
                    ('dwSize', wintypes.DWORD),
                    ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD),
                    ('th32DefaultHeapID', ctypes.c_void_p),
                    ('th32ModuleID', wintypes.DWORD),
                    ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD),
                    ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD),
                    ('szExeFile', wintypes.WCHAR * 260),
                ]

            snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
            if snap == wintypes.HANDLE(-1).value:
                return True
            try:
                pe = PROCESSENTRY32W()
                pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
                children = {}
                if kernel32.Process32FirstW(snap, ctypes.byref(pe)):
                    while True:
                        children[int(pe.th32ProcessID)] = (int(pe.th32ParentProcessID), pe.szExeFile.lower())
                        if not kernel32.Process32NextW(snap, ctypes.byref(pe)):
                            break
            finally:
                kernel32.CloseHandle(snap)
            descendants = {parent}
            while True:
                found = {pid for pid, (ppid, _) in children.items() if ppid in descendants}
                if found <= descendants:
                    break
                descendants |= found
            for pid in descendants - {parent}:
                exe_name = children[pid][1]
                if exe_name not in ('ego.exe', 'chrome.exe', 'chrome_crashpad_handler.exe'):
                    return True
            return False
        except Exception:
            return True
    children = {}
    try:
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields = (entry / 'stat').read_text().split(') ', 1)[1].split()
                children[int(entry.name)] = (int(fields[1]), fields[0])
            except FileNotFoundError:
                continue
        descendants = {parent}
        while True:
            found = {pid for pid, (ppid, _) in children.items() if ppid in descendants}
            if found <= descendants:
                break
            descendants |= found
        for pid in descendants - {parent}:
            if children[pid][1] == 'Z':
                continue
            entry = proc / str(pid)
            try:
                executable = (entry / 'exe').resolve(strict=True).name
            except FileNotFoundError:
                try:
                    executable = Path(os.fsdecode((entry / 'cmdline').read_bytes().split(b'\0')[0])).name
                except FileNotFoundError:
                    continue
            if executable not in ('chrome', 'chrome_crashpad_handler'):
                return True
        return False
    except (OSError, ValueError, IndexError):
        return True


def stalled_actions(progress, now):
    return [name for name, row in list(progress.items())
            if name not in ('memory-refresh',) and now - row['at'] > 900]


def action_outcome(result=None, error=None):
    """A live loop and ok=True do not establish a completed publication."""
    if error is not None:
        from common.collection_observability import failure_details
        return {'status':'failed',**failure_details(error),
                'requiresRepair':True,'publicationVerified':False}
    value=result if isinstance(result,dict) else {}
    action=value.get('action') or value.get('state') or value.get('status') or 'observed'
    blocked=(action in ('held','blocked','error','failed','all_topics_published') or value.get('ok') is False)
    return {'status':'awaiting_content_input' if action=='all_topics_published' else 'blocked' if blocked else 'observed',
            'action':action,'reason':str(value.get('reason') or '')[:400],
            'requiresRepair':blocked,'publicationVerified':value.get('publicPublicationVerified') is True}


def initialize_memory(store, stopped, on_busy=None):
    """Wait for actual shared-store contention; never break a lock or erase the store."""
    while not stopped.is_set():
        try:
            store.initialize();return True
        except (OSError,sqlite3.OperationalError) as exc:
            busy=(isinstance(exc,OSError) and (exc.errno in (11,35,36) or (exc.errno==13 and not exc.filename))) or (
                isinstance(exc,sqlite3.OperationalError) and any(t in str(exc).lower() for t in ('locked','busy')))
            if not busy:raise
            if on_busy:on_busy(exc)
            logging.warning('Memory initialization waiting for shared writer: %s',type(exc).__name__)
            stopped.wait(1)
    return False


def main():
    _mutex_handle = None
    _pid_file = _ROOT / 'dashboard' / 'data' / 'memory_worker.pid'
    if os.name == 'nt':
        try:
            import ctypes
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            _mutex_handle = kernel32.CreateMutexW(None, False, 'Local\\BaroLabMemoryWorkerSingleton')
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                return
        except Exception:
            pass
    try:
        _pid_file.parent.mkdir(parents=True, exist_ok=True)
        _pid_file.write_text(str(os.getpid()), encoding='utf-8')
    except Exception:
        pass
    try:
        from server.mission_control import Collector
        host_collector = Collector()
        host_collector.start()
    except Exception:
        host_collector = None

    from common.hermes_memory import _store
    from common.llm_client import process_verified_work_once
    from server.project_monitor import sample_project_health_once, process_project_monitor_once, process_project_feedback_once
    from server.agent_tools import process_staff_request_once, process_staff_review_once
    from common.project_autonomy import process_project_autonomy_once
    from common.editorial_recovery import process_once as process_editorial_recovery_once
    from brunch_posting.posting import process_brunch_autonomy_once
    from naver_cafe_posting.posting import process_cafe_autonomy_once
    from youtube_posting.posting import process_youtube_autonomy_once
    from agents.crew_reasoning import resume_ceo_once, resume_background_once
    from common.work_agenda import process_once as process_agendas
    from dashboard.agents.synapse import refresh_once
    from dashboard.agents.style_strategy import review_once
    from common.conference_dispatch import process_once as process_conferences
    from common.work_agenda import admit_ready_once as admit_ready_work

    stopped = threading.Event()
    loaded_sources = {str(p.relative_to(_ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (_ROOT/'dashboard/server/memory_worker.py',
                                _ROOT/'dashboard/common/work_agenda.py',
                                _ROOT/'dashboard/agents/crew_reasoning.py',
                                _ROOT/'dashboard/common/operating_plan.py',
                                _ROOT/'dashboard/common/channel_parameters.py',
                                _ROOT/'dashboard/common/conference_dispatch.py',
                                _ROOT/'dashboard/common/naver_ab.py',
                                _ROOT/'dashboard/common/asset_map.py',
                                _ROOT/'dashboard/agents/agent_tools.py',
                                _ROOT/'dashboard/common/staff_capabilities.py',
                                _ROOT/'dashboard/common/project_autonomy.py',
                                _ROOT/'dashboard/common/ego_executor.py',
                                _ROOT/'dashboard/common/collection_observability.py',
                                _ROOT/'dashboard/common/editorial_recovery.py',
                                _ROOT/'dashboard/common/llm_usage.py',
                                _ROOT/'dashboard/common/hermes_memory.py',
                                _ROOT/'cf_posting/posting.py',
                                _ROOT/'naver_blog_posting/posting.py',
                                _ROOT/'dashboard/common/naver_download_workflow.py',
                                _ROOT/'dashboard/common/naver_reader.py',
                                _ROOT/'brunch_posting/posting.py',
                                _ROOT/'naver_cafe_posting/posting.py',
                                _ROOT/'youtube_posting/posting.py')}
    progress = {}
    outcomes = {}
    def mark(name, action):
        progress[name] = {'at': time.monotonic(), 'action': action}
    def watchdog():
        from common.collection_observability import write
        from common.runtime_recovery import host_resource_snapshot
        path = Path.home() / '.barolab/project-monitor/worker-health.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        while not stopped.wait(30):
            stalled = stalled_actions(progress, time.monotonic())
            active = has_active_jobs() if stalled else False
            try:
                resources=host_resource_snapshot()
                if os.name=='nt':write(_ROOT/'dashboard/data/host-resources.json',resources)
                write(path, {'checkedAt': time.time(), 'actions': dict(progress),
                             'hostResources':resources,
                             'stalled': stalled, 'activeJobsPreserved': active,
                             'pid': os.getpid(), 'sourceHashes': loaded_sources, 'outcomes':dict(outcomes)})
            except OSError:
                logging.exception('Worker heartbeat persistence unavailable')
            # A PID-bound graceful reload drains active actions and their leases.
            # No child, browser or uncertain publication is killed or replayed.
            try:
                request = json.loads((_ROOT/'dashboard/data/memory-worker-control.json').read_text(encoding='utf-8'))
                if request.get('action') == 'stop-after-current-actions' and request.get('pid') == os.getpid():
                    stopped.set()
                    return
            except (OSError, ValueError, TypeError):
                pass
            if stalled and not active:
                logging.error('Recovering stalled supervisor actions: %s', stalled)
                os._exit(75)  # systemd restarts only this process; uncertain requests stay fenced.
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    def memory_busy(exc):
        from common.collection_observability import write,load
        write(Path.home()/'.barolab/project-monitor/worker-health.json',{
            'checkedAt':time.time(),'pid':os.getpid(),'sourceHashes':loaded_sources,
            'stalled':['memory-initialization'],'actions':{},'outcomes':{'memory':{'status':'waiting','reason':type(exc).__name__}}})
        request=load(_ROOT/'dashboard/data/memory-worker-control.json')
        if request.get('pid')==os.getpid() and request.get('action')=='stop-after-current-actions':stopped.set()
    if not initialize_memory(_store,stopped,memory_busy):return
    _store.resume_reviews()
    def loop(actions, interval):
        while not stopped.is_set():
            for action in actions:
                if stopped.is_set():
                    break
                try:
                    mark(threading.current_thread().name, action.__name__)
                    result=action()
                    outcomes[threading.current_thread().name] = {**action_outcome(result),
                        'checkedAt':time.time(),'actionName':action.__name__}
                except Exception as exc:
                    outcomes[threading.current_thread().name] = {**action_outcome(error=exc),
                        'checkedAt':time.time(),'actionName':action.__name__}
                    logging.exception('Worker action failed: %s', action.__name__)
                finally:
                    mark(threading.current_thread().name, 'idle')
            stopped.wait(interval)

    # Observation remains responsive while bounded model calls or learning run.
    def resume_company_manager():
        from agents.crew_reasoning import resume_once
        return resume_once('manager')

    observers = [
        threading.Thread(target=loop, args=([resume_company_manager], 5), name='company-manager'),
        threading.Thread(target=loop, args=([sample_project_health_once], 30), name='project-observer'),
        threading.Thread(target=loop, args=([process_project_monitor_once, process_project_feedback_once], 60), name='project-supervisor'),
        threading.Thread(target=loop, args=([refresh_once], 300), name='memory-refresh'),
        threading.Thread(target=loop, args=([process_staff_request_once], 5), name='staff-executor'),
        threading.Thread(target=loop, args=([process_staff_review_once], 5), name='staff-reviews'),
        threading.Thread(target=loop, args=([resume_ceo_once], 1), name='ceo-goals'),
        threading.Thread(target=loop, args=([process_agendas], 5), name='agenda-dispatch'),
        threading.Thread(target=loop, args=([admit_ready_work, process_conferences], 5), name='publication-dispatch'),
        threading.Thread(target=loop, args=([resume_background_once], 5), name='background-goals'),
        threading.Thread(target=loop, args=([process_project_autonomy_once], 30), name='project-autonomy'),
        threading.Thread(target=loop, args=([process_editorial_recovery_once], 15), name='editorial-recovery'),
        threading.Thread(target=loop, args=([process_brunch_autonomy_once], 600), name='brunch-autonomy'),
        threading.Thread(target=loop, args=([process_cafe_autonomy_once], 600), name='cafe-autonomy'),
        threading.Thread(target=loop, args=([process_youtube_autonomy_once], 600), name='youtube-autonomy'),
        threading.Thread(target=watchdog, name='worker-watchdog'),
    ]
    for worker in observers:
        worker.start()
    try:
        while not stopped.is_set():
            mark('main', 'memory-and-conference-cycle')
            # Restart a consumer that exited; SQLite leases retain ownership.
            _store.resume_reviews()
            try:
                review_once()
            except Exception:
                logging.exception('Style strategy discussion unavailable; existing publishing parameters preserved')
            try:
                learned = process_verified_work_once()
            except sqlite3.OperationalError:
                logging.exception('Learning database busy; retain publishing children and retry next tick')
                learned = False
            if not learned:
                mark('main', 'idle')
                stopped.wait(30)
    finally:
        stopped.set()
        for worker in observers:
            worker.join()
        _store.close()


if __name__ == '__main__':
    main()
