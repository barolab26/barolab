"""Observed KnowledgeIn UI adapter; reuse dedicated browsers, fail closed on ambiguity.

Selectors observed 2026-10-15. Never starts/stops a browser and never retries a
registration click. The caller owns durable duplicate and draft review checks.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit

import requests
import websocket
from bs4 import BeautifulSoup

from common.browser_session import preflight, _local_socket

ACCOUNTS = {"adinfo0905": 9231, "stone0747": 9230}


class AccountProtectionError(RuntimeError):
    """An actual visible service protection/CAPTCHA prevents further work."""


class PostingRejectedError(RuntimeError):
    """The service explicitly rejects answering; caller must halt this account."""


class QuestionUnavailableError(RuntimeError):
    """Question-specific restriction; skip this question without halting account."""


class LoginRequiredError(RuntimeError):
    pass


class DiscoveryResults(list):
    def __init__(self):
        super().__init__()
        self.skipped = []


def _check_service_state(page):
    if urlsplit(page.url).hostname == 'nid.naver.com':
        raise LoginRequiredError('NAVER redirected to authentication; no automatic login')
    # These rejection layers were observed in the actual KnowledgeIn question DOM.
    for selector in ('#notAnswerableLayer', '#deferredExpertLayer', '[role="dialog"]'):
        for dialog in page.locator(selector).all():
            if not dialog.is_visible():
                continue
            message = dialog.inner_text().strip()
            if not message:
                continue
            if any(word in message for word in ('보호조치', '보안문자', '자동입력 방지', 'CAPTCHA')):
                raise AccountProtectionError('Visible NAVER protection challenge; manual resolution required')
            compact = re.sub(r'\s+', '', message)
            if any(word in compact for word in ('계정이제한', '아이디가제한', '글쓰기제한', '답변활동제한')):
                raise AccountProtectionError('Visible NAVER account writing restriction; manual resolution required')
            if selector in ('#notAnswerableLayer', '#deferredExpertLayer'):
                raise QuestionUnavailableError('Visible question/field-specific answer restriction; skip question')


def account_config(account):
    if account not in ACCOUNTS:
        raise ValueError("Only the two authorized non-realname accounts are permitted")
    home = Path("C:/99_포터블브라우저") / ("CentBrowserPotable_" + account)
    executable, profile = home / "chrome.exe", home / "User Data"
    if os.name != 'nt':
        from common.ubuntu_naver_browser import account_paths
        executable, profile, _ = account_paths(ACCOUNTS[account])
    return {"account": account, "cdp_port": ACCOUNTS[account],
            "endpoint": f"http://127.0.0.1:{ACCOUNTS[account]}",
            "exe": str(executable), "profile": str(profile)}


def question_id(url):
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    if (parts.scheme != "https" or parts.hostname != "kin.naver.com" or parts.path != "/qna/detail.naver"
            or parts.username or parts.password or parts.port is not None
            or (parts.fragment and not re.fullmatch(r"answer\d+", parts.fragment))):
        raise ValueError("Expected a KnowledgeIn question URL")
    value = query.get("docId", [""])[0]
    if len(query.get("docId", [])) != 1 or not value.isdigit():
        raise ValueError("Missing numeric question id")
    return value


@contextmanager
def account_lock(account):
    account_config(account)
    directory = Path.home() / ".barolab" / "runtime"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ("kin-" + account + ".lock")).open("a+b") as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def blog_run_lock():
    """Honor the existing blog writer's exact lock without importing its side effects."""
    path = Path(__file__).resolve().parents[1] / 'naver_blog_posting/data/pipeline-run.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def awake_browser(playwright, config):
    """Keep existing suspended tabs awake during attachment; never restart/close tabs.

    This portable browser can freeze background tabs immediately after a probe
    detaches. Playwright waits for every existing page during browser attachment.
    Temporary Page.enable debugger sessions bridge that race without changing
    any tab URL or browser settings.
    """
    info = preflight(config['endpoint'], config['exe'], config['profile'],
                     preferred_host='kin.naver.com', process_timeout=30)
    connections = []
    try:
        targets = requests.get(config['endpoint'] + '/json/list', timeout=4).json()
        for target in targets:
            if target.get('type') != 'page':
                continue
            requests.get(config['endpoint'] + '/json/activate/' + target['id'], timeout=4).raise_for_status()
            address = _local_socket(target['webSocketDebuggerUrl'], config['cdp_port'])
            connection = websocket.create_connection(address, timeout=4, suppress_origin=True)
            connections.append(connection)
            connection.send(json.dumps({'id': 1, 'method': 'Page.enable'}))
            for _ in range(50):
                message = json.loads(connection.recv())
                if message.get('id') == 1:
                    if 'error' in message:
                        raise RuntimeError('Existing tab debugger could not wake safely')
                    break
            else:
                raise RuntimeError('Existing tab debugger acknowledgement unavailable')
        browser = playwright.chromium.connect_over_cdp(info['webSocketDebuggerUrl'],
                                                       timeout=20000, no_defaults=True)
        yield browser
    finally:
        for connection in connections:
            connection.close()


