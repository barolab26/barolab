# NAS Dashboard Operations

## CF doctor read-only status route deployment - 2026-10-20 KST

DSM recreation returned Exit Code 0; NAS GET /api/auditor/status returned HTTP 200 and the growth remodel tab visibly showed 23 fully verified, 7 partial and 2 unknown URLs. DSM's current image is `barolab-dashboard:app-testers-20261019`; the older indexing-guard2 receipt below is historical. Keep this image, existing settings and eleven mounts unchanged. The temporary twelfth `content_auditor.py` mount was removed because the image lacks its `cf_posting.domain_themes` import dependency.

Existing NAS files under `/volume1/yoonlab/10_Project/BaroLab` were updated without new modules or archive files: `dashboard/content.py` supplies `cf_doctor_evidence_summary`, and `dashboard/growth.html` distinguishes full public verification, title-only partial work, unknown outcomes and unavailable audit statistics. The existing `cf_posting/data` read-only mount supplies `daily_schedule.json`. Local source reference: `8c7ebec`.

The NAS-mounted `server/main.py` received only this GET route immediately before `# Mount static sub-projects for pipeline status & output previews`:

```python
# Read-only CF doctor evidence; no auditor worker or write routes on NAS.
@app.get("/api/auditor/status")
def get_cf_doctor_status():
    from content import cf_doctor_evidence_summary
    return {"ok": True, "auditStatus": "not_collected", "auditedCount": None,
            "todayAudited": None, "dailyQuotaTarget": None, "gradeCounts": {},
            "cfDoctorEvidence": cf_doctor_evidence_summary()}
```

Do not replace NAS `main.py` wholesale with the Windows version: it also registers chat, memory and project-health components and starts additional health work. Do not register the full auditor router merely to expose this read-only summary. Original NAS main/source/compose bytes were retained in the current execution memory, not a durable backup file. Recreate only the existing `barolab-dashboard` service through its existing DSM project, then verify HTTP 200 and `cfDoctorEvidence` at the NAS `/api/auditor/status`; until that succeeds, this is preparation rather than a completed deployment. The current ledger fixture yielded 23 fully verified, 7 title-only partial and 2 unknown URLs; these are observed source counts, not fixed targets.

## Revenue and indexing guard deployment receipt - 2026-10-19 KST

The existing NAS `barolab` project now runs one healthy container, `a775d525014d65e6a81cc4f1360d879ac915fed70db9bae5c742df906ccc32e0`, using `barolab-dashboard:indexing-guard2-20261019`. DSM verified the existing eleven mounts, 384 MB memory limit, port 8790 and `barolab_default` network. The shared compose changes only the image tag. `/api/status` and `/api/metrics` returned HTTP 200 after recreation; the updated revenue period completeness fields and dashboard were verified against the running service.

The image adds only `common/channel_attribution.py` and `dashboard/metrics.py` to the exact former apps-paths base. Its retained archive config ID `99a3045901ed630616d15efd66b9e1b4573b27c212a6a0d712df317459c1a557` matches the pre-deployment DSM image; `cd2deeb56e137cd636d61b8dc825a95853698af8078e7b403f2795bbfd69b3fc` is that archive's OCI manifest ID, not a different base. The final new archive is `/volume1/yoonlab/10_Project/BaroLabDeploy/20261019-indexing-guard/barolab-dashboard-indexing-guard2.tar` (59,749,888 bytes; SHA256 `5507dd32de290eb188ddabb7a6ab093c92220ed50b8e1e438cf283e87a3a1987`). Its image-config ID is `64340fb07dabfd1b8a1c771eb4a09b16567ce9a047ae4e5e7f4b2f78cb1e8fa4`. The earlier four-file candidate was superseded and was not deployed.

The base image's `llm_client.py` and `llm_settings.py` remained byte-identical (SHA256 `51a402a091633e7ef48fb8fb389ae23ab719452d38a9979de0e6fd9918c79b54` and `ead1be8a21e56a69f8fc4212a1dcdc1b6580a06f8c6d0eefb0879100133dd440`). The repository's separate protected `common/llm_client.py` hash remains `0bf00120729d63e8c3a4386e46b61a66fed168075b93ab79750911af0c23dff4`; this deployment does not replace runtime model routing. Revenue and other dashboard sources are provided by the existing read-only dashboard mount. Windows collector/channel patches apply on new invocations; no additional NAS auditor or publisher service was introduced.

