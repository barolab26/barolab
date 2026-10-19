"""Deterministic capture guides. Originals stay unchanged; callers own browser rendering."""
import base64
import copy
import hashlib
import html
import json
import re
import textwrap
from pathlib import Path

from PIL import Image


FOCUS_PLANNING_POLICY = (
    '같은 실제 픽셀 관찰에서 클릭할 메뉴·탭·버튼 또는 반드시 읽을 조건의 위치 안내가 필요한지 판단한다. '
    '연결된 action/expectedResult/readerQuestion/captionFocus가 특정 위치를 찾아야 하는 내용이면 필요한 강조를 빈 배열로 면제하지 않는다. '
    '필요하면 focusNeed=required와 원본 sourcePixelSize 기준 box/crop 정수 좌표, 1~3개의 순서대로 번호·click/check·짧은 설명을 반환한다. '
    '모든 box/crop/focusContextCrop은 {x,y,width,height} 객체로 반환한다. x,y는 왼쪽 위, width,height는 너비·높이 길이이며 오른쪽·아래 좌표가 아니다. x+width와 y+height가 원본 크기를 넘으면 안 된다. '
    'box는 정확히 보이는 대상만 둘러싸고 crop은 그 대상을 포함하는 실제 확대 영역이다. UI 내용을 생성하거나 클릭하는 좌표가 아니다. '
    '완성 안내판은 폭780px로 렌더되어 모바일390px에서는 절반 크기로 보인다. 카드 전체가 아니라 실제 눌러야 할 버튼이나 읽어야 할 문장 줄의 범위를 선택한다. 긴 원문은 필요한 구간을 나누어 확대하고, 전체 카드를 작게 넣는 것을 확대로 오인하지 않는다. 위치를 보여주는 맥락 영역은 작아도 되지만 필수 문구의 확대 영역은390px에서 읽을 수 있어야 한다. '
    '클릭 위치를 찾도록 focusContextCrop에는 해당 탭 줄·인접 메뉴·팝업 등 원본의 공간적 맥락을 포함한다. 단독 버튼 확대만으로 위치를 잃지 않게 한다. 전체 긴 화면을 반드시 넣는 것은 아니며 위치 단서가 불필요한 결과 자료는 null로 둘 수 있다. '
    '표시가 불필요한 일반 전체상태 자료는 not_needed와 구체적 이유/빈 배열을 사용한다. 이미 transformations에 annotate가 있으면 중복 생성하지 말고 이미 있는 번호/정확대상/캡션/가림/390px 가독성을 검수해 already_annotated로 판단한다. '
    'focusTitle/focusScope/각 caption은 이미지 밖 설명이며 보이는 조건의 적용 범위를 좁고 정확하게 유지한다. '
    '필수·선택·조건부 표현이 적용되는 대상과 행동을 원문과 같게 유지하고, 특정 단계의 조건을 준비나 절차 전체의 조건으로 옮기지 않는다. '
    '이미 표시된 대상이 틀리거나 필수 글자를 가리거나 번호·설명이 맞지 않으면 usable/alignment를 false로 반려한다. '
)

