"""Keep the existing durable Hermes review queue consumer alive."""

import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def has_active_jobs(proc=Path('/proc'), parent=None):
    """Preserve every non-browser descendant before recovering this supervisor."""
    parent = os.getpid() if parent is None else parent
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


def main():
    from common.hermes_memory import _store
    from common.llm_client import process_verified_work_once
    from server.project_monitor import sample_project_health_once, process_project_monitor_once, process_project_feedback_once
    from server.agent_tools import process_staff_request_once
    from common.project_autonomy import process_project_autonomy_once
    from agents.crew_reasoning import resume_ceo_once, resume_background_once
    from common.work_agenda import process_once as process_agendas
    from dashboard.agents.synapse import refresh_once
    from dashboard.agents.style_strategy import review_once
    from common.conference_dispatch import process_once as process_conferences

    stopped = threading.Event()
    progress = {}
    def mark(name, action):
        progress[name] = {'at': time.monotonic(), 'action': action}
    def watchdog():
        from common.collection_observability import write
        path = Path.home() / '.barolab/project-monitor/worker-health.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        while not stopped.wait(30):
            stalled = stalled_actions(progress, time.monotonic())
            active = has_active_jobs() if stalled else False
            try:
                write(path, {'checkedAt': time.time(), 'actions': dict(progress),
                             'stalled': stalled, 'activeJobsPreserved': active})
            except OSError:
                logging.exception('Worker heartbeat persistence unavailable')
            if stalled and not active:
                logging.error('Recovering stalled supervisor actions: %s', stalled)
                os._exit(75)  # systemd restarts only this process; uncertain requests stay fenced.
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    _store.initialize()
    _store.resume_reviews()
    def loop(actions, interval):
        while not stopped.is_set():
            for action in actions:
                if stopped.is_set():
                    break
                try:
                    mark(threading.current_thread().name, action.__name__)
                    action()
                except Exception:
                    logging.exception('Worker action failed: %s', action.__name__)
                finally:
                    mark(threading.current_thread().name, 'idle')
            stopped.wait(interval)

    # Observation remains responsive while bounded model calls or learning run.
    observers = [
        threading.Thread(target=loop, args=([sample_project_health_once], 30), name='project-observer'),
        threading.Thread(target=loop, args=([process_project_monitor_once, process_project_feedback_once], 60), name='project-supervisor'),
        threading.Thread(target=loop, args=([refresh_once], 300), name='memory-refresh'),
        threading.Thread(target=loop, args=([process_staff_request_once], 5), name='staff-executor'),
        threading.Thread(target=loop, args=([resume_ceo_once], 1), name='ceo-goals'),
        threading.Thread(target=loop, args=([process_agendas, resume_background_once], 5), name='background-goals'),
        threading.Thread(target=loop, args=([process_project_autonomy_once], 30), name='project-autonomy'),
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
                process_conferences()
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