The first DSM UI edit did not persist the new image reference: the project still used `:local`. Its initial recreation receipt was therefore not treated as final deployment proof. Subsequent DSM temporary-container metadata returned `No such container`, and the API became unavailable. The shared compose was corrected from the preserved original bytes, changing only the image tag. Restarting only the Container Manager package through Package Center cleared the management state; the existing project was then rebuilt successfully (Created/Started, ExitCode 0). The whole NAS and Windows publishing schedulers were not restarted. Source data, secret bindings and prior images were retained.

Validation comprised 74 relevant passing tests: revenue collectors 14, revenue UI 5, and traffic/indexing 55. A disposable candidate container with no external network, published ports or credentials verified current `revenue`, `metrics` and `main` imports, then HTTP 200 for `/`, `/api/status` and `/api/metrics` using an empty inventory-schema fixture. Mocked final indexing tests proved dummy URL exclusion and contaminated-sitemap hold without external submission. The three priority sites' read-only sitemap samples contained 81/148/82 URLs respectively and zero dummy URLs, so no removal count or new indexing success is claimed. Public CF sitemap content was not changed.

Original/candidate compose, image hashes, startup evidence and rollback materials are under `C:/Users/baro7/.barolab/deployments/20261019-indexing-guard`. Final DSM evidence is under `C:/Users/baro7/.barolab/scratch/revenue-20261019` (`nas-container-final.txt`, `nas-deploy-final.txt` and screenshots). Rollback must select the retained exact `apps-paths-20261015` image, not assume mutable `:local` is unchanged. Since dashboard source is bind-mounted, image rollback alone does not restore `metrics.py`; the pre-task source backup is explicitly separate from runtime-memory evidence.

## App directory migration · 2026-10-15 KST

Current source inventory paths are `apps/{bible,greeting,magnifier,shopping}/project.json`. `server/projects.py` and both sides of the four read-only compose file binds use these paths. The stable project ID `bible_app`, package names and public URLs are unchanged. The historical receipts below retain their original paths and image details.

Rebuilding the server image and recreating the existing NAS `barolab` project is required: `projects.py` is image content and moved manifest-file mounts need new bindings. Keep the other data/dashboard/secret mounts, port8790, 384MB limit and existing network/settings boundaries. Do not mount Android source directories. The normal Container Manager import/recreate step briefly interrupts dashboard/API availability; independent Windows publishing tasks are not restarted by this deployment.

Preparation and validation evidence is under `C:/Users/baro7/.barolab/deployments/20261015-apps-paths`. The current edited compose is named `docker-compose-current-apps-paths.yml`; `docker-compose-reconstructed-prior-paths.yml` is explicitly a path reconstruction, not an original-byte backup. The SQLite online backup uses a source connection with `query_only=ON` because Windows SQLite rejects the UNC URI authority. The minimal image context contains the same40 allowlisted source/config files as the prior deployment, excluding Android assets, credentials and runtime data.

Root verified the NAS archive import and recreated the existing `barolab` project through DSM Container Manager. Its build terminal reported Recreated/Starting/Started and ExitCode0, the success toast was visible, and the project had one container. The imported archive is `/volume1/yoonlab/10_Project/BaroLabDeploy/20261015-apps-paths/barolab-dashboard-apps-paths.tar` (59,725,824bytes; SHA256 `e1260b8947a1676a63c1803cc71b78adb4960fcc99d828a5e69bd90ee4d53842`). It contains `barolab-dashboard:apps-paths-20261015` and `barolab-dashboard:local`. The locally verified expected image is `sha256:cd2deeb56e137cd636d61b8dc825a95853698af8078e7b403f2795bbfd69b3fc`; actual NAS image-config ID and mount details require root's separate DSM inspection and are not proved by the public API.

