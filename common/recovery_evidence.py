"""Host-bound failed work and source evidence for the existing repair workflow."""
import ast
import hashlib
import json
import re
import os
import shutil
import sys
from pathlib import Path

PROJECT_SOURCES = {
    'cf_blog': ('cf_posting/pipeline_runner.py', 'common/answer_brief.py', 'common/public_capture.py','common/editorial_supervisor.py'),
    'naver_blog': ('naver_blog_posting/pipeline_runner.py', 'naver_blog_posting/visible_editor.py',
                   'naver_blog_posting/material_assets.py', 'common/answer_brief.py','common/editorial_supervisor.py'),
    'naver_kin': ('naver_kin/pipeline.py', 'naver_kin/scheduler.py', 'naver_kin/authoring.py','common/editorial_supervisor.py'),
    'threads': ('threads_posting/pipeline.py', 'threads_posting/authoring.py', 'threads_posting/scheduler.py'),
    'legacy_remodel': ('common/content_maintenance.py', 'common/content_improvement.py'),
}
ARTIFACT_NAMES = ('failure-diagnostics.json', 'prewriter-acquisition-request.json', 'required-materials.json',
    'keyword-evidence.json', 'writer-review.json', 'review.json', 'research.md', 'keywords.md',
    'handoff.json', 'validation.json', 'visible-editor-progress.json', 'native-layout-review.json',
    'selected-evidence.json', 'keyword-selector.json', 'researcher.json', 'source-capture-repair.json')
ARTIFACT_NAMES += ('keyword-title-original.json','keyword-demand-alignment.json','preparation-context.json',
                   'original-work-preparation.json','original-work-acquisition.json')
ARTIFACT_NAMES = ('original-work-acquisition.json','original-work-keyword-evidence/keyword-evidence.json',
                  'original-work-preparation.json') + ARTIFACT_NAMES
FAILED = {'failed', 'error', 'review_required', 'retry_wait', 'material_required', 'planning_required'}


def read_object(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8_000_000:
        return {}
    value = json.loads(path.read_bytes())
    return value if isinstance(value, dict) else {}


def failure_targets(root, project, snapshot=None):
    """Use actual attempt journals, never dashboard account summary='unknown'."""
    root = Path(root)
    if project == 'cf_blog':
        source = root / 'cf_posting/data/daily_schedule.json'
        doc = snapshot if snapshot is not None else read_object(source)
        rows = doc.get('items', [])
        candidates = [(row, doc.get('date'), row.get('domain'), None) for row in rows if isinstance(row, dict)]
    elif project == 'naver_blog':
        source = root / 'naver_blog_posting/data/automation-journal.json'
        doc = read_object(source)
        latest = {}
        for row in doc.get('attempts', []):
            if not isinstance(row, dict): continue
            day = row.get('publicationDate') or str(row.get('reserveTime', ''))[:10]
            slot = row.get('scheduledSlot') or str(row.get('reserveTime', ''))[-5:]
            latest[(row.get('account'), day, slot)] = row
        candidates = [(row, day, account, slot) for (account, day, slot), row in latest.items()]
    else:
        return []
    targets = []
    for row, day, identity, slot in candidates:
        status = row.get('phase') or row.get('status')
        if (status not in FAILED or not isinstance(identity,str) or not identity
                or not isinstance(day,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day)): continue
        if status == 'retry_wait' and not (row.get('lastError') or row.get('failureReason')): continue
        binding = {'project': project, 'date': day, 'identity': identity, 'slot': slot}
        work_id = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        targets.append({**binding, 'workId': work_id, 'sourcePath': str(source),
            'status': status, 'artifactFolder': row.get('artifactFolder'), 'slug': row.get('slug'),
            'failure': row.get('lastError') or row.get('failureReason') or row.get('error') or '',
            'traceback': row.get('lastTraceback') or '',
            'stage': row.get('stageName') or row.get('currentStage') or row.get('failureCategory'),
            'submissionStarted': any(row.get(k) for k in ('submissionStarted', 'submittedAt', 'submissionStartedAt')),
            'order': row.get('order', 0)})
    return sorted(targets, key=lambda row: (-int(row['date'].replace('-','')), row['order'], row['identity']))


def artifact_folder(root, target):
    project_dir = {'cf_blog': 'cf_posting', 'naver_blog': 'naver_blog_posting'}.get(target.get('project'))
    value = str(target.get('artifactFolder') or '').replace('\\', '/')
    if not project_dir or not value: return None
    base = Path(root) / project_dir
    # Legacy Windows/NAS references resolve only to the standard local checkout.
    marker = project_dir + '/output/'
    if marker in value:
        value = value.split(marker, 1)[1]
        path = base / 'output' / value
    else:
        path = Path(value)
        if not path.is_absolute(): path = base / path
    allowed = (base / 'output').resolve()
    if not path.resolve().is_relative_to(allowed) or not path.is_dir(): return None
    if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(base)): return None
    return path.resolve()


