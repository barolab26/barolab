"""Strict outbound attribution for already verified CF articles; no network or publication.

The caller supplies the approved host allowlist and independently verifies the clean
canonical article. This module cannot establish article relevance or authenticity.
"""
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlencode, urlsplit

SOURCES = frozenset(('naver_blog', 'naver_kin', 'threads'))
MEDIUM_BY_SOURCE = {'naver_blog': 'referral', 'naver_kin': 'referral', 'threads': 'social'}
CAMPAIGN = 'cf_bridge'


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Attribution date must be YYYY-MM-DD')
    datetime.strptime(value, '%Y-%m-%d')
    return value


def _canonical(canonical_url, allowed_hosts):
    if not isinstance(allowed_hosts, (list, tuple, set, frozenset)) or not allowed_hosts:
        raise ValueError('Explicit approved host allowlist required')
    if any(not isinstance(h, str) or not re.fullmatch(r'[a-z0-9.-]+', h) for h in allowed_hosts):
        raise ValueError('Allowlist must contain exact lowercase hostnames')
    if not isinstance(canonical_url, str) or not canonical_url.startswith('https://'):
        raise ValueError('Canonical article must use exact HTTPS URL')
    if any(ord(c) <= 32 or ord(c) == 127 for c in canonical_url) or '\\' in canonical_url:
        raise ValueError('Canonical URL contains unsafe characters')
    if any(c in canonical_url for c in ('<', '>', '"', "'")) or re.search(r'%(?![0-9a-fA-F]{2})', canonical_url):
        raise ValueError('Canonical URL contains unsafe delimiters or malformed encoding')
    parsed = urlsplit(canonical_url)
    if (parsed.hostname not in allowed_hosts or parsed.netloc != parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or '?' in canonical_url or '#' in canonical_url):
        raise ValueError('Canonical URL must be clean and match the approved hostname')
    if (not parsed.path or parsed.path == '/' or not parsed.path.startswith('/')
            or '//' in parsed.path or re.search(r'%(?:2f|5c|2e)', parsed.path, re.I)
            or any(p in ('.', '..') for p in parsed.path.split('/'))):
        raise ValueError('Canonical destination must be an unambiguous article path')
    if is_dummy_rescue_url(canonical_url):
        raise ValueError("Reserved test URL cannot be used as an outbound article")
    return canonical_url