At 2026-10-15T02:38:12Z, `/api/projects`, `/api/status` and `/api/growth/action-center` returned HTTP200. The four-project response exactly matched inventory derived from the current `apps/` manifests, retaining IDs `bible_app`, `greeting`, `magnifier`, `shopping`. Consistent before/after DB counts were unchanged: sites21, connections59, daily_metrics0, improvement_actions0, maintenance_jobs1947 and maintenance_attempts5. `live-verification.json`, API responses and consistent SQLite backups retain this evidence outside the source workspace. Seven isolated inventory tests, Compose validation and local-image inventory/import checks passed before deployment.

DSM inspection limitation: after recreation, Container Manager continued showing the temporary name `8ee9d1ccd772_barolab-dashboard`; opening its detail returned `No such container`, including after a page reload. Thus the import/recreate UI receipt and working API/DB results are verified, while direct runtime image-ID/mount inspection remains unverified. This stale UI was not treated as proof of runtime failure, and no additional restart or duplicate recreation was performed.

## Four-app inventory deployment receipt · 2026-10-14 KST

The app-inventory image config is `sha256:4b437bd7037b3a052a8f8264f7a8c86d46520d570e246aa5a448d4e80d3e0a6d`, tagged `barolab-dashboard:daily-apps-20261014` and `barolab-dashboard:local`. The authenticated existing Container Manager `barolab` project was normally stopped and rebuilt after archive import. Container `8ee9d1ccd7722b3bb1dd42541811879a98611aea88764bac7ccaefc6f109e033` is healthy. Its prior eight mounts, memory limit, restart policy, settings boundary and network were preserved; three read-only `daily_apps/{greeting,magnifier,shopping}/project.json` mounts bring the total to eleven.

The read API uses a fixed four-entry manifest allowlist and independently validates each file. A malformed or missing app produces a scoped notice and partial status while preserving the other cards. Seven isolated regression tests passed, including failure isolation, unknown versus measured zero, unsupported verified claims and secret/URL filtering. The dashboard shows the existing Bible app plus 오늘의 안부, 큰글씨 돋보기 and 말로 장보기. New app registration in Play is distinguished from internal testing and public release. All four app revenue and active-user metrics remain unconnected/null and are excluded from blog totals.

Only a reviewed 40-file server/dashboard context was included in the image. Android app sources, APKs, SDKs, signing identities, operating data and credentials were excluded. Consistent SQLite backup/counts, compose rollback copy, source hashes, image/archive receipt, live API snapshots and two dashboard captures are under `C:\Users\baro7\.barolab\deployments\20261014-daily-apps`. The imported archive is `/volume1/yoonlab/10_Project/BaroLabDeploy/20261014-daily-apps/barolab-dashboard-daily-apps.tar`. `/api/projects`, `/api/status` and `/api/growth/action-center` returned HTTP 200. Database counts retained 21 sites, 59 connections, zero daily metrics/improvement records and the existing maintenance attempt; maintenance inventory continued to grow normally. No prior images were removed.

All four manifest file mounts require in-place writes. Recreate the existing project after atomic replacement or rename of a mounted manifest; do not expose whole Android source trees to the dashboard container.

## Bible app inventory deployment receipt · 2026-10-14 KST

The app-inventory image config is `sha256:958333061eee60d9b0645bb0159007f244a9cb39166cfeee3f7a6ce94f3083ca`, tagged `barolab-dashboard:bible-20261014` and `barolab-dashboard:local`. The authenticated existing Container Manager `barolab` project was normally stopped and rebuilt after archive import. Container `fc7339d2d077beab81da4403231a2fa790639df44e56930564ec6bdc292da409` is healthy. Its previous seven mounts, 384 MB limit, restart policy, network and settings boundaries were preserved; one read-only manifest-file mount was added.

`bible_app/project.json` is the single app registration source. `/api/projects` and the main dashboard app card show its milestones, publication link and measured-source status separately from blog totals. Unconnected AdMob revenue and active users remain null/미수집. This deployment registers the project; it does not certify app-store release, device testing or earned ad revenue.

The manifest is mounted as a file, not an app-source directory. Update this JSON **in place** to retain the mounted inode. After an atomic replacement or rename of `project.json`, recreate the existing project so the container sees the new file. APKs, Android SDK/toolchains, signing material, app data and app secrets are absent from the image and mounts. The existing `.dockerignore` already excludes the entire app tree, so no additional whitelist was added.

