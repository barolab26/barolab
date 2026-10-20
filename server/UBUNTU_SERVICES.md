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

The Naver posting runner now resolves those same Ubuntu profiles for reservation
inventory, revision inspection and publication connections. KnowledgeIn reuses
the same verified adinfo0905 and stone0747 profiles. Before a Naver connection,
the process must match `/opt/google/chrome/chrome`, the exact account profile and
CDP port; `ss` must confirm that process owns the loopback-only listener. An open
HTTP port alone is not accepted as account identity.

If the account process is missing, the runner invokes only its installed
`<account>_start_cdp.sh` and verifies ownership again. A missing launcher, wrong
profile or unexpected listener stops the attempt without terminating a browser
or replacing profile data. Existing verified sessions skip the launcher and keep
their tabs. This does not verify Naver login or publication: those remain separate
pipeline checks. No automatic browser stop was added.

On Ubuntu, Naver research and image generation share the CF browser endpoint and runtime
paths instead of connecting to the obsolete separate port 9420. On this Ubuntu
host that endpoint is loopback port 9440, with executable
`/opt/google/chrome/chrome` and profile `~/.config/cdp_gui_9440`. Its process and
listener are verified before connecting. This mapping identifies the existing
shared browser, not the signed-in Google account; Flow login and generation
still require their own checks. The CF start/stop lifecycle is unchanged.
Windows keeps its existing Naver source-browser account `baro76650` on port 9420.

## Visible authorized Naver runs

Use the existing runner with `--visible` alongside its normal account, slot and
publication-date arguments. This opts the run and its child workers into
`BAROLAB_VISIBLE_WORKFLOW=1`; all existing locks, evidence checks, reviews and
duplicate safeguards still apply. Stage updates focus the verified account
window, image work focuses the shared Flow window, and editor preparation and
reservation options bring the working tab to the front. No extra browser or
parallel publishing implementation is created. The flag does not turn a dry run
into a submission or authorize bypassing blocked account state.

Research collected via HTTP is still HTTP evidence, even during a visible run.
Account-bound observations can enter through `--evidence-dir`; visible screenshots
alone do not establish a competitor article's body. If actual competitor bodies
cannot be fetched, collection stops instead of labeling search snippets as an
article excerpt.
An explicitly supplied packet is reused after keyword selection only when its
account and query match exactly, recent-title coverage is complete, and every
competitor body has a matching URL, SHA-256, visible-browser collection marker
and observation time within 24 hours. Changed queries or unverifiable packets
use actual collection again. This is evidence freshness, not a ranking guarantee.

EGO does not execute external response commands. Local events do not automatically send
Gemini messages. Authorized Naver work uses the canonical runner above; merely
seeing an action in a model response is not a local task request. Keep the EGO
service stopped during a supervised visible run to avoid its independent CF and
maintenance loops competing for the shared desktop.

EGO also provides a local explicit entry point:

```sh
~/.venvs/barolab/bin/python3 /mnt/c/10_Project/BaroLab/ego_lite_runner.py \
  --naver-account yoon_master --slot 09:00 --publication-date YYYY-MM-DD \
  --main-keyword "measured query" --topic-seed "reader question" \
  --evidence-dir /private/observed-evidence
```

Supply the intended date and original slot. This acquires EGO's singleton lock
and invokes the same Naver runner with `--visible`; it can submit a reservation
only after all existing gates pass. It is an explicitly authorized local action,
not a Gemini response command. Existing prepared handoffs are reused only through
the runner's normal input/hash and review validation. With no arguments EGO keeps
its original daemon mode; do not start that daemon alongside the supervised run.
`barolab-ego.service` must be inactive for this local entry because both modes
share EGO's singleton lock. This restores supervised visible execution; it does
not restore unattended Naver scheduling or make external model directives trusted.

Recovery status on 2026-10-21: all five account profiles were checked, but login
sessions can expire and must be checked again before submission. The daily
publishing timer `barolab-naver-daily.timer` remains uninstalled; monitor and
metrics timers do not authorize or perform daily publishing. An empty reservation
list is distinct from verified public publication.

