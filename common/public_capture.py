"""Smart section-scrolling public capture and official high-res original photo extractor."""
import asyncio
import hashlib
import io
import ipaddress
import json
import re
import socket
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests


SMART_SECTION_KEYWORDS = (
    '모노레일',
    '이용요금',
    '요금안내',
    '입장요금',
    '주차안내',
    '주차장',
    '오시는길',
    '찾아오시는 길',
    '코스안내',
    '관람안내',
    '예매하기',
    '시간표',
    '승강장',
    '환불',
    '할인',
    '증상',
    '치료',
    '스트레칭',
    '운동법',
    '진단',
)

BLOCKED_DOWNLOAD_EXTENSIONS = (
    '.hwp', '.hwpx', '.zip', '.rar', '.7z', '.tar', '.gz',
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.csv',
    '.exe', '.msi', '.dmg', '.apk', '.iso',
)

DOWNLOAD_TRIGGER_PATTERNS = (
    '/download.jsp', '/download.do', '/filedown', '/filedownload',
    'atchfileid=', 'file_down', 'board_sequence=',
)

_URL_FETCH_CACHE = {}
_DEFAULT_CACHE_DIR = Path.home() / '.barolab' / 'runtime' / 'url-cache'


def sha(value):
    return hashlib.sha256(value).hexdigest()


def is_blocked_download_url(url):
    """Return True if URL points to a non-PDF binary attachment extension (.hwp, .zip, .doc, etc.)."""
    if not isinstance(url, str) or not url.strip():
        return False
    p = urlsplit(url.strip())
    path_lower = urllib.parse.unquote(p.path or '').lower()
    query_lower = urllib.parse.unquote(p.query or '').lower()
    if any(path_lower.endswith(ext) for ext in BLOCKED_DOWNLOAD_EXTENSIONS):
        return True
    if any(ext in query_lower for ext in BLOCKED_DOWNLOAD_EXTENSIONS):
        return True
    return False


def is_pdf_or_download_trigger_url(url):
    """Return True if URL is likely a PDF or server download script."""
    if not isinstance(url, str) or not url.strip():
        return False
    if is_blocked_download_url(url):
        return True
    p = urlsplit(url.strip())
    path_lower = urllib.parse.unquote(p.path or '').lower()
    query_lower = urllib.parse.unquote(p.query or '').lower()
    combined = path_lower + '?' + query_lower
    if path_lower.endswith('.pdf') or '.pdf' in query_lower:
        return True
    return any(pat in combined for pat in DOWNLOAD_TRIGGER_PATTERNS)


def _decode_content_disposition_filename(cd_header):
    if not cd_header:
        return ''
    m_utf8 = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;\r\n]+)", cd_header)
    if m_utf8:
        return urllib.parse.unquote(m_utf8.group(1).strip(' "\''))
    m_plain = re.search(r'filename\s*=\s*"?([^";\r\n]+)"?', cd_header, re.I)
    if m_plain:
        raw = m_plain.group(1).strip(' "\'')
        try:
            raw_bytes = raw.encode('latin-1')
            for enc in ('utf-8', 'cp949', 'euc-kr'):
                try:
                    return raw_bytes.decode(enc)
                except UnicodeDecodeError:
                    continue
        except UnicodeEncodeError:
            pass
        return urllib.parse.unquote(raw)
    return ''


def extract_pdf_in_memory(raw_bytes, url='', content_disposition=''):
    """Extract clean text, page-level text, quotes, and title from PDF bytes in memory without touching Chrome."""
    page_texts = []
    title = _decode_content_disposition_filename(content_disposition)
    if title.lower().endswith('.pdf'):
        title = title[:-4].strip()

    try:
        import pypdfium2 as pdfium
        pdf_doc = pdfium.PdfDocument(raw_bytes)
        try:
            for idx in range(len(pdf_doc)):
                page = pdf_doc[idx]
                textpage = page.get_textpage()
                raw_txt = textpage.get_text_bounded() or ''
                clean_txt = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]+', ' ', raw_txt)
                clean_txt = re.sub(r'\s+', ' ', clean_txt).strip()
                page_texts.append(clean_txt)
        finally:
            try:
                pdf_doc.close()
            except Exception:
                pass
    except Exception:
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
            for page in reader.pages:
                raw_txt = page.extract_text() or ''
                clean_txt = re.sub(r'\s+', ' ', raw_txt).strip()
                page_texts.append(clean_txt)
        except Exception:
            pass

    joined_parts = []
    quotes = []
    for idx, p_txt in enumerate(page_texts):
        if not p_txt:
            continue
        joined_parts.append(f"[{idx + 1}페이지] {p_txt}")
        # Split sentences/clauses cleanly for bounded quotes (never raw binary!)
        for seg in re.split(r'(?<=[.!?다요음함])\s+|\s{2,}', p_txt):
            seg = seg.strip()
            if 30 <= len(seg) <= 280 and seg not in quotes:
                quotes.append(seg)
                if len(quotes) >= 15:
                    break

    full_text = '\n\n'.join(joined_parts)[:20000].strip()
    if not quotes and full_text:
        quotes = [full_text[:220]]
    if not title:
        if page_texts and page_texts[0]:
            title = page_texts[0][:60].strip()
        else:
            title = urllib.parse.unquote(urlsplit(url).path.rsplit('/', 1)[-1] or '공식 PDF 문서')

    return {
        'title': title,
        'text': full_text,
        'quotes': quotes[:15],
        'page_texts': page_texts,
        'page_count': len(page_texts),
    }


