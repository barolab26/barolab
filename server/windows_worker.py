"""Hidden Windows jobs; no web listener and no browser lifecycle changes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

MONITOR_ONLY = __name__ == '__main__' and '--task' in sys.argv and 'naver-monitor' in sys.argv
if MONITOR_ONLY:
    _monitor_boot_log = Path.home()/'.barolab/logs/naver-monitor.log'
    _monitor_boot_log.parent.mkdir(parents=True,exist_ok=True)
    sys.stdout=sys.stderr=_monitor_boot_log.open('a',encoding='utf-8',buffering=1)
    print('[naver-monitor] bootstrap_before_project_imports',flush=True)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if not MONITOR_ONLY:
    from common import codex_cli, dashboard_jobs as jobs

METRICS_STAGE_LIMITS = {'dashboard/revenue.py': 180, 'dashboard/traffic.py': 840,
                        'dashboard/metrics.py': 480, 'naver_kin.measurement': 480,
                        'threads_posting': 480}


def _naver_recovery_schedule_script(apply=False):
    script = r'''[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ErrorActionPreference = 'Stop'
$taskName = 'BaroLab-Naver-Daily'
$task = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction Stop
$actions = @($task.Actions)
if ($actions.Count -ne 1 -or [IO.Path]::GetFileName($actions[0].Execute) -ine 'pythonw.exe' -or
    -not [string]::Equals($actions[0].Arguments, $env:BAROLAB_NAVER_EXPECTED_ARGUMENTS, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Existing Naver task action does not match this project; configuration refused'
}
if (-not $task.Principal.UserId -or [string]$task.Principal.LogonType -ne 'Interactive') {
    throw 'Existing Naver task must retain its interactive desktop account'
}
function Snapshot($value) {
    $info = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath '\'
    [ordered]@{
        taskName=$value.TaskName; state=[string]$value.State;
        enabled=$value.Settings.Enabled; startWhenAvailable=$value.Settings.StartWhenAvailable;
        multipleInstances=[string]$value.Settings.MultipleInstances;
        executionTimeLimit=$value.Settings.ExecutionTimeLimit;
        action=@($value.Actions | ForEach-Object { @{execute=$_.Execute; arguments=$_.Arguments; workingDirectory=$_.WorkingDirectory} });
        principal=@{userId=$value.Principal.UserId; logonType=[string]$value.Principal.LogonType; runLevel=[string]$value.Principal.RunLevel};
        triggers=@($value.Triggers | ForEach-Object { @{type=$_.CimClass.CimClassName; enabled=$_.Enabled; startBoundary=$_.StartBoundary; userId=$_.UserId; interval=$_.Repetition.Interval; duration=$_.Repetition.Duration} });
        lastRunAt=[string]$info.LastRunTime; nextRunAt=[string]$info.NextRunTime; lastResult=$info.LastTaskResult
    }
}
$before = Snapshot $task
$applied = $false
$backup = $null
'''
    if apply:
        script += r'''
$backup = $env:BAROLAB_NAVER_TASK_BACKUP
if (-not $backup) { throw 'Task XML backup path is required' }
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($backup)) | Out-Null
$xml = Export-ScheduledTask -TaskName $taskName -TaskPath '\'
$bytes = [Text.UTF8Encoding]::new($false).GetBytes($xml)
$stream = [IO.File]::Open($backup, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
$tick = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $task.Principal.UserId
$settings = $task.Settings
$settings.Enabled = $true
$settings.StartWhenAvailable = $true
$settings.MultipleInstances = 2
Set-ScheduledTask -TaskName $taskName -TaskPath '\' -Trigger @($tick,$logon) -Settings $settings | Out-Null
$task = Get-ScheduledTask -TaskName $taskName -TaskPath '\'
$after = Snapshot $task
if (@($after.action).Count -ne 1 -or $before.action[0].execute -cne $after.action[0].execute -or
    $before.action[0].arguments -cne $after.action[0].arguments -or
    $before.action[0].workingDirectory -cne $after.action[0].workingDirectory -or
    $before.principal.userId -cne $after.principal.userId -or
    $before.principal.logonType -cne $after.principal.logonType -or
    $before.principal.runLevel -cne $after.principal.runLevel) {
    throw 'Task action or account changed unexpectedly; inspect the saved task XML'
}
if (-not $task.Settings.Enabled -or -not $task.Settings.StartWhenAvailable -or
    [string]$task.Settings.MultipleInstances -ne 'IgnoreNew' -or @($task.Triggers).Count -ne 2 -or
    -not @($task.Triggers | Where-Object { $_.Repetition.Interval -eq 'PT5M' }).Count -or
    -not @($task.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' }).Count) {
    throw 'Naver recovery task configuration could not be verified'
}
$applied = $true
'''
    script += r'''
[ordered]@{applied=$applied; actionVerified=$true; backupPath=$backup; before=$before;
    current=(Snapshot $task); proposed=@{interval='PT5M'; repeatIndefinitely=$true; logonTrigger=$true;
    enabled=$true; startWhenAvailable=$true; multipleInstances='IgnoreNew';
    note='Existing runner decides eligible publication dates, deadlines and duplicate protection'}} | ConvertTo-Json -Depth 7 -Compress
'''
    return script


def configure_naver_recovery_schedule(*, apply=False):
    """Preview by default; explicit apply updates only the existing Naver task."""
    if os.name != 'nt':
        raise RuntimeError('Naver scheduling requires the Windows desktop host')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    env = dict(os.environ, PSModulePath=str(powershell.parent / 'Modules'),
               BAROLAB_NAVER_EXPECTED_ARGUMENTS=f'-B -X utf8 "{ROOT / "server/windows_worker.py"}" --task naver-daily')
    if apply:
        env['BAROLAB_NAVER_TASK_BACKUP'] = str(Path.home() / '.barolab/scratch' / ('naver-daily-before-recovery-' + uuid.uuid4().hex + '.xml'))
    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', _naver_recovery_schedule_script(apply)],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30, env=env,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Naver scheduler configuration failed: ' + result.stderr.strip()[:1200])
    report = json.loads(result.stdout)
    if report.get('actionVerified') is not True or report.get('applied') is not apply:
        raise RuntimeError('Naver scheduler returned an invalid configuration receipt')
    return report


def run_metrics(python, commands):
    """Bound only automation helpers. Attached browser processes are never terminated."""
    from dashboard.metrics import collector_lock
    from common import collection_observability as observation
    runtime_path = ROOT / 'server/data/metrics-runtime.json'
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    with collector_lock(ROOT / 'server/data/metrics-worker.lock') as acquired:
        if not acquired:
            return 0
        try:
            previous = json.loads(runtime_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            previous = {}
        runtime = {'schema': 'metrics-runtime-v2', 'runId': uuid.uuid4().hex,
                   'pid': os.getpid(), 'status': 'running',
                   'startedAt': jobs.stamp(), 'checkedAt': jobs.stamp(), 'stages': [],
                   'budgetSeconds': sum(METRICS_STAGE_LIMITS.values()),
                   'lastProcessSuccessAt': previous.get('lastProcessSuccessAt') or previous.get('lastSuccessAt'),
                   'lastSuccessAt': previous.get('lastCollectionSuccessAt'),
                   'lastCollectionSuccessAt': previous.get('lastCollectionSuccessAt'),
                   'previousInterrupted': previous.get('status') == 'running',
                   'previousStartedAt': previous.get('startedAt'),
                   'successMeaning': 'process_exit_zero_not_source_collection',
                   'sourceHealthNote': '단계 종료 성공과 원천 데이터 수집 성공은 별도 · 원천 timestamp/backoff 확인'}
        code = 0
        outcomes = []
        jobs.write(runtime_path, runtime)
        for script, argument in commands:
            stage = {'script': script, 'status': 'running', 'startedAt': jobs.stamp(),
                     'timeoutSeconds': METRICS_STAGE_LIMITS[script], 'lastProcessSuccessAt': next(
                         (s.get('lastProcessSuccessAt') or s.get('lastSuccessAt') for s in previous.get('stages', []) if s.get('script') == script), None)}
            runtime['stages'].append(stage)
            runtime['currentStage'] = script
            jobs.write(runtime_path, runtime)
            process, started = None, time.monotonic()
            try:
                target = ['-m', script] if script in ('naver_kin.measurement', 'threads_posting') else [str(ROOT / script)]
                process = subprocess.Popen([python, '-u', '-B', '-X', 'utf8', *target, *([argument] if argument else [])],
                    cwd=str(ROOT), stdout=sys.stdout, stderr=sys.stderr,
                    env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', BAROLAB_KEEP_BROWSER='1'),
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                stage['helperPid'] = process.pid
                while True:
                    remaining = METRICS_STAGE_LIMITS[script] - (time.monotonic() - started)
                    if remaining <= 0:
                        # This Popen object is our dedicated Python collector, never a browser.
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill(); process.wait(timeout=5)
                        stage.update(status='timed_out', reason='단계 시간 제한 초과 · 마지막 원천 증거 보존 · 다음 단계 진행')
                        code = max(code, 1)
                        break
                    try:
                        result = process.wait(timeout=min(10, remaining))
                        stage.update(status='completed' if result == 0 else 'failed', exitCode=result)
                        if result == 0:
                            stage['lastProcessSuccessAt'] = jobs.stamp()
                        else:
                            code = max(code, 1)
                        break
                    except subprocess.TimeoutExpired:
                        runtime['checkedAt'] = jobs.stamp()
                        stage['elapsedSeconds'] = round(time.monotonic() - started, 1)
                        jobs.write(runtime_path, runtime)
            except Exception:
                stage.update(status='failed', reason='수집 보조 프로세스 실행 실패 · 다음 단계 진행')
                code = max(code, 1)
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
            stage.update(finishedAt=jobs.stamp(), elapsedSeconds=round(time.monotonic() - started, 1))
            try:
                sources = observation.snapshot_outcomes(ROOT, script)
                for source in sources:
                    source.setdefault('durationSeconds', stage['elapsedSeconds'])
                outcomes.extend(sources)
            except Exception:
                outcomes.append({'source': script, 'scope': 'source-evidence', 'status': 'unknown',
                                 'complete': False, 'reasonCode': 'snapshot_read_failed'})
            if stage['status'] != 'completed':
                outcomes.append({'source': script, 'scope': 'collector-process', 'status': 'failed',
                                 'complete': False, 'attemptedAt': stage['startedAt'],
                                 'reasonCode': 'process_' + stage['status']})
            runtime['checkedAt'] = jobs.stamp()
            jobs.write(runtime_path, runtime)
        try:
            from server.growth import refresh_performance_feedback
            feedback = refresh_performance_feedback()
            runtime['pagePerformance'] = {key: feedback.get(key) for key in ('status', 'complete', 'start', 'end', 'reasonCodes')}
        except Exception as exc:
            runtime['pagePerformance'] = {'status': 'error', 'complete': False, 'reason': type(exc).__name__}
            code = max(code, 1)
        runtime.update(status='completed' if code == 0 else 'partial_failure', finishedAt=jobs.stamp(),
                       checkedAt=jobs.stamp(), currentStage=None)
        if code == 0:
            runtime['lastProcessSuccessAt'] = runtime['finishedAt']
        try:
            health = observation.finish_run(ROOT / 'server/data', runtime, outcomes, desktop=True)
            runtime['collectionStatus'] = health.get('collectionStatus', 'unknown')
            if runtime['collectionStatus'] == 'success':
                runtime['lastCollectionSuccessAt'] = runtime['finishedAt']
                runtime['lastSuccessAt'] = runtime['finishedAt']
        except Exception:
            runtime['collectionStatus'] = 'unknown'
            runtime['observabilityStatus'] = 'record_failed'
            # Persist a visible failure without exposing exception text or blocking collectors.
            try:
                observation.write(ROOT / 'server/data/collection-observability-error.json',
                                  {'checkedAt': jobs.stamp(), 'reasonCode': 'ledger_write_failed'})
            except OSError:
                print('Observability ledger unavailable; collection health unknown', flush=True)
        try:
            observation.export_public_health(ROOT / 'server/data', ROOT / 'dashboard/data/collection-health.json')
        except Exception:
            print('Public collection status export unavailable; private ledger preserved', flush=True)
        jobs.write(runtime_path, runtime)
        return code


def run_task(task):
    python = str(Path(sys.executable).with_name('python.exe')) if os.name == 'nt' else sys.executable
    if task == 'maintenance':
        try:
            result = subprocess.run([python, '-u', '-B', '-X', 'utf8', '-m', 'common.content_maintenance'],
                cwd=str(ROOT), stdout=sys.stdout, stderr=sys.stderr, timeout=580,
                env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return result.returncode
        except subprocess.TimeoutExpired:
            from common.content_maintenance import runtime
            runtime(status='interrupted', stage='idle', reason='유지보수 보조 프로세스 580초 상한 · 적용 상태는 다음 회차 확인', activeJob=None)
            return 1
    commands = {
        'cleaner': [('cf_posting/pipeline_runner.py', '--catch-up-once')],
        'cf-retry': [('cf_posting/pipeline_runner.py', '--manual-retry-once')],
        'metrics': [('dashboard/revenue.py', '--collect'), ('dashboard/traffic.py', '--collect'), ('dashboard/metrics.py', '--collect'),
                    ('naver_kin.measurement', ''), ('threads_posting', 'measure')],
        'naver-monitor': [('naver_blog_posting/pipeline_runner.py', '--monitor')],
        'naver-daily': [('naver_blog_posting/pipeline_runner.py', '--catch-up')],
    }
    if task == 'naver-daily' and os.name != 'nt':
        commands[task] = [('ego_lite_runner.py', '--naver-catch-up')]
    if task == 'metrics':
        return run_metrics(python, commands[task])
    code = 0
    for script, argument in commands[task]:
        if task == 'naver-monitor':
            print('[naver-monitor] child_start timeout=210s',flush=True)
        result = subprocess.run([python, '-u', '-B', '-X', 'utf8', str(ROOT / script), argument],
            cwd=str(ROOT), stdout=sys.stdout, stderr=sys.stderr,
            env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', BAROLAB_KEEP_BROWSER='1'),
            timeout=210 if task == 'naver-monitor' else None,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        code = max(code, result.returncode)
        if task == 'naver-monitor':print('[naver-monitor] child_exit code='+str(result.returncode),flush=True)
    if task == 'cleaner' and code == 0:
        launch_idle_maintenance(python)
    return code


def launch_idle_maintenance(python):
    """Cleaner never waits for maintenance; publishing retains its own priority."""
    from common.content_maintenance import state, idle_reason, runtime, lock_available, DATA
    from datetime import datetime, timezone, timedelta
    config = state()
    if not config['policy']['enabled'] or idle_reason():
        return False
    last = config['runtime'].get('lastLaunchedAt')
    if last:
        try:
            if datetime.now(timezone.utc) - datetime.fromisoformat(last) < timedelta(minutes=config['policy']['auditIntervalMinutes']):
                return False
        except ValueError:
            return False
    if config['runtime'].get('status') == 'running':
        if not lock_available(DATA / 'content-maintenance.lock'):
            return False
        runtime(status='interrupted', stage='idle', reason='이전 보조 프로세스 잠금 해제 확인 · 중단된 작업은 반영 조회로 복구')
    process = subprocess.Popen([python, '-u', '-B', '-X', 'utf8', str(ROOT / 'server/windows_worker.py'), '--task', 'maintenance'],
        cwd=str(ROOT), env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    runtime(lastLaunchedAt=datetime.now(timezone.utc).isoformat(), launcher='existing_cf_cleaner_idle_hook', helperPid=process.pid)
    return True


def serve_cf_retries():
    # Separate from slow Codex connection tests; the scheduler owns the CF lock.
    while True:
        try:
            jobs.write(ROOT / 'server/data/cf-retry-runtime.json',
                       {'pid': os.getpid(), 'checkedAt': jobs.stamp(), 'status': 'watching',
                        'pollSeconds': 1, 'manualOnly': True})
            if jobs.pending('cf-retry'):
                jobs.write(ROOT / 'server/data/cf-retry-runtime.json',
                           {'pid': os.getpid(), 'checkedAt': jobs.stamp(),
                            'status': 'dispatching', 'manualOnly': True})
                run_task('cf-retry')
        except Exception as exc:
            print('CF retry watcher:', type(exc).__name__, flush=True)
        time.sleep(1)


def serve_cf_cleaner():
    while True:
        try:
            run_task('cleaner')
        except Exception as exc:
            print('CF cleaner loop error:', type(exc).__name__, flush=True)
        time.sleep(60)


def serve():
    # Prevent repeated task starts from running the same CLI request twice.
    from dashboard.metrics import collector_lock
    lock = Path.home() / '.barolab' / 'dashboard-worker.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    with collector_lock(lock) as acquired:
        if not acquired:
            return
        threading.Thread(target=serve_cf_retries, daemon=True, name='cf-retry-watcher').start()
        threading.Thread(target=serve_cf_cleaner, daemon=True, name='cf-cleaner-loop').start()
        threading.Thread(target=serve_collection_watchdog, daemon=True, name='collection-health-watcher').start()
        threading.Thread(target=serve_sre_system_watchdog, daemon=True, name='sre-system-watchdog').start()
        threading.Thread(target=serve_growth_actions, daemon=True, name='growth-action-worker').start()
        refreshed = 0
        while True:
            try:
                if time.monotonic() - refreshed > 30:
                    codex_cli.refresh_runtime()
                    refreshed = time.monotonic()
                for job in jobs.pending('codex-test'):
                    age = time.time() - jobs.path(job['id']).stat().st_mtime
                    if age > 330:
                        jobs.finish(job, error='연결 테스트 요청이 만료되었습니다. 다시 테스트하세요.')
                        continue
                    job.update(status='running', startedAt=jobs.stamp())
                    jobs.write(jobs.path(job['id']), job)
                    try:
                        result, _ = codex_cli.generate_local('Return JSON {"ok":true}.', job['payload']['model'])
                        jobs.finish(job, result=result)
                    except Exception as exc:
                        jobs.finish(job, error=str(exc))
            except Exception as exc:
                print(type(exc).__name__, str(exc)[:200], flush=True)
            time.sleep(2)


def serve_growth_actions():
    """Consume local and NAS requests; uncertain running jobs are never replayed."""
    from dashboard.metrics import collector_lock
    directories = [ROOT / 'server/data/control-jobs',
                   Path(os.environ.get('BAROLAB_NAS_ROOT', r'\\otns\yoonlab\10_Project\BaroLab')) / 'server/data/control-jobs']
    while True:
        for directory in dict.fromkeys(directories):
            if not directory.is_dir():
                continue
            for job_path in directory.glob('*.json'):
                job = None
                try:
                    job = json.loads(job_path.read_text(encoding='utf-8'))
                    if job.get('kind') not in ('growth-radar', 'growth-doctor') or job.get('status') != 'pending':
                        continue
                    with collector_lock(job_path.with_suffix('.lock')) as acquired:
                        if not acquired:
                            continue
                        job = json.loads(job_path.read_text(encoding='utf-8'))
                        if job.get('status') != 'pending':
                            continue
                        payload = job.get('payload') or {}
                        command = [sys.executable, '-B', '-X', 'utf8', str(ROOT / 'cf_posting/pipeline_runner.py'),
                                   '--' + job['kind']]
                        if job['kind'] == 'growth-doctor':
                            from naver_kin.pipeline import CF_BASE_DOMAINS
                            domain = payload.get('domain') or ''
                            if domain and domain not in CF_BASE_DOMAINS:
                                raise ValueError('Unapproved growth domain')
                            if domain:
                                command.extend(['--growth-domain', domain])
                            command.extend(['--growth-limit', str(max(1, min(int(payload.get('limit', 5)), 10)))])
                            if payload.get('apply') is True:
                                command.append('--apply-growth')
                        job.update(status='running', startedAt=jobs.stamp(), workerPid=os.getpid())
                        jobs.write(job_path, job)
                        process = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True,
                                                 encoding='utf-8', errors='replace', timeout=1800,
                                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                        output = (process.stdout or '').strip()
                        result = None
                        decoder = json.JSONDecoder()
                        for offset, char in enumerate(output):
                            if char != '{':
                                continue
                            try:
                                parsed, end = decoder.raw_decode(output[offset:])
                                if not output[offset + end:].strip():
                                    result = parsed
                                    break
                            except ValueError:
                                continue
                        job.update(status='succeeded' if process.returncode == 0 and result is not None else 'failed',
                                   finishedAt=jobs.stamp(), exitCode=process.returncode, result=result,
                                   outputTail=(output or process.stderr or '')[-3000:])
                        jobs.write(job_path, job)
                except Exception as exc:
                    # A timeout can follow a remote mutation; never auto-requeue it.
                    try:
                        if not isinstance(job, dict):
                            continue
                        job.update(status='interrupted_unknown' if isinstance(exc, subprocess.TimeoutExpired) else 'failed',
                                   finishedAt=jobs.stamp(), error=type(exc).__name__)
                        jobs.write(job_path, job)
                    except Exception:
                        pass
        time.sleep(5)


def serve_collection_watchdog():
    from common.collection_observability import watchdog_check, export_public_health
    while True:
        try:
            watchdog_check(ROOT / 'server/data', desktop=True)
            export_public_health(ROOT / 'server/data', ROOT / 'dashboard/data/collection-health.json')
        except Exception:
            print('Collection watchdog check unavailable; see collection health freshness', flush=True)
        time.sleep(60)


def serve_sre_system_watchdog():
    from common.system_watchdog import run_system_watchdog
    while True:
        try:
            run_system_watchdog(trigger_source='windows-worker-10m', broadcast=True)
        except Exception as exc:
            print('SRE system watchdog error:', type(exc).__name__, flush=True)
        time.sleep(600)


def mirror_worker_state():
    """Publish Windows-owned observations and consistent ledgers to NAS; never growth DB/settings."""
    import sqlite3
    from contextlib import closing
    from common.dashboard_jobs import atomic_text
    from dashboard.metrics import collector_lock
    nas = Path(os.environ.get('BAROLAB_NAS_ROOT', r'\\otns\yoonlab\10_Project\BaroLab'))
    if os.name != 'nt' or not (nas / 'server/data').is_dir():
        return {'state': 'unavailable', 'files': [], 'errors': []}
    report = {'state': 'synced', 'files': [], 'errors': []}
    snapshots = (
        'server/data/browser-status.json', 'server/data/metrics.json', 'server/data/traffic.json',
        'server/data/revenue.json', 'server/data/collection-health.json',
        'server/data/kin-automation-state.json', 'server/data/kin-measurement.json',
        'server/data/threads-measurement.json',
        'dashboard/data/kin.json', 'dashboard/data/kin-measurement.json',
        'dashboard/data/threads.json', 'dashboard/data/threads-measurement.json',
        'dashboard/data/collection-health.json', 'dashboard/data/metrics.json',
        'cf_posting/data/daily_schedule.json', 'naver_blog_posting/data/public-verification.json',
    )
    with collector_lock(ROOT / 'server/data/nas-mirror.lock') as acquired:
        if not acquired:
            return {'state': 'busy', 'files': [], 'errors': []}
        for relative in (*snapshots, 'server/data/kin.sqlite3', 'server/data/threads.sqlite3'):
            source, destination = ROOT / relative, nas / relative
            if not source.is_file() or not destination.parent.is_dir():
                continue
            temporary = None
            try:
                modified = source.stat().st_mtime
                if relative.endswith('.sqlite3'):
                    wal = Path(str(source) + '-wal')
                    if wal.is_file():
                        modified = max(modified, wal.stat().st_mtime)
                if destination.is_file() and destination.stat().st_mtime >= modified:
                    continue
                if relative.endswith('.sqlite3'):
                    # Only the Windows workers write these ledgers; NAS exposes read-only summaries.
                    # SQLite backup includes committed WAL pages; never copy a running DB file.
                    if any(Path(str(destination) + suffix).exists() for suffix in ('-wal', '-journal')):
                        raise RuntimeError('NAS ledger has an active journal; mirror refused')
                    temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
                    deadline = time.monotonic() + 20
                    def check_progress(status, remaining, total):
                        if time.monotonic() > deadline:
                            raise TimeoutError('SQLite backup deadline')
                    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as src:
                        with closing(sqlite3.connect(str(temporary), timeout=2)) as dst:
                            src.backup(dst, pages=128, progress=check_progress, sleep=0.1)
                            dst.execute('PRAGMA journal_mode=DELETE')
                            if dst.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                                raise RuntimeError('SQLite backup integrity failed')
                    os.replace(temporary, destination)
                else:
                    content = source.read_text(encoding='utf-8-sig')
                    json.loads(content)
                    atomic_text(destination, content)
                os.utime(destination, (modified, modified))
                report['files'].append(relative)
            except Exception as exc:
                report['errors'].append({'file': relative, 'error': type(exc).__name__})
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        report['errors'].append({'file': relative, 'error': 'temporary_cleanup_failed'})
        if report['errors']:
            report['state'] = 'partial'
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', choices=('serve', 'cleaner', 'metrics', 'naver-monitor', 'naver-daily', 'maintenance', 'watchdog'), default='serve')
    parser.add_argument('--configure-naver-recovery', choices=('preview', 'apply'))
    args = parser.parse_args()
    if args.configure_naver_recovery:
        print(json.dumps(configure_naver_recovery_schedule(apply=args.configure_naver_recovery == 'apply'), ensure_ascii=False))
        return 0
    logs = Path.home() / '.barolab' / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / (args.task + '.log')).open('a', encoding='utf-8', buffering=1) as output:
        sys.stdout = sys.stderr = output
        if args.task == 'naver-monitor':print('[naver-monitor] worker_enter',flush=True)
        try:
            return serve() if args.task == 'serve' else run_task(args.task)
        except Exception:
            import traceback
            traceback.print_exc()
            return 1
        finally:
            if args.task in ('naver-monitor', 'metrics'):
                try:
                    print('[nas-mirror] ' + json.dumps(mirror_worker_state()), flush=True)
                except Exception as exc:
                    print('[nas-mirror] failed: ' + type(exc).__name__, flush=True)


if __name__ == '__main__':
    sys.exit(main())
