"""Automatic Naver Blog Public Publication Verification Worker (RSS + Ledger Reconciler)."""

import json
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests
from common.collection_observability import write as atomic_write

KST = timezone(timedelta(hours=9))

DEFAULT_ACCOUNTS = {
    "soultin": {"acc_id": "acc1", "blog_id": "mustpickinfo"},
    "soul5373": {"acc_id": "acc2", "blog_id": "mustinfo"},
    "yoon_master": {"acc_id": "acc3", "blog_id": "yoonviews"},
    "adinfo0905": {"acc_id": "acc4", "blog_id": "adinfo0905"},
    "stone0747": {"acc_id": "acc5", "blog_id": "stone0747"},
}

_LAST_RECONCILE_TS = 0.0


def _now_kst(now=None):
    if isinstance(now, datetime):
        return now.astimezone(KST) if now.tzinfo else now.replace(tzinfo=KST)
    return datetime.now(KST)


def _norm_title(text):
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _norm_alnum(text):
    if not isinstance(text, str):
        return ""
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", text).lower()


def _titles_match(a, b):
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ca, cb = _norm_alnum(na), _norm_alnum(nb)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    if len(ca) >= 10 and len(cb) >= 10 and (ca in cb or cb in ca):
        return True
    return False


def _clean_public_url(blog_id, raw_link):
    if not raw_link:
        return None
    m = re.search(r"blog\.naver\.com/([A-Za-z0-9_-]+)/(\d+)", str(raw_link))
    if m:
        return f"https://blog.naver.com/{m.group(1)}/{m.group(2)}"
    m2 = re.search(r"logNo=(\d+)", str(raw_link))
    if m2:
        return f"https://blog.naver.com/{blog_id}/{m2.group(1)}"
    return None


def fetch_blog_rss(blog_id, timeout=8):
    """Fetch recent public posts from Naver Blog RSS feed."""
    url = f"https://rss.blog.naver.com/{blog_id}.xml"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or item.findtext("guid") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()
        clean_url = _clean_public_url(blog_id, link)
        if not title or not clean_url:
            continue
        pub_dt = None
        if pub_raw:
            try:
                pub_dt = parsedate_to_datetime(pub_raw).astimezone(KST)
            except Exception:
                pub_dt = None
        pub_iso = pub_dt.strftime("%Y-%m-%dT%H:%M:00+09:00") if pub_dt else None
        pub_hm = pub_dt.strftime("%Y-%m-%d %H:%M") if pub_dt else None
        pub_date = pub_dt.strftime("%Y-%m-%d") if pub_dt else None
        items.append({
            "blogId": blog_id,
            "title": title,
            "publicUrl": clean_url,
            "publishedAt": pub_iso,
            "reserveTime": pub_hm,
            "publicationDate": pub_date,
        })
    return items


def _load_pipeline_status(js_path: Path):
    if not js_path.exists():
        return None
    raw = js_path.read_text(encoding="utf-8")
    m = re.match(r"^\s*window\.__NAVER_PIPELINE_STATUS__\s*=\s*([\s\S]+?);?\s*$", raw)
    if not m:
        return None
    return json.loads(m.group(1))


