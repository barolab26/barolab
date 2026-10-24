"""Registered scheduler/collector recovery; never restart active jobs or submit content."""
import subprocess
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


def runtime_state(project):
    rows = []
    for unit in UNITS.get(project, ()):
        result = subprocess.run(['systemctl', '--user', 'show', unit,
            '--property=LoadState,ActiveState,SubState,UnitFileState'],
            capture_output=True, text=True, timeout=5, check=True)
        rows.append({'unit': unit, **dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)})
    return rows


def recover_project_runtime(project):
    if project not in UNITS:
        raise ValueError('Unregistered runtime project')
    if (Path.home() / 'EGO_EXEC_DISABLED').exists():
        return {'ok': False, 'status': 'held', 'reason': 'execution_disabled'}
    rows = runtime_state(project)
    actions = []
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
