"""Owned user-systemd units for the existing KnowledgeIn scheduler."""
from pathlib import Path
import subprocess

UNITS = (
    ('barolab-kin.timer', 'barolab-kin.service', '--tick'),
    ('barolab-kin-measurement.timer', 'barolab-kin-measurement.service', '--measure'),
)


def observe(root, stamp, query=None):
    query = query or subprocess.run

    def properties(unit):
        result = query(['systemctl', '--user', 'show', unit, '--no-pager',
                        '--property=LoadState,ActiveState,UnitFileState,NextElapseUSecRealtime,'
                        'LastTriggerUSec,Result,ExecMainStatus,ExecMainStartTimestamp,ExecStart,Unit,WorkingDirectory'],
                       capture_output=True, text=True, timeout=10)
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if result.returncode and values.get('LoadState') != 'not-found':
            raise RuntimeError('systemd observation failed')
        return values

    rows = []
    try:
        for timer, service, action in UNITS:
            observed, job = properties(timer), properties(service)
            command = job.get('ExecStart', '')
            matches = (job.get('WorkingDirectory') == str(root) and '-m naver_kin.scheduler ' + action in command
                       and job.get('LoadState') == 'loaded' and observed.get('Unit') == service)
            registered = observed.get('LoadState') == 'loaded' and matches
            failed = (observed.get('ActiveState') == 'failed' or job.get('ActiveState') == 'failed'
                      or job.get('Result') not in (None, '', 'success')
                      or job.get('ExecMainStatus') not in (None, '', '0'))
            rows.append({'taskName': timer, 'service': service, 'registered': registered,
                         'enabled': observed.get('UnitFileState') in ('enabled', 'enabled-runtime'),
                         'workflowMatches': matches,
                         'state': 'Missing' if not registered else 'Failed' if failed else
                                  'Running' if job.get('ActiveState') == 'activating' else
                                  'Ready' if observed.get('ActiveState') == 'active' else 'Disabled',
                         'nextRunAt': observed.get('NextElapseUSecRealtime'),
                         'lastRunAt': job.get('ExecMainStartTimestamp'),
                         'lastResult': job.get('Result'), 'lastExitStatus': job.get('ExecMainStatus')})
        return {'status': 'observed', 'platform': 'systemd-user', 'checkedAt': stamp(), 'tasks': rows}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return {'status': 'unavailable', 'platform': 'systemd-user', 'checkedAt': stamp(),
                'reason': 'scheduler_query_failed'}


def unit_contents(root, python):
    # Absolute checkout + interpreter are part of the owned action identity.
    if any('\n' in str(path) or '"' in str(path) for path in (root, python)):
        raise ValueError('Unsupported unit path')
    service = ('[Unit]\nDescription=BaroLab KnowledgeIn {label}\nAfter=network-online.target\n\n'
               '[Service]\nType=oneshot\nWorkingDirectory={root}\n'
               'Environment=DISPLAY=:10\nEnvironment=PYTHONUNBUFFERED=1\n'
               'ExecStart="{python}" -u -B -X utf8 -m naver_kin.scheduler {action} --scheduled\n'
               'TimeoutStartSec=55min\nUMask=0077\n')
    timer = ('[Unit]\nDescription=BaroLab KnowledgeIn {label}\n\n[Timer]\n'
             'OnCalendar={calendar}\nPersistent=false\nUnit={service}\n\n'
             '[Install]\nWantedBy=timers.target\n')
    result = {}
    for timer_name, service_name, action in UNITS:
        label = 'condition check' if action == '--tick' else 'read-only measurement'
        result[service_name] = service.format(root=root, python=python, label=label, action=action)
        result[timer_name] = timer.format(label=label, service=service_name,
            calendar='*-*-* *:00/5:00 Asia/Seoul' if action == '--tick' else '*-*-* 20:30:00 Asia/Seoul')
    return result


def install_disabled(root, python, home=None, run=None):
    """Install only owned inactive units; never enable or start a timer."""
    run = run or subprocess.run
    target = (home or Path.home()) / '.config/systemd/user'
    contents = unit_contents(root, python)
    # Check every destination before writing any file.
    for name, value in contents.items():
        path = target / name
        if path.exists() and path.read_text(encoding='utf-8') != value:
            raise RuntimeError('Existing systemd unit differs; review before replacement: ' + name)
        state = run(['systemctl', '--user', 'show', name, '--property=LoadState,ActiveState,UnitFileState'],
                    capture_output=True, text=True, timeout=10)
        properties = dict(line.split('=', 1) for line in state.stdout.splitlines() if '=' in line)
        if state.returncode and properties.get('LoadState') != 'not-found':
            raise RuntimeError('Cannot verify existing unit before installation')
        if properties.get('ActiveState') in ('active', 'activating') or properties.get('UnitFileState') in ('enabled', 'enabled-runtime'):
            raise RuntimeError('Existing unit is enabled or active; installation is not a stop operation')
    target.mkdir(parents=True, exist_ok=True)
    for name, value in contents.items():
        path = target / name
        path.write_text(value, encoding='utf-8')
        path.chmod(0o600)
    run(['systemctl', '--user', 'daemon-reload'], check=True, timeout=15)
    return {'state': 'installed_disabled', 'platform': 'systemd-user',
            'enabledByThisOperation': False, 'units': list(contents)}
