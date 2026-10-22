# -*- coding: utf-8 -*-
"""
CLI entrypoint for Doctor Content Auditor (`python common/content_auditor.py --run-once`).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVER_DIR = ROOT / "server"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from server.content_auditor import (
    get_auditor_status,
    run_patrol_batch,
    scan_and_register_fake_ai_image_posts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="BaroLab Content Doctor CLI")
    parser.add_argument("--run-once", action="store_true", help="Run one immediate audit & repair batch")
    parser.add_argument("--count", type=int, default=5, help="Number of posts to audit")
    parser.add_argument("--domain", default=None, help="Optional target domain")
    parser.add_argument("--scan-fake-images", action="store_true", help="Also scan and strip fake card images")
    args = parser.parse_args()

    if args.scan_fake_images:
        scan_res = scan_and_register_fake_ai_image_posts()
        print(f"[Doctor] Fake image scan: {json.dumps(scan_res, ensure_ascii=False)}", flush=True)

    res = run_patrol_batch(count=max(1, min(20, args.count)), target_domain=args.domain, broadcast_to_chat=True)
    st = get_auditor_status()
    summary = {
        "ok": True,
        "auditedNow": res.get("auditedCount", 0),
        "totalAudited": st.get("auditedCount", 0),
        "totalInventory": st.get("totalInventory", 1984),
        "gradeCounts": st.get("gradeCounts", {}),
        "categoryPatchedCount": st.get("categoryPatchedCount", 0),
        "remodelQueueCount": st.get("remodelQueueCount", 0),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
