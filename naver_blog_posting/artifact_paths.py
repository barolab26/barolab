"""Read relocated evidence only for explicitly known project output roots."""
from pathlib import Path, PureWindowsPath
import hashlib
import json


def resolve_artifact_folder(value, account, base):
    """Return an existing account-contained folder, or None if uninspectable."""
    if not isinstance(value, str) or not value or account not in (
            'soultin', 'soul5373', 'yoon_master', 'adinfo0905', 'stone0747'):
        return None
    output = (Path(base) / 'output' / account).resolve()
    candidate = Path(value)
    native = candidate.resolve()
    if native.is_relative_to(output) and native != output and native.is_dir():
        return native
    windows = PureWindowsPath(value)
    relocated = False
    if windows.is_absolute():
        prefixes = (
            PureWindowsPath(r'\\otns\yoonlab\10_Project\BaroLab\naver_blog_posting\output'),
            PureWindowsPath(r'C:\10_Project\BaroLab\naver_blog_posting\output'),
        )
        for prefix in prefixes:
            try:
                suffix = windows.relative_to(prefix)
            except ValueError:
                continue
            if len(suffix.parts) < 2 or suffix.parts[0] != account or '..' in suffix.parts:
                return None
            candidate = Path(base) / 'output' / Path(*suffix.parts)
            relocated = True
            break
        else:
            return None
    candidate = candidate.resolve()
    if candidate.is_relative_to(output) and candidate != output and candidate.is_dir():
        if relocated:
            try:
                manifest = json.loads((candidate / 'migration-evidence.json').read_text(encoding='utf-8-sig'))
                files = manifest['files']
                if (manifest.get('schema') != 'naver-evidence-migration-v1'
                        or PureWindowsPath(manifest['source']) != windows
                        or not isinstance(files, dict) or 'reservation-evidence.json' not in files):
                    return None
                for name, digest in files.items():
                    if Path(name).name != name or '\\' in name or name in ('.', '..'):
                        return None
                    evidence = (candidate / name).resolve()
                    if not evidence.is_relative_to(candidate):
                        return None
                    if hashlib.sha256(evidence.read_bytes()).hexdigest() != digest:
                        return None
            except (OSError, ValueError, KeyError, TypeError):
                return None
        return candidate
    return None
