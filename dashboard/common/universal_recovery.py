"""Universal autonomous obstacle clearer, circuit breaker, and self-healing engine.

Prevents hardcoded whack-a-mole fixes and infinite loops by:
1. Universal Obstacle Clearing (OS dialogs via X11 wmctrl + ESC key cascade + generic DOM backdrop buster)
2. 2-Strike Circuit Breaker (stops blind repetitive loops, resets sessions to clean state)
3. Autonomous Diagnosis (inspects DOM/OS blockers before retrying, self-heals without human intervention)
"""

import json
import logging
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'dashboard/data'
CIRCUIT_STATE_FILE = DATA / 'circuit_breaker.json'

logger = logging.getLogger('universal_recovery')


def clear_x11_modal_dialogs(display=None):
    """Detect and close any blocking OS dialogs like 'Open Files', '열기', 'Alert'."""
    displays = [display] if display else [os.environ.get('BAROLAB_DISPLAY'), ':11', ':10', ':0']
    closed = []
    for cand in dict.fromkeys(d for d in displays if d):
        try:
            res = subprocess.run(
                ["wmctrl", "-lp"],
                env=dict(os.environ, DISPLAY=cand),
                capture_output=True,
                text=True,
                timeout=3
            )
            if res.returncode != 0:
                continue

            for line in res.stdout.splitlines():
                parts = line.split(None, 4)
                if len(parts) < 5:
                    continue
                win_id, desktop, pid, client_machine, title = parts[0], parts[1], parts[2], parts[3], parts[4]
                # Identify file dialogs, alerts, or modal popups
                title_lower = title.lower()
                is_stuck_dialog = any(token in title_lower for token in (
                    'open files', 'open file', 'select file', '파일 선택', '열기',
                    'save as', '다른 이름으로 저장', 'confirm', 'alert'
                ))
                if is_stuck_dialog:
                    subprocess.run(
                        ["wmctrl", "-ic", win_id],
                        env=dict(os.environ, DISPLAY=cand),
                        timeout=2
                    )
                    closed.append({'windowId': win_id, 'title': title, 'display': cand, 'pid': pid})
        except Exception:
            pass
    return closed


def clear_dom_blocking_overlays(frame_or_page):
    """Universal DOM modal and backdrop buster.
    
    Finds overlays/modals blocking mouse interaction and dismisses or removes them.
    Never relies on specific account or template class names.
    """
    js_buster = """() => {
        const results = [];
        // 1. Common modal/backdrop/overlay patterns
        const overlaySelectors = [
            '[aria-modal="true"]',
            '[role="dialog"]',
            '[role="alertdialog"]',
            '.modal', '.modal-backdrop',
            '.dim', '.dimmed', '.backdrop',
            'div[class*="popup"]',
            'div[class*="layer"]',
            'div[class*="modal"]',
            'div[class*="overlay"]'
        ];
        
        const candidateElements = new Set();
        overlaySelectors.forEach(sel => {
            try {
                document.querySelectorAll(sel).forEach(el => candidateElements.add(el));
            } catch(e) {}
        });

        // 2. High z-index fixed/absolute elements covering a large portion of the viewport
        document.querySelectorAll('div').forEach(el => {
            try {
                const style = window.getComputedStyle(el);
                const z = parseInt(style.zIndex, 10);
                if ((style.position === 'fixed' || style.position === 'absolute') && z >= 100) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 200 && rect.height > 150) {
                        candidateElements.add(el);
                    }
                }
            } catch(e) {}
        });

        // 3. Action on candidate overlays: try clicking close/cancel buttons first, then hide
        for (const el of candidateElements) {
            if (!el || el.offsetWidth === 0 || el.offsetHeight === 0) continue;
            
            let handled = false;
            // Look for generic close buttons
            const closeBtn = el.querySelector(
                'button[aria-label*="닫기"], button[aria-label*="close"], button[aria-label*="Close"], ' +
                'button.close, [class*="close"], [class*="btn_close"], [class*="btnClose"], ' +
                'button:has-text("닫기"), button:has-text("취소"), a:has-text("닫기"), a:has-text("취소")'
            );
            
            if (closeBtn && closeBtn.offsetWidth > 0) {
                try {
                    closeBtn.click();
                    results.push({ action: 'clicked_close_button', text: closeBtn.innerText.slice(0, 30) });
                    handled = true;
                } catch(e) {}
            }
            
            // If still visible and blocking after click attempt, neutralize pointer events
            if (!handled) {
                try {
                    el.style.setProperty('display', 'none', 'important');
                    el.style.setProperty('pointer-events', 'none', 'important');
                    results.push({ action: 'neutralized_overlay_style', tag: el.tagName, className: el.className });
                } catch(e) {}
            }
        }
        return results;
    }"""
    try:
        return frame_or_page.evaluate(js_buster)
    except Exception:
        return []