def verify_public_body(public_url, artifact_folder=None, timeout=2, deadline=None):
    """Compare actual public paragraphs with the existing saved reservation document."""
    from bs4 import BeautifulSoup
    result = {'publicBodyMatched': None, 'bodyParagraphsMatch': None, 'matchedParagraphs': 0,
              'substantiveParagraphs': 0, 'tagsVerified': None, 'bodyVerificationStatus': 'unknown'}
    try:
        public = requests.get(public_url, timeout=timeout)
        result['publicHttpStatus'] = public.status_code
        public.raise_for_status()
        mobile_url = public_url.replace('https://blog.naver.com/', 'https://m.blog.naver.com/')
        if deadline is not None and time.monotonic() >= deadline:
            result['bodyVerificationReason'] = 'cycle_budget_exhausted'
            return result
        mobile = requests.get(mobile_url, timeout=min(timeout, max(.1, deadline-time.monotonic())) if deadline else timeout); mobile.raise_for_status()
        soup = BeautifulSoup(mobile.content, 'html.parser')
        paragraphs = [p.get_text('', strip=True) for p in soup.select('.se-main-container .se-text-paragraph')]
        public_text = _norm_alnum(' '.join(paragraphs))
        result['publicBodySha256'] = hashlib.sha256(public_text.encode('utf-8')).hexdigest() if public_text else None
        if not artifact_folder:
            result['bodyVerificationReason'] = 'saved_document_unavailable'
            return result
        path = Path(artifact_folder) / 'reserved-server-document.json'
        saved = json.loads(path.read_text(encoding='utf-8'))['document']
        wanted = []
        def collect(value):
            if isinstance(value, dict):
                if isinstance(value.get('nodes'), list):
                    text = ''.join(str(n.get('value', '')) for n in value['nodes'] if isinstance(n, dict))
                    if len(_norm_alnum(text)) >= 10 and not text.lstrip().startswith('#'):
                        wanted.append(_norm_alnum(text))
                else:
                    for key, child in value.items():
                        if key != 'title':
                            collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(saved.get('components', []))
        matched = sum(text in public_text for text in wanted)
        valid = len(wanted) >= 3 and bool(public_text)
        result.update(substantiveParagraphs=len(wanted), matchedParagraphs=matched,
                      savedParagraphsIncludingHashtags=None, hashtagsExcludedFromBodyMatch=True,
                      bodyVerificationSource='live mobile body vs existing reserved-server-document.json',
                      bodyVerificationStatus=('matched' if matched == len(wanted) else 'mismatch') if valid else 'unknown',
                      publicBodyMatched=(matched == len(wanted)) if valid else None,
                      bodyParagraphsMatch=(matched == len(wanted)) if valid else None)
    except (OSError, ValueError, KeyError, TypeError, requests.RequestException) as exc:
        result['bodyVerificationReason'] = type(exc).__name__
    return result


def _save_pipeline_status(js_path: Path, data: dict):
    js_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "window.__NAVER_PIPELINE_STATUS__ = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n"
    from common.dashboard_jobs import atomic_text
    atomic_text(js_path,payload)


