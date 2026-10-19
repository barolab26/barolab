"""Persistent manual installation confirmations; never Google opt-in evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
INITIAL_INSTALLED = {'baro76650@gmail.com', 'barolab26@gmail.com'}
_THREAD_LOCK = threading.RLock()
_LOCAL_FIELDS = {'accounts', 'localTracking', 'installationInitializedAt',
                 'installationHistory', 'removedAccounts', 'nextAccountSlot', 'revision', 'contractVersion',
                 'consoleEvidence', 'consoleEvidenceCheckedAt', 'consoleEvidenceSource'}


class RevisionConflict(ValueError):
    pass


def normalize_emails(raw):
    tokens = re.split(r'[\s,;]+', raw) if isinstance(raw, str) else raw if isinstance(raw, list) else []
    result = []
    for item in tokens:
        if isinstance(item, str):
            for token in re.split(r'[\s,;]+', item):
                email = token.strip().lower()
                if re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', email) and email not in result:
                    result.append(email)
    return result[:30]


def _path():
    return ROOT / 'server/data/app_testers.json'


def _now(value=None):
    value = value or datetime.now(KST)
    if value.tzinfo is None:
        raise ValueError('Timezone-aware timestamp required')
    return value.astimezone(KST)


@contextmanager
def _locked():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK:
        with path.with_suffix('.json.lock').open('a+b') as handle:
            if handle.seek(0, 2) == 0:
                handle.write(b'0'); handle.flush()
            acquired = False
            deadline = time.monotonic() + 5
            try:
                while not acquired:
                    handle.seek(0)
                    try:
                        if os.name == 'nt':
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Tester ledger busy')
                        time.sleep(.05)
                yield
            finally:
                if acquired:
                    handle.seek(0)
                    if os.name == 'nt':
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read():
    for path in (_path(), ROOT / 'data/app_testers.json'):
        if path.exists():
            # Corrupt canonical data must fail visibly, never fall back and reset.
            value = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(value, dict):
                raise ValueError('Invalid tester ledger')
            return value
    return {'emails': [], 'apps': {}, 'syncStatus': 'roster_unavailable'}


def _write(doc):
    path = _path()
    fd, tmp = tempfile.mkstemp(prefix='app-testers-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(doc, stream, ensure_ascii=False, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _tracking(doc, now):
    tracking = doc.setdefault('localTracking', {})
    count = sum(row.get('installed') is True for row in doc['accounts'])
    started = tracking.get('startedAt')
    if count < 12 and started:
        tracking.setdefault('history', []).append({'type': 'continuity_reset', 'startedAt': started,
            'endedAt': now.isoformat(), 'installedCount': count, 'reason': 'below_12_manual_confirmations'})
        started = None
    elif count >= 12 and not started:
        started = now.isoformat()
        tracking.setdefault('history', []).append({'type': 'local_period_started', 'startedAt': started,
                                                  'installedCount': count})
    elapsed = 0
    day = 0
    completion = None
    status = 'waiting_for_12'
    if started:
        start = datetime.fromisoformat(started).astimezone(KST)
        elapsed = max(0, (now - start).total_seconds())
        day = min(14, max(1, (now.date() - start.date()).days + 1))
        completion = (start + timedelta(days=14)).isoformat()
        status = 'local_14_days_elapsed' if elapsed >= 14 * 86400 else 'tracking'
    tracking.update(installedCount=count, requiredCount=12, requiredDays=14, startedAt=started,
                    dayNumber=day, elapsedDays=int(elapsed // 86400), completionAt=completion,
                    status=status, scope='manual_installation_confirmation', timezone='Asia/Seoul',
                    googleQualificationVerified=False)
    tracking.setdefault('history', [])


def _prepare(doc, now):
    doc['emails'] = normalize_emails(doc.get('emails', []))
    doc['emailCount'] = len(doc['emails'])
    first = not doc.get('installationInitializedAt')
    existing = {row['email']: row for row in doc.get('accounts', []) if isinstance(row, dict) and row.get('email')}
    next_slot = max([doc.get('nextAccountSlot', 1)] + [int(row.get('slot', 0))+1 for row in existing.values()])
    rows = []
    for email in doc['emails']:
        row = existing.pop(email, None)
        if row is None:
            installed = first and email in INITIAL_INSTALLED
            row = {'id': 'tester-' + hashlib.sha256(email.encode()).hexdigest()[:16],
                   'slot': next_slot, 'email': email, 'installed': installed,
                   'installedAt': now.isoformat() if installed else None,
                   'installationScope': 'all_four_apps',
                   'installationSource': 'user_explicit_initial_confirmation' if installed else None}
            next_slot += 1
        rows.append(row)
    if existing:
        doc.setdefault('removedAccounts', []).extend({**row, 'removedAt': now.isoformat()} for row in existing.values())
    doc.update(accounts=rows, nextAccountSlot=next_slot, contractVersion='tester-installations-v1')
    doc.setdefault('revision', 0)
    doc.setdefault('installationInitializedAt', now.isoformat())
    doc.setdefault('installationHistory', [])
    doc.setdefault('requiredClosedTesters', 12)
    doc.setdefault('requiredClosedDays', 14)
    _tracking(doc, now)
    return doc


def load_app_testers(*, now=None):
    with _locked():
        original = _read()
        doc = _prepare(copy.deepcopy(original), _now(now))
        # Derived day counters need not rewrite storage on every GET. Migration
        # and roster reconciliation do persist exactly once.
        meaningful = ('accounts', 'installationInitializedAt', 'removedAccounts', 'nextAccountSlot')
        if any(doc.get(k) != original.get(k) for k in meaningful):
            doc['revision'] += 1
            _write(doc)
        return doc


def save_app_testers(incoming, *, now=None):
    """Legacy/automator merge: a stale save cannot overwrite checkbox state."""
    with _locked():
        when = _now(now)
        current = _prepare(_read(), when)
        for key, value in incoming.items():
            if key in _LOCAL_FIELDS or key in ('playConsoleStatus', 'consoleEvidence'):
                continue
            if key == 'apps' and isinstance(value, dict):
                for app, fields in value.items():
                    current.setdefault('apps', {}).setdefault(app, {}).update(copy.deepcopy(fields))
            else:
                current[key] = copy.deepcopy(value)
        current = _prepare(current, when)
        current['revision'] += 1
        current['lastSavedAt'] = when.isoformat()
        _write(current)
        return current


def patch_installation(account_id, installed, *, expected_revision=None, now=None):
    if type(installed) is not bool:
        raise ValueError('installed must be a boolean')
    with _locked():
        when = _now(now)
        doc = _prepare(_read(), when)
        if expected_revision is not None and expected_revision != doc['revision']:
            raise RevisionConflict('Tester ledger changed; reload before updating')
        row = next((x for x in doc['accounts'] if x['id'] == account_id), None)
        if row is None:
            raise KeyError('Unknown tester account')
        if row['installed'] is installed:
            return doc
        event = {'accountId': account_id, 'installed': installed, 'at': when.isoformat(),
                 'previousInstalledAt': row.get('installedAt'), 'scope': 'all_four_apps'}
        row.update(installed=installed, installedAt=when.isoformat() if installed else None,
                   installationSource='user_checkbox_confirmation')
        doc['installationHistory'].append(event)
        _tracking(doc, when)
        doc['revision'] += 1
        doc['lastSavedAt'] = when.isoformat()
        _write(doc)
        return doc


def save_console_evidence(snapshot):
    """Collector-only merge; successful per-app observations never change installs."""
    allowed_apps = {'bible_app', 'greeting', 'magnifier', 'shopping'}
    observations = {}
    for app, observed in snapshot.get('apps', {}).items():
        if app not in allowed_apps or observed.get('status') != 'collected':
            continue
        when = datetime.fromisoformat(observed['checkedAt'].replace('Z', '+00:00'))
        if when.tzinfo is None:
            raise ValueError('Console observation timezone required')
        for key in ('googleOptInCount', 'googleInstallCount', 'continuousTestDays'):
            value = observed.get(key)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('Explicit nonnegative Console measurement required')
        observations[app] = {key: copy.deepcopy(observed.get(key)) for key in
            ('status', 'checkedAt', 'lastAttemptAt', 'stale', 'alpha', 'internal',
             'googleOptInCount', 'googleInstallCount', 'continuousTestDays', 'evidence')}
    if not observations:
        return {'saved': False, 'apps': 0}
    with _locked():
        doc = _prepare(_read(), _now())
        before = copy.deepcopy(doc)
        evidence = doc.setdefault('consoleEvidence', {})
        for app, observed in observations.items():
            old = evidence.get(app, {}).get('checkedAt')
            if old and datetime.fromisoformat(old.replace('Z', '+00:00')) > datetime.fromisoformat(observed['checkedAt'].replace('Z', '+00:00')):
                continue
            evidence[app] = observed
        doc['consoleEvidenceCheckedAt'] = max(x['checkedAt'] for x in evidence.values())
        doc['consoleEvidenceSource'] = 'server/data/play-console-status.json; verified rendered Play Console UI'
        if doc != before:
            _write(doc)
        return {'saved': doc != before, 'apps': len(observations), 'revision': doc['revision']}