GUIDE_QA_POLICY = (
    '주석 안내판은 실제 클릭·확인 대상의 테두리/번호/설명 일치, 원본 공간적 맥락, 글자 비가림과390px 가독성을 확인한다. '
    '필수·선택·조건부 표현이 원문의 어느 대상·행동에 적용되는지 캡션과 대조하고, 적용 대상을 옮겨 의미가 달라진 경우 기존 alignment 기준으로 반려한다. '
    '원본 관찰의 통과는 새 안내판 픽셀의 승인으로 대신하지 않는다. '
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _text(value, name, limit=160):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Invalid capture guide ' + name)
    return value.strip()


def _box(value, width, height):
    if not isinstance(value, list) or len(value) != 4 or any(type(v) is not int for v in value):
        raise ValueError('Guide coordinates must be four integer source pixels')
    x,y,w,h = value
    if min(x,y) < 0 or min(w,h) <= 0 or x+w > width or y+h > height:
        raise ValueError('Guide coordinates exceed actual capture')
    return value


def validate_guide_spec(spec, width, height, source_sha):
    if not isinstance(spec,dict) or spec.get('version') != 1 or spec.get('sourceSha256') != source_sha:
        raise ValueError('Capture guide schema/source binding mismatch')
    _text(spec.get('title'),'title',70)
    _text(spec.get('scope'),'scope',200)
    if spec.get('contextCrop'):
        _box(spec['contextCrop'],width,height)
    targets = spec.get('targets')
    if not isinstance(targets,list) or not 1 <= len(targets) <= 3:
        raise ValueError('A capture guide needs one to three targets')
    for number,target in enumerate(targets,1):
        if not isinstance(target,dict) or type(target.get('number')) is not int or target['number'] != number:
            raise ValueError('Guide target numbers must match caption order')
        if target.get('kind') not in ('click','check'):
            raise ValueError('Guide target must be click or check')
        _text(target.get('caption'),'caption')
        x,y,w,h = _box(target.get('box'),width,height)
        cx,cy,cw,ch = _box(target.get('crop',[0,0,width,height]),width,height)
        if x < cx or y < cy or x+w > cx+cw or y+h > cy+ch:
            raise ValueError('Guide detail crop must contain its highlighted target')
    return copy.deepcopy(spec)


def _svg(source_bytes, mime, width, height, spec):
    # All new text lives outside the original-pixel viewports. Each target can
    # show a separate real-pixel closeup instead of shrinking a whole screen.
    rows=[]; y=44
    def text_lines(text, size=32, columns=22, color='#172033'):
        nonlocal y
        for line in textwrap.wrap(text,width=columns,break_long_words=True):
            rows.append(f'<text x="24" y="{y}" font-size="{size}" fill="{color}">{html.escape(line)}</text>')
            y += size+15
    text_lines(spec['title'],36,20)
    text_lines(spec['scope'],28,25,'#475569')
    y += 8
    if spec.get('contextCrop'):
        text_lines('화면에서 위치 찾기',28,25,'#475569')
        cx,cy,cw,ch=spec['contextCrop'];context_height=round(732*ch/cw,3)
        rows.append(f'<svg x="24" y="{y}" width="732" height="{context_height}" viewBox="{cx} {cy} {cw} {ch}" overflow="hidden"><use href="#capture-pixels"/>')
        for target in spec['targets']:
            x,by,w,h=target['box']
            if x>=cx and by>=cy and x+w<=cx+cw and by+h<=cy+ch:
                color='#1646b7' if target['kind']=='click' else '#8c4500'
                dash=' stroke-dasharray="10 7"' if target['kind']=='check' else ''
                rows.append(f'<rect x="{x}" y="{by}" width="{w}" height="{h}" fill="none" stroke="{color}" stroke-width="2" vector-effect="non-scaling-stroke"{dash}/>')
        rows.append('</svg>');y += context_height+38
    for target in spec['targets']:
        color = '#1646b7' if target['kind']=='click' else '#8c4500'
        kind = '누를 곳 · 실선' if target['kind']=='click' else '확인할 곳 · 점선'
        number=target['number']
        rows.append(f'<circle cx="48" cy="{y+20}" r="23" fill="{color}"/>')
        rows.append(f'<text x="48" y="{y+31}" font-size="32" fill="white" text-anchor="middle">{number}</text>')
        rows.append(f'<text x="86" y="{y+31}" font-size="30" font-weight="700" fill="{color}">{kind}</text>')
        y += 62
        cx,cy,cw,ch=target.get('crop',[0,0,width,height]); view_height=round(732*ch/cw,3)
        x,by,w,h=target['box'];dash=' stroke-dasharray="10 7"' if target['kind']=='check' else ''
        rows.append(f'<svg x="24" y="{y}" width="732" height="{view_height}" viewBox="{cx} {cy} {cw} {ch}" overflow="hidden">'
            '<use href="#capture-pixels"/>'
            f'<rect data-guide-target="{number}" x="{x}" y="{by}" width="{w}" height="{h}" fill="none" '
            f'stroke="{color}" stroke-width="3" vector-effect="non-scaling-stroke"{dash}/></svg>')
        y += view_height+42
        text_lines(f'{number}. '+target['caption'])
        y += 24
    total=round(y+12)
    payload=base64.b64encode(source_bytes).decode('ascii')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="780" height="{total}" viewBox="0 0 780 {total}" '
        'font-family="Malgun Gothic,Apple SD Gothic Neo,sans-serif">'
        f'<title>{html.escape(spec["title"])}</title><rect width="780" height="{total}" fill="white"/>'
        f'<defs><image id="capture-pixels" width="{width}" height="{height}" href="data:{mime};base64,{payload}"/></defs>'
        +''.join(rows)+'</svg>'),total


