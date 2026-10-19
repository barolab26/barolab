"""Shared home/category card layout and narrowly scoped settings deployment."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

REVISION = "20261019_vertical_cards_v3"
STYLE_ID = "barolab-post-card-layout"
CARD_CSS = """
/* BAROLAB_VERTICAL_CARDS_V3: home and category lists only. */
html body .layout:has(#postGrid), html body[data-shell-family][data-domain] .layout:has(#postGrid),
html body .wrap:has(.guide-layout #postGrid) {
  display: block !important; width: 100% !important; max-width: 1120px !important;
  margin-inline: auto !important; padding-inline: 24px !important; box-sizing: border-box !important;
}
html body .main-area:has(#postGrid) { width: 100% !important; min-width: 0 !important; max-width: none !important; }
html body .guide-layout:has(#postGrid) { display: block !important; }
html body .guide-layout:has(#postGrid) .guide-topics nav { flex-direction: row !important; flex-wrap: wrap !important; margin-bottom: 24px; }
html body :is(#postGrid.grid, .guide-layout .grid:has(> .card)) {
  display: grid !important; grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
  gap: 24px !important; width: 100% !important; max-width: 1120px !important;
  margin-inline: auto !important; padding: 0 !important; box-sizing: border-box !important;
}
html body :is(#postGrid, .guide-layout .grid) .card, html body :is(#postGrid, .guide-layout .grid) .card:first-child {
  display: flex !important; flex-direction: column !important; grid-column: auto !important;
  width: 100% !important; min-width: 0 !important; max-width: none !important;
  margin: 0 !important; padding: 0 !important; overflow: hidden !important; box-sizing: border-box !important;
}
html body :is(#postGrid, .guide-layout .grid) .card .card-link, html body :is(#postGrid, .guide-layout .grid) .card:first-child .card-link,
html body :is(#postGrid, .guide-layout .grid) .card.no-image .card-link {
  display: flex !important; flex-direction: column !important; grid-template-columns: none !important;
  width: 100% !important; min-width: 0 !important; height: 100% !important;
  gap: 0 !important; padding: 0 !important; align-items: stretch !important; box-sizing: border-box !important;
}
html body :is(#postGrid, .guide-layout .grid) .card .thumb, html body :is(#postGrid, .guide-layout .grid) .card:first-child .thumb,
html body :is(#postGrid, .guide-layout .grid) .card.no-image .thumb {
  display: block !important; width: 100% !important; height: auto !important;
  min-height: 0 !important; max-height: none !important; aspect-ratio: 16 / 9 !important;
  flex: none !important; flex-shrink: 0 !important; border-radius: 12px 12px 0 0 !important;
  margin: 0 !important; padding: 0 !important; overflow: hidden !important;
  position: relative !important; box-sizing: border-box !important;
}
html body :is(#postGrid, .guide-layout .grid) .card .thumb img, html body :is(#postGrid, .guide-layout .grid) .card .thumb-empty {
  display: block !important; width: 100% !important; height: 100% !important;
  object-fit: cover !important; position: absolute !important; inset: 0 !important; box-sizing: border-box !important;
}
html body :is(#postGrid, .guide-layout .grid) .card .card-body, html body :is(#postGrid, .guide-layout .grid) .card:first-child .card-body {
  display: flex !important; flex-direction: column !important; flex: 1 1 auto !important;
  width: 100% !important; min-width: 0 !important; max-width: none !important;
  padding: 18px 20px !important; gap: 8px !important; margin: 0 !important; box-sizing: border-box !important;
}
html body :is(#postGrid, .guide-layout .grid) .card h3, html body :is(#postGrid, .guide-layout .grid) .card:first-child h3 {
  display: -webkit-box !important; -webkit-box-orient: vertical !important; -webkit-line-clamp: 2 !important;
  line-clamp: 2; overflow: hidden !important; font-size: 1.125rem !important; font-weight: 700 !important; line-height: 1.45 !important;
  max-height: 2.9em !important; margin: 0 !important; word-break: keep-all !important; overflow-wrap: break-word !important;
}
html body :is(#postGrid, .guide-layout .grid) .card .excerpt, html body :is(#postGrid, .guide-layout .grid) .card:first-child .excerpt {
  display: -webkit-box !important; -webkit-box-orient: vertical !important; -webkit-line-clamp: 3 !important;
  line-clamp: 3; overflow: hidden !important; font-size: .925rem !important; line-height: 1.6 !important; color: #475569 !important;
  max-height: 4.8em !important; margin: 0 !important; word-break: keep-all !important; overflow-wrap: break-word !important;
}
html body :is(#postGrid, .guide-layout .grid) .card .meta { margin-top: auto !important; flex-wrap: wrap !important; }
@media (min-width: 640px) and (max-width: 1023px) {
  html body :is(#postGrid.grid, .guide-layout .grid:has(> .card)) { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 20px !important; }
  html body .layout:has(#postGrid), html body[data-shell-family][data-domain] .layout:has(#postGrid),
  html body .wrap:has(.guide-layout #postGrid) { padding-inline: 20px !important; }
}
@media (max-width: 639px) {
  html body :is(#postGrid.grid, .guide-layout .grid:has(> .card)) { grid-template-columns: minmax(0, 1fr) !important; gap: 16px !important; }
  html body .layout:has(#postGrid), html body[data-shell-family][data-domain] .layout:has(#postGrid),
  html body .wrap:has(.guide-layout #postGrid) { padding-inline: 16px !important; }
}
""".strip()


def patch_card_head(head: str) -> str:
    """Preserve all existing ads/scripts/verification tags; replace only our block."""
    pattern = rf'<style\b[^>]*\bid=["\']{STYLE_ID}["\'][^>]*>.*?</style>'
    cleaned = re.sub(pattern, "", head, flags=re.S | re.I).rstrip()
    return cleaned + f'\n<style id="{STYLE_ID}">\n{CARD_CSS}\n</style>'


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def patch_mustpick_cards(source: str) -> str:
    """The older mustpick renderer lacks both thumbnail and body containers."""
    marker = "/* BAROLAB_MUSTPICK_VERTICAL_CARDS_V1 */"
    if marker in source:
        return source
    start = source.index("function renderHomePage(")
    end = source.index('__name(renderHomePage, "renderHomePage");', start)
    section = source[start:end]
    ssr = '    return `<article class="card"><a class="card-link" href="/${escapeHtml(p.slug)}">\n      <span class="cat">'
    ssr_new = '    return `<article class="card"><a class="card-link" href="/${escapeHtml(p.slug)}">\n      <div class="thumb">${p.thumbnail ? `<img src="${escapeHtml(p.thumbnail)}" alt="${escapeHtml(p.title)}" loading="lazy" />` : `<div class="thumb-empty" aria-hidden="true"></div>`}</div><div class="card-body">\n      <span class="cat">'
    close = '    </a></article>`;'
    client = "    return '<article class=\"card\"><a class=\"card-link\" href=\"/'+escHtml(p.slug)+'\"><span class=\"cat\">'"
    client_new = "    return '<article class=\"card\"><a class=\"card-link\" href=\"/'+escHtml(p.slug)+'\"><div class=\"thumb\">'+(p.thumbnail?'<img src=\"'+escHtml(p.thumbnail).replace(/\"/g,'&quot;')+'\" alt=\"'+escHtml(p.title).replace(/\"/g,'&quot;')+'\" loading=\"lazy\" />':'<div class=\"thumb-empty\" aria-hidden=\"true\"></div>')+'</div><div class=\"card-body\"><span class=\"cat\">'"
    client_close = "+'</div></a></article>';"
    for anchor in (ssr, close, client, client_close):
        if section.count(anchor) != 1:
            raise ValueError("Mustpick card renderer anchor changed; review required")
    section = section.replace(ssr, ssr_new).replace(close, '    </div></a></article>`;')
    section = section.replace(client, client_new).replace(client_close, "+'</div></div></a></article>';")
    patched = source[:start] + marker + "\n" + section + source[end:]
    return re.sub(r'_baro_v=[A-Za-z0-9_]+', '_baro_v=' + REVISION, patched)


def verify_public_layout(domain: str) -> dict:
    """Inspect actual normal public home/category responses, not cache-busting URLs."""
    import requests
    from bs4 import BeautifulSoup
    from cf_posting.domain_themes import DOMAIN_WORKER_NAMES
    if domain not in DOMAIN_WORKER_NAMES:
        raise ValueError('Unknown domain')
    base = 'https://www.' + domain
    pages, pending = [], [base + '/']
    with requests.Session() as session:
        while pending:
            url = pending.pop(0)
            response = session.get(url, timeout=30)
            response.raise_for_status(); response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            if not pages:
                pending = list(dict.fromkeys(urljoin(base, a['href']) for a in soup.select('a[href^="/?cat="]')))
            styles = soup.select('style#' + STYLE_ID)
            cards = soup.select(':is(#postGrid, .guide-layout .grid) .card')
            valid_shape = all(card.select_one('.card-link > .thumb') is not None
                              and card.select_one('.card-link > .card-body') is not None for card in cards)
            css_exact = len(styles) == 1 and styles[0].get_text().strip() == CARD_CSS
            pages.append({'url': url, 'httpStatus': response.status_code, 'cardCount': len(cards),
                          'imageCount': len(soup.select(':is(#postGrid, .guide-layout .grid) .thumb img')),
                          'emptyImageCount': len(soup.select(':is(#postGrid, .guide-layout .grid) .thumb-empty')),
                          'ownedStyleCount': len(styles), 'cssExact': css_exact,
                          'cardStructureValid': valid_shape, 'postGridPresent': soup.select_one('#postGrid') is not None,
                          'htmlSha256': digest(response.text),
                          'passed': css_exact and valid_shape and soup.select_one('#postGrid') is not None})
    return {'domain': domain, 'checkedAt': datetime.now(timezone.utc).isoformat(),
            'passed': all(page['passed'] for page in pages), 'pages': pages}


def deploy_card_layout(domain: str, *, backup_dir: Path, apply=False) -> dict:
    """Use existing site authentication; write adsense_code only, never credentials."""
    import requests
    from bs4 import BeautifulSoup
    from dotenv import dotenv_values
    from cf_posting.domain_themes import DOMAIN_WORKER_NAMES, BASE_DIR
    from cf_posting.seo_templates import verify_worker_route, worker_module, worker_module_name, preserved_metadata
    from common.content_maintenance import api_key, cache_binding

    if domain not in DOMAIN_WORKER_NAMES:
        raise ValueError("Domain is not in the configured 16-site inventory")
    base = "https://www." + domain
    zone, cf_headers = cache_binding(domain)
    with requests.Session() as cf, requests.Session() as site:
        cf.headers.update({key: value for key, value in cf_headers.items() if key.lower() != 'content-type'})
        zone_resp = cf.get(f"https://api.cloudflare.com/client/v4/zones/{zone}", timeout=30)
        zone_resp.raise_for_status()
        zone_data = zone_resp.json()["result"]
        if zone_data["name"] != domain:
            raise ValueError("Exact domain zone mismatch")
        account = zone_data["account"]["id"]
        worker = DOMAIN_WORKER_NAMES[domain]
        route = verify_worker_route(domain, worker, session=cf, account=account)
        worker_resp = cf.get(f"https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts/{worker}", timeout=30)
        worker_resp.raise_for_status()
        worker_source = worker_module(worker_resp)
        patched_worker = patch_mustpick_cards(worker_source) if domain == 'must-pick.com' else worker_source
        cache_versions = set(re.findall(r'_baro_v=([A-Za-z0-9_]+)', worker_source))
        try:
            site.headers["x-api-key"] = api_key(domain)
        except ValueError:
            pass
        current = site.get(base + "/api/settings", timeout=25)
        if current.status_code in (401, 403):
            cfg = dotenv_values(BASE_DIR / ".env")
            password = cfg.get(domain.split(".")[0].replace("-", "").upper() + "_CF_ADMIN_PASSWORD")
            if not password:
                raise ValueError("Existing site authentication unavailable")
            login = site.post(base + "/api/auth/login", json={"password": password}, timeout=25)
            login.raise_for_status()
            site.headers.pop("x-api-key", None)
            site.headers["Authorization"] = "Bearer " + login.json()["token"]
            current = site.get(base + "/api/settings", timeout=25)
        current.raise_for_status()
        settings = current.json()["settings"]
        before = settings.get("adsense_code", "")
        after = patch_card_head(before)
        backup_dir.mkdir(parents=True, exist_ok=True)
        if patched_worker != worker_source:
            (backup_dir / (domain + '-worker-before.js')).write_text(worker_source, encoding='utf-8')
            (backup_dir / (domain + '-worker-after.js')).write_text(patched_worker, encoding='utf-8')
        backup = backup_dir / (domain + "-head-before.html")
        if not backup.exists():
            backup.write_text(before, encoding="utf-8")
        (backup_dir / (domain + "-head-after.html")).write_text(after, encoding="utf-8")
        home = requests.get(base + "/", timeout=30)
        home.raise_for_status(); home.encoding = "utf-8"
        soup = BeautifulSoup(home.text, "html.parser")
        categories = list(dict.fromkeys(urljoin(base, a["href"]) for a in soup.select('a[href^="/?cat="]')))
        pages = [base + "/"] + categories
        result = {"domain": domain, "revision": REVISION, "route": route,
                  "beforeSha256": digest(before), "afterSha256": digest(after),
                  "workerSha256": digest(worker_source), "workerChanged": False,
                  "status": "prepared", "categoryCount": len(categories)}
        if apply:
            check = site.get(base + "/api/settings", timeout=25); check.raise_for_status()
            if check.json()["settings"].get("adsense_code", "") != before:
                raise ValueError("Concurrent head change; refusing overwrite")
            if patched_worker != worker_source:
                endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts/{worker}"
                worker_settings = cf.get(endpoint + '/settings', timeout=30)
                worker_settings.raise_for_status()
                metadata = preserved_metadata(worker_settings.json()['result'])
                module_name = worker_module_name(worker_resp)
                metadata['main_module'] = module_name
                latest = cf.get(endpoint, timeout=30); latest.raise_for_status()
                if worker_module(latest) != worker_source:
                    raise ValueError('Concurrent Worker edit; refusing overwrite')
                changed_worker = cf.put(endpoint, files={
                    'metadata': ('metadata.json', json.dumps(metadata), 'application/json'),
                    module_name: (module_name, patched_worker.encode(), 'application/javascript+module')}, timeout=40)
                changed_worker.raise_for_status()
                if changed_worker.json().get('success') is not True:
                    raise ValueError('Worker update unconfirmed')
                readback = cf.get(endpoint, timeout=30); readback.raise_for_status()
                if worker_module(readback) != patched_worker:
                    raise ValueError('Worker source readback mismatch')
                result.update(workerChanged=True, workerAfterSha256=digest(patched_worker))
            if after != before:
                updated = site.put(base + "/api/settings", json={"adsense_code": after}, timeout=30)
                updated.raise_for_status()
                if updated.json().get("success") is not True:
                    raise ValueError("Settings update not confirmed")
            verify = site.get(base + "/api/settings", timeout=25); verify.raise_for_status()
            saved = verify.json()["settings"]
            if saved.get("adsense_code") != after:
                raise ValueError("Saved head does not match candidate")
            changed = [k for k in set(settings) | set(saved) if k != "adsense_code" and settings.get(k) != saved.get(k)]
            if changed:
                raise ValueError("Unrelated settings changed during deployment")
            purge_urls = pages + [p + ("&" if "?" in p else "?") + "_baro_v=" + v for p in pages for v in cache_versions]
            for offset in range(0, len(purge_urls), 30):
                purge = cf.post(f"https://api.cloudflare.com/client/v4/zones/{zone}/purge_cache",
                                json={"files": purge_urls[offset:offset + 30]}, timeout=30)
                purge.raise_for_status()
                if purge.json().get("success") is not True:
                    raise ValueError("Exact home/category cache purge unconfirmed")
            result.update(status="deployed", preservedOtherSettings=True, cachePurgedUrls=len(purge_urls))
        result["checkedAt"] = datetime.now(timezone.utc).isoformat()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", action="append", required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    for domain in args.domain:
        result = deploy_card_layout(domain, backup_dir=args.backup_dir, apply=args.apply)
        (args.backup_dir / (domain + "-deployment.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