def _check_account_blog_not_busy(account: str):
    """Only block if this exact account is actively running a Naver blog post right now."""
    wf_path = Path(__file__).resolve().parents[1] / "naver_blog_posting" / "data" / "active-workflow.json"
    if not wf_path.is_file():
        return
    try:
        wf = json.loads(wf_path.read_text(encoding="utf-8"))
        if wf.get("status") == "running" and wf.get("account") == account:
            raise RuntimeError(f"Account {account} is currently running a Naver blog post")
    except RuntimeError:
        raise
    except Exception:
        pass


@contextmanager
def session(account):
    from playwright.sync_api import sync_playwright
    config = account_config(account)
    _check_account_blog_not_busy(account)
    with account_lock(account), sync_playwright() as playwright, awake_browser(playwright, config) as browser:
        ctx = browser.contexts[0]
        pages = ctx.pages
        kin = [p for p in pages if urlsplit(p.url).hostname == "kin.naver.com" and not _has_editor_draft(p)]
        if kin:
            page = kin[0]
        else:
            page = next(
                (p for p in pages if p.url.rstrip("/") in ("https://www.naver.com", "https://naver.com", "about:blank")),
                None,
            )
            if page is None:
                # Open a dedicated KnowledgeIn tab while preserving all existing user tabs (including any open editor drafts) untouched
                page = ctx.new_page()
        page.bring_to_front()
        page.set_default_timeout(12000)
        preserve_editor(page)
        page.goto("https://kin.naver.com/", wait_until="domcontentloaded", timeout=25000)
        _check_service_state(page)
        identity = page.locator(".my_service .user_id")
        if identity.count() != 1 or identity.inner_text().strip() != account:
            raise LoginRequiredError("Logged-in KnowledgeIn identity does not match authorized account")
        yield page
        # Only disconnect Playwright. browser.close() would close the user's browser.


def _has_editor_draft(page):
    try:
        return any(text.strip() for text in page.locator('.se-canvas .__se-node').all_inner_texts())
    except Exception:
        return False


def preserve_editor(page):
    """Check before navigating, so another author's unsaved Kin draft survives."""
    if _has_editor_draft(page):
        raise RuntimeError('Existing KnowledgeIn editor draft requires manual review')


def _own_answer_map(page, max_pages=3):
    """Authenticated own-answer links bind full account to public answer numbers (bounded to recent 3 pages = 60 items)."""
    pending = ['https://kin.naver.com/myinfo/answerList.naver']
    visited, result = set(), {}
    while pending and len(visited) < max_pages:
        url = pending.pop(0)
        if url in visited:
            continue
        visited.add(url)
        response = page.context.request.get(url, timeout=15000)
        if response.status != 200 or urlsplit(response.url).path != '/myinfo/answerList.naver':
            raise RuntimeError('Authenticated own-answer inventory unavailable')
        soup = BeautifulSoup(response.text(), 'html.parser')
        for link in soup.select('a[href]'):
            value = urlsplit(link['href'])
            query = parse_qs(value.query)
            if value.path == '/qna/mydetail.naver':
                doc, aid = query.get('docId', [''])[0], query.get('answerNo', [''])[0]
                if doc.isdigit() and aid.isdigit():
                    result.setdefault(doc, set()).add(aid)
            if value.path == '/myinfo/answerList.naver' and query.get('page', [''])[0].isdigit():
                page_no = int(query.get('page', ['0'])[0])
                if 1 <= page_no <= max_pages:
                    candidate = 'https://kin.naver.com' + value.path + '?' + value.query
                    if candidate not in visited and candidate not in pending:
                        pending.append(candidate)
    return result


