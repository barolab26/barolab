"""
Real-time bridge allowing background pipelines (`cf_posting`, `naver_blog_posting`, `growth.py`)
to broadcast live agent collaboration messages and in-place task status updates into the
BaroLab Meeting Room (`server/chat_room.py` & `dashboard/chat.html`).
"""

import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
ROOM_MAIN_FILE = BASE_DIR / "server" / "data" / "chats" / "room-main.json"


def emit_pipeline_crew_message(
    who: str,
    text: str,
    handoff: Optional[str] = None,
    status: str = "completed",
    step: str = "",
    result_summary: str = "",
    deliverable_url: str = "",
    deliverable_label: str = "",
    synapse_linked: bool = False,
    synapse_label: str = "",
    msg_id: Optional[str] = None,
) -> Optional[str]:
    """
    Send a live autonomous crew message or in-place status update to the meeting room server.
    Never raises an exception so pipelines are never blocked.
    """
    ts = int(time.time() * 1000)
    mid = msg_id or f"auto-{ts}-{who}"
    payload: Dict[str, Any] = {
        "id": mid,
        "who": who,
        "text": text,
        "ts": ts,
        "autonomous": True,
        "taskTracker": {
            "handoff": handoff or "",
            "status": status,
            "step": step,
            "resultSummary": result_summary or step,
            "deliverableUrl": deliverable_url,
            "deliverableLabel": deliverable_label,
            "synapseLinked": synapse_linked,
            "synapseLabel": synapse_label or ("🧠 기억 그래프에 새 노하우 연결됨" if synapse_linked else ""),
        },
    }

    for port in (8791, 8790):
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/chat/autonomous/event",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=0.9) as resp:
                if resp.status == 200:
                    return mid
        except Exception:
            continue

    # Fallback: append directly to room-main.json if HTTP server is not listening on loopback
    try:
        if ROOM_MAIN_FILE.is_file():
            room = json.loads(ROOM_MAIN_FILE.read_text(encoding="utf-8"))
            if isinstance(room, dict):
                msgs = room.setdefault("messages", [])
                existing = next((m for m in msgs if m.get("id") == mid), None)
                if existing:
                    existing.update(payload)
                else:
                    msgs.append(payload)
                tmp = ROOM_MAIN_FILE.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(room, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(ROOM_MAIN_FILE)
                return mid
    except Exception:
        pass
    return None