def clear_all_obstacles(page=None, frame=None, port=None):
    """Executes the full Universal Obstacle Clearer cascade."""
    report = {'osDialogsClosed': [], 'escapePressed': False, 'domOverlaysNeutralized': []}

    # Step 1: OS-level modal window clearance
    report['osDialogsClosed'] = clear_x11_modal_dialogs()

    # Step 2: Global Escape key cascade (dismisses active popovers/tooltips)
    if page:
        try:
            for _ in range(3):
                page.keyboard.press('Escape')
                time.sleep(0.05)
            report['escapePressed'] = True
        except Exception:
            pass

    # Step 3: DOM-level overlay and modal buster
    targets = [t for t in (frame, page) if t is not None]
    for target in targets:
        actions = clear_dom_blocking_overlays(target)
        if actions:
            report['domOverlaysNeutralized'].extend(actions)

    return report


# --- Circuit Breaker & State Recovery ---

def _load_circuit_state():
    if CIRCUIT_STATE_FILE.exists():
        try:
            return json.loads(CIRCUIT_STATE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {'failures': {}}


def _save_circuit_state(state):
    CIRCUIT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = CIRCUIT_STATE_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(CIRCUIT_STATE_FILE)


class CircuitBreaker:
    """Tracks consecutive action failures and enforces session reset instead of infinite loops."""

    @classmethod
    def record_failure(cls, key, error_msg):
        state = _load_circuit_state()
        entry = state['failures'].setdefault(key, {'count': 0, 'firstFailedAt': time.time(), 'errors': []})
        entry['count'] += 1
        entry['lastFailedAt'] = time.time()
        entry['errors'].append(str(error_msg)[:300])
        entry['errors'] = entry['errors'][-5:]
        _save_circuit_state(state)
        return entry['count']

    @classmethod
    def record_success(cls, key):
        state = _load_circuit_state()
        if key in state['failures']:
            del state['failures'][key]
            _save_circuit_state(state)

    @classmethod
    def failure_count(cls, key):
        state = _load_circuit_state()
        return state.get('failures', {}).get(key, {}).get('count', 0)

    @classmethod
    def should_circuit_break(cls, key, max_strikes=2):
        """Returns True if the operation has failed consecutively >= max_strikes times."""
        return cls.failure_count(key) >= max_strikes


def execute_with_universal_recovery(action_fn, page=None, frame=None, port=None, action_key='action', max_retries=1):
    """Executes action_fn wrapped with universal obstacle clearing and circuit break recovery.
    
    1. If action_fn raises an exception:
       - Runs clear_all_obstacles(page, frame, port) to eliminate modal/dialog blockers.
       - Retries action_fn once.
    2. If retry still fails:
       - Records failure in CircuitBreaker.
       - If failure count >= 2: triggers clean session reset (reload / fresh navigation) rather than looping.
    3. On success: clears circuit breaker counter.
    """
    try:
        result = action_fn()
        CircuitBreaker.record_success(action_key)
        return result
    except Exception as initial_exc:
        # First-response: Universal Obstacle Clearer
        logger.warning(f"Action '{action_key}' failed ({initial_exc}). Triggering universal obstacle clearer...")
        obstacles = clear_all_obstacles(page=page, frame=frame, port=port)
        time.sleep(0.3)

        # Retry once after clearing
        try:
            result = action_fn()
            CircuitBreaker.record_success(action_key)
            logger.info(f"Action '{action_key}' recovered successfully after obstacle clearing: {obstacles}")
            return result
        except Exception as retry_exc:
            strikes = CircuitBreaker.record_failure(action_key, retry_exc)
            logger.error(f"Action '{action_key}' failed twice (strike {strikes}): {retry_exc}")
            
            # Circuit breaker: if repeated failure, reset session cleanly
            if strikes >= 2 and page:
                try:
                    logger.warning(f"Circuit breaker tripped for '{action_key}'. Reloading page for clean state reset...")
                    page.reload(wait_until='domcontentloaded', timeout=15000)
                    time.sleep(1)
                    clear_all_obstacles(page=page, frame=frame, port=port)
                except Exception:
                    pass

            raise retry_exc