def prepare_capture_guide(record, spec, outdir):
    """Prepare immutable source/spec/SVG/HTML; this does not claim pixel approval."""
    record=copy.deepcopy(record);source=Path(record['filePath']).resolve()
    if record.get('source') != 'capture' or _sha(source) != record.get('sha256'):
        raise ValueError('Guide needs an unchanged actual capture')
    original=Path(record.get('originalPath',source)).resolve()
    original_sha=record.get('originalSha256',record['sha256'])
    if _sha(original) != original_sha:
        raise ValueError('Retained original capture changed')
    with Image.open(source) as image:
        width,height=image.size;mime=Image.MIME.get(image.format)
        if image.format not in ('JPEG','PNG','WEBP') or width*height>40000000:
            raise ValueError('Unsupported capture pixels')
        image.verify()
    spec=validate_guide_spec(spec,width,height,record['sha256'])
    svg,guide_height=_svg(source.read_bytes(),mime,width,height,spec)
    document=('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(spec["title"])}</title><style>html,body{{margin:0;background:white}}svg{{display:block;width:100%;height:auto;max-width:780px;margin:auto}}</style>'+svg+'</html>')
    out=Path(outdir).resolve();out.mkdir(parents=True,exist_ok=False)
    files={'source':out/('source'+source.suffix.lower()),'original':out/('original'+original.suffix.lower()),
           'spec':out/'guide-spec.json','svg':out/'guide.svg','html':out/'guide.html','record':out/'source-record.json'}
    files['source'].write_bytes(source.read_bytes());files['original'].write_bytes(original.read_bytes())
    files['spec'].write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    files['svg'].write_text(svg,encoding='utf-8');files['html'].write_text(document,encoding='utf-8')
    files['record'].write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    receipt={'version':1,'renderer':'capture-guide-svg-v1','width':780,'height':guide_height,
             'artifacts':{key:{'path':str(path),'sha256':_sha(path)} for key,path in files.items()},
             'visualReviewRequired':True}
    path=out/'guide-receipt.json';path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return path


def verify_capture_guide(metadata, allowed_roots=None):
    """Integrity is not semantic approval; the existing pixel review still decides."""
    receipt_path=Path(metadata['receiptPath']).resolve()
    if allowed_roots and not any(receipt_path.is_relative_to(Path(root).resolve()) for root in allowed_roots):
        raise ValueError('Capture guide receipt outside approved roots')
    if _sha(receipt_path) != metadata['receiptSha256']:
        raise ValueError('Capture guide receipt changed')
    receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('version') != 1 or receipt.get('renderer') != 'capture-guide-svg-v1':
        raise ValueError('Unsupported capture guide receipt')
    for entry in receipt['artifacts'].values():
        path=Path(entry['path']).resolve()
        if not path.is_relative_to(receipt_path.parent) or _sha(path) != entry['sha256']:
            raise ValueError('Capture guide artifact changed or escaped its bundle')
    spec=json.loads(Path(receipt['artifacts']['spec']['path']).read_text(encoding='utf-8'))
    if 'targets' in metadata and (metadata['targets'] != spec['targets'] or metadata.get('scope') != spec['scope']
                                 or metadata.get('sourceSha256') != spec['sourceSha256']):
        raise ValueError('Capture guide target/caption/source binding changed')
    return receipt


