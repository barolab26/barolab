"""Verify and reuse a dedicated local CDP browser without changing its lifecycle."""
import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, quote

import requests
import websocket


def _deny_downloads_sync(page):
    """Prevent Chrome from saving automatic file downloads to the local Downloads folder."""
    try:
        page.on('download', lambda d: d.cancel())
    except Exception:
        pass
    try:
        cdp = page.context.new_cdp_session(page)
        for method in ('Browser.setDownloadBehavior', 'Page.setDownloadBehavior'):
            try:
                cdp.send(method, {'behavior': 'deny'})
            except Exception:
                pass
        cdp.detach()
    except Exception:
        pass


async def deny_downloads_async(page_or_context):
    """Prevent Chrome from saving automatic file downloads in async Playwright contexts/pages."""
    try:
        if hasattr(page_or_context, 'on'):
            page_or_context.on('download', lambda d: asyncio.ensure_future(d.cancel()))
    except Exception:
        pass
    try:
        context = page_or_context.context if hasattr(page_or_context, 'context') else page_or_context
        target_page = page_or_context if hasattr(page_or_context, 'context') else (context.pages[0] if getattr(context, 'pages', None) else None)
        if target_page is not None:
            cdp = await context.new_cdp_session(target_page)
            for method in ('Browser.setDownloadBehavior', 'Page.setDownloadBehavior'):
                try:
                    await cdp.send(method, {'behavior': 'deny'})
                except Exception:
                    pass
            await cdp.detach()
    except Exception:
        pass


class PageScope:
    """Own only pages created here; borrowed pages and pending drafts survive."""
    def __init__(self, on_warning=print):
        self.created = {}
        self.retained = {}
        self.acquisitions = []
        self.on_warning = on_warning

    def __enter__(self):
        return self

    def acquire(self, context, can_reuse):
        for page in list(context.pages):
            try:
                if can_reuse(page) is True:
                    _deny_downloads_sync(page)
                    self.acquisitions.append({'page': page, 'owned': self.owns(page), 'reused': True})
                    return page
            except Exception:
                continue  # An unreadable existing page is never safe to reuse.
        page = context.new_page()
        _deny_downloads_sync(page)
        self.created[id(page)] = page
        self.acquisitions.append({'page': page, 'owned': True, 'reused': False})
        return page

    def owns(self, page):
        return self.created.get(id(page)) is page

    def retain(self, page, reason='Pending draft or unverified submission'):
        if id(page) in self.created:
            self.retained[id(page)] = str(reason)

    def complete(self, page):
        self.retained.pop(id(page), None)

    def __exit__(self, exc_type, exc_value, traceback):
        for identity, page in self.created.items():
            if identity in self.retained:
                try:
                    self.on_warning('[BROWSER] Owned tab retained: ' + self.retained[identity])
                except Exception:
                    pass
                continue
            try:
                page.close()
            except Exception as error:
                try:
                    self.on_warning('[BROWSER] Owned completed tab could not close: ' + type(error).__name__)
                except Exception:
                    pass  # Cleanup logging must not replace the original failure.
        return False


@asynccontextmanager
async def flow_generation_lock(timeout=600):
    """Serialize CF/Naver submissions to the same dedicated Flow browser."""
    directory = Path.home() / '.barolab' / 'runtime'
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / 'flow-generation.lock').open('a+b')
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        if handle.seek(0, 2) == 0:
            handle.write(b'0')
            handle.flush()
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
                    raise RuntimeError('Another publishing job is using Flow; retry after its photographs finish')
                await asyncio.sleep(2)
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _local_socket(address, port):
    value = urlsplit(address)
    if value.scheme != 'ws' or value.hostname not in ('127.0.0.1', 'localhost') or value.port != port:
        raise RuntimeError('CDP websocket does not match the dedicated local port')
    return address


