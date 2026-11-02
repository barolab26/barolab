"""Install dedicated Ubuntu/Windows EGO LITE account launchers and open manual Naver login."""
import argparse
import ast
import json
import os
import re
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
LOGIN_URL = "https://nid.naver.com/nidlogin.login"
# Google and Naver logins were consolidated into this existing Chrome profile on Linux.
PROFILE_DIRECTORIES = {} if os.name == "nt" else {"soultin": "Profile 1"}
EGO_EXE = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Citro Labs/ego lite/Application/ego.exe"
EGO_SOURCE_PROFILES = {
    "soultin": ("Profile 3", 38),
    "soul5373": ("Profile 4", 39),
    "yoon_master": ("Profile 5", 41),
    "adinfo0905": ("Profile 6", 36),
    "stone0747": ("Profile 7", 37),
    "cf-flow": ("Profile 3", 38),
    "threads": ("Profile 3", 38),
}
_WIN_PID_CACHE = {}


def browser_executable():
    return EGO_EXE if os.name == "nt" else Path("/opt/google/chrome/chrome")


def _win_pid_alive(pid):
    if not pid or os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == 259
        return False
    finally:
        kernel32.CloseHandle(handle)


def _win_port_listening_pid(port):
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    res = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True,
                         encoding="ascii", errors="ignore", timeout=5, creationflags=cflags)
    rows = []
    for line in (res.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            local_addr = parts[1]
            if local_addr.endswith(f":{port}"):
                rows.append((local_addr, int(parts[4])))
    return rows


def accounts():
    tree = ast.parse((ROOT / "naver_blog_posting/posting.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ACCOUNT_MAP" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError("ACCOUNT_MAP missing")


def process_identity(port, profile, proc=Path("/proc")):
    """Match the main Chrome / EGO LITE process to the exact port and profile."""
    if os.name == "nt" and proc == Path("/proc"):
        expected_profile = str(Path(profile).resolve()).lower()
        expected_exe = str(EGO_EXE.resolve()).lower()
        cache_key = (int(port), expected_profile)
        cached_pid = _WIN_PID_CACHE.get(cache_key)
        if cached_pid and _win_pid_alive(cached_pid):
            listeners = _win_port_listening_pid(port)
            if len(listeners) == 1 and listeners[0][1] == cached_pid:
                return cached_pid
        ps = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        cmd = (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            f"Get-CimInstance Win32_Process -Filter \"Name = 'ego.exe' AND CommandLine LIKE '%--remote-debugging-port={int(port)}%'\" "
            "| Select-Object ProcessId, ExecutablePath, CommandLine | ConvertTo-Json -Compress"
        )
        cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run([str(ps), "-NoProfile", "-NonInteractive", "-Command", cmd],
                             capture_output=True, text=True, encoding="utf-8", timeout=10, creationflags=cflags)
        raw_out = (res.stdout or "").strip()
        if not raw_out:
            return None
        try:
            items = json.loads(raw_out)
            if isinstance(items, dict):
                items = [items]
        except ValueError:
            return None
        matches = []
        for item in items or []:
            cmdline = str(item.get("CommandLine") or "")
            if "--type=" in cmdline:
                continue
            if f"--remote-debugging-port={port}" not in cmdline:
                continue
            m = re.search(r'--user-data-dir=(?:"([^"]+)"|(\S+))', cmdline)
            actual_profile = str(Path(m.group(1) or m.group(2)).resolve()).lower() if m else ""
            if actual_profile != expected_profile:
                raise RuntimeError(f"Port {port} belongs to a different Chrome profile")
            exe_path = str(Path(item.get("ExecutablePath") or "").resolve()).lower()
            if exe_path != expected_exe:
                raise RuntimeError(f"Unexpected executable on port {port}")
            matches.append(int(item["ProcessId"]))
        if len(matches) > 1:
            raise RuntimeError(f"Multiple Chrome owners for port {port}")
        if matches:
            _WIN_PID_CACHE[cache_key] = matches[0]
            return matches[0]
        return None

    matches = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
            if f"--remote-debugging-port={port}".encode() not in raw:
                continue
            args = [part.decode() for part in raw.split(b"\0") if part]
            # Chrome can rewrite argv into one space-separated process title.
            if len(args) == 1:
                args = shlex.split(args[0])
            if f"--remote-debugging-port={port}" not in args:
                continue
            if any(arg.startswith("--type=") for arg in args):
                continue
            if f"--user-data-dir={profile}" not in args:
                raise RuntimeError(f"Port {port} belongs to a different Chrome profile")
            executable = (entry / "exe").resolve()
            if executable != Path("/opt/google/chrome/chrome"):
                raise RuntimeError(f"Unexpected executable on port {port}")
            matches.append(int(entry.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    if len(matches) > 1:
        raise RuntimeError(f"Multiple Chrome owners for port {port}")
    return matches[0] if matches else None


def listener_owner(port, pid):
    if os.name == "nt":
        rows = _win_port_listening_pid(port)
        if len(rows) != 1 or rows[0][1] != int(pid):
            raise RuntimeError(f"Cannot verify listener ownership for port {port}")
        if rows[0][0] not in (f"127.0.0.1:{port}", f"[::1]:{port}"):
            raise RuntimeError(f"CDP port {port} is not loopback-only")
        return
    result = subprocess.run(["ss", "-ltnp", f"sport = :{port}"], capture_output=True, text=True, check=True)
    rows = result.stdout.splitlines()[1:]
    if len(rows) != 1 or f"pid={pid}," not in rows[0]:
        raise RuntimeError(f"Cannot verify listener ownership for port {port}")
    if rows[0].split()[3] not in (f"127.0.0.1:{port}", f"[::1]:{port}"):
        raise RuntimeError(f"CDP port {port} is not loopback-only")


def account_paths(port):
    exe = browser_executable()
    if port==9440:
        return exe,Path.home()/'.config/cdp_gui_9440',None
    if port==9450:
        return exe,Path.home()/'.config/cdp_threads_mustpickinfo',None
    account = "soultin" if port == 9226 else next((key for key, value in accounts().items() if value["cdp_port"] == port), None)
    if account is None:
        raise ValueError("Unknown Naver account port")
    home = Path.home()
    ext = "cmd" if os.name == "nt" else "sh"
    return (exe, home / ".config" / f"cdp_naver_{account}",
            home / ".barolab/browsers" / account / f"{account}_start_cdp.{ext}")


def _ensure_win_page_tab(port, default_url="https://www.naver.com"):
    if os.name != "nt":
        return
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as resp:
            tabs = json.load(resp)
        if any(t.get("type") == "page" for t in tabs):
            return
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as resp:
            ver = json.load(resp)
        import websocket
        bws = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=5, suppress_origin=True)
        try:
            bws.send(json.dumps({"id": 1, "method": "Target.createTarget", "params": {"url": default_url}}))
            bws.recv()
        finally:
            bws.close()
        time.sleep(0.5)
    except Exception:
        pass


def _ensure_ego_user_data_ready(profile_dir):
    """Ensure EGO LITE user-data-dir has ego_config.json so it never triggers first-run onboarding."""
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    cfg = profile_dir / "ego_config.json"
    if not cfg.exists():
        cfg.write_text('{\n   "not_first_run": true\n}\n', encoding="utf-8")
    fr = profile_dir / "First Run"
    if not fr.exists():
        fr.write_text("", encoding="utf-8")


def _find_ego_cli():
    candidate = Path.home() / ".local/share/ego/active_version_dir/ego-browser.exe"
    if candidate.is_file():
        return candidate
    return next((Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Citro Labs/ego lite/Application").glob("*/ego-browser.exe"), None)


def sync_cookies_from_ego_profile(port, account_key):
    """Seed cookies from the main Windows EGO LITE profile into the dedicated CDP instance and ensure its EGO TaskSpace is open."""
    if os.name != "nt" or account_key not in EGO_SOURCE_PROFILES:
        return False
    _, profile, _ = account_paths(port)
    marker = profile / ".ego_cookies_synced"
    accs = accounts()
    default_url = (
        "https://labs.google/fx/ko/tools/flow" if account_key == "cf-flow"
        else ("https://www.threads.com/@mustpickinfo" if account_key == "threads"
              else ("https://kin.naver.com" if account_key in ("adinfo0905", "stone0747")
                    else f"https://blog.naver.com/{accs.get(account_key, {}).get('blog_id', '')}"))
    )
    _ensure_win_page_tab(port, default_url)
    import websocket
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as resp:
            tabs = [t for t in json.load(resp) if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        if not tabs:
            return False
        ws_url = tabs[0]["webSocketDebuggerUrl"]
        cur_tab_url = str(tabs[0].get("url") or "")
        ws = websocket.create_connection(ws_url, timeout=5, suppress_origin=True)
        try:
            ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
            current = json.loads(ws.recv()).get("result", {}).get("cookies", [])
            if cur_tab_url in ("about:blank", "chrome://newtab/", "chrome://new-tab-page/", ""):
                ws.send(json.dumps({"id": 9, "method": "Page.navigate", "params": {"url": default_url}}))
                ws.recv()
        finally:
            ws.close()
        has_naver = any("naver" in c.get("domain", "") and c.get("name") == "NID_AUT" for c in current)
        has_google = any("google" in c.get("domain", "") and c.get("name") in ("SID", "__Secure-1PSID") for c in current)
        has_threads = any(("threads" in c.get("domain", "") or "instagram" in c.get("domain", "")) and c.get("name") == "sessionid" for c in current)
        marker_fresh = False
        if marker.exists():
            try:
                marker_fresh = (time.time() - float(marker.read_text(encoding="utf-8").strip())) < 21600
            except Exception:
                marker_fresh = False
        if account_key == "cf-flow" and has_google and marker_fresh:
            return True
        if account_key == "threads" and has_threads and marker_fresh:
            return True
        if account_key not in ("cf-flow", "threads") and has_naver and marker_fresh:
            return True

        from common.ego_taskspace import extract_profile_cookies, inject_profile_cookies
        cookies = extract_profile_cookies(
            account_key,
            default_url=default_url,
            include_default_profile=(account_key in ("cf-flow", "threads")),
        )
        ego_has_naver = any("naver" in c.get("domain", "") and c.get("name") == "NID_AUT" for c in (cookies or []))
        if account_key not in ("cf-flow", "threads") and has_naver and not ego_has_naver:
            naver_cookies = [c for c in current if "naver" in c.get("domain", "")]
            inject_profile_cookies(account_key, naver_cookies, default_url=default_url)
            marker.write_text(str(int(time.time())), encoding="utf-8")
            return True
        if not cookies:
            return False
        clean_cookies = []
        for c in cookies:
            item = {k: c[k] for k in ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires", "priority", "sameParty", "sourceScheme", "sourcePort") if k in c and c[k] is not None}
            if item.get("expires", -1) <= 0:
                item.pop("expires", None)
            clean_cookies.append(item)
        ws = websocket.create_connection(ws_url, timeout=5, suppress_origin=True)
        try:
            ws.send(json.dumps({"id": 2, "method": "Network.setCookies", "params": {"cookies": clean_cookies}}))
            ws.recv()
            ws.send(json.dumps({"id": 3, "method": "Page.navigate", "params": {"url": default_url}}))
            ws.recv()
        finally:
            ws.close()
        marker.write_text(str(int(time.time())), encoding="utf-8")
        return True
    except Exception:
        return False


def ensure_account(port):
    """Reuse the verified account, or invoke its launcher / EGO LITE CDP instance."""
    exe, profile, script = account_paths(port)
    _ensure_ego_user_data_ready(profile)
    pid = process_identity(port, profile)
    if pid is None:
        if port in (9440,9450):
            profile.mkdir(parents=True,exist_ok=True)
            cmd_args = [str(exe),f'--remote-debugging-port={port}',f'--user-data-dir={profile}',
                '--remote-debugging-address=127.0.0.1',
                *([f'--ego-server-name=barolab-{port}', '--window-position=-32000,-32000', '--window-size=1280,900'] if os.name == 'nt' else ['--restore-last-session']),
                '--class=BaroLab-Threads' if port==9450 else '--class=BaroLab-CF-Flow',
                '--profile-directory=Default',
                '--no-first-run','--no-default-browser-check',
                *(['https://www.threads.com/@mustpickinfo' if port==9450 else 'https://labs.google/fx/ko/tools/flow']
                  if not (profile/'Default/Preferences').exists() else [])]
            _spawn_ego_on_user_desktop(cmd_args, env=dict(os.environ,DISPLAY=os.environ.get('BAROLAB_DISPLAY',':10')))
            for _ in range(100):
                time.sleep(.2);pid=process_identity(port,profile)
                if pid:
                    try:listener_owner(port,pid)
                    except RuntimeError:continue
                    break
            if pid and os.name == "nt":
                _win_hide_from_taskbar(pid)
                sync_cookies_from_ego_profile(port, "threads" if port == 9450 else "cf-flow")
        elif os.name == "nt":
            account = "soultin" if port == 9226 else next((k for k, v in accounts().items() if v["cdp_port"] == port), None)
            if not account:
                raise RuntimeError(f"Unknown account for port {port}")
            launch(account)
        elif not script.is_file():
            raise RuntimeError(f"Dedicated Ubuntu account launcher missing: {script}")
        else:subprocess.run([str(script)], check=True, timeout=35, stdout=subprocess.DEVNULL)
        pid = process_identity(port, profile)
    if pid is None:
        raise RuntimeError(f"Dedicated Ubuntu account process missing on port {port}")
    listener_owner(port, pid)
    if os.name == "nt":
        account_key = "cf-flow" if port == 9440 else ("threads" if port == 9450 else ("soultin" if port == 9226 else next((k for k, v in accounts().items() if v["cdp_port"] == port), None)))
        if account_key:
            sync_cookies_from_ego_profile(port, account_key)
    gc_blank_tabs(port)
    if os.name == "nt":
        _win_hide_from_taskbar(pid)
    return pid


def close_account(port):
    """Close temporary port-bound browser worker on Windows after an on-demand slot finishes."""
    if os.name != "nt":
        return False
    try:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
                ver = json.load(resp)
            import websocket
            ws = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=2, suppress_origin=True)
            try:
                ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
            finally:
                ws.close()
            time.sleep(0.3)
        except Exception:
            pass
        _, profile, _ = account_paths(port)
        pid = process_identity(port, profile)
        if pid:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
    except Exception:
        pass
    return False


def _win_find_browser_hwnds(pid):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, lparam):
        win_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
        if win_pid.value == int(pid):
            cls_buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls_buf, 64)
            if cls_buf.value.startswith("Chrome_WidgetWin_"):
                found.append(int(hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return found


def _win_find_browser_hwnd(pid):
    hwnds = _win_find_browser_hwnds(pid)
    return hwnds[0] if hwnds else None


def _win_hide_from_taskbar(pid):
    """Hide temporary port-bound CDP worker windows from the Windows Taskbar while keeping the single main EGO Lite window clean."""
    if os.name != "nt" or not pid:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        for hwnd in _win_find_browser_hwnds(pid):
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.ShowWindow(hwnd, 0)  # SW_HIDE removes taskbar button immediately
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (ex_style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
            user32.SetWindowPos(hwnd, 0, -32000, -32000, 1280, 900, 0x0010 | 0x0004 | 0x0020)
    except Exception:
        pass


def _spawn_ego_on_user_desktop(cmd_args, env=None, log_path=None):
    """Spawn EGO LITE directly via Popen without blocking the ego_cli bootstrap pipe."""
    if os.name == "nt" and "--start-minimized" not in cmd_args:
        cmd_args = [cmd_args[0], "--start-minimized", *cmd_args[1:]]
    if log_path:
        with Path(log_path).open("ab") as log:
            subprocess.Popen(cmd_args, env=env, stdout=log, stderr=log, start_new_session=(os.name != "nt"))
    else:
        subprocess.Popen(cmd_args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=(os.name != "nt"))
    return True


def inspect_workflow_window(port):
    """Read the verified browser's window mapping without focusing, starting or navigating."""
    if port == 9440:
        executable, profile = browser_executable(), Path.home() / ".config/cdp_gui_9440"
    else:
        executable, profile, _ = account_paths(port)
    if os.name == "nt":
        pid = process_identity(port, profile)
        hwnd = _win_find_browser_hwnd(pid) if pid else None
        return {'status':'observed','port':port,'browserPid':pid or 0,'display':'windows',
                'windowId':f'0x{hwnd:08x}' if hwnd else f'0x{int(pid or 0):08x}','wmPid':int(pid or 0),'mapped':True,'attemptedDisplays':['windows'],'browserStarted':False}
    from common.browser_session import _runtime
    pid = _runtime(port, str(executable), str(profile))["ProcessId"]
    display=os.environ.get('BAROLAB_DISPLAY')
    if not display:
        try:
            display=next((item.split('=',1)[1] for item in (Path('/proc')/str(pid)/'environ').read_bytes().decode().split('\0') if item.startswith('DISPLAY=')),None)
        except (OSError,UnicodeError):
            pass
    displays=[display] if display else [':10']
    # Chrome can rewrite its environment; locate its verified PID on existing X servers.
    if not display:
        displays.extend(':'+p.name[1:] for p in sorted(Path('/tmp/.X11-unix').glob('X*'))[:16] if re.fullmatch(r'X\d+',p.name))
        displays.extend(':'+p.name[2:-5] for p in sorted(Path('/tmp').glob('.X*-lock'))[:16] if re.fullmatch(r'\.X\d+-lock',p.name))
    attempted=[]
    for candidate in dict.fromkeys(displays):
        if not re.fullmatch(r':\d+(?:\.\d+)?',candidate):raise RuntimeError('Expected local workflow DISPLAY')
        attempted.append(candidate)
        environment = dict(os.environ, DISPLAY=candidate)
        try:
            windows = subprocess.run(["wmctrl", "-lp"], env=environment, capture_output=True,
                                     text=True, check=True, timeout=5)
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
            continue
        for line in windows.stdout.splitlines():
            fields = line.split(None, 4)
            if len(fields) >= 3 and fields[2] == str(pid) and re.fullmatch(r'0x[0-9a-fA-F]+',fields[0]):
                return {'status':'observed','port':port,'browserPid':pid,'display':candidate,
                        'windowId':fields[0],'wmPid':int(fields[2]),'mapped':None,'attemptedDisplays':attempted,'browserStarted':False}
    return {'status':'not_found','port':port,'browserPid':pid,'display':None,'windowId':None,
            'wmPid':None,'mapped':None,'attemptedDisplays':attempted,'browserStarted':False}


def focus_workflow_window(port, *, steal_os_focus=False):
    """Activate the workflow browser tab internally without stealing OS desktop focus on Windows."""
    dismiss_stuck_dialogs()
    window=inspect_workflow_window(port)
    if window['status']=='observed':
        if os.name == 'nt' and window.get('display') == 'windows':
            if steal_os_focus:
                try:
                    import ctypes
                    user32 = ctypes.windll.user32
                    hwnd = _win_find_browser_hwnd(window.get('browserPid'))
                    if hwnd:
                        if user32.IsIconic(hwnd):
                            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        user32.SetForegroundWindow(hwnd)
                except Exception:
                    pass
            try:
                with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as resp:
                    tabs = [t for t in json.load(resp) if t.get("type") == "page" and t.get("id")]
                if tabs:
                    urlopen(f"http://127.0.0.1:{port}/json/activate/{tabs[0]['id']}", timeout=2).read()
            except Exception:
                pass
            return
        subprocess.run(['wmctrl','-ia',window['windowId']],env=dict(os.environ,DISPLAY=window['display']),check=True,timeout=5)
        return
    raise RuntimeError(f"Verified browser window is not visible on DISPLAY for port {port}")


def install(home=Path.home()):
    runtime = home / ".barolab/browsers"
    for account, config in accounts().items():
        directory = runtime / account
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        if os.name == "nt":
            script = directory / f"{account}_start_cdp.cmd"
            script.write_text(f'@echo off\r\n"{sys.executable}" "{Path(__file__).resolve()}" --account {account}\r\n', encoding="utf-8")
        else:
            script = directory / f"{account}_start_cdp.sh"
            command = [sys.executable, str(Path(__file__).resolve()), "--account", account]
            script.write_text("#!/bin/sh\nset -eu\nexec " + shlex.join(command) + "\n", encoding="utf-8")
            script.chmod(0o700)
    return runtime


def launch(account):
    config = accounts()[account]
    port = config["cdp_port"]
    profile = Path.home() / ".config" / f"cdp_naver_{account}"
    runtime = Path.home() / ".barolab/browsers" / account
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)
    _ensure_ego_user_data_ready(profile)
    pid = process_identity(port, profile)
    reused = pid is not None
    profile_directory = PROFILE_DIRECTORIES.get(account, "Default")
    if not reused:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Port {port} is occupied by an unverified process")
        # Set the visible Chrome profile name only before a new profile is created.
        preferences = profile / profile_directory / "Preferences"
        fresh_profile = not preferences.exists()
        if fresh_profile:
            preferences.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            preferences.write_text(json.dumps({"profile": {"name": f"BaroLab · {account}"}, "session": {"restore_on_startup": 1}}), encoding="utf-8")
            preferences.chmod(0o600)
        environment = dict(os.environ, DISPLAY=os.environ.get("BAROLAB_DISPLAY", ":10"))
        exe = str(browser_executable()) if os.name == "nt" else "/usr/bin/google-chrome"
        start_url = "https://www.naver.com" if (os.name == "nt" and fresh_profile) else (LOGIN_URL if fresh_profile else None)
        cmd_args = [
            exe, f"--user-data-dir={profile}",
            f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
            *([f"--ego-server-name=barolab-{port}", "--window-position=-32000,-32000", "--window-size=1280,900"] if os.name == "nt" else ["--restore-last-session"]),
            f"--class=BaroLab-{account}", f"--profile-directory={profile_directory}",
            "--no-first-run", "--no-default-browser-check",
            *([start_url] if start_url else []),
        ]
        _spawn_ego_on_user_desktop(cmd_args, env=environment, log_path=(runtime / "chrome.log"))
        for _ in range(100):
            time.sleep(0.2)
            try:
                pid = process_identity(port, profile)
                if pid:
                    listener_owner(port, pid)
                    break
            except RuntimeError:
                continue
        else:
            raise RuntimeError(f"Chrome did not expose verified CDP for {account}; see {runtime / 'chrome.log'}")
    listener_owner(port, pid)
    if os.name == "nt":
        sync_cookies_from_ego_profile(port, account)
    with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as response:
        version = json.load(response)
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
        tabs = json.load(response)
    if not version.get("Browser", "").startswith("Chrome/"):
        raise RuntimeError("Unexpected CDP browser")
    if os.name == "nt":
        hwnd = _win_find_browser_hwnd(pid)
        if hwnd:
            import ctypes
            ctypes.windll.user32.SetWindowTextW(hwnd, f"BaroLab | {account} | {config['blog_id']} | EGO LITE")
            ctypes.windll.user32.SetWindowPos(hwnd, 0, -32000, -32000, 1280, 900, 0x0010 | 0x0004)
        _win_hide_from_taskbar(pid)
    else:
        environment = dict(os.environ, DISPLAY=os.environ.get("BAROLAB_DISPLAY", ":10"))
        windows = subprocess.run(["wmctrl", "-lp"], env=environment, capture_output=True, text=True, check=True)
        for line in windows.stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 3 and parts[2] == str(pid):
                subprocess.run(["wmctrl", "-ir", parts[0], "-T",
                                f"BaroLab | {account} | {config['blog_id']} | Naver login"],
                               env=environment, check=True)
    receipt = {
        "account": account, "blogId": config["blog_id"], "port": port, "pid": pid,
        "profile": str(profile), "profileDirectory": profile_directory,
        "sessionPolicy": "persistent_profile_tabs", "reused": reused, "owned": not reused,
        "tabCount": sum(tab.get("type") == "page" for tab in tabs),
        "manualLoginRequired": "not_verified",
        "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (runtime / "launch-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--install", action="store_true")
    selection.add_argument("--account", choices=tuple(accounts()))
    args = parser.parse_args()
    if args.install:
        print(install())
    else:
        from common import runtime_locks as fcntl
        directory = Path.home() / ".barolab/browsers" / args.account
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (directory / "launch.lock").open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            launch(args.account)


def gc_blank_tabs(port):
    """Close empty unfocused blank tabs and prune stale benchmark/search tabs on port 9440; active/login/editor tabs are preserved."""
    import requests
    import websocket
    from urllib.parse import urlsplit, quote
    try:
        response=requests.get(f'http://127.0.0.1:{port}/json/list',timeout=.5)
        tabs=[t for t in response.json() if t.get('type')=='page']
        if len(tabs)<=1:return 0
        closed=0
        for tab in tabs:
            if len(tabs)-closed<=1:break
            url=str(tab.get('url') or '')
            is_blank=url in ('about:blank','chrome://newtab/','')
            is_stale_bench=(port==9440 and ('search.naver.com/search.naver' in url or 'blog.naver.com/' in url) and 'PostWrite' not in url)
            if not is_blank and not is_stale_bench:continue
            address=tab.get('webSocketDebuggerUrl','')
            u=urlsplit(address)
            if u.scheme!='ws' or u.hostname not in ('127.0.0.1','localhost') or u.port!=port:continue
            ws=None
            try:
                ws=websocket.create_connection(address,timeout=.3,suppress_origin=True)
                expr=("!document.hasFocus() && document.visibilityState !== 'visible'" if is_stale_bench
                      else "(location.href === 'about:blank' || location.href.startsWith('chrome://newtab')) && !document.hasFocus()")
                ws.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{'expression':expr,'returnByValue':True}}))
                result=json.loads(ws.recv())
                if result.get('id')==1 and result.get('result',{}).get('result',{}).get('value') is True:
                    reply=requests.get(f"http://127.0.0.1:{port}/json/close/"+quote(tab['id'],safe=''),timeout=.3)
                    closed+=int(reply.status_code==200)
            except (OSError,ValueError,websocket.WebSocketException):pass
            finally:
                if ws:ws.close()
        return closed
    except (requests.RequestException,ValueError,TypeError):return 0


def dismiss_stuck_dialogs(display=None):
    """Detect and close any blocking OS dialogs like 'Open Files' on the workflow DISPLAY."""
    if os.name == "nt" and display is None:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        closed = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    cls_buf = ctypes.create_unicode_buffer(64)
                    user32.GetClassNameW(hwnd, cls_buf, 64)
                    if cls_buf.value == "#32770" and any(t in title for t in ("Open Files", "파일 선택", "열기", "File Upload")):
                        user32.PostMessageW(hwnd, 0x0010, 0, 0)
                        closed.append(("windows", f"0x{int(hwnd):08x}", title))
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)
        return closed
    displays = [display] if display else [os.environ.get('BAROLAB_DISPLAY'), ':11', ':10']
    closed = []
    for cand in dict.fromkeys(d for d in displays if d):
        try:
            res = subprocess.run(["wmctrl", "-l"], env=dict(os.environ, DISPLAY=cand),
                                 capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if any(t in line for t in ('Open Files', '파일 선택', '열기', 'File Upload')):
                        win_id = line.split()[0]
                        subprocess.run(["wmctrl", "-ic", win_id], env=dict(os.environ, DISPLAY=cand), timeout=2)
                        closed.append((cand, win_id, line))
        except Exception:
            pass
    return closed