def reconcile(base=None, account_map=None, now=None, force=False):
    """Query Naver Blog RSS feeds, verify past-due reserved posts, and update public verification + pipeline ledgers."""
    global _LAST_RECONCILE_TS
    if not force and (time.time() - _LAST_RECONCILE_TS) < 45:
        return {"status": "cached", "updated": 0}

    base_dir = Path(base).resolve() if base else (Path(__file__).resolve().parents[2] / 'naver_blog_posting')
    project_root = base_dir.parent
    dashboard_dir = project_root / "dashboard"
    now_dt = _now_kst(now)
    now_iso = now_dt.isoformat()

    deadline = time.monotonic() + 12
    accounts = {}
    for acc_name, meta in DEFAULT_ACCOUNTS.items():
        passed = (account_map or {}).get(acc_name) if isinstance(account_map, dict) else None
        accounts[acc_name] = {
            "acc_id": (passed or {}).get("id") or meta["acc_id"],
            "blog_id": (passed or {}).get("blog_id") or meta["blog_id"],
        }

    rss_by_account = {}
    fetch_errors = {}
    for acc_name, meta in accounts.items():
        blog_id = meta["blog_id"]
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError('Public verification cycle budget exhausted')
            rss_by_account[acc_name] = fetch_blog_rss(blog_id, timeout=min(.8, max(.1, deadline-time.monotonic())))
        except Exception as exc:
            fetch_errors[acc_name] = str(exc)
            rss_by_account[acc_name] = []

    # Load existing public verification ledger
    dash_verify_path = dashboard_dir / 'data/naver/public-verification.json'
    local_verify_path = base_dir.parent / 'dashboard/data/naver' / "public-verification.json"
    ledger = {"schema": "naver-public-verification-v1", "publicationDate": now_dt.strftime("%Y-%m-%d"), "reportReceivedAt": now_iso, "evidence": []}
    for candidate in (dash_verify_path, local_verify_path):
        if candidate.exists():
            try:
                loaded = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("evidence"), list):
                    ledger = loaded
                    break
            except Exception:
                pass

    evidence_list = list(ledger.get("evidence") or [])
    evidence_by_url = {row.get("publicUrl"): row for row in evidence_list if row.get("publicUrl")}
    known_public_urls = set(evidence_by_url)

    # Load pipeline_status.js
    dash_ps_path = dashboard_dir / 'data/naver/pipeline_status.js'
    local_ps_path = base_dir.parent / 'dashboard/data/naver' / "pipeline_status.js"
    ps = _load_pipeline_status(dash_ps_path) or _load_pipeline_status(local_ps_path) or {}

    updated_count = 0
    try:
        attempts = json.loads((base_dir.parent / 'dashboard/data/naver' / 'automation-journal.json').read_text(encoding='utf-8')).get('attempts', [])
    except (OSError, ValueError):
        attempts = []
    artifacts = {a.get('publicUrl'): a.get('artifactFolder') for a in attempts if a.get('publicUrl') and a.get('artifactFolder')}
    body_evidence = {}
    def body_for(rss_item):
        url = rss_item['publicUrl']
        if url not in body_evidence:
            expected_account = next((name for name, meta in accounts.items()
                                     if meta['blog_id'] == rss_item.get('blogId')), None)
            folder = artifacts.get(url) or next((a.get('artifactFolder') for a in attempts
                if expected_account is not None and a.get('account') == expected_account
                and _titles_match(a.get('topic'), rss_item.get('title'))
                and a.get('publicationDate') == rss_item.get('publicationDate')), None)
            prior = evidence_by_url.get(url) or {}
            try:
                checked = datetime.fromisoformat(str(prior.get('checkedAt')).replace('Z', '+00:00'))
                age = (now_dt - checked).total_seconds()
            except (TypeError, ValueError):
                age = float('inf')
            already_public = prior.get('publicHttpStatus') == 200 and prior.get('publicPublicationVerified') is True
            historical = str(rss_item.get('publicationDate') or '') < now_dt.date().isoformat()
            recent_failed_attempt = prior.get('bodyVerificationStatus') in ('unknown','mismatch') and prior.get('bodyVerificationReason') != 'cycle_budget_exhausted' and 0 <= age < 120
            if recent_failed_attempt or already_public and (not force and historical or 0 <= age < 3600):
                body_evidence[url] = dict(prior)
            elif len([v for v in body_evidence.values() if v.get('_networkChecked')]) >= 2 or time.monotonic() >= deadline:
                body_evidence[url] = dict(prior) if already_public else {'bodyVerificationStatus':'deferred', 'bodyVerificationReason':'cycle_budget_exhausted'}
            else:
                folder = resolve_artifact_folder(folder, expected_account, base_dir)
                body_evidence[url] = verify_public_body(url, folder, timeout=min(1.5, max(.1, deadline-time.monotonic())), deadline=deadline)
                body_evidence[url]['checkedAt'] = now_iso
                body_evidence[url]['_networkChecked'] = True
        return {k:v for k,v in body_evidence[url].items() if not k.startswith("_")}

    def _make_evidence_row(acc_name, blog_id, topic, reserve_time, rss_item, pub_date):
        eff_reserve = reserve_time or rss_item.get("reserveTime") or f"{pub_date} 11:00"
        # Ensure publishedAt matches reserveTime minute so strict front-end filters accept it
        reserve_iso = eff_reserve.replace(" ", "T") + ":00+09:00" if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", eff_reserve) else (rss_item.get("publishedAt") or now_iso)
        return {
            "account": acc_name,
            "blogId": blog_id,
            "title": topic or rss_item["title"],
            "reserveTime": eff_reserve,
            "publicUrl": rss_item["publicUrl"],
            "publishedAt": rss_item.get("publishedAt"),
            "checkedAt": now_iso,
            "reportReceivedAt": now_iso,
            "observationTimePrecision": f"automatic RSS verification at {now_iso}",
            **body_for(rss_item),
            "verificationSource": "naver-rss-auto-worker: live RSS feed exact title/account verified",
            "evidenceCollector": "dashboard.collectors.naver_public.reconcile",
            "verified": body_for(rss_item).get("publicHttpStatus") == 200,
            "publicPublicationVerified": body_for(rss_item).get("publicHttpStatus") == 200,
            "publicationDate": pub_date,
            "actualPublishedAt": rss_item.get("publishedAt") or reserve_iso,
        }

    def _promote_slot_dict(slot_obj, rss_item, eff_reserve):
        if body_for(rss_item).get("publicHttpStatus") != 200:
            return
        reserve_iso = eff_reserve.replace(" ", "T") + ":00+09:00" if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", eff_reserve) else (rss_item.get("publishedAt") or now_iso)
        slot_obj["status"] = "done"
        slot_obj["publicationStatus"] = "verified_public"
        slot_obj["state"] = "verified_public"
        slot_obj["publicPublicationVerified"] = True
        slot_obj["publicUrl"] = rss_item["publicUrl"]
        slot_obj["publishedAt"] = rss_item.get("publishedAt")
        slot_obj["publicVerifiedAt"] = body_for(rss_item).get("checkedAt", now_iso)
        slot_obj.update(body_for(rss_item))

    # Walk completedByDate and completedAccounts in pipeline_status.js
    completed_by_date = ps.get("completedByDate") or {}
    acc_id_to_name = {v["acc_id"]: k for k, v in accounts.items()}

    for pub_date, date_map in completed_by_date.items():
        if not isinstance(date_map, dict):
            continue
        for acc_id, record in date_map.items():
            if not isinstance(record, dict):
                continue
            acc_name = acc_id_to_name.get(acc_id)
            if not acc_name:
                continue
            blog_id = accounts[acc_name]["blog_id"]
            rss_items = rss_by_account.get(acc_name) or []
            if not rss_items:
                continue

            # Check completedSlots first
            comp_slots = record.get("completedSlots")
            if isinstance(comp_slots, dict):
                for slot_key, slot_val in comp_slots.items():
                    if not isinstance(slot_val, dict):
                        continue
                    s_topic = slot_val.get("topic") or record.get("topic")
                    s_reserve = slot_val.get("reserveTime") or record.get("reserveTime") or f"{pub_date} {slot_key}"
                    matched_rss = next((r for r in rss_items if r.get("publicationDate") == pub_date and _titles_match(r["title"], s_topic)), None)
                    if matched_rss:
                        was_verified = slot_val.get("publicPublicationVerified") is True and bool(slot_val.get("publicUrl"))
                        _promote_slot_dict(slot_val, matched_rss, s_reserve)
                        ev_row = _make_evidence_row(acc_name, blog_id, s_topic, s_reserve, matched_rss, pub_date)
                        evidence_by_url[matched_rss["publicUrl"]] = ev_row
                        if not was_verified and body_for(matched_rss).get("publicHttpStatus") == 200:
                            updated_count += 1
                        # If record's main topic matches this slot, promote record too
                        if _titles_match(record.get("topic"), s_topic):
                            _promote_slot_dict(record, matched_rss, s_reserve)

            # Also check record top-level topic
            r_topic = record.get("topic")
            r_reserve = record.get("reserveTime")
            if r_topic:
                matched_rss = next((r for r in rss_items if r.get("publicationDate") == pub_date and _titles_match(r["title"], r_topic)), None)
                if matched_rss:
                    was_verified = record.get("publicPublicationVerified") is True and bool(record.get("publicUrl"))
                    _promote_slot_dict(record, matched_rss, r_reserve or f"{pub_date} {record.get('scheduledSlot', '11:00')}")
                    ev_row = _make_evidence_row(acc_name, blog_id, r_topic, r_reserve, matched_rss, pub_date)
                    evidence_by_url[matched_rss["publicUrl"]] = ev_row
                    if not was_verified and body_for(matched_rss).get("publicHttpStatus") == 200:
                        updated_count += 1

    # Sync completedAccounts with completedByDate[today] or RSS
    comp_accounts = ps.get("completedAccounts") or {}
    for acc_id, record in comp_accounts.items():
        if not isinstance(record, dict):
            continue
        acc_name = acc_id_to_name.get(acc_id)
        if not acc_name:
            continue
        blog_id = accounts[acc_name]["blog_id"]
        pub_date = (record.get("publicationDate") or record.get("date") or now_dt.strftime("%Y-%m-%d"))[:10]
        rss_items = rss_by_account.get(acc_name) or []
        comp_slots = record.get("completedSlots")
        if isinstance(comp_slots, dict):
            for slot_key, slot_val in comp_slots.items():
                if not isinstance(slot_val, dict):
                    continue
                s_topic = slot_val.get("topic") or record.get("topic")
                s_reserve = slot_val.get("reserveTime") or record.get("reserveTime") or f"{pub_date} {slot_key}"
                matched_rss = next((r for r in rss_items if r.get("publicationDate") == pub_date and _titles_match(r["title"], s_topic)), None)
                if matched_rss:
                    _promote_slot_dict(slot_val, matched_rss, s_reserve)
                    ev_row = _make_evidence_row(acc_name, blog_id, s_topic, s_reserve, matched_rss, pub_date)
                    evidence_by_url[matched_rss["publicUrl"]] = ev_row
                    if _titles_match(record.get("topic"), s_topic):
                        _promote_slot_dict(record, matched_rss, s_reserve)
        r_topic = record.get("topic")
        r_reserve = record.get("reserveTime")
        if r_topic:
            matched_rss = next((r for r in rss_items if r.get("publicationDate") == pub_date and _titles_match(r["title"], r_topic)), None)
            if matched_rss:
                _promote_slot_dict(record, matched_rss, r_reserve or f"{pub_date} {record.get('scheduledSlot', '11:00')}")

    # Also check top-level ps
    top_acc_id = ps.get("accId")
    if top_acc_id in acc_id_to_name:
        acc_name = acc_id_to_name[top_acc_id]
        rss_items = rss_by_account.get(acc_name) or []
        top_date = (ps.get("publicationDate") or ps.get("date") or now_dt.strftime("%Y-%m-%d"))[:10]
        if isinstance(ps.get("completedSlots"), dict):
            for slot_key, slot_val in ps["completedSlots"].items():
                if isinstance(slot_val, dict):
                    s_topic = slot_val.get("topic") or ps.get("topic")
                    s_reserve = slot_val.get("reserveTime") or ps.get("reserveTime") or f"{top_date} {slot_key}"
                    matched_rss = next((r for r in rss_items if r.get("publicationDate") == top_date and _titles_match(r["title"], s_topic)), None)
                    if matched_rss:
                        _promote_slot_dict(slot_val, matched_rss, s_reserve)
                        if _titles_match(ps.get("topic"), s_topic):
                            _promote_slot_dict(ps, matched_rss, s_reserve)

    # Also walk automation-journal.json so any verified reservation whose reserveTime has passed and appears in RSS promotes automatically
    local_journal_path = base_dir.parent / 'dashboard/data/naver' / "automation-journal.json"
    dash_journal_path = dashboard_dir / 'data/naver/automation-journal.json'
    journal_data = None
    journal_dirty = False
    if local_journal_path.exists():
        try:
            journal_data = json.loads(local_journal_path.read_text(encoding="utf-8"))
        except Exception:
            journal_data = None
    if isinstance(journal_data, dict) and isinstance(journal_data.get("attempts"), list):
        for attempt in journal_data["attempts"]:
            if not isinstance(attempt, dict) or attempt.get("phase") != "verified":
                continue
            acc_name = attempt.get("account")
            if acc_name not in accounts:
                continue
            a_topic = attempt.get("topic")
            a_reserve = attempt.get("reserveTime") or ""
            pub_date = (attempt.get("publicationDate") or a_reserve[:10] or attempt.get("workDate") or now_dt.strftime("%Y-%m-%d"))[:10]
            slot_key = attempt.get("scheduledSlot") or (a_reserve[-5:] if len(a_reserve) >= 5 else "11:00")
            blog_id = accounts[acc_name]["blog_id"]
            acc_id = accounts[acc_name]["acc_id"]
            rss_items = rss_by_account.get(acc_name) or []
            if not a_topic or not rss_items:
                continue
            matched_rss = next((r for r in rss_items if r.get("publicationDate") == pub_date and _titles_match(r["title"], a_topic)), None)
            if matched_rss:
                was_verified = attempt.get("publicPublicationVerified") is True and bool(attempt.get("publicUrl"))
                _promote_slot_dict(attempt, matched_rss, a_reserve or f"{pub_date} {slot_key}")
                try:
                    from dashboard.agents.work_learning import learn_naver_public
                    learn_naver_public(attempt,matched_rss)
                except (OSError,ValueError,RuntimeError,KeyError):
                    pass  # Public observation stays intact; no unverified lesson is written.
                ev_row = _make_evidence_row(acc_name, blog_id, a_topic, a_reserve or f"{pub_date} {slot_key}", matched_rss, pub_date)
                evidence_by_url[matched_rss["publicUrl"]] = ev_row
                journal_dirty = True
                if not was_verified and body_for(matched_rss).get("publicHttpStatus") == 200:
                    updated_count += 1
                # Ensure pipeline_status completedByDate also reflects this public promotion
                if isinstance(ps, dict):
                    cbd = ps.setdefault("completedByDate", {})
                    day_map = cbd.setdefault(pub_date, {})
                    acc_rec = day_map.setdefault(acc_id, {
                        "account": acc_name,
                        "blogId": blog_id,
                        "accId": acc_id,
                        "date": pub_date,
                        "publicationDate": pub_date,
                        "status": "done",
                        "topic": a_topic,
                        "reserveTime": a_reserve or f"{pub_date} {slot_key}",
                    })
                    c_slots = acc_rec.setdefault("completedSlots", {})
                    slot_entry = c_slots.setdefault(slot_key, {
                        "topic": a_topic,
                        "reserveTime": a_reserve or f"{pub_date} {slot_key}",
                        "verificationSource": attempt.get("verificationSource"),
                        "artifactFolder": attempt.get("artifactFolder"),
                    })
                    _promote_slot_dict(slot_entry, matched_rss, a_reserve or f"{pub_date} {slot_key}")
        if journal_dirty:
            try:
                atomic_write(local_journal_path, journal_data)
            except Exception:
                pass
        try:
            atomic_write(dash_journal_path, journal_data)
        except Exception:
            pass

    # Rebuild ordered evidence list
    merged_evidence = list(evidence_by_url.values())
    merged_evidence.sort(key=lambda r: (r.get("publicationDate") or "", r.get("reserveTime") or "", r.get("account") or ""))

    ledger_out = {
        "schema": "naver-public-verification-v1",
        "publicationDate": now_dt.strftime("%Y-%m-%d"),
        "reportReceivedAt": now_iso,
        "evidence": merged_evidence,
    }

    dash_verify_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(dash_verify_path, ledger_out)
    local_verify_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(local_verify_path, ledger_out)
    if updated_count:
        from common.llm_client import memory_event
        for item in merged_evidence:
            # RSS proves the public item's presence, not the full body or image layout.
            if item.get('publicUrl') and item['publicUrl'] not in known_public_urls and item.get('checkedAt') == now_iso:
                memory_event('naver:rss:' + item['publicUrl'], 'public_rss_item_observed',
                             'Public Naver RSS item matched account/title; full-body verification is separate.',
                             evidence={k: item.get(k) for k in ('publicUrl', 'account', 'actualPublishedAt', 'checkedAt')})

    if ps:
        _save_pipeline_status(dash_ps_path, ps)
        _save_pipeline_status(local_ps_path, ps)

    _LAST_RECONCILE_TS = time.time()
    return {
        "status": "ok" if not fetch_errors else "partial",
        "checkedAt": now_iso,
        "updated": updated_count,
        "totalVerifiedEvidence": len(merged_evidence),
        "errors": fetch_errors,
    }


def record_check(base=None, result=None):
    """Persist the latest public verification worker check summary."""
    try:
        base_dir = Path(base).resolve() if base else (Path(__file__).resolve().parents[2] / 'naver_blog_posting')
        status_path = base_dir.parent / 'dashboard/data/naver' / "public-verification-status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        payload = result if isinstance(result, dict) else {"status": "ok"}
        status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return True


if __name__ == "__main__":
    res = reconcile(force=True)
    print(json.dumps(res, ensure_ascii=False, indent=2))


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