def fetch_url_cached(url, *, cache_dir=None, timeout=15, allow_redirects=True, ttl_seconds=21600):
    """
    Single-fetch URL cache (1회 조회 원칙):
    Fetches any URL at most once per pipeline run / cache TTL, automatically detects
    PDFs vs non-PDF attachment downloads vs HTML, extracts PDF text in memory,
    and caches PDF bytes in `.url-cache` (never in user's Downloads folder).
    """
    if not isinstance(url, str) or not url.strip():
        return {'kind': 'error', 'url': str(url), 'reason': 'empty_url'}
    norm_url = url.strip()
    if is_blocked_download_url(norm_url):
        res = {
            'kind': 'blocked_attachment',
            'url': norm_url,
            'status_code': 0,
            'reason': 'Blocked non-PDF attachment extension in URL',
            'collectedAt': datetime.now(timezone.utc).isoformat(),
        }
        _URL_FETCH_CACHE[norm_url] = res
        return res

    now_ts = time.time()
    mem = _URL_FETCH_CACHE.get(norm_url)
    if mem and (now_ts - mem.get('_cached_ts', 0) < ttl_seconds):
        return mem

    cache_root = (Path(cache_dir) / '.url-cache') if cache_dir else _DEFAULT_CACHE_DIR
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        cache_root = _DEFAULT_CACHE_DIR
        cache_root.mkdir(parents=True, exist_ok=True)

    url_hash = sha(norm_url.encode('utf-8'))[:24]
    meta_path = cache_root / f"{url_hash}.json"
    pdf_path = cache_root / f"{url_hash}.pdf"

    if meta_path.is_file():
        try:
            disk_meta = json.loads(meta_path.read_text(encoding='utf-8'))
            if now_ts - disk_meta.get('_cached_ts', 0) < ttl_seconds:
                if disk_meta.get('kind') != 'pdf' or pdf_path.is_file():
                    _URL_FETCH_CACHE[norm_url] = disk_meta
                    return disk_meta
        except Exception:
            pass

    try:
        with requests.get(
            norm_url,
            timeout=timeout,
            allow_redirects=allow_redirects,
            stream=True,
            headers={'User-Agent': 'Mozilla/5.0'},
        ) as response:
            status_code = response.status_code
            if status_code != 200:
                res = {
                    'kind': 'http_error',
                    'url': norm_url,
                    'status_code': status_code,
                    'reason': f'HTTP {status_code}',
                    'collectedAt': datetime.now(timezone.utc).isoformat(),
                    '_cached_ts': now_ts,
                }
                _URL_FETCH_CACHE[norm_url] = res
                return res

            content_type = (response.headers.get('Content-Type') or '').lower()
            content_disp = response.headers.get('Content-Disposition') or ''
            cd_filename = _decode_content_disposition_filename(content_disp)

            iterator = response.iter_content(chunk_size=16384)
            first_chunk = next(iterator, b'')
            is_pdf_magic = first_chunk.startswith(b'%PDF-')
            is_pdf_header = (
                is_pdf_magic
                or 'application/pdf' in content_type
                or cd_filename.lower().endswith('.pdf')
                or urlsplit(norm_url).path.lower().endswith('.pdf')
            )
            is_attachment_header = (
                'attachment' in content_disp.lower()
                or any(
                    b_ct in content_type
                    for b_ct in (
                        'application/octet-stream',
                        'application/x-hwp',
                        'application/haansofthwp',
                        'application/zip',
                        'application/msword',
                        'application/vnd.ms-',
                        'application/vnd.openxmlformats',
                    )
                )
                or (cd_filename and any(cd_filename.lower().endswith(ext) for ext in BLOCKED_DOWNLOAD_EXTENSIONS))
            )

            if is_attachment_header and not is_pdf_magic:
                # Immediately close stream without downloading non-PDF attachment
                res = {
                    'kind': 'blocked_attachment',
                    'url': norm_url,
                    'status_code': status_code,
                    'content_type': content_type,
                    'content_disposition': content_disp,
                    'filename': cd_filename,
                    'reason': f'Blocked non-PDF attachment download ({content_type}; {cd_filename or content_disp})',
                    'collectedAt': datetime.now(timezone.utc).isoformat(),
                    '_cached_ts': now_ts,
                }
                try:
                    meta_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
                except Exception:
                    pass
                _URL_FETCH_CACHE[norm_url] = res
                return res

            if is_pdf_header and is_pdf_magic:
                chunks = [first_chunk]
                size = len(first_chunk)
                started = time.monotonic()
                for chunk in iterator:
                    size += len(chunk)
                    if size > 18_000_000 or (time.monotonic() - started) > 25:
                        break
                    chunks.append(chunk)
                raw_bytes = b''.join(chunks)
                try:
                    pdf_path.write_bytes(raw_bytes)
                except Exception:
                    pass
                pdf_extracted = extract_pdf_in_memory(raw_bytes, url=norm_url, content_disposition=content_disp)
                res = {
                    'kind': 'pdf',
                    'url': norm_url,
                    'status_code': status_code,
                    'content_type': content_type,
                    'content_disposition': content_disp,
                    'filename': cd_filename,
                    'title': pdf_extracted['title'],
                    'text': pdf_extracted['text'],
                    'quotes': pdf_extracted['quotes'],
                    'page_texts': pdf_extracted['page_texts'],
                    'page_count': pdf_extracted['page_count'],
                    'pdf_cache_path': str(pdf_path.resolve()),
                    'bodySha256': sha(pdf_extracted['text'].encode('utf-8')),
                    'collectedAt': datetime.now(timezone.utc).isoformat(),
                    '_cached_ts': now_ts,
                }
                try:
                    meta_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
                except Exception:
                    pass
                _URL_FETCH_CACHE[norm_url] = res
                return res

            # Standard HTML / XML / text response
            chunks = [first_chunk]
            size = len(first_chunk)
            started = time.monotonic()
            for chunk in iterator:
                size += len(chunk)
                if size > 2_000_000 or (time.monotonic() - started) > 25:
                    raise RuntimeError('Evidence response exceeds bounded limit')
                chunks.append(chunk)
            raw_bytes = b''.join(chunks)
            enc = response.encoding if (response.encoding and response.encoding.lower() != 'iso-8859-1') else 'utf-8'
            html_text = raw_bytes.decode(enc, errors='replace')
            res = {
                'kind': 'html',
                'url': norm_url,
                'status_code': status_code,
                'content_type': content_type,
                'html': html_text,
                'collectedAt': datetime.now(timezone.utc).isoformat(),
                '_cached_ts': now_ts,
            }
            try:
                meta_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception:
                pass
            _URL_FETCH_CACHE[norm_url] = res
            return res
    except Exception as exc:
        res = {
            'kind': 'error',
            'url': norm_url,
            'status_code': 0,
            'reason': f'{type(exc).__name__}: {str(exc)[:240]}',
            'collectedAt': datetime.now(timezone.utc).isoformat(),
            '_cached_ts': now_ts,
        }
        _URL_FETCH_CACHE[norm_url] = res
        return res