The 40-file reviewed build context, consistent SQLite backup/counts, previous compose, image/archive receipt, live API snapshots and `app-dashboard-live.png` are under `C:\Users\baro7\.barolab\deployments\20261014-bible-dashboard`. The imported archive is `/volume1/yoonlab/10_Project/BaroLabDeploy/20261014-bible-dashboard/barolab-dashboard-bible.tar`. `/api/status`, `/api/projects` and `/api/growth/action-center` returned HTTP 200; actual UI showed 하루말씀 and both measurement sources unconnected. Database counts retained 21 sites, 59 connections and zero daily metrics/improvement records; ongoing maintenance rows increased normally. No image cleanup or browser lifecycle changes were performed.

## Existing-content maintenance deployment receipt · 2026-10-14 KST

The maintenance image config is `sha256:6079ab71b7d93d758b7010ccb8f9376600971bb958875e3f4fa7a97cd27f7b69`, tagged `barolab-dashboard:maintenance-20261014` and `barolab-dashboard:local`. Only the existing `barolab` project was recreated through its authenticated Container Manager `build_stream`. The running container is `e0c7fdabf0c444ded293b19110eada5bd533ad497958300b52f0fb1d0e777832`, healthy, with all seven prior data/secret mounts preserved. Previous diagnosis and growth images remain available; no image cleanup was performed.

The reviewed 36-file build context excludes credentials and operating data. `beautifulsoup4>=4.15,<5` supplies the new engine dependency. Disposable-image imports and read-only initialization passed without a model configuration or any remote article writes. Consistent SQLite, compose, runtime and separate policy backups, source hashes and live UI captures are under `C:\Users\baro7\.barolab\deployments\20261014-maintenance`; the imported archive is under `/volume1/yoonlab/10_Project/BaroLabDeploy/20261014-maintenance/`.

Live status, action-center and maintenance APIs returned HTTP 200. Pre-existing row counts were preserved: 21 sites, 59 connections, zero daily metrics/improvement records, 1,929 maintenance jobs and zero modification attempts. Automatic inspection is enabled; basic structure checks continue while the research provider is waiting for its recorded retry time. Basic checks, deep source review, verified edits and unassessed inventory are distinct UI measures. At validation, deep reviews and actual article writes were still zero. The first edit must satisfy measured evidence, independent review, daily limits and public verification; no success is inferred from enabling inspection.

The CF prepublication reviewer receives the same deterministic content audit. Existing unsafe HTML checks remain the submission gate; structural recommendations and research hypotheses do not create blanket rejection rules. Runtime backup/version receipts and public verification stay separate from later search-performance observation. The supported editing scope is existing CF articles; Naver editing is not implied by this deployment.

## Diagnosis deployment receipt · 2026-10-14 KST

The final diagnosis image config is `sha256:53022d6bd54ea1a4b893788e41d0002e7e81b96a865b226c49d3a8aa5d0262c7`, tagged `barolab-dashboard:diagnosis-20261014` and `barolab-dashboard:local`. It was imported and applied to the existing `barolab` project only. Live diagnosis covers 16 domains, includes the matched Nolplace page/query pair, and exposes read-time collection health with actual account retry timing. Forecast execution times are labelled as estimates.

Health is healthy; existing data and secret mounts are unchanged. SQLite migration added `diagnosis_snapshot` while preserving all pre-deployment row counts, including zero improvement records. No production test plans were created. Consistent backups, the reviewed 34-file build-context hash manifest and live UI captures are under `C:\Users\baro7\.barolab\deployments\20261014-diagnosis`. The earlier growth image and backups are retained.

## Growth deployment receipt · 2026-10-14 KST

The reviewed growth image `barolab-dashboard:growth-20261014` was imported with the existing `barolab-dashboard:local` alias and applied through the existing `barolab` project's `build_stream`. The running image config ID is `sha256:3bdea2f17d95dfb429155abc050eb4e1931c831129fddf51c0b4b742e5ddc78d`; container ID is `97a3cb1d4708454d9de0eb955d8f25bc7a32ccc0a36d42ac3f3db3b260d60944`. Health is healthy. Existing data mounts, secret mount and security settings are unchanged.

