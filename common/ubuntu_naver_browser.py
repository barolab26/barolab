"""Install dedicated Ubuntu account launchers and open manual Naver login."""
import argparse
import ast
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
LOGIN_URL = "https://nid.naver.com/nidlogin.login"


def accounts():
    tree = ast.parse((ROOT / "naver_blog_posting/pipeline_runner.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ACCOUNT_MAP" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError("ACCOUNT_MAP missing")


def process_identity(port, profile, proc=Path("/proc")):
    """Match the main Chrome process to the exact port and profile."""
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
    result = subprocess.run(["ss", "-ltnp", f"sport = :{port}"], capture_output=True, text=True, check=True)
    rows = result.stdout.splitlines()[1:]
    if len(rows) != 1 or f"pid={pid}," not in rows[0]:
        raise RuntimeError(f"Cannot verify listener ownership for port {port}")
    if rows[0].split()[3] not in (f"127.0.0.1:{port}", f"[::1]:{port}"):
        raise RuntimeError(f"CDP port {port} is not loopback-only")


def account_paths(port):
    if port==9440:
        return Path('/opt/google/chrome/chrome'),Path.home()/'.config/cdp_gui_9440',None
    account = next((key for key, value in accounts().items() if value["cdp_port"] == port), None)
    if account is None:
        raise ValueError("Unknown Naver account port")
    home = Path.home()
    return (Path("/opt/google/chrome/chrome"), home / ".config" / f"cdp_naver_{account}",
            home / ".barolab/browsers" / account / f"{account}_start_cdp.sh")


def ensure_account(port):
    """Reuse the verified account, or invoke only its installed start script."""
    _, profile, script = account_paths(port)
    pid = process_identity(port, profile)
    if pid is None:
        if port==9440:
            profile.mkdir(parents=True,exist_ok=True)
            subprocess.Popen(['/opt/google/chrome/chrome',f'--remote-debugging-port={port}',f'--user-data-dir={profile}',
                '--remote-debugging-address=127.0.0.1','--no-first-run','--no-default-browser-check','https://flow.google.com'],
                env=dict(os.environ,DISPLAY=os.environ.get('BAROLAB_DISPLAY',':10')),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            for _ in range(100):
                time.sleep(.2);pid=process_identity(port,profile)
                if pid:break
        elif not script.is_file():
            raise RuntimeError(f"Dedicated Ubuntu account launcher missing: {script}")
        else:subprocess.run([str(script)], check=True, timeout=35, stdout=subprocess.DEVNULL)
        pid = process_identity(port, profile)
    if pid is None:
        raise RuntimeError(f"Dedicated Ubuntu account process missing on port {port}")
    listener_owner(port, pid)
    gc_blank_tabs(port)
    return pid


def focus_workflow_window(port):
    """Focus only the verified existing workflow browser; never start or navigate."""
    from common.browser_session import _runtime
    if port == 9440:
        executable, profile = Path("/opt/google/chrome/chrome"), Path.home() / ".config/cdp_gui_9440"
    else:
        executable, profile, _ = account_paths(port)
    pid = _runtime(port, str(executable), str(profile))["ProcessId"]
    environment = dict(os.environ, DISPLAY=os.environ.get("BAROLAB_DISPLAY", ":10"))
    windows = subprocess.run(["wmctrl", "-lp"], env=environment, capture_output=True,
                             text=True, check=True, timeout=5)
    for line in windows.stdout.splitlines():
        fields = line.split(None, 4)
        if len(fields) >= 3 and fields[2] == str(pid):
            subprocess.run(["wmctrl", "-ia", fields[0]], env=environment, check=True, timeout=5)
            return
    raise RuntimeError(f"Verified browser window is not visible on DISPLAY for port {port}")


def install(home=Path.home()):
    runtime = home / ".barolab/browsers"
    for account, config in accounts().items():
        directory = runtime / account
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
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
    pid = process_identity(port, profile)
    reused = pid is not None
    if not reused:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Port {port} is occupied by an unverified process")
        # Set the visible Chrome profile name only before a new profile is created.
        preferences = profile / "Default/Preferences"
        if not preferences.exists():
            preferences.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            preferences.write_text(json.dumps({"profile": {"name": f"BaroLab · {account}"}}), encoding="utf-8")
            preferences.chmod(0o600)
        environment = dict(os.environ, DISPLAY=os.environ.get("BAROLAB_DISPLAY", ":10"))
        with (runtime / "chrome.log").open("ab") as log:
            subprocess.Popen([
                "/usr/bin/google-chrome", f"--user-data-dir={profile}",
                f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
                f"--class=BaroLab-{account}", "--no-first-run", "--no-default-browser-check",
                "--new-window", LOGIN_URL,
            ], env=environment, stdout=log, stderr=log, start_new_session=True)
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
    with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as response:
        version = json.load(response)
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
        tabs = json.load(response)
    if not version.get("Browser", "").startswith("Chrome/"):
        raise RuntimeError("Unexpected CDP browser")
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
        "profile": str(profile), "reused": reused, "owned": not reused,
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
    if sys.platform != "linux":
        parser.error("Run in Ubuntu")
    if args.install:
        print(install())
    else:
        import fcntl
        directory = Path.home() / ".barolab/browsers" / args.account
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (directory / "launch.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            launch(args.account)


def gc_blank_tabs(port):
    """Close only empty, unfocused blank tabs; login/editor/search tabs are preserved."""
    import requests
    import websocket
    try:
        response=requests.get(f'http://127.0.0.1:{port}/json/list',timeout=.3)
        tabs=[t for t in response.json() if t.get('type')=='page']
        if not any(t.get('url') not in ('about:blank','chrome://newtab/','') for t in tabs):return 0
        closed=0
        for tab in tabs:
            if tab.get('url')!='about:blank':continue
            address=tab.get('webSocketDebuggerUrl','')
            from urllib.parse import urlsplit,quote
            u=urlsplit(address)
            if u.scheme!='ws' or u.hostname not in ('127.0.0.1','localhost') or u.port!=port:continue
            ws=None
            try:
                ws=websocket.create_connection(address,timeout=.3,suppress_origin=True)
                ws.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{'expression':"location.href === 'about:blank' && !document.hasFocus() && (!document.body || document.body.innerHTML.trim() === '')",'returnByValue':True}}))
                result=json.loads(ws.recv())
                if result.get('id')==1 and result.get('result',{}).get('result',{}).get('value') is True:
                    reply=requests.get(f"http://127.0.0.1:{port}/json/close/"+quote(tab['id'],safe=''),timeout=.3)
                    closed+=int(reply.status_code==200)
            except (OSError,ValueError,websocket.WebSocketException):pass
            finally:
                if ws:ws.close()
        return closed
    except (requests.RequestException,ValueError,TypeError):return 0