def task_evidence(root, target):
    """Bounded, hashed artifacts from this work alone, with privacy filtering."""
    from common.hermes_memory import learning_text
    folder = artifact_folder(root, target)
    artifacts, budget = [], 48_000
    if folder:
        for name in dict.fromkeys(ARTIFACT_NAMES):
            path = folder / name
            if (not path.resolve().is_relative_to(folder) or not path.is_file() or path.is_symlink()
                    or any(p.is_symlink() for p in path.parents if p.is_relative_to(folder))
                    or path.stat().st_size > 1_000_000): continue
            raw = path.read_bytes()
            text = learning_text(raw.decode('utf-8', errors='replace')[:min(budget, 10000)])
            artifacts.append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'content': text})
            budget -= len(text)
            if budget <= 0: break
    capability = None
    if folder and target.get('project') == 'cf_blog' and not target.get('submissionStarted'):
        request = read_object(folder / 'prewriter-acquisition-request.json')
        handoff = read_object(folder / 'handoff.json')
        if (request.get('status') == 'answer_inputs_required'
                and any(row.get('kind') in ('source_fact','actual_capture','observed_data','original_photo') for row in request.get('missingInputs', []))
                and not (folder / 'article.json').exists() and not list(folder.glob('*publication*receipt*'))
                and handoff.get('domain') == target['identity']
                and not (folder / 'source-fact-continuation.json').exists()):
            capability = {'kind': 'cf_prewriter_continuation', 'folder': str(folder),
                          'domain': target['identity'], 'originalRunId': handoff.get('runId')}
    elif folder and target.get('project') == 'naver_blog' and not target.get('submissionStarted'):
        context = read_object(folder / 'preparation-context.json')
        alignment = read_object(folder / 'keyword-demand-alignment.json')
        original = read_object(folder / 'keyword-title-original.json')
        handoff = read_object(folder / 'handoff.json')
        question = (alignment.get('inputs') or {}).get('readerQuestion')
        query = original.get('title')
        if (context.get('account') == target['identity'] and context.get('publicationDate') == target['date']
                and context.get('scheduledSlot') == target['slot'] and not handoff.get('stages')
                and isinstance(question,str) and 1<=len(question)<=1600
                and isinstance(query,str) and 1<=len(query)<=100
                and not (folder/'original-work-acquisition-claim.json').exists()
                and not (folder/'reservation-evidence.json').exists()):
            capability = {'kind':'naver_same_question_preparation','folder':str(folder),
                'account':target['identity'],'readerQuestion':question,'query':query}
        elif (context.get('account') == target['identity'] and context.get('publicationDate') == target['date']
                and context.get('scheduledSlot') == target['slot'] and len(handoff.get('stages',[]))>=3
                and not (folder/'original-work-acquisition-claim.json').exists()
                and not (folder/'reservation-evidence.json').exists()):
            accepted=read_object(folder/'keyword-selector.json')
            question=(accepted.get('readerGoal') or {}).get('question') or accepted.get('readerQuestion')
            if isinstance(question,str) and 1<=len(question)<=1600:
                capability={'kind':'naver_original_review','folder':str(folder),
                    'account':target['identity'],'readerQuestion':question}
    return {'target': target, 'artifacts': artifacts, 'inputCapability': capability}