Private migrated evidence is stored in the ignored
`naver_blog_posting/output/<account>/<artifact>/` directories. A known legacy
path is read through `artifact_paths.py` only after a migration manifest and its
copied evidence hashes validate; incomplete copies and missing historical
evidence remain unknown. Journal paths and submission flags are preserved.
Restore and reconcile missing evidence before enabling daily publishing.

Historical failed attempts can be isolated from a new future slot without
changing their journal status using `python -m naver_blog_posting.account_reconciliation
--account <account> --preflight-file <private-proof.json> --inventory-file
<private-public-inventory.json>` (run as one command). The preflight must come
from an actual authenticated account and two independent, complete
reservation observations. The command validates a complete public inventory
hash and checks its current first page before issuing a private receipt.
It refuses an active publisher and expires ten minutes after the oldest fresh
observation; copying a timestamp forward cannot refresh evidence. Unknown,
submitting, current-day and changed failures remain blocked. Candidate titles
and the actual reservation list still require the pipeline's duplicate checks.
One renewal during a running job requires `--worker-id <exact-id>`, genuinely
new account/reservation observations, an unchanged historical failure set, and
proof that this worker started within the original idle receipt's lifetime.
The renewal applies only to that worker's account and target day and expires
again after ten minutes; it cannot be renewed repeatedly. Refresh immediately
before the existing submission checks for a long generation run.
Complete nonempty reservation lists are accepted only when both independent
modern-editor counts equal the distinct title/time rows and both legacy-editor
counts are zero. An occupied target time stays blocked unless the same exact
title/time already has verified local evidence. A different future slot can be
planned; final submission rechecks the live list and rejects either a matching
time or matching normalized title. A failed list observation blocks submission.
The repeatable live collector is `python -m naver_blog_posting.account_reconciliation
--account <account> --refresh`. It reuses the approved account launcher/profile,
checks signed-in account and blog ownership, performs the existing two-pass
reservation observation, and collects or head-validates the full public catalog.
Only its temporary tabs are closed. For the one permitted active-job renewal,
add the exact `--worker-id`; coordinate this immediately before submission.
This command prepares evidence only and does not generate content or submit it.
This capability does not itself enable the daily timer.

The explicit EGO Naver entry runs this fresh reconciliation before launching the
canonical pipeline and stops if it fails. `--prepared-dir <account-output-folder>`
forwards an existing handoff to the canonical validator; it does not bypass review
or change the requested content fingerprint. The daemon must remain inactive while
using this singleton-protected local entry. This is not automatic daily recovery.

Visual approvals now include actual decoded image bytes, their SHA256, the exact
image plan hash, and an independent pixel-review verdict. Missing or changed
evidence blocks handoff; rejected verdicts remain in the review JSON. External
material imports and planning-failure reclassification remain explicitly blocked
until their verification contracts are implemented.

The daily unit and timer in this directory are source templates only: they have
not been installed or enabled. On Ubuntu, `windows_worker.py --task naver-daily`
routes through `ego_lite_runner.py --naver-catch-up` and EGO's singleton lock into
the existing bounded coordinator. It refreshes actual account evidence before
planning and again before each selected worker, and uses the visible workflow.
Before submission it performs the existing single active-worker renewal using
the exact worker identity; failure or missing identity stops submission. The
original idle proof must still have been valid at worker start. There is no TTL
extension without new observations and no repeated renewal lease.
The seven existing daily slots remain unchanged; this adds no publication quota
and does not execute missed slots at shifted times. The EGO daemon must be stopped
and the approved desktop/profile sessions available before this entry can run.
`ego_lite_runner.py --naver-catch-up --dry-run` only reads the current recovery plan;
it does not refresh evidence, open a browser, generate content or submit anything.
An expired receipt can block a new attempt even while previously verified
reservation evidence remains stored. Timer activation requires a separate
operational decision after representative publication verification.