def _parse_question_ownership(html, account, identifier):
    """Read only observed authenticated question markers; incomplete evidence is unknown."""
    soup = BeautifulSoup(html, 'html.parser')
    scripts = '\n'.join(node.get_text() for node in soup.find_all('script'))
    identities = set(re.findall(r'\bloginUserId\s*:\s*"([A-Za-z0-9_-]+)"', scripts))
    if not re.search(r'\bnaver\.isLogin\s*=\s*true\s*;', scripts) or identities != {account}:
        raise LoginRequiredError('Authenticated question identity is missing or mismatched')
    result = {'account': account, 'question_id': identifier, 'known': False,
              'complete': False, 'answer_ids': [], 'reason': 'question_evidence_incomplete'}
    if not soup.select_one('.questionDetail') or not soup.select_one('.endTitleSection'):
        return result
    # Actual server-rendered ElementBaLogSender has this question's global total,
    # including answers beyond the initial page. Never infer absence from a write button.
    totals = re.findall(r'window\.oElementBaLogSender\s*=\s*new\s+naver\.kin\.pc\.detail\.ElementBaLogSender\(\{\s*'
                        r'dirId\s*:\s*\d+\s*,\s*docId\s*:\s*(\d+)\s*,\s*totalAnswerCount\s*:\s*(\d+)\s*,', scripts)
    matching = [int(total) for doc, total in totals if doc == str(identifier)]
    if len(matching) != 1:
        return result
    total = matching[0]
    nodes = soup.select('.answerArea[id^=answer_]')
    numbers = [node.get('id', '').split('_', 1)[-1] for node in nodes]
    if any(not value.isdigit() for value in numbers) or len(set(numbers)) != len(numbers):
        return result
    dom_counts = [node.get_text(strip=True).replace(',', '')
                  for node in soup.select('._answerCount,._totalAnswerCount')]
    if any(not count.isdigit() or int(count) != total for count in dom_counts):
        return result
    result.update(total_answers=total, loaded_answers=len(nodes))
    own = []
    for node, number in zip(nodes, numbers):
        marker = '_myAnswer' in node.get('class', [])
        control = bool(node.select(f'#optModify{number},#optDelete{number}'))
        if marker or control:
            own.append(number)
        if marker != control:
            return {**result, 'answer_ids': own, 'reason': 'ownership_markers_disagree'}
    result['answer_ids'] = own
    # Positive ownership survives pagination; absence still requires every answer.
    result['verified_owned_answer_ids'] = own
    if len(nodes) != total:
        return {**result, 'reason': 'question_answers_partially_loaded'}
    return {**result, 'known': True, 'complete': True, 'reason': 'complete_authenticated_question'}


def _question_ownership(page, account, url):
    identifier = question_id(url)
    response = page.context.request.get(url, timeout=15000)
    if response.status != 200 or question_id(response.url) != identifier:
        raise RuntimeError('Authenticated question ownership response unavailable')
    return _parse_question_ownership(response.text(), account, identifier)


def _read(page, url):
    identifier = question_id(url)
    page.goto(url, wait_until="domcontentloaded", timeout=25000)
    _check_service_state(page)
    soup = BeautifulSoup(page.content(), "html.parser")
    title = soup.select_one(".endTitleSection")
    body = soup.select_one(".questionDetail")
    if not title or not body:
        raise RuntimeError("Question selectors changed or question is unavailable")
    for element in title.select(".blind, svg"):
        element.decompose()
    return {"question_url": url, "question_id": identifier,
            "title": title.get_text(" ", strip=True),
            "body": page.locator(".questionDetail").inner_text().strip(),
            "image_urls": [x.get("src") for x in body.select("img")],
            "requires_visual_evidence": bool(body.select('img, video, iframe, .kin_movie_info')),
            "answer_count": len(soup.select(".answerArea[id^=answer_]")),
            "answer_button_present": bool(soup.select('._answerWriteButton')),
            "existing_answers": [x.get_text('\n', strip=True)[:10000]
                                 for x in soup.select('.answerArea[id^=answer_]')],
            "captured_at": datetime.now(timezone.utc).isoformat()}


def read_question(account, url):
    with session(account) as page:
        return _read(page, url)