Live `/api/growth/action-center` returned 16 domains, 15 comparable completed 28-day pairs and 45 unique article candidates. `must-joy.com` lacked an exact complete previous/current pair. The main page displays the first 3 candidates and growth displays the first 9, with their full candidate count stated. Shared improvement records were empty; HTTP CRUD and security checks used an isolated disposable database, leaving no production test records.

The original NAS image ID `sha256:3f93245ba065e67572b78a56ac880107cf594264962944565044b950093cadf5` was retained; no image cleanup was performed. Consistent pre-deployment SQLite, compose and container metadata backups are under `C:\Users\baro7\.barolab\deployments\20261014-growth`. The imported archive is outside the source workspace at `/volume1/yoonlab/10_Project/BaroLabDeploy/20261014-growth/barolab-dashboard-growth.tar`. Deployment validation captures are stored with those backups.

The production dashboard runs as `barolab-dashboard` in the Synology NAS Container Manager project `barolab`.

- Dashboard: `http://192.168.45.190:8790/` (also `http://otns:8790/`).
- NAS workspace: `/volume1/yoonlab/10_Project/BaroLab`.
- Start, stop, or restart the project through DSM Container Manager. The container uses `restart: unless-stopped`; manually stopped containers remain stopped.
- FreeLLMAPI remains in Windows Docker at `http://127.0.0.1:3001/`. No native Windows dashboard web server is required. `start_server.bat` only displays the NAS address.

## Data and settings

The dashboard and both publishing pipelines' status/output directories are mounted directly from the NAS, read-only. `server/data` is writable and retains todos, JSON state, and the growth SQLite database across container replacement.

The encryption key is `server/data-secret/llm-settings.key`, mounted as a Docker secret. Back it up together with `server/data/llm-settings.json` when that settings file exists. Neither file is included in the image or publicly served. Linux and Windows share the versioned Fernet format; older Windows DPAPI ciphertext remains readable on Windows.

The Windows `BaroLab-Naver-Monitor` task runs briefly every five minutes and writes local browser observations to shared `server/data/browser-status.json`. It opens no server port and does not control browser lifecycle. NAS displays unknown browser state when an observation is older than seven minutes. Windows-only AGY CLI is not installed inside this dashboard container.

## Revenue collection

`dashboard/revenue.py` collects read-only AdSense, AdPost and Coupang commission reports into `server/data/revenue.json`. The NAS serves this snapshot through `/api/metrics`; credentials are loaded only on the Windows collector host from `cf_posting/.env`.

The existing `BaroLab-Metrics-Collector` task runs revenue collection followed by indexing/traffic collection every 30 minutes. It starts no web server. Manual refresh: `python -B -X utf8 dashboard/revenue.py --collect`. Keep the dedicated soul5373 browser (CDP 9333) logged in with its AdPost main page open; the collector never closes its browser or tabs.

AdSense is limited to inventoried SJ CF domains. AdPost covers the connected account's blog media. Coupang covers the account's commission report, including non-blog subIds; sales volume is excluded. Unconnected providers, missing days and pending report placeholders remain unknown. Values are estimated, retained by month and displayed separately in USD/KRW. Connection failures preserve previous successful evidence and its timestamp; measurements older than two hours show a delay notice.

## Domain traffic and search reports

`dashboard/traffic.py --collect` queries GA4 and Search Console with the configured read-only service accounts. Domain/property/reader mappings are in private `server/data/metrics-config.json`; report snapshots are in `server/data/traffic.json`. The existing 30-minute metrics task runs revenue, domain traffic, then indexing collection. Its short Windows workers do not open web server ports.

GA4 queries exact root/www hosts and deduplicates users independently for today, yesterday, the last seven days and the last 30 days. Channel shares use sessions; explicit Naver search referrals are classified as search, and blog/cafe referrals remain external. Thresholding, sampling, truncated rows, mismatched source totals and stale evidence remain visible.

