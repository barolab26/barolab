"""Bounded growth work dispatched by the existing EGO Lite runner."""
import datetime
import os
from pathlib import Path
import sys
import threading
import time

EXEC_KILL_SWITCH = Path.home() / 'EGO_EXEC_DISABLED'


def growth_cycle():
    """Reuse the maintenance journal, collection receipts and publication locks."""
    from common import content_maintenance as maintenance
    from dashboard.metrics import collector_lock
    from dashboard.server.worker import run_metrics
    config = maintenance.state()
    if EXEC_KILL_SWITCH.exists() or not config["policy"]["enabled"]:
        return {"status": "paused", "dailyTargetUsd": 100}
    with collector_lock(maintenance.DATA / "ego-growth.lock") as acquired:
        if not acquired:
            return {"status": "already_running", "dailyTargetUsd": 100}
        previous = config["runtime"].get("egoLastCycleAt")
        interval = datetime.timedelta(minutes=max(30, config["policy"]["cycleIntervalMinutes"]))
        if previous:
            try:
                elapsed = maintenance.now() - datetime.datetime.fromisoformat(previous)
                if elapsed < interval:
                    return {"status": "waiting", "dailyTargetUsd": 100,
                            "nextCycleAt": (datetime.datetime.fromisoformat(previous) + interval).isoformat()}
            except (ValueError, TypeError):
                return {"status": "blocked", "reason": "Invalid cycle timestamp", "dailyTargetUsd": 100}
        maintenance.runtime(egoLastCycleAt=maintenance.stamp(), launcher="ego_lite",
                            egoPid=os.getpid(), dailyTargetUsd=100)
        # Collection owns its existing lock and distinguishes process success from source coverage.
        metrics = maintenance.read(maintenance.DATA / "metrics-runtime.json")
        collected = metrics.get("finishedAt")
        try:
            completed = {stage.get("script") for stage in metrics.get("stages", [])
                         if stage.get("status") == "completed"}
            required = {"dashboard/revenue.py", "dashboard/traffic.py"}
            traffic = maintenance.read(maintenance.DATA / "traffic.json").get("growthCollection", {})
            interval_hours = 6 if traffic.get("status") == "completed" else 0.5
            fresh = (required <= completed and collected
                     and datetime.timedelta(0) <= maintenance.now() - datetime.datetime.fromisoformat(collected)
                     < datetime.timedelta(hours=interval_hours))
        except (ValueError, TypeError):
            fresh = False
        if not fresh:
            run_metrics(sys.executable, [("dashboard/revenue.py", "--collect"),
                                         ("dashboard/traffic.py", "--collect")])
        if EXEC_KILL_SWITCH.exists():
            return {"status": "paused", "dailyTargetUsd": 100}
        result = maintenance.run_once()
        return {"status": result.get("runtime", {}).get("status", "unknown"),
                "reason": result.get("runtime", {}).get("reason"),
                "dailyTargetUsd": 100, "checkedAt": maintenance.stamp(),
                "maintenance": result.get("growth", {}),
                "sourceStatus": maintenance.read(maintenance.DATA / "metrics-runtime.json").get("collectionStatus", "unknown")}



def growth_worker():
    from common import content_maintenance as maintenance
    from dashboard.metrics import collector_lock
    with collector_lock(maintenance.DATA / 'ego-growth-loop.lock') as acquired:
        if not acquired:
            return
        while True:
            try:
                result = growth_cycle()
            except Exception as exc:
                result = {'status': 'failed', 'reason': type(exc).__name__, 'dailyTargetUsd': 100}
            try:
                maintenance.runtime(egoStatus=result)
            except Exception as exc:
                print(f"[GROWTH] Could not persist cycle status: {type(exc).__name__}", flush=True)
            time.sleep(60)


def start_worker():
    threading.Thread(target=growth_worker, daemon=True, name='ego-growth').start()