def discover(account, keywords, limit=10, sort='none', page_number=1, include_latest=False, track=None):
    # Observed NAVER links: none=accuracy (Track B), date=latest (Track A), vcount=recommendation.
    if track == 'track_a_latest' and sort == 'none':
        sort = 'date'
    elif track == 'track_b_search_top' and sort not in ('none', 'date', 'vcount'):
        sort = 'none'
    if sort not in ('none', 'date', 'vcount'):
        raise ValueError('Unsupported observed KnowledgeIn search sort')
    if not isinstance(page_number, int) or not 1 <= page_number <= 3:
        raise ValueError('Bounded search page must be between 1 and 3')
    results, seen = DiscoveryResults(), set()
    with session(account) as page:
        groups = []
        searches = []
        if include_latest and keywords:
            # 50:50 hybrid discovery across Track A (date/latest) and Track B (none/search_top)
            for idx, keyword in enumerate(keywords):
                primary_sort = 'date' if (track == 'track_a_latest' or (track is None and idx % 2 == 0)) else 'none'
                secondary_sort = 'none' if primary_sort == 'date' else 'date'
                searches.append((keyword, primary_sort))
                if len(searches) < 6:
                    searches.append((keyword, secondary_sort))
        else:
            searches = [(keyword, sort) for keyword in keywords]
        for keyword, ordering in searches:
            page.goto("https://kin.naver.com/search/list.naver?" + urlencode(
                {"query": keyword, "section": "qna", "sort": ordering, 'page': page_number}), wait_until="domcontentloaded", timeout=25000)
            hrefs = page.locator("._searchListTitleAnchor").evaluate_all("es=>es.map(e=>e.href)")
            groups.append([(href, ordering) for href in hrefs])
        # Round robin gives each configured topic & track a chance within the bounded limit.
        links = [group[i] for i in range(max((len(g) for g in groups), default=0))
                 for group in groups if len(group) > i]
        for item_link in links:
            url, ordering = item_link if isinstance(item_link, tuple) else (item_link, sort)
            identifier = question_id(url)
            if identifier in seen:
                continue
            seen.add(identifier)
            try:
                item = _read(page, url)
                if isinstance(item, dict) and 'title' in item:
                    item.setdefault('search_sort', ordering)
                    item.setdefault('track', track or ('track_a_latest' if ordering == 'date' else 'track_b_search_top'))
                results.append(item)
            except QuestionUnavailableError:
                results.skipped.append({'question_url': url, 'question_id': identifier,
                                        'reason': 'question_unavailable'})
                continue
            if len(results) >= min(limit, 20):
                return results
    return results


def publish(account, question_url, answer_text, before_submit=None):
    if not callable(before_submit):
        raise ValueError("Durable before_submit callback is required")
    with session(account) as page:
        ownership = _question_ownership(page, account, question_url)
        if ownership['answer_ids']:
            raise RuntimeError('Account already has an answer on this question')
        if not ownership['known'] or not ownership['complete']:
            if ownership.get('reason') == 'question_answers_partially_loaded':
                recent_map = _own_answer_map(page, max_pages=3)
                if question_id(question_url) in recent_map:
                    raise RuntimeError('Account already has an answer on this question')
            else:
                raise RuntimeError('Current-question ownership is unknown: ' + ownership['reason'])
        _read(page, question_url)
        page.locator("._answerWriteButton").first.click()
        _check_service_state(page)
        editor = page.locator(".se-canvas .se-text-paragraph").first
        editor.wait_for(state="visible")
        # Preserve existing text instead of silently overwriting a user's draft.
        nodes = page.locator(".se-canvas .se-text-paragraph .__se-node")
        if any(text.strip() for text in nodes.all_inner_texts()):
            raise RuntimeError("Existing editor text requires manual review")
        editor.click()
        # Observed SmartEditor strips embedded newlines from insert_text. Real
        # Enter keystrokes preserve reviewed paragraph boundaries and autolink.
        _type_paragraphs(page.keyboard, answer_text)
        page.wait_for_timeout(1500)
        rendered = "\n".join(page.locator(".se-canvas .se-text-paragraph").all_inner_texts())
        if _normalized(rendered) != _normalized(answer_text):
            raise RuntimeError("Editor did not retain the reviewed answer exactly")
        urls = re.findall(r'https://[^\s<>]+', answer_text)
        actual_links = page.locator('.se-canvas a[href], .se-canvas .se-link[data-href]').evaluate_all(
            'es=>es.map(e=>e.href || e.getAttribute("data-href"))')
        if any(url not in actual_links for url in urls):
            raise RuntimeError('Reviewed outbound URL is not a clickable editor hyperlink')
        button = page.locator("#answerRegisterButton")
        if button.count() != 1 or not button.is_enabled():
            raise RuntimeError("Registration is unavailable")
        before_submit()
        # Any exception from this point is an uncertain submission; caller must not retry.
        button.click(timeout=12000)
        page.wait_for_timeout(2500)
        try:
            if button.count() == 1 and button.is_visible():
                button.click(timeout=8000)
                page.wait_for_timeout(3000)
        except Exception:
            pass
        _check_service_state(page)
        soup = BeautifulSoup(page.content(), "html.parser")
        matches = [node for node in soup.select(".answerArea[id^=answer_]")
                   if _normalized(answer_text) in _normalized(node.get_text("\n"))]
        if len(matches) != 1:
            first_line = _normalized(answer_text.split("\n")[0])
            matches = [node for node in soup.select(".answerArea._myAnswer[id^=answer_]")
                       if first_line and first_line in _normalized(node.get_text("\n"))]
        if len(matches) != 1:
            return {"answer_url": question_url, "answer_id": None,
                    "reason": "submitted_unverified: answer not uniquely identified"}
        aid = matches[0]["id"].split("_", 1)[1]
        return {"answer_url": exact_answer_url(question_url, aid), "answer_id": aid}