Search Console uses only properties covering the inventoried canonical host and reports ending three days before the source's Pacific date. API readers provide aggregate and query/page reports. SJ owner reports unavailable to the API reader are read through the existing SJ browser (CDP 9226), with pinned email, property and report dates; those query rows do not supply page URLs. Average position is not a fixed SERP rank. Keyword rows are a partial, privacy-filtered list.

Naver Search Advisor belongs to `soultin` (CDP 9334), independently of the AdPost income account `soul5373` (CDP 9333). If Naver requests an additional login challenge, keep the account browser open and wait for the user to complete it. Report collection does not grant permissions, accept enrollment terms, solve challenges or fabricate ranks.

The CF/Naver summary cards use this same traffic snapshot: publishing complete/pending, today's blog/domain visitor sum, and historical visitor sums. These are sums across blogs/domains, not deduplicated people across the whole system. Naver public visitor counters require no login and expose only the latest five daily counts; the Naver card labels the five-day cumulative total explicitly. Refresh those counters alone with `dashboard/traffic.py --collect-naver`; the normal traffic collector includes them every 30 minutes. Missing/stale counters remain unknown and partial totals show their collection coverage.

`index.html` is the compact overview; `growth.html` uses the same `/api/metrics` reports for domain details, channel sources, search queries and revenue. Google position buckets (5/10/50/100) are cumulative counts of exposed query/page observations, not a complete keyword inventory or fixed live SERP ranks. Low-impression observations are distinguished, and shortened report periods keep their actual dates. Naver/Bing ranking data remain unmeasured/unconnected rather than zero. The growth page offers position, impression and keyword filters, including an optional 11–50 position range for review.

## Existing article maintenance

CF publishing and the shared Flow generator use `common/browser_session.py` to verify
the actual Windows process owning CDP 9420, executable and user-data directory. Existing
tabs are probed; only nonresponsive tabs are activated and rechecked before attachment.
The existing Flow tab is restored after recovery. The browser, profiles and login sessions
are retained; normal CF completion does not run the stop batch. Windows workers require
the already installed `requests`, `websocket-client` and Playwright packages.

CF schedule items retain total/current-round attempts, stage timestamps, browser runtime,
last failure/retry time, recent attempt results and model call events. Auto routing keeps
requested and API-returned model IDs separate; missing historical model evidence stays
unknown. The CF timeline displays these fields and preserves publication reconciliation
holds after an uncertain submission. Status writes are replaced atomically by the runner.
After confirmed browser recovery, `python -B cf_posting/scheduler.py --retry-browser-failures`
queues the previously failed CDP initialization jobs for the next unlocked cleaner pass.
It retains counters/history and does not bypass uncertain-publication reconciliation holds.

`dashboard/content.py` joins the existing public article inventory, individual URL inspection evidence and the traffic collector's monthly page reports. It supplies `contentAudit` through the existing `/api/metrics` endpoint; `content.js` renders the growth dashboard's management list with domain/state/URL filters and pagination. No separate server, account-specific script or copied inventory is introduced.

Index evidence expires after 26 hours; search sources after two hours. Search observation does not certify current indexing, and absence of a page row is not zero impressions or non-indexing. Reports remain a partial set of Google's returned rows. Root/www aliases are joined only for search observations; URL inspection stays tied to the inspected host. Ambiguous multiple host rows are left for inspection rather than inventing a weighted page rank. Candidate position bands are review aids, not ranking guarantees.

Non-indexing guidance distinguishes canonical/duplicate/redirect exclusions, access or indexing configuration, and crawled content. The list recommends investigation or content improvement; it does not rewrite, delete, merge articles, or resubmit every URL. Any material content change should retain the original URL, record what changed and compare source-aligned periods after remeasurement.

## Updating the image

The shared dashboard theme is in `dashboard/traffic.css`, scoped by `body.control-room`.
The overview, growth and CF/Naver operations pages share navigation and semantic colors;
publishing logic and source snapshots remain in their existing modules. Overview actions
link to `growth.html?bucket=...#content-management`, where the corresponding filter is
selected. Keep unknown/partial/stale labels visible when changing the layout. The design
was reviewed using the installed `frontend-design` and `ui-ux-pro-max` skills, with a
bounded authenticated FreeLLMAPI layout draft reviewed before integration.