def _listener_owners(port, deadline):
    """Use the native socket table; NetTCPIP CIM startup can exhaust the budget."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError('Dedicated browser identity lookup exceeded its time budget')
    try:
        result = subprocess.run(['netstat.exe', '-ano', '-p', 'tcp'],
            capture_output=True, text=True, encoding='ascii', errors='replace', timeout=remaining,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Dedicated browser listener information is unavailable') from exc
    if result.returncode:
        raise RuntimeError('Dedicated browser listener information is unavailable')
    owners = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[0] != 'TCP' or fields[3] != 'LISTENING':
            continue
        host, separator, local_port = fields[1].rpartition(':')
        if not separator or local_port != str(port):
            continue
        if host not in ('127.0.0.1', '[::1]') or not fields[4].isdigit() or int(fields[4]) <= 0:
            raise RuntimeError('Dedicated browser listener must have one local process owner')
        owners.add(int(fields[4]))
    return owners


def _runtime(port, expected_exe, expected_profile, *, process_timeout=30):
    if os.name != 'nt':
        if port in (9334, 9333, 9335, 9231, 9230, 9440):
            from common.ubuntu_naver_browser import account_paths, process_identity, listener_owner
            if port == 9440:
                executable, profile = Path('/opt/google/chrome/chrome'), Path.home() / '.config/cdp_gui_9440'
            else:
                executable, profile, _ = account_paths(port)
            if Path(expected_exe) != executable or Path(expected_profile) != profile:
                raise RuntimeError('Dedicated Ubuntu account paths do not match the expected browser/profile')
            pid = process_identity(port, profile)
            if pid is None:
                raise RuntimeError(f'Dedicated Ubuntu account process missing on port {port}')
            listener_owner(port, pid)
            return {'ProcessId': pid, 'ExecutablePath': str(executable), 'ProfilePath': str(profile)}
        try:
            ver_resp = requests.get(f'http://127.0.0.1:{port}/json/version', timeout=4)
            if ver_resp.ok:
                ws_url = ver_resp.json().get('webSocketDebuggerUrl', '')
                if _local_socket(ws_url, port):
                    return {
                        'ProcessId': 0,
                        'ExecutablePath': str(expected_exe),
                        'ProfilePath': str(expected_profile),
                        'fastPath': True,
                    }
        except Exception:
            pass
        raise RuntimeError(f'Dedicated portable browser on port {port} is unavailable')
    if type(port) is not int or not 1 <= port <= 65535 or process_timeout <= 0:
        raise ValueError('Invalid dedicated browser identity lookup parameters')
    command = rf'''[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ErrorActionPreference = 'Stop'
$pids = @(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction Stop |
 Where-Object {{ $_.LocalAddress -in @('127.0.0.1', '::1') }} |
 Select-Object -ExpandProperty OwningProcess -Unique)
if ($pids.Count -ne 1) {{ throw "Expected exactly one listener on port {port}" }}
Get-CimInstance Win32_Process -Filter ("ProcessId = " + $pids[0]) |
Select-Object ProcessId,ExecutablePath,@{{Name='ProfilePath';Expression={{
 if($_.CommandLine -match '"--user-data-dir(?:=|\s+)([^"]+)"|--user-data-dir(?:=|\s+)(?:"([^"]+)"|(\S+))') {{
 if($matches[1]) {{$matches[1]}} elseif($matches[2]) {{$matches[2]}} else {{$matches[3]}}}}}}}} | ConvertTo-Json -Compress'''
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    environment = dict(os.environ, PSModulePath=str(powershell.parent / 'Modules'))
    try:
        result = subprocess.run(
            [str(powershell), '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=process_timeout, env=environment,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        try:
            ver_resp = requests.get(f'http://127.0.0.1:{port}/json/version', timeout=4)
            if ver_resp.ok:
                ws_url = ver_resp.json().get('webSocketDebuggerUrl', '')
                if _local_socket(ws_url, port):
                    return {
                        'ProcessId': 0,
                        'ExecutablePath': str(expected_exe),
                        'ProfilePath': str(expected_profile),
                        'fastPath': True,
                    }
        except Exception:
            pass
        raise RuntimeError('Dedicated browser process information is unavailable') from exc
    if result.returncode:
        raise RuntimeError('Dedicated browser process information is unavailable')
    try:
        rows = json.loads(result.stdout.strip() or '[]')
    except ValueError as exc:
        raise RuntimeError('Dedicated browser process information is malformed') from exc
    rows = [rows] if isinstance(rows, dict) else rows
    norm = lambda value: os.path.normcase(os.path.normpath(value or ''))
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or not isinstance(rows[0].get('ExecutablePath'), str) or not isinstance(rows[0].get('ProfilePath'), str)
            or norm(rows[0]['ExecutablePath']) != norm(expected_exe) or norm(rows[0]['ProfilePath']) != norm(expected_profile)):
        raise RuntimeError('CDP port is not owned by the expected dedicated browser/profile')
    return rows[0]


def _responsive(target, port, timeout=2):
    connection = None
    try:
        address = _local_socket(target['webSocketDebuggerUrl'], port)
        connection = websocket.create_connection(address, timeout=timeout, suppress_origin=True)
        connection.send(json.dumps({'id': 1, 'method': 'Page.getFrameTree'}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            connection.settimeout(max(.01, deadline - time.monotonic()))
            result = json.loads(connection.recv())
            if result.get('id') == 1:
                return bool(result.get('result', {}).get('frameTree'))
        return False
    except (websocket.WebSocketException, OSError, ValueError, KeyError):
        return False
    finally:
        if connection:
            connection.close()


def preflight(endpoint, expected_exe, expected_profile, preferred_host='flow.google.com', log=print, *, process_timeout=30):
    value = urlsplit(endpoint)
    if value.scheme != 'http' or value.hostname not in ('127.0.0.1', 'localhost') or not value.port:
        raise RuntimeError('Dedicated browser endpoint must be local HTTP with an explicit port')
    port = value.port
    runtime = _runtime(port, expected_exe, expected_profile, process_timeout=process_timeout)
    response = requests.get(endpoint.rstrip('/') + '/json/version', timeout=4)
    response.raise_for_status()
    version = response.json()
    address = _local_socket(version['webSocketDebuggerUrl'], port)
    response = requests.get(endpoint.rstrip('/') + '/json/list', timeout=4)
    response.raise_for_status()
    targets = response.json()
    pages = [target for target in targets if target.get('type') == 'page']
    with ThreadPoolExecutor(max_workers=8) as pool:
        healthy = list(pool.map(lambda target: _responsive(target, port), pages))
    blocked = [target for target, ready in zip(pages, healthy) if not ready]

    def activate(target):
        identifier = quote(target['id'], safe='')
        response = requests.get(endpoint.rstrip('/') + '/json/activate/' + identifier, timeout=4)
        response.raise_for_status()

    for target in blocked:
        activate(target)
        if not _responsive(target, port):
            raise RuntimeError('Existing browser tab remains unresponsive after activation; browser retained')
        log(f"[BROWSER] Recovered suspended tab {target['id']}; browser and login retained")
    if blocked:
        preferred = next((target for target in pages if urlsplit(target.get('url', '')).hostname == preferred_host), None)
        if preferred:
            activate(preferred)
    info = {'pid': runtime['ProcessId'], 'profile': expected_profile, 'port': port,
            'browser': version.get('Browser'), 'tabs': len(pages), 'recoveredTabs': len(blocked),
            'checkedAt': datetime.now(timezone.utc).isoformat(),
            'webSocketDebuggerUrl': address}
    log(f"[BROWSER] Reusing PID {info['pid']} / CDP {port} / {info['browser']} / {len(pages)} tabs")
    return info


async def connect_async(playwright, endpoint, expected_exe, expected_profile, log=print):
    info = await asyncio.to_thread(preflight, endpoint, expected_exe, expected_profile, 'flow.google.com', log)
    browser = await playwright.chromium.connect_over_cdp(info['webSocketDebuggerUrl'], timeout=20000, no_defaults=True)
    if browser.contexts:
        await deny_downloads_async(browser.contexts[0])
    return browser, {key: value for key, value in info.items() if key != 'webSocketDebuggerUrl'}


def connect_sync(playwright, endpoint, expected_exe, expected_profile, log=print):
    info = preflight(endpoint, expected_exe, expected_profile, log=log)
    browser = playwright.chromium.connect_over_cdp(info['webSocketDebuggerUrl'], timeout=20000, no_defaults=True)
    if browser.contexts and browser.contexts[0].pages:
        _deny_downloads_sync(browser.contexts[0].pages[0])
    return browser