def _type_paragraphs(keyboard, text):
    for line in text.split('\n'):
        if line:
            keyboard.insert_text(line)
        keyboard.press('Enter')


def _normalized(text):
    return re.sub(r"\s+", " ", text.replace("\u200b", "")).strip()


def exact_answer_url(url, answer_id):
    """Select the actual answer page, not the question's old answerNo pagination."""
    question_id(url)
    if not str(answer_id or '').isdigit():
        raise ValueError('Exact numeric answer ID required')
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query['answerNo'] = [str(answer_id)]
    return parsed._replace(query=urlencode(query, doseq=True), fragment='answer' + str(answer_id)).geturl()


def verify_public(account, answer_url, expected_text, outbound_url, answer_id=None):
    """Anonymous HTTP evidence only; masked identities never prove an exact account."""
    account_config(account)
    identifier = question_id(answer_url)
    evidence = {"account": None, "question_id": identifier, "answer_id": str(answer_id or ""),
                "verified": False, "public": False, "outbound_url": outbound_url,
                "answer_text_sha256": hashlib.sha256(expected_text.encode("utf-8")).hexdigest(),
                "checked_at": datetime.now(timezone.utc).isoformat()}
    if answer_id and str(answer_id).isdigit():
        answer_url = exact_answer_url(answer_url, answer_id)
        evidence['answer_url'] = answer_url
    response = requests.get(answer_url, timeout=20, allow_redirects=False,
                            headers={"User-Agent": "Mozilla/5.0"})
    if response.status_code != 200:
        return {**evidence, "reason": "anonymous HTTP response unavailable"}
    soup = BeautifulSoup(response.text, "html.parser")
    if not answer_id or not str(answer_id).isdigit():
        return {**evidence, "reason": "exact answer id unavailable"}
    node = soup.select_one("#answer_" + str(answer_id))
    if not node or _normalized(expected_text) not in _normalized(node.get_text("\n")):
        return {**evidence, "reason": "answer body not publicly matched"}
    links = {a.get("href") for a in node.select("a[href]")}
    if outbound_url not in links:
        return {**evidence, "reason": "exact attributed outbound URL not publicly matched"}
    # NAVER normally masks IDs. Never infer exact author from a four-character prefix.
    author_links = [a.get("href", "") for a in node.select(".profile_card a[href]")]
    identity_proven = any(parse_qs(urlsplit(u).query).get("userId") == [account] for u in author_links)
    evidence.update(public=True)
    if not identity_proven:
        # Public rendering proves visibility. Separate authenticated own-answer inventory
        # proves account ownership without treating author-only visibility as public proof.
        try:
            with session(account) as page:
                ownership = _question_ownership(page, account, answer_url)
                identity_proven = str(answer_id) in ownership.get('verified_owned_answer_ids', [])
        except Exception as exc:
            return {**evidence, 'reason': 'public body/link matched; ownership inventory unavailable: ' + str(exc)}
        if not identity_proven:
            return {**evidence, "reason": "public body/link matched; exact author identity unavailable"}
        evidence['ownership_evidence'] = 'authenticated exact-account current-question _myAnswer and owner controls; exact answer ID'
    return {**evidence, "account": account, "verified": True,
            "reason": "anonymous answer body/link matched; exact account ownership separately verified"}
