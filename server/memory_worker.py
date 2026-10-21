"""Keep the existing durable Hermes review queue consumer alive."""

import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    from common.hermes_memory import _store
    from common.llm_client import process_verified_work_once
    from common.repair_workflow import process_repair_diagnosis_once

    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    _store.initialize()
    _store.resume_reviews()
    try:
        while not stopped.is_set():
            # Restart a consumer that exited; SQLite leases retain ownership.
            _store.resume_reviews()
            diagnosed = process_repair_diagnosis_once()
            if not process_verified_work_once() and not diagnosed:
                stopped.wait(30)
    finally:
        _store.close()


if __name__ == '__main__':
    main()