def _identity(canonical_url, *, source, account, publication_date, slot, article_id, allowed_hosts):
    _canonical(canonical_url, allowed_hosts)
    if source not in SOURCES:
        raise ValueError('Unsupported explicit attribution source')
    if not isinstance(account, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', account):
        raise ValueError('Attribution account must be a non-PII account key')
    _day(publication_date)
    if not isinstance(slot, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', slot):
        raise ValueError('Attribution slot must be valid HH:MM')
    if not isinstance(article_id, str) or not article_id.strip() or len(article_id) > 512:
        raise ValueError('Stable article/attempt ID required')
    payload = [source, account, publication_date, slot, canonical_url, article_id]
    token = hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()[:16]
    content = account + '_' + publication_date.replace('-', '') + '_' + slot.replace(':', '') + '_' + token
    return token, content


def build_outbound_url(canonical_url, *, source, account, publication_date, slot, article_id, allowed_hosts):
    _, content = _identity(canonical_url, source=source, account=account,
                          publication_date=publication_date, slot=slot, article_id=article_id,
                          allowed_hosts=allowed_hosts)
    return canonical_url + '?' + urlencode({'utm_source': source, 'utm_medium': MEDIUM_BY_SOURCE[source],
                                           'utm_campaign': CAMPAIGN, 'utm_content': content})


def validate_outbound_url(outbound_url, canonical_url, *, source, account, publication_date, slot, article_id, allowed_hosts):
    expected = build_outbound_url(canonical_url, source=source, account=account,
                                  publication_date=publication_date, slot=slot,
                                  article_id=article_id, allowed_hosts=allowed_hosts)
    if not isinstance(outbound_url, str) or outbound_url != expected:
        raise ValueError('Outbound URL differs from exact verified article and approved attribution')
    return True


def build_attribution_receipt(canonical_url, *, source, account, work_date, publication_date, slot, article_id, allowed_hosts):
    _day(work_date)
    token, content = _identity(canonical_url, source=source, account=account,
                              publication_date=publication_date, slot=slot,
                              article_id=article_id, allowed_hosts=allowed_hosts)
    if work_date > publication_date:
        raise ValueError('Work date cannot follow intended publication date')
    outbound = build_outbound_url(canonical_url, source=source, account=account,
                                  publication_date=publication_date, slot=slot,
                                  article_id=article_id, allowed_hosts=allowed_hosts)
    return {'schema': 'cf-channel-attribution-v1', 'source': source, 'medium': MEDIUM_BY_SOURCE[source],
            'campaign': CAMPAIGN, 'account': account, 'workDate': work_date,
            'publicationDate': publication_date, 'scheduledSlot': slot,
            'canonicalUrl': canonical_url, 'outboundUrl': outbound,
            'postToken': token, 'utmContent': content,
            'articleIdSha256': hashlib.sha256(article_id.encode('utf-8')).hexdigest(),
            'verificationScope': 'exact attribution derivation only; canonical article verified separately'}


# ============================================================================
# AdSense READY filter and explicit traffic focus (Kin / Threads / Naver Bridge)
# ============================================================================
from pathlib import Path

# Explicit CEO traffic focus; this is not a claim of current measured RPM rank.
PRIORITY_CF_DOMAINS = ('woorinote.kr', 'must-good.com', 'must-pick.com')
HIGH_CPC_TIER1_DOMAINS = PRIORITY_CF_DOMAINS  # Compatibility name for existing callers.
HIGH_CPC_TIER2_DOMAINS = (
    'baronote.kr', 'justinfo.co.kr', 'daynote.kr', 'meganote.kr',
    'maxnote.kr', 'topnote.kr', 'smilenote.kr',
)


def is_dummy_rescue_url(value):
    """Match the reserved test slug prefix, after bounded URL decoding, not query text."""
    from urllib.parse import unquote
    raw = str(value or '').strip()
    path = urlsplit(raw).path
    for _ in range(2):
        path = unquote(path)
    return any(segment.casefold().startswith('index-rescue-') for segment in path.split('/'))


DEFAULT_ADSENSE_READY_CF_DOMAINS = frozenset({
    'must-pick.com',
    'baronote.kr',
    'daynote.kr',
    'joynote.kr',
    'justinfo.co.kr',
    'maxnote.kr',
    'meganote.kr',
    'must-good.com',
    'must-joy.com',
    'smilenote.kr',
    'soulnote.kr',
    'topnote.kr',
    'woorinote.kr',
    'nolplace.com',
})
DEFAULT_ADSENSE_PENDING_CF_DOMAINS = frozenset({
    'healthcox.com',
    'tripmarvel.com',
})


def get_adsense_ready_cf_domains(root_dir=None):
    """
    Return the set of CF domains approved for external bridge traffic (`siteStatus == 'READY'`),
    explicitly excluding `GETTING_READY` (under AdSense review, e.g. `healthcox.com`) until approved.
    """
    base = Path(root_dir) if root_dir else Path(__file__).resolve().parents[2]
    cfg_path = base / 'dashboard' / 'data' / 'metrics-config.json'
    ready = set()
    pending = set(DEFAULT_ADSENSE_PENDING_CF_DOMAINS)
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
            for acc_cfg in (cfg.get('adsense_accounts') or {}).values():
                if not isinstance(acc_cfg, dict):
                    continue
                for p_dom in (acc_cfg.get('pending_sites') or []):
                    pending.add(str(p_dom).lower().removeprefix('www.'))
                for dom, st in (acc_cfg.get('site_status') or {}).items():
                    clean_dom = str(dom).lower().removeprefix('www.')
                    if st == 'READY':
                        ready.add(clean_dom)
                        pending.discard(clean_dom)
                    elif st in ('GETTING_READY', 'NEEDS_ATTENTION', 'REQUIRES_REVIEW'):
                        pending.add(clean_dom)
                        ready.discard(clean_dom)
        except Exception:
            pass
    if not ready:
        ready = set(DEFAULT_ADSENSE_READY_CF_DOMAINS) - pending
    return frozenset(ready - pending)


def is_adsense_ready_url_or_domain(url_or_domain, root_dir=None):
    """
    Return True if `url_or_domain` belongs to an AdSense `READY` CF domain (or owned Naver blog),
    and False if it belongs to a `GETTING_READY` domain such as `healthcox.com`.
    """
    if not url_or_domain:
        return False
    raw = str(url_or_domain).strip().lower()
    if raw.startswith('http://') or raw.startswith('https://'):
        host = (urlsplit(raw).hostname or '').lower()
    else:
        host = raw.split('/')[0].lower()
    clean_dom = host.removeprefix('www.')
    if clean_dom in ('blog.naver.com', 'm.blog.naver.com'):
        return True
    ready_set = get_adsense_ready_cf_domains(root_dir=root_dir)
    return clean_dom in ready_set


def domain_cpc_priority_rank(url_or_domain):
    """Return the explicit traffic-focus tier; lower ranks first, not measured RPM."""
    raw = str(url_or_domain or '').strip().lower()
    if raw.startswith('http://') or raw.startswith('https://'):
        host = (urlsplit(raw).hostname or '').lower()
    else:
        host = raw.split('/')[0].lower()
    clean_dom = host.removeprefix('www.')
    if clean_dom in HIGH_CPC_TIER1_DOMAINS:
        return (0, HIGH_CPC_TIER1_DOMAINS.index(clean_dom))
    if clean_dom in HIGH_CPC_TIER2_DOMAINS:
        return (1, HIGH_CPC_TIER2_DOMAINS.index(clean_dom))
    if clean_dom in ('blog.naver.com', 'm.blog.naver.com'):
        return (3, 0)
    return (2, 0)

