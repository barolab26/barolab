# -*- coding: utf-8 -*-
"""
CLI Scheduler wrapper for CF Posting (`python cf_posting/scheduler.py --tick`).
Delegates to `cf_posting/pipeline_runner.py --catch-up-once`.
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT = BASE_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from cf_posting.pipeline_runner import catch_up_once


def main() -> int:
    parser = argparse.ArgumentParser(description="CF Posting Scheduler CLI")
    parser.add_argument("--tick", action="store_true", help="Run one catch-up tick")
    parser.add_argument("--catch-up-once", action="store_true", help="Alias for --tick")
    parser.parse_known_args()
    catch_up_once()
    return 0


if __name__ == "__main__":
    sys.exit(main())
