"""Summarize historical routing records without inferring current failures."""
import json
from pathlib import Path


def read_routing_summary(ledger_path):
    ledger_path = Path(ledger_path)
    recent_ledger = []
    if ledger_path.is_file():
        try:
            lines = [ln.strip() for ln in ledger_path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
            for ln in lines[-20:]:
                try:
                    record = json.loads(ln)
                    if isinstance(record, dict):
                        recent_ledger.append(record)
                except (ValueError, TypeError):
                    pass
        except OSError:
            pass

    counts = {"success": 0, "invalid": 0, "failed": 0, "unknown": 0}
    for record in recent_ledger:
        status = record.get("status")
        if status in ("ok", "success", "returned", "completed"):
            counts["success"] += 1
        elif status == "invalid":
            counts["invalid"] += 1
        elif status == "failed":
            counts["failed"] += 1
        elif status is None and record.get("ok") is True:
            counts["success"] += 1
        else:
            counts["unknown"] += 1

    times = [record.get("time_utc") for record in recent_ledger]
    providers = sorted({record["provider"] for record in recent_ledger
                        if isinstance(record.get("provider"), str) and record["provider"].strip()})
    return {
        "total": len(recent_ledger),
        **counts,
        "countUnit": "records",
        "sourcePeriod": {
            "first": times[0] if times and isinstance(times[0], str) and times[0].strip() else None,
            "last": times[-1] if times and isinstance(times[-1], str) and times[-1].strip() else None,
        },
        "providers": providers,
        "currentFailureCount": None,
    }


def format_routing_summary(lg):
    period = lg.get("sourcePeriod") or {}
    first = period.get("first")
    last = period.get("last")
    period_text = f"기간 {first} ~ {last}" if first and last else "시점 미상"
    providers = ", ".join(lg.get("providers") or []) or "미상"
    observation = "" if lg["total"] else " / 과거 기록 미관측"
    return (
        f"3. .agent-routing/ledger.jsonl 최근 20줄 범위의 과거 기록 {lg['total']}건 "
        f"({period_text}, 제공자: {providers}): 성공 {lg['success']}건 / "
        f"invalid {lg.get('invalid', 0)}건 / failed {lg['failed']}건 / "
        f"unknown {lg.get('unknown', 0)}건 / 현재 실패 미관측 / 원인 미상{observation}"
    )
