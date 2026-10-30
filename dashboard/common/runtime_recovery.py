"""Registered scheduler/collector recovery; never restart active jobs or submit content."""
import os
import subprocess
import sys
from pathlib import Path

UNITS = {
    'cf_blog': ('barolab-parameters-prepare.timer', 'barolab-parameters-dispatch.timer'),
    'naver_blog': ('barolab-parameters-prepare.timer', 'barolab-parameters-dispatch.timer',
                   'barolab-naver-monitor.timer', 'barolab-naver-monitor.service'),
    'naver_kin': ('barolab-kin.timer', 'barolab-kin-measurement.timer',
                  'barolab-kin-measurement.service'),
    'collections': ('barolab-metrics.timer', 'barolab-metrics.service',
                    'barolab-revenue-refresh.timer', 'barolab-revenue-refresh.service',
                    'barolab-indexing.timer', 'barolab-indexing.service'),
}
WINDOWS_TASKS = {
    'barolab-metrics.timer': 'BaroLab-Metrics-Collector',
    'barolab-metrics.service': 'BaroLab-Metrics-Collector',
    'barolab-naver-monitor.timer': 'BaroLab-Naver-Monitor',
    'barolab-naver-monitor.service': 'BaroLab-Naver-Monitor',
    'barolab-kin.timer': 'BaroLab-Kin-Seven-Day-Pilot',
    'barolab-kin-measurement.timer': 'BaroLab-Kin-Seven-Day-Pilot-Measurement',
    'barolab-kin-measurement.service': 'BaroLab-Kin-Seven-Day-Pilot-Measurement',
}


def windows_runtime_state(project):
    """Observe registered tasks; Windows has no implicit systemd services."""
    import json
    units = UNITS.get(project, ())
    names = sorted({WINDOWS_TASKS[u] for u in units if u in WINDOWS_TASKS})
    tasks = {}
    observation_error = None
    if names:
        script = "$names=@(" + ','.join("'" + name + "'" for name in names) + ");"
        script += ("$rows=@(foreach($name in $names){$task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue;"
                   "if($task){[PSCustomObject]@{name=$name;state=$task.State.ToString();enabled=[bool]$task.Settings.Enabled}}});"
                   "ConvertTo-Json -InputObject $rows -Compress")
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                    capture_output=True, text=True, timeout=15, check=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            rows = json.loads(result.stdout or '[]')
            tasks = {r['name']: r for r in (rows if isinstance(rows, list) else [rows])}
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            observation_error = 'scheduler_observation_failed'
    rows = []
    for unit in units:
        name = WINDOWS_TASKS.get(unit)
        task = tasks.get(name)
        row = {'unit': unit, 'source': 'windows-task-scheduler', 'taskName': name,
               'LoadState': 'unknown' if observation_error else 'not-found',
               'ActiveState': 'unknown', 'SubState': 'unknown', 'UnitFileState': 'unknown'}
        if task:
            enabled = task.get('enabled') is True and task.get('state') != 'Disabled'
            running = task.get('state') == 'Running'
            row.update(LoadState='loaded', UnitFileState='enabled' if enabled else 'disabled',
                       ActiveState='active' if running or enabled and unit.endswith('.timer') else 'inactive',
                       SubState='running' if running else 'waiting' if enabled else 'disabled')
            if task.get('state') not in ('Ready', 'Running', 'Queued', 'Disabled'):
                row.update(ActiveState='unknown', SubState='unknown', reason='scheduler_state_unknown')
        else:
            row['reason'] = (observation_error or 'registered_task_not_found') if name else 'no_registered_task_mapping'
        rows.append(row)
    return rows


def runtime_state(project):
    if os.name == 'nt':
        return windows_runtime_state(project)
    rows = []
    for unit in UNITS.get(project, ()):
        result = subprocess.run(['systemctl', '--user', 'show', unit,
            '--property=LoadState,ActiveState,SubState,UnitFileState'],
            capture_output=True, text=True, timeout=5, check=True)
        rows.append({'unit': unit, **dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)})
    return rows


def recover_project_runtime(project):
    from common import work_agenda as agendas
    if agendas.enabled():agendas.require(project=project)
    if project not in UNITS:
        raise ValueError('Unregistered runtime project')
    if (Path.home() / 'EGO_EXEC_DISABLED').exists():
        return {'ok': False, 'status': 'held', 'reason': 'execution_disabled'}
    rows = runtime_state(project)
    actions = []
    if os.name == 'nt':
        service = {'collections': 'barolab-metrics.service', 'naver_blog': 'barolab-naver-monitor.service',
                   'naver_kin': 'barolab-kin-measurement.service'}.get(project)
        observed = next((row for row in rows if row['unit'] == service), {})
        if service and (observed.get('LoadState') != 'loaded' or observed.get('UnitFileState') != 'enabled'):
            return {'ok': False, 'status': 'held', 'project': project, 'before': rows,
                    'reason': 'registered_collector_disabled_or_unobserved', 'recoveryVerified': False}
        if observed.get('SubState') == 'running':
            return {'ok': True, 'status': 'already_running', 'project': project, 'before': rows,
                    'startRequested': [], 'recoveryVerified': False}
        root = Path(__file__).resolve().parents[2]
        cflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        if project == 'naver_blog':
            subprocess.Popen([sys.executable, '-u', '-B', '-m', 'dashboard.server.worker', '--task', 'naver-monitor'], cwd=str(root), creationflags=cflags)
            actions.append('barolab-naver-monitor.service')
        elif project == 'naver_kin':
            subprocess.Popen([sys.executable, '-u', '-B', '-m', 'naver_kin.posting', '--measure'], cwd=str(root), creationflags=cflags)
            actions.append('barolab-kin-measurement.service')
        elif project == 'collections':
            subprocess.Popen([sys.executable, '-u', '-B', '-m', 'dashboard.server.worker', '--task', 'metrics'], cwd=str(root), creationflags=cflags)
            actions.append('barolab-metrics.service')
        return {'ok': True, 'status': 'observed', 'project': project, 'before': rows,
                'startRequested': actions, 'after': runtime_state(project),
                'recoveryVerified': False, 'reason': 'Fresh source evidence required after scheduler/collector start'}
    for row in rows:
        # Disabled/masked timers are explicit holds, never missing schedules.
        if row['LoadState'] != 'loaded' or row.get('UnitFileState') in ('masked', 'disabled'):
            continue
        if row['ActiveState'] in ('active', 'activating', 'deactivating', 'reloading'):
            continue
        if row['unit'].endswith('.service'):
            timer = next((r for r in rows if r['unit'] == row['unit'].replace('.service', '.timer')), {})
            if timer.get('ActiveState') != 'active':
                continue
        subprocess.run(['systemctl', '--user', 'start', '--no-block', row['unit']],
                       capture_output=True, text=True, timeout=5, check=True)
        actions.append(row['unit'])
    return {'ok': True, 'status': 'observed', 'project': project, 'before': rows,
            'startRequested': actions, 'after': runtime_state(project),
            'recoveryVerified': False, 'reason': 'Fresh source evidence required after scheduler/collector start'}
