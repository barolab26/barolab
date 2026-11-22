"""Lightweight standard-library-only Naver blog execution-owner gate."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def legacy_naver_submission_allowed(root=None) -> bool:
    root_dir = Path(root) if root is not None else ROOT
    marker = root_dir / 'dashboard/data/naver/execution-owner.json'
    try:
        raw = marker.read_text(encoding='utf-8')
    except FileNotFoundError:
        return True
    except Exception:
        return False
    try:
        data = json.loads(raw)
    except Exception:
        return False
    return (
        isinstance(data, dict)
        and data.get('schema') == 'naver-execution-owner-v1'
        and data.get('legacy_submission_enabled') is True
    )


def require_legacy_naver_submission_allowed(root=None) -> None:
    if not legacy_naver_submission_allowed(root):
        raise RuntimeError('Legacy Naver blog submission is disabled by execution-owner.json')