def complete_capture_guide(receipt_path, raster_path):
    """Bind a caller-owned browser export; never turns a render into passed review."""
    receipt_path=Path(receipt_path).resolve();raster_path=Path(raster_path).resolve()
    metadata={'receiptPath':str(receipt_path),'receiptSha256':_sha(receipt_path),'visualReviewRequired':True}
    receipt=verify_capture_guide(metadata)
    if not raster_path.is_relative_to(receipt_path.parent) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.(jpg|jpeg|png|webp)',raster_path.name):
        raise ValueError('Guide render must be a safe image inside its bundle')
    with Image.open(raster_path) as image:
        if image.format not in ('JPEG','PNG','WEBP') or image.width != receipt['width'] or abs(image.height-receipt['height'])>1:
            raise ValueError('Guide render dimensions do not match its full document')
        image.verify()
    record=json.loads(Path(receipt['artifacts']['record']['path']).read_text(encoding='utf-8'))
    spec=json.loads(Path(receipt['artifacts']['spec']['path']).read_text(encoding='utf-8'))
    # Acquisition observations describe the source capture, which may contain
    # content outside the guide crops. Keep them distinct from guide display.
    source_observation = {key: copy.deepcopy(record[key]) for key in (
        'action', 'expectedResult', 'observedResult', 'nextLocation', 'environment',
        'captureMethod', 'capturedAt', 'sourceUrl', 'pixelObservation', 'observationFile'
    ) if key in record}
    source_observation.update(scope='source_capture_only',
        sourceSha256=receipt['artifacts']['source']['sha256'],
        sourceRecordPath=receipt['artifacts']['record']['path'],
        sourceRecordSha256=receipt['artifacts']['record']['sha256'])
    displayed = spec['scope'] + ' 표시된 안내: ' + ' '.join(
        f"{target['number']}. {target['caption']}" for target in spec['targets'])
    record.update(sourceObservation=source_observation,
        expectedResult='현재 안내판에서 확인할 범위: ' + displayed,
        observedResult='현재 안내판의 표시 명세: ' + displayed,
        observationScope='derived_guide_display_only; not a new browser action or outcome observation')
    if 'pixelObservation' in record:
        record['pixelObservationScope']='Original source pixels only; the derived guide requires final actual-pixel review.'
    record.update(filename=raster_path.name,filePath=str(raster_path),sha256=_sha(raster_path),
        originalPath=receipt['artifacts']['original']['path'],originalSha256=receipt['artifacts']['original']['sha256'],
        transformations=list(dict.fromkeys(record.get('transformations',[])+['annotate'])),
        captureGuide={**metadata,'sourceSha256':receipt['artifacts']['source']['sha256'],'targets':spec['targets'],'scope':spec['scope']})
    return record


def focus_region_fields():
    """Optional fields for an existing real-pixel observation, not a new model pass."""
    dimensions={key:{'type':'integer','minimum':0 if key in ('x','y') else 1}
                for key in ('x','y','width','height')}
    rectangle={'type':'object','properties':dimensions,'required':list(dimensions),'additionalProperties':False,
               'description':'Original image pixels: x/y are the top-left corner; width/height are lengths, not right/bottom coordinates.'}
    target={'number':{'type':'integer','minimum':1,'maximum':3},
            'kind':{'type':'string','enum':['click','check']},'box':rectangle,'crop':rectangle,
            'caption':{'type':'string'}}
    return {'focusNeed':{'type':'string','enum':['required','not_needed','already_annotated']},
            'focusReason':{'type':'string'},'focusTitle':{'type':'string'},'focusScope':{'type':'string'},
            'focusContextCrop':{'anyOf':[rectangle,{'type':'null'}]},
            'focusRegions':{'type':'array','maxItems':3,'items':{'type':'object','properties':target,
                'required':list(target),'additionalProperties':False}}}


