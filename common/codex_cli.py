"""Codex subscription adapter. Credentials remain on the Windows worker."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

from common import dashboard_jobs as jobs

RUNTIME = jobs.ROOT / 'server' / 'data' / 'codex-runtime.json'
MAX_TURN_CHARS = 750_000


def _verified_installed_codex(executable, config):
    """Inspect the signature before running a replacement's version command."""
    env = environment(config)
    env['BAROLAB_CODEX_VERIFY_PATH'] = str(executable)
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    # Do not inherit PowerShell 7 module paths into Windows PowerShell 5.1.
    env['PSModulePath'] = str(powershell.parent / 'Modules')
    script = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $ErrorActionPreference = 'Stop'; "
        "$s = Get-AuthenticodeSignature -LiteralPath $env:BAROLAB_CODEX_VERIFY_PATH; "
        "$publisher = if ($s.SignerCertificate) { $s.SignerCertificate.GetNameInfo("
        "[System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) } else { '' }; "
        "@{status=$s.Status.ToString();publisher=$publisher} | ConvertTo-Json -Compress"
    )
    options = dict(capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
                   env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        signature = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', script], **options)
        evidence = json.loads(signature.stdout)
        if signature.returncode or evidence.get('status') != 'Valid' or evidence.get('publisher') != 'OpenAI OpCo, LLC':
            return False
        version = subprocess.run([str(executable), '--version'], **options)
        return version.returncode == 0 and re.fullmatch(r'codex-cli \d+\.\d+\.\d+(?:[-+.][\w.-]+)?', version.stdout.strip()) is not None
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _resolve_executable(config):
    executable = Path(config['executable'])
    if executable.is_file():
        return str(executable)
    install = (Path.home() / 'AppData/Local/OpenAI/Codex/bin').resolve()
    missing = executable.resolve()
    if (missing.name.lower() != 'codex.exe' or missing.parent.parent != install
            or not re.fullmatch(r'[a-f0-9]{16}', missing.parent.name)):
        raise RuntimeError('Codex CLI 설치·로그인 경로를 확인하세요.')
    verified = []
    for candidate in install.glob('*/codex.exe'):
        resolved = candidate.resolve()
        if (resolved.parent.parent == install and re.fullmatch(r'[a-f0-9]{16}', resolved.parent.name)
                and resolved.is_file() and _verified_installed_codex(resolved, config)):
            verified.append(resolved)
    if not verified:
        raise RuntimeError('Codex CLI 교체 경로를 확정할 수 없습니다. 서명·버전이 검증된 설치 파일이 없습니다.')
    verified.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    chosen = str(verified[0])
    try:
        worker_path = Path.home() / '.barolab' / 'codex-worker.json'
        if worker_path.is_file():
            saved = json.loads(worker_path.read_text(encoding='utf-8'))
            saved['executable'] = chosen
            worker_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except Exception:
        pass
    return chosen


def local_config():
    path = Path.home() / '.barolab' / 'codex-worker.json'
    if not path.is_file():
        raise RuntimeError('Windows Codex 작업 호스트 설정이 없습니다.')
    config = json.loads(path.read_text(encoding='utf-8'))
    if not Path(config['home']).is_dir():
        raise RuntimeError('Codex CLI 설치·로그인 경로를 확인하세요.')
    config['executable'] = _resolve_executable(config)
    return config


def environment(config):
    env = dict(os.environ, CODEX_HOME=config['home'])
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN'):
        env.pop(key, None)
    return env


def refresh_runtime():
    config = local_config()
    response = subprocess.run([config['executable'], 'login', 'status'], env=environment(config),
        capture_output=True, text=True, encoding='utf-8', timeout=15,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    authenticated = response.returncode == 0 and 'ChatGPT' in response.stdout + response.stderr
    cache = Path(config['home']) / 'models_cache.json'
    data = json.loads(cache.read_text(encoding='utf-8')) if cache.is_file() else {}
    models = [{'id': row['slug'], 'label': row.get('display_name', row['slug'])}
              for row in data.get('models', []) if row.get('visibility') == 'list']
    runtime = {'installed': True, 'authenticated': authenticated, 'authMethod': 'chatgpt' if authenticated else 'unavailable',
               'models': models, 'modelsFetchedAt': data.get('fetched_at'), 'checkedAt': jobs.stamp()}
    jobs.write(RUNTIME, runtime)
    return runtime


def runtime():
    try:
        data = json.loads(RUNTIME.read_text(encoding='utf-8'))
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(data['checkedAt'])).total_seconds()
        data['online'] = 0 <= age < 120
        return data
    except (OSError, ValueError, KeyError):
        return {'installed': False, 'authenticated': False, 'online': False, 'models': []}


def configured_reasoning_effort(config, model, requested):
    if requested is None:
        return 'low'
    if requested not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
        raise RuntimeError('지원하지 않는 reasoning_effort 요청값입니다.')
    try:
        cache = json.loads((Path(config['home'])/'models_cache.json').read_text(encoding='utf-8'))
        row = next(row for row in cache.get('models', []) if row.get('slug') == model)
        supported = {item['effort'] for item in row.get('supported_reasoning_levels', [])}
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        raise RuntimeError('선택 모델의 추론 강도 지원 정보를 확인할 수 없습니다.') from None
    if requested not in supported:
        raise RuntimeError('선택 모델이 요청한 추론 강도를 지원하지 않습니다: ' + requested)
    return requested


def _cli_error_detail(stdout, stderr):
    """Keep CLI error messages, never model responses or full captured streams."""
    messages = [line.strip() for line in stderr.splitlines() if re.match(r'^\s*Error:', line, re.I)]
    if not messages:
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get('type') not in ('error', 'turn.failed'):
                continue
            error = event.get('error')
            message = error.get('message') if isinstance(error, dict) else event.get('message')
            if isinstance(message, str):
                messages.append(message)
    summary = ' | '.join(messages) or '구조화 오류 메시지 없음'
    summary = re.sub(r'(?i)\binput_value\s*=.*', 'input_value=[omitted]', summary)
    summary = re.sub(r'(?i)\bBearer\s+\S+', 'Bearer [redacted]', summary)
    summary = re.sub(r'(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password)["\x27]?\s*[:=]\s*)["\x27]?[^\s,"\x27]+', r'\1[redacted]', summary)
    summary = re.sub(r'\b(?:sk|rk)-[A-Za-z0-9_-]{12,}', '[redacted]', summary)
    return summary[:1600]


def _prepare_cli_image(image_path: Path, folder: Path, index: int) -> Path:
    """Create a 960x960 JPEG CLI copy without modifying the audited original."""
    from PIL import Image, ImageOps
    target = folder / f'cli_vision_{index}_{image_path.stem}.jpg'
    with Image.open(image_path) as asset:
        rgb = ImageOps.pad(asset.convert('RGB'), (960, 960), method=Image.Resampling.LANCZOS, color='white')
        rgb.save(target, format='JPEG', quality=68, optimize=True)
    return target


def _fallback_candidates(config, primary_model, primary_effort, allowed):
    """Build ordered (model, effort) retry candidates for model capacity / timeout resilience."""
    efforts = []
    start_effort = 'medium' if primary_effort == 'high' and os.getenv('BAROLAB_FORCE_HIGH_EFFORT') != '1' else primary_effort
    for cand_effort in (start_effort, 'medium', 'low'):
        if cand_effort not in efforts:
            try:
                efforts.append(configured_reasoning_effort(config, primary_model, cand_effort))
            except RuntimeError:
                pass
    if not efforts:
        efforts = [primary_effort]
    candidates = [(primary_model, eff) for eff in efforts]
    for backup_model in ('gpt-6-luna', 'gpt-5.4-mini', 'gpt-5.3-codex'):
        if backup_model != primary_model and backup_model in allowed:
            for cand_effort in ('medium', 'low'):
                try:
                    valid_eff = configured_reasoning_effort(config, backup_model, cand_effort)
                    if (backup_model, valid_eff) not in candidates:
                        candidates.append((backup_model, valid_eff))
                except RuntimeError:
                    pass
    return candidates


def generate_local(prompt, model, images=None, response_schema=None, audit_directory=None, reasoning_effort=None):
    from common.llm_client import parse_json
    config = local_config()
    allowed = {row['id'] for row in runtime().get('models', [])}
    if model not in allowed:
        try:
            allowed = {row['id'] for row in refresh_runtime().get('models', [])}
        except Exception:
            pass
    if model not in allowed:
        raise RuntimeError('로그인 계정의 모델 목록에 없는 Codex 모델입니다.')
    effort = configured_reasoning_effort(config, model, reasoning_effort)
    scratch = Path.home() / '.barolab' / 'scratch'
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='codex-json-', dir=scratch) as folder:
        folder_path = Path(folder)
        output = str(folder_path / 'response.json')
        schema = folder_path / 'schema.json'
        schema.write_text(json.dumps(response_schema or {'type':'object','properties':{'json':{'type':'string'}},'required':['json'],'additionalProperties':False}),encoding='utf-8')
        original_images = []
        cli_image_arguments = []
        for idx, filename in enumerate(images or [], 1):
            image = Path(filename).resolve()
            allowed_roots = (jobs.ROOT / 'cf_posting' / 'output',
                             jobs.ROOT / 'naver_blog_posting' / 'output', scratch)
            if not image.is_file() or image.suffix.lower() not in ('.jpg', '.jpeg', '.png') or not any(image.is_relative_to(root.resolve()) for root in allowed_roots):
                raise RuntimeError('검증된 작업 산출물 이미지 경로가 아닙니다.')
            original_images.append(image)
            cli_image_arguments.extend(['--image', str(_prepare_cli_image(image, folder_path, idx))])
        audit_folder = None
        if audit_directory is not None:
            from PIL import Image
            audit_root = Path(audit_directory).resolve()
            approved = (jobs.ROOT / 'cf_posting' / 'output', jobs.ROOT / 'naver_blog_posting' / 'output')
            if not any(audit_root.is_relative_to(root.resolve()) for root in approved):
                raise RuntimeError('모델 진단 기록은 포스팅 산출물 폴더에만 저장할 수 있습니다.')
            call_id = uuid.uuid4().hex
            audit_folder = audit_root / call_id
            audit_folder.mkdir(parents=True, exist_ok=False)
            attached = []
            for path in original_images:
                with Image.open(path) as asset:
                    width, height = asset.size
                attached.append({'imageIndex': len(attached) + 1, 'filename': path.name,
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'width': width, 'height': height})
            (audit_folder / 'request.json').write_text(json.dumps({'schemaVersion': 1, 'callId': call_id,
                'provider': 'codex', 'model': model, 'attachments': attached,
                'requestedReasoningEffort': reasoning_effort, 'configuredReasoningEffort': effort},
                ensure_ascii=False, indent=2), encoding='utf-8')
            (audit_folder / 'status.json').write_text(json.dumps({'status': 'calling'}), encoding='utf-8')
        image_order = '\n'.join(f'Attached image {n}: {Path(filename).name}' for n,filename in enumerate(images or [],1))
        instruction = 'Return the task result directly as the required JSON schema. No Markdown.\n' if response_schema else 'Return the task JSON object serialized into the outer schema string field json. No Markdown inside the JSON string.\n'
        safe_prompt = prompt if len(prompt) <= MAX_TURN_CHARS else (prompt[:MAX_TURN_CHARS] + '\n...[truncated for CLI turn limit]')
        full_input = 'Do not use tools, access files, or execute commands. Solve the task using supplied text and attached images.\n' + instruction + image_order + '\n' + safe_prompt

        candidates = _fallback_candidates(config, model, effort, allowed)
        last_error = None
        for attempt_idx, (cand_model, cand_effort) in enumerate(candidates):
            if Path(output).is_file():
                try:
                    Path(output).unlink()
                except OSError:
                    pass
            command = [config['executable'], 'exec', *cli_image_arguments,
                       '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
                       '--sandbox', 'read-only', '--json', '--color', 'never', '--model', cand_model,
                       '-c', 'forced_login_method="chatgpt"', '-c', f'model_reasoning_effort="{cand_effort}"',
                       '-c', 'project_doc_max_bytes=0', '-c', 'web_search="disabled"',
                       '-c', 'features.shell_tool=false', '-c', 'features.apply_patch_freeform=false',
                       '-c', 'features.multi_agent=false', '--output-schema', str(schema), '--output-last-message', output, '-']
            try:
                result = subprocess.run(command, input=full_input,
                    capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=folder,
                    env=environment(config), timeout=300, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired:
                if attempt_idx + 1 < len(candidates):
                    time.sleep(1.5)
                    continue
                if audit_folder is not None:
                    if Path(output).is_file():
                        (audit_folder / 'response.json').write_bytes(Path(output).read_bytes())
                    (audit_folder / 'status.json').write_text(json.dumps({'status': 'timeout'}), encoding='utf-8')
                raise RuntimeError('Codex CLI 생성 제한시간 5분 초과.') from None

            error_detail = _cli_error_detail(result.stdout, result.stderr) if result.returncode else None
            if result.returncode:
                combined = (result.stdout + '\n' + result.stderr).strip().lower()
                retriable = any(w in combined for w in ('capacity', 'overloaded', 'server_error', '502', '503', '504', 'rate limit', 'try again', 'input_too_large', 'maximum length'))
                if retriable and attempt_idx + 1 < len(candidates):
                    if 'input_too_large' in combined or 'maximum length' in combined:
                        safe_prompt = safe_prompt[:220_000]
                        full_input = 'Do not use tools, access files, or execute commands. Solve the task using supplied text and attached images.\n' + instruction + image_order + '\n' + safe_prompt
                    time.sleep(2.0)
                    continue
                if audit_folder is not None:
                    if Path(output).is_file():
                        (audit_folder / 'response.json').write_bytes(Path(output).read_bytes())
                    (audit_folder / 'status.json').write_text(json.dumps({'status': 'cli_returned',
                        'returnCode': result.returncode, 'responsePresent': Path(output).is_file(),
                        'errorSummary': error_detail}, ensure_ascii=False), encoding='utf-8')
                reason = '구독 사용량 한도 초과' if any(word in combined for word in ('usage limit', 'rate limit', 'quota', '429')) else f'CLI 오류 ({error_detail})'
                raise RuntimeError('Codex CLI 생성 실패: ' + reason)

            if audit_folder is not None:
                if Path(output).is_file():
                    (audit_folder / 'response.json').write_bytes(Path(output).read_bytes())
                (audit_folder / 'status.json').write_text(json.dumps({'status': 'cli_returned',
                    'returnCode': result.returncode, 'responsePresent': Path(output).is_file(),
                    'errorSummary': error_detail}, ensure_ascii=False), encoding='utf-8')
            if not Path(output).is_file():
                raise RuntimeError('Codex CLI가 최종 JSON을 반환하지 않았습니다.')
            events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            if not any(event.get('type') == 'turn.completed' for event in events):
                raise RuntimeError('Codex CLI 실행이 정상 완료되지 않았습니다.')
            response = parse_json(Path(output).read_text(encoding='utf-8'))
            if response_schema:
                return response, model
            if not isinstance(response.get('json'), str):
                raise RuntimeError('Codex 구조화 응답 계약 불일치')
            try:
                return parse_json(response['json']), model
            except RuntimeError:
                (scratch / 'codex-json-last-invalid.json').write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf-8')
                raise
        raise last_error or RuntimeError('Codex CLI 생성 실패')


def generate(prompt, model, images=None, response_schema=None, audit_directory=None, reasoning_effort=None):
    if os.name == 'nt':
        return generate_local(prompt, model, images, response_schema, audit_directory=audit_directory,
                              reasoning_effort=reasoning_effort)
    if reasoning_effort is not None:
        raise RuntimeError('명시적 추론 강도 선택은 Windows 포스팅 작업에서 실행하세요.')
    info = runtime()
    if not info.get('online') or not info.get('authenticated'):
        raise RuntimeError('Windows Codex 작업 호스트가 연결되지 않았습니다.')
    # The NAS connection test is the sole remote generation operation.
    if prompt != 'Return JSON {"ok":true}.':
        raise RuntimeError('일반 원고 생성은 Windows 포스팅 작업에서 실행하세요.')
    job = jobs.enqueue('codex-test', {'model': model})
    deadline = time.monotonic() + 330
    while time.monotonic() < deadline:
        state = jobs.load(job['id'])
        if state['status'] == 'succeeded':
            return state['result'], model
        if state['status'] == 'failed':
            raise RuntimeError(state['error'])
        time.sleep(0.5)
    raise RuntimeError('Windows Codex 연결 테스트 응답 시간 초과.')