From the repository root:

```powershell
docker build -f server/Dockerfile -t barolab-dashboard:local .
docker image save --platform linux/amd64 -o server/deploy/barolab-dashboard.tar barolab-dashboard:local
```

Import the archive in NAS Container Manager, then build the existing `barolab` project to recreate its container. Remove the temporary archive after successful import. Keep the configured NAS gateway in `BAROLAB_TRUSTED_CLIENTS` consistent with the project's actual Docker network; do not disable the settings origin checks.

The migration verification receipt and dashboard captures are in `server/deploy/`. Windows data, browser-storage, and scheduled-task backups are under `C:\Users\baro7\.barolab`.

## Codex subscription and manual retries

`settings.html` offers **Codex CLI · ChatGPT 구독** and the models returned by the logged-in Windows CLI cache. `common/codex_cli.py` runs isolated, read-only JSON jobs with explicit model selection and no silent API fallback. Subscription credentials stay in the existing Windows Codex home; `.barolab/codex-worker.json` records its executable and home paths locally.

`BaroLab-Dashboard-Worker` runs `server/windows_worker.py --task serve` through `pythonw.exe`, updates `server/data/codex-runtime.json`, and handles NAS connection-test requests through private `server/data/control-jobs/`. It opens no web port. The NAS reads model availability and verifies the selected connection using an actual Windows CLI request.

The CF timeline's **선택한 작업 다시 실행** button accepts failed/review-held jobs through `/api/workflows/cf/retry`. The existing cleaner processes these requests under its global lock, checks public posts and submission receipts, and restarts every editorial agent. Previous attempts and rejected artifacts remain available. An already submitted or publicly verified article is never recreated by this button.

The cleaner, metrics collector, Naver monitor and Naver daily task all use the same hidden Windows runner. Its child processes set `CREATE_NO_WINDOW`; logs are under `C:\Users\baro7\.barolab\logs`. Task XML backups remain in `.barolab/task-backups-20261012/`. Preserve the current task enablement and triggers. A read-only check on 2026-10-14 found `BaroLab-Naver-Daily` enabled, targeting this project's `server/windows_worker.py --task naver-daily`, with the next start at 10:00 KST; the older disabled-state description was stale.


## Naver publishing workflow

`naver_blog_posting/pipeline_runner.py` is the single entry point for publishing, execution journals and monitoring. The hidden Windows worker routes `naver-monitor` and `naver-daily` here.

- `python -B -X utf8 naver_blog_posting/pipeline_runner.py --monitor`: observe state and browser health without publishing.
- The monitor includes all five accounts and seven daily slots. The 10:00 KST start is the preparation runner start; planned public slots are 11:00/19:00 for adinfo0905 and stone0747, 19:30 for soultin, 20:00 for soul5373, and 20:30 for yoon_master. A verified reservation is distinct from a confirmed public article.
- `python -B -X utf8 naver_blog_posting/pipeline_runner.py --account soultin --reserve-time 19:30`: run the agent workflow and reserve a reviewed article using today's KST 24-hour time.
- Add `--dry-run` to prepare and inspect the actual editor draft without submitting. This still invokes models and image generation.

The required content sequence is keyword selector, researcher, writer, image maker, assembler and independent reviewer, followed by the reserved publisher. Each role reads `agents/` instructions and passes real model responses, predecessor artifacts and immutable hashes. Missing evidence, changed files or unresolved reviews block submission. Recent title inventory and competitor samples retain their partial coverage.

Photos are uploaded individually; captions use native image fields. The current visual review adapter requires the configured Codex provider. Full PC/mobile editor captures must pass actual review. Reservation title/time are checked twice and the saved native document must match the approved content/style hash. Uncertain submissions cannot automatically retry across midnight. Browsers and publication evidence are retained.

Historical tests, debugging scripts and screenshots were moved outside the repository to `C:\BaroLabArchive\20261013`. `common/` contains active publishing/dashboard dependencies. Deliberation configuration, processes and installation paths were removed; deletion-policy restrictions left retired plugin files isolated in `C:\Users\baro7\.barolab\archive\20261013-cleanup`.