def focus_planning_required(source):
    """A verified completed guide needs pixel QA, not another coordinate plan."""
    guide = source.get('captureGuide')
    if guide:
        verify_capture_guide(guide)
        if _sha(source['filePath']) != source['sha256']:
            raise ValueError('Focus source changed before phase selection')
    if source.get('source', 'capture') != 'capture':
        return False
    # Legacy annotate records retain their existing contract; an unverified
    # annotation flag alone never grants this completed-guide exemption.
    return not (guide and 'annotate' in source.get('transformations', []))


def focus_review_batches(sources, max_images=3):
    """Preserve order while keeping coordinate planning separate from guide QA."""
    if type(max_images) is not int or not 1 <= max_images <= 3:
        raise ValueError('Focus review batches must contain one to three images')
    batches = []
    for index, source in enumerate(sources):
        needed = focus_planning_required(source)
        if not batches or batches[-1][0] != needed or len(batches[-1][1]) == max_images:
            batches.append((needed, []))
        batches[-1][1].append(index)
    return batches


def observed_focus_spec(observed, source):
    """Bind model coordinates to host-measured source bytes and dimensions."""
    if not focus_planning_required(source):
        if any(key in observed for key in focus_region_fields()):
            raise ValueError('QA-only visual observation cannot contain focus planning fields')
        return None
    need=observed.get('focusNeed');regions=observed.get('focusRegions')
    _text(observed.get('focusReason'),'focusReason',500)
    if need not in ('required','not_needed','already_annotated') or not isinstance(regions,list):
        raise ValueError('Actual pixel focus decision is missing')
    already='annotate' in source.get('transformations',[])
    if need=='already_annotated' and not already:
        raise ValueError('An unannotated source cannot claim an existing guide')
    if need!='required':
        if regions:raise ValueError('Focus exemption cannot also contain regions')
        return None
    if already:raise ValueError('Do not annotate an existing guide twice')
    if source.get('source') != 'capture':raise ValueError('Only actual captures use UI focus regions')
    with Image.open(source['filePath']) as pixels:width,height=pixels.size
    if _sha(source['filePath']) != source['sha256']:
        raise ValueError('Focus source changed after observation')
    def named_rectangle(value):
        keys=('x','y','width','height')
        if not isinstance(value,dict) or set(value)!=set(keys):
            raise ValueError('Model focus rectangle needs named x/y/width/height')
        return [value[key] for key in keys]
    targets=[{**target,'box':named_rectangle(target.get('box')),'crop':named_rectangle(target.get('crop'))}
             for target in regions]
    context=observed.get('focusContextCrop')
    return validate_guide_spec({'version':1,'sourceSha256':source['sha256'],
        'title':observed.get('focusTitle'),'scope':observed.get('focusScope'),
        'contextCrop':[] if context is None else named_rectangle(context),'targets':targets},width,height,source['sha256'])


def rasterize_capture_guides(context, receipt_paths):
    """Render only self-contained guide documents in one owned existing-browser tab."""
    from common.browser_session import PageScope
    rendered=[]
    with PageScope() as owned:
        page=owned.acquire(context,lambda candidate:False)
        for receipt_path in receipt_paths:
            receipt_path=Path(receipt_path).resolve()
            receipt=verify_capture_guide({'receiptPath':str(receipt_path),'receiptSha256':_sha(receipt_path)})
            # A shorter viewport adds a scrollbar, shrinking responsive SVG pixels.
            page.set_viewport_size({'width':receipt['width'],'height':receipt['height']})
            page.set_content(Path(receipt['artifacts']['html']['path']).read_text(encoding='utf-8'),wait_until='load')
            page.evaluate('()=>document.fonts.ready')
            raster=receipt_path.parent/('guide-'+receipt['artifacts']['source']['sha256'][:12]+'.png')
            if raster.exists():raise FileExistsError('Guide render already exists')
            page.screenshot(path=str(raster),full_page=False)
            complete_capture_guide(receipt_path,raster)
            rendered.append(raster)
    return rendered