def render_pdf_page_to_png(url, output_path, *, target_keywords=(), cache_dir=None):
    """
    Render the most relevant page of a PDF (matching target_keywords, tables, exercise guides, or diagrams)
    directly in Python memory using pypdfium2 into a high-resolution PNG screenshot (width >= 1440px).
    Zero browser download or popup is ever triggered.
    """
    import pypdfium2 as pdfium
    cached = fetch_url_cached(url, cache_dir=cache_dir)
    if cached.get('kind') != 'pdf':
        raise RuntimeError(f"URL is not a renderable PDF ({cached.get('kind')}: {cached.get('reason')})")
    pdf_cache_path = Path(cached.get('pdf_cache_path', ''))
    if not pdf_cache_path.is_file():
        raise RuntimeError('Cached PDF bytes not found for in-memory rendering')

    raw_bytes = pdf_cache_path.read_bytes()
    pdf_doc = pdfium.PdfDocument(raw_bytes)
    try:
        page_count = len(pdf_doc)
        if page_count == 0:
            raise RuntimeError('PDF document has 0 pages')
        page_texts = cached.get('page_texts') or []
        priority_kws = list(dict.fromkeys(
            [k for k in (target_keywords or ()) if k]
            + ['운동', '스트레칭', '치료', '증상', '진단', '표', '단계', '방법', '안내', '요금', '코스', '배치도', '기준']
        ))

        best_idx = 0
        best_score = -1
        best_kw = None
        for idx in range(page_count):
            ptxt = page_texts[idx] if idx < len(page_texts) else ''
            score = min(len(ptxt) // 100, 10)
            matched_here = None
            for rank, kw in enumerate(priority_kws):
                if kw and kw in ptxt:
                    bonus = max(25 - rank * 2, 5)
                    score += bonus
                    if matched_here is None:
                        matched_here = kw
            if score > best_score:
                best_score = score
                best_idx = idx
                best_kw = matched_here

        page = pdf_doc[best_idx]
        w_pt = max(1.0, float(page.get_width()))
        scale = max(2.2, 1440.0 / w_pt)
        bitmap = page.render(scale=scale)
        pil_img = bitmap.to_pil()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pil_img.save(str(output_path), format='PNG')
        width, height = pil_img.size
        page_text = (page_texts[best_idx] if best_idx < len(page_texts) else cached.get('text', ''))[:4000]
        return {
            'pageIndex': best_idx + 1,
            'pageCount': page_count,
            'matchedKeyword': best_kw or (priority_kws[0] if priority_kws else '핵심 안내'),
            'width': width,
            'height': height,
            'pageText': page_text or cached.get('text', '')[:4000],
            'title': cached.get('title', '공식 PDF 안내문'),
        }
    finally:
        try:
            pdf_doc.close()
        except Exception:
            pass



def public_https_url(value):
    if not isinstance(value, str) or value != value.strip():
        raise ValueError('Invalid public source URL')
    p = urlsplit(value)
    host = (p.hostname or '').lower()
    if (p.scheme != 'https' or not host or p.username or p.password or p.port not in (None, 443)
            or host == 'localhost' or host.endswith(('.local', '.localhost', '.internal', '.test', '.invalid'))
            or '.' not in host or '\\' in value):
        raise ValueError('Public HTTPS source required')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError('Private source address rejected')
    return urlunsplit((p.scheme, p.netloc, p.path or '/', p.query, ''))


def assert_public_dns(url):
    host = urlsplit(public_https_url(url)).hostname
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('Source DNS is not exclusively public')


def extract_target_keywords(text, extra_keywords=()):
    """Extract prioritized section keywords from request description/action and defaults."""
    combined = str(text or '')
    found = []
    for kw in list(extra_keywords) + list(SMART_SECTION_KEYWORDS):
        if kw and kw in combined and kw not in found:
            found.append(kw)
    for kw in SMART_SECTION_KEYWORDS:
        if kw not in found:
            found.append(kw)
    return found


def plan_public_captures(missing, brief, facts, sources, official_url, *, max_plans=4):
    """Bind explicit requests/section fact references and attach smart scroll keywords."""
    source_index = {}
    for source in sources:
        try:
            url = public_https_url(source['url'])
            text = source['text']
            acquired = datetime.fromisoformat(source['collectedAt'].replace('Z', '+00:00'))
            if not official_url(url) or not isinstance(text, str) or not text.strip() or acquired.tzinfo is None:
                continue
            digest = sha(text.encode('utf-8'))
            if source.get('bodySha256', digest) != digest:
                continue
            source_index[url] = digest
        except (KeyError, TypeError, ValueError):
            continue
    fact_index = {f['id']: f for f in facts}
    planned, seen = [], set()
    for request in missing:
        text = str(request.get('description', '')) + '\n' + str(request.get('acquisitionAction', ''))
        sections = [s for s in brief.get('sections', []) if s.get('form') in ('steps', 'criteria', 'comparison', 'example')
                    and ('section ' + s['id'] + ':') in str(request.get('description', ''))]
        if request.get('kind') not in ('actual_capture', 'original_photo') and not (request.get('kind') == 'observed_data' and sections):
            continue
        candidates = re.findall(r'https://[^\s<>\[\]"\']+', text)
        for section in sections:
            candidates += [fact_index[fid].get('url', fact_index[fid].get('sourceUrl', ''))
                           for fid in section.get('factIds', []) if fid in fact_index]
        target_keywords = extract_target_keywords(text, request.get('keywords', ()))
        for raw in candidates:
            try:
                url = public_https_url(raw.rstrip('.,;)'))
            except (TypeError, ValueError):
                continue
            scroll_key = (url, tuple(target_keywords[:3]))
            if url not in source_index or scroll_key in seen:
                continue
            seen.add(scroll_key)
            planned.append({
                'url': url,
                'sourceBodySha256': source_index[url],
                'sectionIds': [s['id'] for s in sections],
                'request': request,
                'targetKeywords': target_keywords,
                'collectOriginals': bool(request.get('collectOriginals', True)),
            })
            if len(planned) >= max_plans:
                return planned
    return planned


def scroll_to_smart_section(page, keywords=None, target_selector=None):
    """
    Activate matching in-page tabs (e.g., '찾아오시는 길', '이용시간/요금', '모노레일')
    and scroll the matching section heading/table/map into viewport for accurate capture.
    """
    kw_list = list(keywords or SMART_SECTION_KEYWORDS)
    initial_url = page.url

    # 1. If an explicit CSS selector is provided, scroll it near the top of the viewport
    if target_selector:
        try:
            loc = page.locator(target_selector).first
            if loc.count() and loc.is_visible():
                loc.evaluate("node => node.scrollIntoView({block: 'start', behavior: 'instant'})")
                page.wait_for_timeout(300)
                page.evaluate("() => window.scrollBy(0, -90)")
                return {'matchedKeyword': target_selector, 'selector': target_selector,
                        'scrollY': page.evaluate("() => window.scrollY")}
        except Exception:
            pass

    # 2. Check if an in-page tab matches one of our priority keywords (without changing URL)
    tab_selectors = '[role="tab"], .tab, .nav-link, button[aria-controls], li[aria-controls]'
    for kw in kw_list[:6]:
        try:
            tabs = page.locator(tab_selectors)
            count = min(tabs.count(), 25)
            for idx in range(count):
                tab = tabs.nth(idx)
                label = (tab.inner_text(timeout=500) or '').strip()
                if kw in label and len(label) <= 40:
                    if tab.is_visible():
                        tab.click(timeout=1500)
                        page.wait_for_timeout(400)
                        panel_id = tab.get_attribute('aria-controls')
                        if panel_id:
                            page.evaluate(
                                """(pid) => {
                                    const panel = document.getElementById(pid);
                                    if (panel) {
                                        document.querySelectorAll('.tabpanel').forEach(p => p.classList.remove('active', 'is-active'));
                                        panel.classList.add('active', 'is-active');
                                        panel.style.display = 'block';
                                    }
                                    const mapWrap = panel ? panel.querySelector('.naver-map') : null;
                                    if (mapWrap) mapWrap.style.display = 'block';
                                }""",
                                panel_id,
                            )
                        break
        except Exception:
            continue

    # 3. Locate the best matching heading, price table, or map container and bring it to top of viewport
    candidate_selectors = (
        'h1, h2, h3, h4, p.title, .section__header, table, .section-use-price, '
        '.monorail-guide, .map, #map, .tabpanel.active, dt, th, strong'
    )
    for kw in kw_list:
        try:
            elements = page.locator(candidate_selectors)
            count = min(elements.count(), 80)
            for idx in range(count):
                el = elements.nth(idx)
                if not el.is_visible():
                    continue
                txt = (el.inner_text(timeout=400) or '').strip()
                if kw in txt and 1 <= len(txt) <= 120:
                    el.evaluate("node => node.scrollIntoView({block: 'start', behavior: 'instant'})")
                    page.wait_for_timeout(300)
                    page.evaluate("() => window.scrollBy(0, -90)")
                    if public_https_url(page.url) == public_https_url(initial_url):
                        return {
                            'matchedKeyword': kw,
                            'matchedText': txt[:80],
                            'scrollY': page.evaluate("() => window.scrollY"),
                        }
        except Exception:
            continue

    return {'matchedKeyword': None, 'matchedText': '', 'scrollY': page.evaluate("() => window.scrollY")}


def collect_high_res_page_images(page, target_url, folder, *, min_width=500, min_height=320, max_images=4):
    """
    Extract high-resolution real scene / official map images (`<img>` and official media assets)
    from the current official page so they can be used as `source: "original"` or `"capture"`.
    """
    from PIL import Image

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    collected = []
    seen_urls = set()

    try:
        dom_candidates = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('img').forEach(img => {
                    const src = img.currentSrc || img.src || img.getAttribute('src') || '';
                    const alt = (img.alt || '').trim();
                    const w = img.naturalWidth || img.width || 0;
                    const h = img.naturalHeight || img.height || 0;
                    if (src) out.push({src, alt, w, h, kind: 'img'});
                });
                const html = document.documentElement.innerHTML || '';
                const re = /(?:https:\\/\\/cdn\\.maketicket\\.co\\.kr\\/[A-Za-z0-9_./&-]+|\\/[A-Za-z0-9_./&-]+\\.(?:jpg|jpeg|png|webp))/gi;
                const matches = html.match(re) || [];
                matches.forEach(m => out.push({src: m, alt: '', w: 0, h: 0, kind: 'html_ref'}));
                return out;
            }"""
        )
    except Exception:
        dom_candidates = []

    for cand in dom_candidates:
        if len(collected) >= max_images:
            break
        raw_src = str(cand.get('src') or '').strip()
        if not raw_src or raw_src.startswith('data:'):
            continue
        lower_src = raw_src.lower()
        if any(skip in lower_src for skip in ('favicon', 'logo', 'icon_', 'btn-', 'arrow', 'sns-', 'ico_')):
            continue
        try:
            full_url = public_https_url(urljoin(target_url, raw_src))
            assert_public_dns(full_url)
        except Exception:
            continue
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        try:
            req = urllib.request.Request(full_url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': target_url})
            raw_bytes = urllib.request.urlopen(req, timeout=12).read()
            with Image.open(io.BytesIO(raw_bytes)) as im:
                width, height = im.size
                fmt = (im.format or 'JPEG').upper()
            if width < min_width or height < min_height:
                continue
            ext = '.png' if fmt == 'PNG' else '.jpg'
            ident = 'official-orig-' + sha(full_url.encode('utf-8'))[:12]
            out_path = folder / (ident + ext)
            if not out_path.exists():
                out_path.write_bytes(raw_bytes)
            digest = sha(out_path.read_bytes())
            collected.append({
                'materialId': ident,
                'filename': out_path.name,
                'filePath': str(out_path.resolve()),
                'sha256': digest,
                'source': 'original',
                'sourceUrl': full_url,
                'pageUrl': target_url,
                'stepId': ident,
                'capturedAt': datetime.now(timezone.utc).isoformat(),
                'captureMethod': 'official_original_asset',
                'width': width,
                'height': height,
                'alt': cand.get('alt') or '',
                'action': f'공식 페이지({target_url}) 내 고해상도 원본 시각자료({width}x{height}) 수집',
                'observedResult': f'공식 원본 이미지 자산 확보: {full_url}',
            })
        except Exception:
            continue

    return collected


def capture_public_pages(context, plan, folder, environment):
    """
    Open verified official public URLs, perform smart section scrolling/tab activation
    to target headings/tables/maps (`scroll_into_view_if_needed`), capture the viewport,
    and optionally collect high-res official `<img>` assets.
    For PDF URLs, renders the target page directly in memory (pypdfium2) without browser download.
    """
    from common.browser_session import PageScope
    from PIL import Image
    rows, checked_hosts = [], set()
    for idx, item in enumerate(plan):
        target = item['url']
        assert_public_dns(target)
        target_keywords = item.get('targetKeywords') or extract_target_keywords(
            str(item.get('request', {}).get('description', '')) + ' ' +
            str(item.get('request', {}).get('acquisitionAction', ''))
        )

        # Pre-check via single-fetch URL cache before touching the browser
        cached_meta = fetch_url_cached(target, cache_dir=folder)
        if cached_meta.get('kind') == 'blocked_attachment':
            raise RuntimeError('Blocked binary attachment download URL: ' + str(cached_meta.get('reason')))
        if cached_meta.get('kind') == 'pdf':
            suffix = sha((target + '|pdf|' + str(idx)).encode())[:16]
            identity = 'public-' + suffix
            path = Path(folder) / (identity + '.png')
            if path.exists():
                identity = f'public-{suffix}-{idx+1}'
                path = Path(folder) / (identity + '.png')
            pdf_render = render_pdf_page_to_png(
                target,
                path,
                target_keywords=target_keywords,
                cache_dir=folder,
            )
            matched_kw = pdf_render.get('matchedKeyword')
            page_no = pdf_render.get('pageIndex', 1)
            page_cnt = pdf_render.get('pageCount', 1)
            action_desc = (
                f"검증된 공식 공개 PDF 문서({target})를 브라우저 로컬 다운로드 없이 메모리에서 직접 열어 "
                f"'{matched_kw}' 관련 핵심 안내 페이지({page_no}/{page_cnt}쪽)를 고해상도 PNG({pdf_render['width']}x{pdf_render['height']})로 변환 캡처."
            )
            rows.append({
                'materialId': identity,
                'filename': path.name,
                'filePath': str(path.resolve()),
                'sha256': sha(path.read_bytes()),
                'source': 'capture',
                'sourceUrl': target,
                'sourceBodySha256': item['sourceBodySha256'],
                'stepId': identity,
                'capturedAt': datetime.now(timezone.utc).isoformat(),
                'captureMethod': 'browser_screenshot',
                'pdfPageRenderedInMemory': True,
                'environment': environment + ' (in-memory PDF page renderer)',
                'width': pdf_render['width'],
                'height': pdf_render['height'],
                'smartScroll': {
                    'scrolled': True,
                    'matchedKeyword': matched_kw,
                    'pdfPage': page_no,
                    'pdfPageCount': page_cnt,
                    'scrollY': 0,
                },
                'action': action_desc,
                'expectedResult': item['request']['acquisitionAction'],
                'observedResult': f"공식 PDF {page_no}/{page_cnt}쪽 메모리 고해상도 렌더링 완료. 추출 텍스트: " + pdf_render['pageText'],
                'observationLimits': '브라우저 파일 다운로드 없이 메모리에서 렌더링된 공식 PDF 페이지 화면.',
                'requestedSectionIds': item['sectionIds'],
            })
            (Path(folder) / (identity + '.json')).write_text(
                json.dumps(rows[-1], ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            continue

        with PageScope() as scope:
            def reuse(page):
                try:
                    return public_https_url(page.url) == target
                except ValueError:
                    return False
            page = scope.acquire(context, reuse)
            blocked_navigation = []

            def guard(route, request):
                try:
                    url = public_https_url(request.url)
                    host = urlsplit(url).hostname
                    if request.method not in ('GET', 'HEAD'):
                        raise ValueError('Read-only requests only')
                    if is_blocked_download_url(url) or is_pdf_or_download_trigger_url(url):
                        blocked_navigation.append('Blocked file download URL in browser route')
                        raise ValueError('Blocked file download URL')
                    if request.is_navigation_request() and request.frame == page.main_frame and url != target:
                        blocked_navigation.append('Unapproved document navigation')
                        raise ValueError('Unapproved document navigation')
                    if host not in checked_hosts:
                        if len(checked_hosts) >= 48:
                            raise ValueError('Resource host budget exceeded')
                        assert_public_dns(url)
                        checked_hosts.add(host)
                    route.continue_()
                except (ValueError, OSError):
                    route.abort()

            owned = scope.owns(page)
            if owned:
                page.route('**/*', guard)
            try:
                if owned:
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    response = page.goto(target, wait_until='domcontentloaded', timeout=18000)
                    if response is None or response.status != 200:
                        raise RuntimeError('Public page did not return HTTP 200')
                    resp_cd = (response.headers.get('content-disposition') or '').lower()
                    if 'attachment' in resp_cd:
                        raise RuntimeError('Blocked attachment Content-Disposition on public page')
                    page.wait_for_timeout(1000)
                if blocked_navigation or public_https_url(page.url) != target:
                    raise RuntimeError('Public page navigation crossed the approved URL boundary')
                if page.locator('input[type="password"]:visible, form[action*="login" i]:visible').count():
                    raise RuntimeError('Visible authentication form: capture requires user access')

                # Smart section scroll & tab activation for target keywords
                scroll_info = scroll_to_smart_section(
                    page,
                    keywords=target_keywords,
                    target_selector=item.get('targetSelector'),
                )
                page.wait_for_timeout(350)

                text = page.evaluate("() => document.body ? document.body.innerText : ''")[:4000]
                if not text.strip():
                    raise RuntimeError('Public guidance body unavailable')

                suffix = sha((target + '|' + str(scroll_info.get('matchedKeyword') or idx)).encode())[:16]
                identity = 'public-' + suffix
                path = Path(folder) / (identity + '.png')
                if path.exists():
                    identity = f'public-{suffix}-{idx+1}'
                    path = Path(folder) / (identity + '.png')

                page.screenshot(path=str(path), full_page=False, timeout=10000)
                if public_https_url(page.url) != target:
                    raise RuntimeError('Source tab moved during capture; image is not accepted')
                with Image.open(path) as pixels:
                    width, height = pixels.size

                matched_kw = scroll_info.get('matchedKeyword')
                action_desc = (
                    f"검증된 공식 공개 URL({target})에서 '{matched_kw}' 섹션으로 스마트 스크롤 이동(scrollY={scroll_info.get('scrollY', 0)}) 후 화면 캡처."
                    if matched_kw else
                    '검증된 공식 공개 URL의 현재 화면을 열어 읽음.'
                )
                rows.append({
                    'materialId': identity,
                    'filename': path.name,
                    'filePath': str(path.resolve()),
                    'sha256': sha(path.read_bytes()),
                    'source': 'capture',
                    'sourceUrl': target,
                    'sourceBodySha256': item['sourceBodySha256'],
                    'stepId': identity,
                    'capturedAt': datetime.now(timezone.utc).isoformat(),
                    'captureMethod': 'browser_screenshot',
                    'environment': environment,
                    'width': width,
                    'height': height,
                    'smartScroll': scroll_info,
                    'action': action_desc,
                    'expectedResult': item['request']['acquisitionAction'],
                    'observedResult': '스마트 스크롤 viewport 캡처를 저장함. DOM 텍스트(픽셀 확인 아님): ' + text,
                    'observationLimits': '현재 스크롤된 섹션 영역 캡처. 모바일 390px 가독성은 capture_guide.py 확대 안내판 및 후속 픽셀 관찰에서 확인.',
                    'requestedSectionIds': item['sectionIds'],
                })
                (Path(folder) / (identity + '.json')).write_text(
                    json.dumps(rows[-1], ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )

                # Also collect high-resolution official `<img>` / media assets on the page if requested
                if item.get('collectOriginals'):
                    orig_dir = Path(folder) / 'official-originals'
                    originals = collect_high_res_page_images(page, target, orig_dir)
                    if originals:
                        rows[-1]['collectedOriginals'] = originals
            finally:
                if owned:
                    page.unroute('**/*', guard)
    return rows


async def run_in_source_browser(operation, endpoint, executable, profile):
    """Run a host-authored operation on the existing, verified source browser (tab-isolated via PageScope)."""
    from common.browser_session import flow_generation_lock
    def run():
        from playwright.sync_api import sync_playwright
        from common.browser_session import connect_sync
        with sync_playwright() as driver:
            browser = connect_sync(driver, endpoint, executable, profile)
            return operation(browser.contexts[0])
    try:
        async with flow_generation_lock(timeout=3):
            return await asyncio.to_thread(run)
    except RuntimeError:
        return await asyncio.to_thread(run)


async def acquire_public_captures(folder, missing, brief, facts, sources, official_url,
                                  endpoint, executable, profile, *, capture=None):
    """Acquire smart-scrolled public section captures and official original images."""
    plan = plan_public_captures(missing, brief, facts, sources, official_url)
    if not plan:
        return None
    directory = Path(folder) / 'public-source-acquisition'
    try:
        directory.mkdir(exist_ok=False)
    except FileExistsError:
        return None

    def save(name, value):
        with (directory / name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)

    save('request.json', {
        'plan': plan,
        'firstBrief': brief,
        'missingInputs': missing,
        'sourceBindings': {p['url']: p['sourceBodySha256'] for p in plan},
        'attempts': 1,
    })
    try:
        if capture is not None:
            rows = await asyncio.to_thread(capture)
        else:
            rows = await run_in_source_browser(
                lambda context: capture_public_pages(
                    context,
                    plan,
                    directory,
                    'PC web; dedicated source browser; smart section scroll viewport',
                ),
                endpoint,
                executable,
                profile,
            )
        if len(rows) != len(plan):
            raise RuntimeError('Incomplete capture batch')
        save('result.json', {
            'status': 'captured_not_pixel_or_answer_approved',
            'materials': rows,
            'pixelReviewRequired': True,
            'researchReplanRequired': True,
        })
        return rows
    except Exception as error:
        save('result.json', {
            'status': 'acquisition_failed',
            'errorType': type(error).__name__,
            'reason': str(error)[:600],
            'pixelReviewRequired': True,
        })
        return None
