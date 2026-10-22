"""Keep the existing durable Hermes review queue consumer alive."""

import logging
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    from common.hermes_memory import _store
    from common.llm_client import process_verified_work_once
    from server.project_monitor import sample_project_health_once
    from server.agent_tools import process_staff_request_once
    from common.project_autonomy import process_project_autonomy_once
    from dashboard.agents.synapse import refresh_once

    stopped = threading.Event()
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
                    action()
                except Exception:
                    logging.exception('Worker action failed: %s', action.__name__)
            stopped.wait(interval)

    # Observation remains responsive while bounded model calls or learning run.
    observers = [
        threading.Thread(target=loop, args=([sample_project_health_once, refresh_once], 30), name='project-observer'),
        threading.Thread(target=loop, args=([process_staff_request_once], 5), name='staff-executor'),
        threading.Thread(target=loop, args=([process_project_autonomy_once], 30), name='project-autonomy'),
    ]
    for worker in observers:
        worker.start()
    try:
        while not stopped.is_set():
            # Restart a consumer that exited; SQLite leases retain ownership.
            _store.resume_reviews()
            if not process_verified_work_once():
                stopped.wait(30)
    finally:
        stopped.set()
        for worker in observers:
            worker.join()
        _store.close()


if __name__ == '__main__':
    main()