def error_source_frames(root, project, errors):
    """Locate literal raise sites in registered source, without inventing a traceback."""
    from common.coding_job import _file
    frames = []
    for name in PROJECT_SOURCES.get(project, ()):
        try:
            path = _file(Path(root), name)
            text = path.read_text(encoding='utf-8-sig'); tree = ast.parse(text)
        except (OSError, ValueError, SyntaxError): continue
        for function in ast.walk(tree):
            if not isinstance(function,(ast.FunctionDef,ast.AsyncFunctionDef)): continue
            raises=[node for node in ast.walk(function) if isinstance(node,ast.Raise)]
            if not raises: continue
            literals=[node for node in ast.walk(function) if isinstance(node,ast.Constant) and isinstance(node.value,str)]
            matches=[node for node in literals if len(node.value.strip())>=12 and node.value in errors]
            if matches:
                match=max(matches,key=lambda node:len(node.value))
                location=min(raises,key=lambda node:abs(node.lineno-match.lineno))
                frames.append({'path':name,'line':location.lineno,'match':match.value,
                               'kind':'host_literal_raise_match'})
    # More specific matches take precedence; one editable region per source.
    frames.sort(key=lambda row: -len(row['match']))
    selected = {}
    for frame in frames: selected.setdefault(frame['path'], frame)
    return list(selected.values())[:5]


def environment_evidence(root, project):
    """Report capabilities and route names, never keys, cookies or auth files."""
    from common import llm_settings
    config = llm_settings.load()
    roles = {}
    for role in ('jarvis','patch','radar','doctor','publi','trace'):
        brain = llm_settings.get_agent_brain(role, config)
        roles[role] = {field: brain.get(field) for field in ('provider','model','reasoningEffort')}
    sources = {}
    for name in PROJECT_SOURCES.get(project, ()):
        path = Path(root) / name
        sources[name] = {'exists':path.is_file(), 'readable':os.access(path,os.R_OK),
                         'writable':os.access(path,os.W_OK)}
    return {'pythonAvailable':Path(sys.executable).is_file(),
            'isolatedTestRunnerInstalled':bool(shutil.which('bwrap')),
            'sourceAccess':sources,'assignedModels':roles,
            'executionContract':'Model proposes a bounded patch; host reviews, sandbox-tests and applies it. '
                'Actual inputs and public results remain separately verified.'}


def public_work_observation(root, target):
    """A trace employee can inspect the actual public counterpart, read-only."""
    if target.get('project') != 'cf_blog': return {'status':'registered_public_probe_unavailable'}
    from cf_posting import pipeline_runner as runner
    from common.hermes_memory import learning_text
    import requests
    from bs4 import BeautifulSoup
    domain=target['identity']
    if domain not in runner.ALL_DOMAINS: raise ValueError('Unregistered public work domain')
    folder=artifact_folder(root,target)
    if not folder: return {'status':'original_handoff_unavailable'}
    handoff=read_object(folder/'handoff.json')
    keywords=runner.read_document(folder/'keywords.md')
    candidates=[]
    try:
        for post in runner.published_inventory('https://www.'+domain):
            if post.get('slug')!=handoff.get('slug') and post.get('title')!=keywords.get('title'):continue
            url='https://www.'+domain+'/'+post['slug']
            page=requests.get(url,timeout=10,allow_redirects=False)
            soup=BeautifulSoup(page.text,'html.parser')
            for node in soup.select('script,style,nav,footer,header'):node.decompose()
            try:excerpt=learning_text(soup.get_text(' ',strip=True)[:12000])
            except ValueError:excerpt='[Public text omitted by privacy filter; response hash retained.]'
            candidates.append({'postId':post.get('id'),'slug':post.get('slug'),'title':post.get('title'),
                'publicUrl':url,'publishedAt':post.get('published_at') or post.get('created_at'),
                'httpStatus':page.status_code,'bodySha256':hashlib.sha256(page.content).hexdigest(),
                'bodyExcerpt':excerpt,'publicationSuccessInferred':False})
            if len(candidates)>=2:break
    except (OSError,ValueError,RuntimeError,requests.RequestException) as exc:
        causes=[]
        current=exc
        for _ in range(3):
            if current is None:break
            try:message=learning_text(str(current)[:800])
            except ValueError:message='[Error detail omitted by privacy filter.]'
            causes.append({'type':type(current).__name__,'message':message})
            current=current.__cause__
        return {'status':'public_probe_failed','errorType':type(exc).__name__,
                'causes':causes,
                'httpStatus':getattr(getattr(exc,'response',None),'status_code',None)}
    return {'status':'observed','candidates':candidates,
            'scope':'Actual current public responses; same-task content and publication date still require verification.'}


def work_barrier(project, root=None):
    """A durable failed work claim fences new work until source-backed completion."""
    root = Path(root or Path(__file__).resolve().parents[1])
    state = read_object(root / 'server/data/project-autonomy-state.json')
    work = state.get('projects', {}).get(project, {}).get('failureWork')
    return work if isinstance(work, dict) and work.get('status') != 'public_verified' else None
