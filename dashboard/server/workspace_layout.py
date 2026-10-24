#!/usr/bin/env python3
import os
import sys
import time
import subprocess

# Precise seamless tiling zones for 5120 x 1440 display (Top panel height = 27)
# Total screen: 5120 x 1440. Usable workarea: X 0..5120, Y 27..1440 (Height: 1413)
ZONE_LEFT   = (0, 27, 1830, 1413)       # Left Column: ARGO Control Hub
ZONE_CENTER = (3100, 27, 2020, 1413)    # Right: account browsers share the same area
ZONE_R_TOP  = (3560, 27, 1560, 930)     # Right Top: Gemini
ZONE_R_BOT  = (1830, 27, 1270, 1413)    # Middle: EGO LITE Live Monitor

CURRENT_DISPLAY = None

def detect_display():
    global CURRENT_DISPLAY
    candidates = [os.environ.get("BAROLAB_DISPLAY"), ":11", os.environ.get("DISPLAY"), ":10", ":0"]
    for disp in candidates:
        if not disp:
            continue
        env = os.environ.copy()
        env["DISPLAY"] = disp
        try:
            res = subprocess.check_output(['wmctrl', '-l'], env=env, stderr=subprocess.DEVNULL, timeout=2).decode()
            if 'xfce4-panel' in res or 'Desktop' in res:
                CURRENT_DISPLAY = disp
                return disp
        except Exception:
            continue
    CURRENT_DISPLAY = ":10"
    return CURRENT_DISPLAY

def get_env():
    disp = CURRENT_DISPLAY or detect_display()
    env = os.environ.copy()
    env["DISPLAY"] = disp
    return env

def get_frame_extents(wid, env):
    try:
        out = subprocess.check_output(['xprop', '-id', wid, '_NET_FRAME_EXTENTS'], env=env, stderr=subprocess.DEVNULL, timeout=2).decode()
        val = out.split('=', 1)[1].strip()
        parts = [int(p.strip()) for p in val.split(',')]
        return parts[0], parts[1], parts[2], parts[3]
    except Exception:
        return 0, 0, 0, 0

def snap_exact(wid, fx, fy, fw, fh, env):
    l, r, t, b = get_frame_extents(wid, env)
    cw = max(100, fw - (l + r))
    ch = max(50, fh - (t + b))
    
    subprocess.run(['wmctrl', '-i', '-r', wid, '-b', 'remove,maximized_vert,maximized_horz'], env=env, stderr=subprocess.DEVNULL)
    subprocess.run(['wmctrl', '-ir', wid, '-e', f'0,{fx},{fy},{cw},{ch}'],
                   env=env, stderr=subprocess.DEVNULL, check=True, timeout=2)


def get_window_props(wid, env):
    try:
        out = subprocess.check_output(['xprop', '-id', wid, 'WM_CLASS', 'WM_WINDOW_ROLE'], env=env, stderr=subprocess.DEVNULL, timeout=2).decode()
    except Exception:
        return "", ""
    wm_class = ""
    wm_role = ""
    for line in out.splitlines():
        if 'WM_CLASS' in line:
            wm_class = line.split('=', 1)[-1].strip()
        elif 'WM_WINDOW_ROLE' in line:
            wm_role = line.split('=', 1)[-1].strip()
    return wm_class, wm_role

WINDOW_ORDER = (
    ('dashboard', '01 Dashboard', ZONE_LEFT),
    ('ego', '02 EGO LITE', ZONE_R_BOT),
    ('soultin', '03 soultin · 개인 1', ZONE_CENTER),
    ('soul5373', '04 soul5373 · 개인 2', ZONE_CENTER),
    ('yoon_master', '05 yoon_master · 개인 3', ZONE_CENTER),
    ('adinfo0905', '06 adinfo0905 · 비실명 1', ZONE_CENTER),
    ('stone0747', '07 stone0747 · 비실명 2', ZONE_CENTER),
    ('cf-flow', '08 CF Flow', ZONE_CENTER),
    ('threads', '09 Threads', ZONE_CENTER),
)


def window_identity(title, wm_class):
    identity = wm_class.lower()
    if 'localhost' in identity or 'barolab-dashboard' in identity:
        return WINDOW_ORDER[0]
    if 'xfce4-terminal' in identity and 'ego' in title.lower():
        return WINDOW_ORDER[1]
    for row in WINDOW_ORDER[2:]:
        key = 'cdp_gui_9440' if row[0] == 'cf-flow' else row[0]
        if key in identity or ('cf-flow' == row[0] and 'barolab-cf-flow' in identity):
            return row
    return None


def classify_and_position(wid, title, env, position=True):
    wm_class, wm_role = get_window_props(wid, env)
    if 'browser' not in wm_role.lower() and 'dialog' in wm_role.lower():
        return None
    row = window_identity(title, wm_class)
    if row is None:
        return None
    key, label, zone = row
    if title != label:
        subprocess.run(['wmctrl', '-ir', wid, '-T', label], env=env,
                       check=True, timeout=2)
    if position:
        snap_exact(wid, *zone, env)
    return key


def process_windows(known_windows, force_all=False):
    env = get_env()
    try:
        out = subprocess.check_output(['wmctrl', '-l'], env=env, stderr=subprocess.DEVNULL, timeout=2).decode()
    except Exception:
        detect_display()
        return

    current_wids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        wid = parts[0]
        current_wids.add(wid)
        title = ' '.join(parts[3:])

        role = classify_and_position(wid, title, env,
                                     position=force_all or wid not in known_windows)
        if role:
            known_windows[wid] = role

    closed = set(known_windows.keys()) - current_wids
    for wid in closed:
        known_windows.pop(wid, None)

def main():
    disp = detect_display()
    force_once = '--once' in sys.argv or '--snap' in sys.argv
    known_windows = {}

    print(f"[*] Seamless Layout Keeper active on DISPLAY={disp}", flush=True)

    if force_once:
        process_windows(known_windows, force_all=True)
        print("[*] Snap complete.")
        return

    while True:
        try:
            process_windows(known_windows, force_all=False)
        except Exception as e:
            print(f"[!] Error in loop: {e}", flush=True)
        time.sleep(1.0)

if __name__ == '__main__':
    main()
