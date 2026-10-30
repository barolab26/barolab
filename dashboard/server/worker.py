"""Bounded Ubuntu jobs; publishing is owned by the durable dispatcher."""
import argparse,json,os,subprocess,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
# Scheduled jobs must resolve the same modules as the dashboard launcher.
IMPORT_PATHS = (ROOT, ROOT / 'dashboard', ROOT / 'dashboard' / 'server')
for import_path in reversed(IMPORT_PATHS):
    sys.path.insert(0, str(import_path))
sys.dont_write_bytecode=True
from common import dashboard_jobs as jobs
from common.ego_telemetry import export_environment
METRICS_STAGE_LIMITS={'dashboard/revenue.py':180,'dashboard/traffic.py':840,'dashboard/metrics.py':480,
                      'naver_kin.posting':480,'threads_posting.posting':480}


def run_metrics(python, commands):
    """Bound only automation helpers. Attached browser processes are never terminated."""
    from dashboard.collectors.metrics import collector_lock
    from common import collection_observability as observation
    collector_paths = {
        'dashboard/revenue.py': 'dashboard/collectors/revenue.py',
        'dashboard/traffic.py': 'dashboard/collectors/traffic.py',
        'dashboard/metrics.py': 'dashboard/collectors/metrics.py',
    }
    runtime_path = ROOT / 'dashboard/data/metrics-runtime.json'
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    with collector_lock(ROOT / 'dashboard/data/metrics-worker.lock') as acquired:
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
                target = ['-m', script] if script in ('naver_kin.posting', 'threads_posting.posting') else [str(ROOT / collector_paths.get(script, script))]
                process = subprocess.Popen([python, '-u', '-B', '-X', 'utf8', *target, *(argument if isinstance(argument, (list, tuple)) else [argument] if argument else [])],
                    cwd=str(ROOT), stdout=sys.stdout, stderr=sys.stderr,
                    env=dict(export_environment(), PYTHONPATH=os.pathsep.join(
                        [*(str(p) for p in IMPORT_PATHS), os.environ.get('PYTHONPATH', '')]),
                        PYTHONUTF8='1', PYTHONIOENCODING='utf-8', BAROLAB_KEEP_BROWSER='1'),
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
            health = observation.finish_run(ROOT / 'dashboard/data', runtime, outcomes, desktop=True)
            runtime['collectionStatus'] = health.get('collectionStatus', 'unknown')
            if runtime['collectionStatus'] == 'success':
                runtime['lastCollectionSuccessAt'] = runtime['finishedAt']
                runtime['lastSuccessAt'] = runtime['finishedAt']
        except Exception:
            runtime['collectionStatus'] = 'unknown'
            runtime['observabilityStatus'] = 'record_failed'
            # Persist a visible failure without exposing exception text or blocking collectors.
            try:
                observation.write(ROOT / 'dashboard/data/collection-observability-error.json',
                                  {'checkedAt': jobs.stamp(), 'reasonCode': 'ledger_write_failed'})
            except OSError:
                print('Observability ledger unavailable; collection health unknown', flush=True)
        try:
            observation.export_public_health(ROOT / 'dashboard/data', ROOT / 'dashboard/data/public/collection-health.json')
        except Exception:
            print('Public collection status export unavailable; private ledger preserved', flush=True)
        jobs.write(runtime_path, runtime)
        return code


def run_task(task):
    if task=='serve':
        if os.name == 'nt':
            return subprocess.run([sys.executable, '-u', '-B', '-m', 'dashboard.server.memory_worker'], cwd=ROOT, timeout=60, env=export_environment()).returncode
        return subprocess.run(['systemctl','--user','start','barolab-memory-review.service'],timeout=30).returncode
    if task=='metrics':
        return run_metrics(sys.executable,[('dashboard/revenue.py','--collect'),('dashboard/traffic.py','--collect'),
            ('dashboard/metrics.py',['--collect','--read-only']),('naver_kin.posting','--measure'),('threads_posting.posting','measure')])
    if task=='naver-monitor':
        from naver_blog_posting.posting import pipeline_lock
        from common.channel_parameters import monitor
        from dashboard.collectors.naver_public import reconcile
        try:
            with pipeline_lock():
                reconcile(ROOT/'naver_blog_posting')
                monitor()
        except RuntimeError as exc:
            if 'already running' not in str(exc): raise
        return 0
    commands={
      'cleaner':['-m','common.channel_parameters','cf-cycle'],
      'naver-daily':['-m','common.channel_parameters','naver-cycle'],
      'maintenance':['-m','common.content_maintenance'],
      'watchdog':['-m','common.system_watchdog','--heal-now'],
    }
    return subprocess.run([sys.executable,'-u','-B',*commands[task]],cwd=ROOT,
                          env=dict(export_environment(),DISPLAY=os.environ.get('DISPLAY',':10')),
                          timeout=5400).returncode


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',choices=('serve','cleaner','metrics','naver-monitor','naver-daily','maintenance','watchdog'),default='serve')
    args=parser.parse_args()
    return run_task(args.task)


if __name__=='__main__':sys.exit(main())
