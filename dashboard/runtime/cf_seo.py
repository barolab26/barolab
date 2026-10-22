"""Apply a narrow, repeatable SEO patch to existing Cloudflare SSR templates.

Never deploy a local full template over a live Worker: each site's current script
and settings are read first, and only its published-post renderer is changed.
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import fnmatch
import json
import re
from pathlib import Path

ROBOTS = "index,follow,max-image-preview:large,max-snippet:-1"
REVISION = "20261019_postseo_v1"


def patch_public_post_sort(source: str) -> str:
    """Add explicit popularity ordering to the existing public listing only."""
    start_marker = '  if (method === "GET" && path === "/api/posts") {'
    end_marker = '  if (method === "POST" && path === "/api/posts") {'
    if source.count(start_marker) != 1 or source.count(end_marker) != 1:
        raise ValueError("Post-list route changed; review before patching")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    section = source[start:end]
    status_line = '    const status = String(url.searchParams.get("status") || "published");'
    sort_line = '    const sort = status === "published" && url.searchParams.get("sort") === "views" ? "views" : "recent";'
    old_order = '      sql += " ORDER BY COALESCE(publish_at, created_at) DESC LIMIT ? OFFSET ?";'
    new_order = ('      sql += sort === "views"\n'
                 '        ? " ORDER BY views DESC, id DESC LIMIT ? OFFSET ?"\n'
                 '        : " ORDER BY COALESCE(publish_at, created_at) DESC LIMIT ? OFFSET ?";')
    old_response = '    return json({ success: true, posts: rows.results || [], page, limit });'
    new_response = '    return json({ success: true, posts: rows.results || [], page, limit, sort });'
    if sort_line in section:
        # Reject partial/different patches instead of silently declaring support.
        if any(section.count(item) != 1 for item in (status_line, sort_line, new_order, new_response)):
            raise ValueError("Unexpected existing post-sort patch")
        return source
    if any(section.count(item) != 1 for item in (status_line, old_order, old_response)):
        raise ValueError("Post-list query changed; review before patching")
    section = section.replace(status_line, status_line + "\n" + sort_line, 1)
    section = section.replace(old_order, new_order, 1).replace(old_response, new_response, 1)
    return source[:start] + section + source[end:]


def patch_post_template(source: str) -> str:
    start = source.index("function renderPostPage(")
    end_marker = '__name(renderPostPage, "renderPostPage");'
    if end_marker not in source[start:]:
        end_marker = '\nfunction injectMidAd('
    end = source.index(end_marker, start)
    section = source[start:end]
    if not re.search(r'"@type"\s*:\s*"BlogPosting"', section):
        raise ValueError("Expected real-post BlogPosting schema is absent")
    if '"@type": "FAQPage"' in section and "post.content" not in section:
        raise ValueError("FAQ schema must derive from the displayed post content")
    tag = f'<meta name="robots" content="{ROBOTS}" />'
    existing = re.findall(r'<meta\s+name="robots"[^>]*>', section)
    if existing:
        if any("noindex" in item.lower() for item in existing):
            raise ValueError("Refusing to override an intentional noindex post renderer")
        section = re.sub(r'<meta\s+name="robots"[^>]*>', tag, section)
    else:
        anchor = '<meta name="viewport" content="width=device-width, initial-scale=1" />'
        if section.count(anchor) not in (1, 2):
            raise ValueError("Post viewport anchor changed; review before patching")
        # The existing must-pick renderer has two public post variants.
        section = section.replace(anchor, anchor + "\n" + tag)
    patched = source[:start] + section + source[end:]
    # Existing cache keys need a new generation so current articles update too.
    patched = re.sub(r'_baro_v=[A-Za-z0-9_]+', "_baro_v=" + REVISION, patched)
    return patched.replace('new Request(url.toString(), { method: "GET" })',
        'new Request(url.toString() + (url.search ? "&" : "?") + "_baro_v=' +
        REVISION + '", { method: "GET" })')


def worker_module_name(response) -> str:
    content_type = response.headers.get("Content-Type", "")
    if "multipart/" not in content_type:
        return "index.js"
    message = email.message_from_bytes(
        ("Content-Type: " + content_type + "\r\n\r\n").encode() + response.content,
        policy=email.policy.default,
    )
    parts = list(message.iter_parts())
    if len(parts) != 1:
        raise ValueError("Multi-module Worker requires explicit preservation review")
    name = parts[0].get_filename() or parts[0].get_param("name", header="Content-Disposition")
    if name not in ("index.js", "worker.js"):
        raise ValueError("Unknown module name requires explicit preservation review")
    return name


def worker_module(response) -> str:
    worker_module_name(response)
    content_type = response.headers.get("Content-Type", "")
    if "multipart/" not in content_type:
        return response.text
    message = email.message_from_bytes(
        ("Content-Type: " + content_type + "\r\n\r\n").encode() + response.content,
        policy=email.policy.default,
    )
    return next(message.iter_parts()).get_payload(decode=True).decode("utf-8")


def preserved_metadata(settings: dict) -> dict:
    keys = ("compatibility_date", "compatibility_flags", "usage_model", "placement",
            "tags", "tail_consumers", "logpush", "observability", "limits")
    metadata = {key: settings[key] for key in keys if key in settings}
    metadata.update(main_module="index.js", keep_assets=True,
                    keep_bindings=sorted({b["type"] for b in settings.get("bindings", [])}))
    if not metadata.get("compatibility_date"):
        raise ValueError("Cannot preserve unknown compatibility date")
    return metadata


def verify_worker_route(domain: str, worker: str, *, session, account: str) -> dict:
    """Fail closed if the configured Worker is not the current www root route."""
    api = "https://api.cloudflare.com/client/v4"
    zones = session.get(api + "/zones", params={"name": domain}, timeout=30)
    zones.raise_for_status()
    routes = []
    for zone in zones.json().get("result", []):
        response = session.get(api + f'/zones/{zone["id"]}/workers/routes', timeout=30)
        response.raise_for_status()
        routes.extend(response.json().get("result", []))
    matches = [r for r in routes if fnmatch.fnmatch("https://www." + domain + "/", r["pattern"])
               or fnmatch.fnmatch("www." + domain + "/", r["pattern"])]
    if matches:
        selected = max(matches, key=lambda item: len(item["pattern"].replace("*", "")))
        if selected.get("script") == worker:
            return {"verified": True, "route": selected["pattern"], "worker": worker}
        raise ValueError("Configured Worker differs from actual www route")
    custom = session.get(api + f"/accounts/{account}/workers/domains", timeout=30)
    custom.raise_for_status()
    if any(x.get("hostname") == "www." + domain and x.get("service") == worker
           for x in custom.json().get("result", [])):
        return {"verified": True, "route": "www." + domain, "worker": worker}
    raise ValueError("No verified www Worker route in the configured Cloudflare account")


def deploy_post_seo(domain: str, worker: str, *, session, account: str,
                    backup_dir: Path, apply: bool = False) -> dict:
    """Return safe evidence only. Session owns credentials; never serialize it."""
    route = verify_worker_route(domain, worker, session=session, account=account)
    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts/{worker}"
    current = session.get(endpoint, timeout=30)
    current.raise_for_status()
    source = worker_module(current)
    module_name = worker_module_name(current)
    settings_response = session.get(endpoint + "/settings", timeout=30)
    settings_response.raise_for_status()
    settings = settings_response.json()["result"]
    metadata = preserved_metadata(settings)
    metadata["main_module"] = module_name
    patched = patch_post_template(source)
    backup_dir.mkdir(parents=True, exist_ok=True)
    before_path = backup_dir / f"{worker}-before.js"
    if not before_path.exists():
        before_path.write_bytes(source.encode("utf-8"))
    (backup_dir / f"{worker}-after.js").write_bytes(patched.encode("utf-8"))
    digest = lambda text: hashlib.sha256(text.encode()).hexdigest()
    result = dict(domain=domain, worker=worker, beforeSha256=digest(source),
                  afterSha256=digest(patched), status="prepared", revision=REVISION,
                  route=route, moduleName=module_name)
    if apply and patched != source:
        # Detect concurrent edits immediately before a write.
        check = session.get(endpoint, timeout=30)
        check.raise_for_status()
        if digest(worker_module(check)) != digest(source):
            raise RuntimeError("Worker changed concurrently; deployment stopped")
        response = session.put(endpoint, files={
            "metadata": ("metadata.json", json.dumps(metadata), "application/json"),
            module_name: (module_name, patched.encode(), "application/javascript+module"),
        }, timeout=40)
        response.raise_for_status()
        if response.json().get("success") is not True:
            raise RuntimeError("Cloudflare did not confirm deployment")
        result["status"] = "deployed"
    elif apply:
        result["status"] = "already_applied"
    return result


def deploy_configured_post_seo(domain: str, *, backup_dir: Path, apply=False):
    """Resolve the existing site's own account, including the separate nolplace account."""
    import requests
    from common.content_maintenance import cache_binding
    from dashboard.runtime.cf_themes import DOMAIN_WORKER_NAMES
    worker = DOMAIN_WORKER_NAMES[domain]
    zone, headers = cache_binding(domain)
    with requests.Session() as session:
        session.headers.update({k: v for k, v in headers.items() if k != "Content-Type"})
        response = session.get(f"https://api.cloudflare.com/client/v4/zones/{zone}", timeout=30)
        response.raise_for_status()
        account = response.json()["result"]["account"]["id"]
        return deploy_post_seo(domain, worker, session=session, account=account,
                               backup_dir=backup_dir, apply=apply)
