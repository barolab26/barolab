# Ubuntu dashboard and evidence collection

The PC's Ubuntu dashboard at port 8790 is the canonical live dashboard.
These user services use `/mnt/c/10_Project/BaroLab` and
`~/.venvs/barolab/bin/python3`; they do not start or restart the EGO runner.

Install from Ubuntu:

```sh
mkdir -p ~/.config/systemd/user
cp /mnt/c/10_Project/BaroLab/server/barolab-dashboard.service ~/.config/systemd/user/
cp /mnt/c/10_Project/BaroLab/server/barolab-metrics.service ~/.config/systemd/user/
cp /mnt/c/10_Project/BaroLab/server/barolab-metrics.timer ~/.config/systemd/user/
cp /mnt/c/10_Project/BaroLab/server/barolab-naver-monitor.service ~/.config/systemd/user/
cp /mnt/c/10_Project/BaroLab/server/barolab-naver-monitor.timer ~/.config/systemd/user/
chmod 644 ~/.config/systemd/user/barolab-*.service ~/.config/systemd/user/barolab-*.timer
systemctl --user daemon-reload
systemctl --user enable barolab-dashboard.service barolab-metrics.timer barolab-naver-monitor.timer
```

Before starting the dashboard, identify the existing process listening on 8790.
Gracefully stop only that verified dashboard process before starting
`systemctl --user start barolab-dashboard.service`.
Start `barolab-metrics.timer` after checking for active collectors.
`Persistent=true` can cause an immediate catch-up run.
Start `barolab-naver-monitor.timer` to refresh reservation and public evidence
every five minutes. This uses the existing monitor lock, does not submit posts,
and records its output in `~/.barolab/logs/naver-monitor.log`.
User lingering must be enabled (`loginctl show-user "$USER" -p Linger`).
WSL itself must be started after Windows boots; user units do not boot WSL.

The metrics service reuses `dashboard/metrics.py --collect --read-only` and its
`metrics-run.lock`. It gathers evidence without sitemap or IndexNow submissions.
It does not replace the separate revenue collector. Missing credentials or
browser sessions remain partial or unknown even when the process exits zero.

The dashboard sets `BAROLAB_DISABLE_BACKGROUND=1`, suppressing autonomous chat
radar and the periodic project audit that can trigger content remodeling.
Live snapshots and read-only Play Console observation remain available.
`BAROLAB_HEALTH_BROADCAST=0` also suppresses audit messages if background work is
explicitly re-enabled later.

Verify with:

```sh
systemctl --user status barolab-dashboard.service barolab-metrics.timer
systemctl --user list-timers barolab-metrics.timer
journalctl --user -u barolab-metrics.service -n 30 --no-pager
curl --fail http://127.0.0.1:8790/api/live-snapshot
```

## Manual Naver account login

Install private per-account Ubuntu launchers:

```sh
~/.venvs/barolab/bin/python3 /mnt/c/10_Project/BaroLab/common/ubuntu_naver_browser.py --install
~/.barolab/browsers/soultin/soultin_start_cdp.sh
```

Replace `soultin` in both path components for the other accounts.
The launcher reads `ACCOUNT_MAP` directly and verifies the Chrome executable,
profile, process ID and loopback listener before reusing an existing window.
Repeated starts preserve existing tabs. New windows open the ordinary Naver
login page; the user signs in manually. No passwords or publications are handled.
The launcher labels the initial handoff window title with the account and blog
ID using `wmctrl`, and new Chrome profiles have an account-specific visible
profile name. Navigation can update the window title.

| Account | Blog ID | CDP port |
| --- | --- | --- |
| soultin | mustpickinfo | 9334 |
| soul5373 | mustinfo | 9333 |
| yoon_master | yoonviews | 9335 |
| adinfo0905 | adinfo0905 | 9231 |
| stone0747 | stone0747 | 9230 |

Profiles live outside Git at `~/.config/cdp_naver_<account>` with mode 700.
The existing soultin profile is retained in place. Launch scripts, logs and
receipts live at `~/.barolab/browsers/<account>`. GUI display defaults to `:10`;
set `BAROLAB_DISPLAY` only when the Ubuntu desktop uses another display.