## Live snapshot deployment · 2026-10-19 KST

Implementation, local verification, and the NAS API deployment are verified. Restarting the DSM Container Manager package recovered its stale metadata (`a775d525014d_barolab-dashboard`); the existing project's stop returned exit 0, and its build reported Recreated, Started, and exit 0. The live `/api/status`, `/api/metrics`, and `/api/live-snapshot` endpoints all returned HTTP 200. The first snapshot was generated at `2026-10-19T12:34:45.549103+00:00` (21:34:45 KST), with all three databases reported collected. The next periodic refresh was independently verified from the on-disk file; see the timestamp receipt below.

The NAS deployment retains the production image's existing `main.py` routes and adds only the reviewed snapshot imports, helpers, endpoint, and startup/shutdown hooks. The full local `main.py` must not replace it: the production image lacks local-only dependencies such as `memory_graph`. The prepared runtime `main.py` is mounted read-only through Compose. Existing data volumes, secrets, and database ownership remain unchanged.

`GET /api/live-snapshot` returns `server/data/live_snapshot.json`, generated at startup and every 300 seconds. A missing or expired cache is refreshed on demand. Writes use the existing atomic JSON helper. The export contains system status, whitelisted GA4/indexing/traffic aggregates, source dates, and KST daily publication counts. CF counts require the current schedule date and a valid public URL; Naver counts require a verified public URL and the actual publication timestamp converted to KST. Reservations are not public publications. Missing/stale evidence remains unknown or partial. The snapshot's generation time does not change source dates.

SQLite reads use `mode=ro`, `query_only`, and closed connections. Core tables export counts and selected state aggregates only; documents, answer text, tokens, and credentials are excluded. The active files are `server/data/growth.sqlite3`, `server/data/kin.sqlite3`, and `server/data/threads.sqlite3`. The requested legacy `server/data/threads/ledger.db` is inspected only if it already exists. Threads main and followup counts remain separate; an uncertain submission is not verified publication.

Windows owns the Kin and Threads ledgers. The existing Windows `naver-monitor` task (five-minute cadence) and metrics task mirror a fixed allowlist of safe observation JSON files and consistent SQLite backups to `BAROLAB_NAS_ROOT` (default `\\otns\yoonlab\10_Project\BaroLab`) on completion, including failure completion. SQLite backup includes committed WAL pages and is validated before replacement. An active destination journal blocks replacement. The NAS-owned growth database and private settings are never overwritten by this mirror. NAS readers must not enqueue or publish against these worker-owned replica databases.

The NAS creates the aggregate snapshot from its own data and mirrored observations. `sync_github.ps1` retrieves that NAS endpoint before Git staging, checks the schema and freshness, and retains the previous file with a warning when retrieval fails. It checks native Git exit codes and refuses changed tracked files covered by `.gitignore`. Five-minute JSON refresh does not itself perform a five-minute Git push.

After the user clarified that Drive means Google Drive, the connected Google Drive account was searched and a root-level `live_snapshot.json` was uploaded. Its file ID is `1qObiKwiO4ZMQ4MVM2BpGeoNQAKW_yE46`; metadata readback verified the initial 7,655-byte file and an in-place update to 7,725 bytes at 12:40:13 UTC. The active `barolab-google-drive` heartbeat is configured every five minutes to retrieve the NAS snapshot, refresh the local JSON, and update that same Google Drive file through the connector. Initial upload and automation registration are verified; a subsequent scheduled update still requires execution evidence. Routine unchanged/non-actionable runs stay quiet; failures must preserve the previous file and must not be reported as successful synchronization. Synology Drive's `yoonlab` shared-folder service was confirmed disabled and was not changed.

Periodic refresh verified without another API call: NAS file generatedAt advanced from `2026-10-19T12:34:45.549103+00:00` to `2026-10-19T12:39:48.564056+00:00` (303 seconds). The second snapshot reports `complete: true`, CDP 5/5 and all three databases collected. The Windows dashboard worker was restarted only after confirming no active child/control job, so the corrected browser observation schema is now loaded in memory.
