# KnowledgeIn alternating-account experiment

The original trial dates were **2026-10-15 through 2026-10-21 KST**, with
measurement through October 24. The existing configuration now has
`continuousMode: true`; this migration preserves that value rather than extending
or restarting the trial. Read `dashboard/data/kin-automation.json` for the actual
enable setting, interval and caps. The two authorized accounts
are `adinfo0905` and `stone0747`; their existing dedicated CDP browsers must already
be authenticated. On Ubuntu, only these two existing profiles are verified and
reused. A closed browser blocks the check; open it beforehand with its dedicated
account launcher. A scheduler service never starts Chrome, so its cgroup cleanup
cannot terminate a browser it created. Never replace this with an ad hoc command.

## Completion-based cadence

The scheduler checks conditions every five minutes. This does **not** mean
publishing every five minutes. After a genuine operating round completes, the
configured interval/jitter applies (currently 20 minutes with 18–22 minute jitter);
the final submission contract also enforces a minimum 15-minute completion gap.
Accounts alternate;
a suspended account or exhausted account cap is skipped in favor of an available
account. The global cooldown survives midnight and process restarts.

A round includes discovery, source capture, model writing, independent review,
publication if approved, public verification, and its measurement update. Review
rejections, no suitable questions, and connection/login errors still finish a round
and start its cooldown. A no-op condition check does not change the cooldown,
account turn, or operating budget and does not query GA4.

The existing configuration permits at most **20 submission attempts globally and
10 per account per KST day**, including uncertain submissions. The separate
model-usage budget is **20 operating rounds globally and 10 per account daily**,
including unsuccessful/rejected rounds. The existing
manual pilot publication counts toward today's operating and submission limits.
These are upper limits, not promises of successful answers.

Private SQLite `operating_cadence` holds the last completion, last account, and one
durable in-flight reservation. Reservation, account selection and operating caps
are checked with `BEGIN IMMEDIATE`. The final pre-submit gate rechecks the exact
reservation/question/account, live enable setting, service suspension, trial date,
current KST attribution date and submission caps atomically. Manual sends without
the same reservation cannot bypass the interval. Question IDs remain globally unique.

The initial completion anchor is taken once from the latest genuine recorded
publication; no-post authoring exercises are excluded. Later verification refreshes
do not change that anchor. If a process dies mid-round, the next owner marks it
interrupted/unknown and applies the configured cooldown from recovery. Previously uncertain
submissions are never automatically reposted. There is no burst catch-up.

The model is explicitly `gpt-6.1-sol` in this KnowledgeIn-only configuration, using
the existing authenticated ChatGPT subscription through `common.codex_cli`.
Global model settings are unchanged. FreeLLMAPI and provider fallbacks are prohibited.
Questions and source pages remain untrusted data. Every automatic answer requires a
separate evidence review and deterministic URL/source/account binding checks. Existing
manual drafts are preserved. Only the selected question is claimed; search counts may
contain repeats and are not represented as unique selected questions.

Selection may return `no_good_match`; it must not force an answer from a related
institution or product. Explicit target names/model IDs and historical
time-sensitive contexts are checked before writing and after selection. These
bounded checks do not replace the independent review's required exact-target,
time-scope and question-resolution judgments. Old evergreen questions may qualify.
A sourced disclaimer or generic checklist that leaves the actual question
unanswered fails review, as does an unverified promise of screenshots or tables.

## Ubuntu user services

`python -m naver_kin.scheduler --register` installs the four owned systemd user
units disabled. It never enables or starts them and never changes configuration
caps, trial dates or continuous mode. The tick timer checks every five minutes;
the measurement timer runs at **20:30 Asia/Seoul**, independent of host timezone.
Both call the existing scheduler with the current virtual-environment Python.
They require the existing `:10` desktop and authenticated dedicated profiles.
User lingering keeps the scheduler available but does not create a GUI session.

`--status` reports actual systemd timer and linked-service states; a failed
service remains failed even when its timer is active. Saved Windows task status
is historical evidence and is not merged into this observation.
`--tick --dry-run` reads the existing SQLite ledger without schema writes, model
calls, browser launches, operating claims or answer submission. An exact
account/blog lock still protects a real round from overlapping browser work.
The two timers remain disabled until uncertain submissions are reconciled,
the safety checks pass, and one supervised eligible round has completed.

## Historical Windows tasks and operations

`python -m naver_kin.scheduler --configure --model gpt-6.1-sol --start-date 2026-10-15`
prepares a disabled configuration. After supervisor implementation review,
`--register` replaces only this workflow's owned tasks with one five-minute condition
trigger and the separate daily 20:30 measurement task. Task names remain
`BaroLab-Kin-Seven-Day-Pilot` and `BaroLab-Kin-Seven-Day-Pilot-Measurement`.
Publication ends on October 21, measurement on October 24. Date/enable guards
also apply at the last moment before clicking; a long generation cannot extend the
trial or silently use yesterday's attribution date after midnight.

`--status` reads actual task registration, enable state, next run and last result.
`--tick --dry-run` observes cadence without generating, reserving, submitting or
advancing a turn. `--authoring-dry-run --account adinfo0905` exercises actual
research/writing/review only and leaves private artifacts, never an operating claim.
The ordinary tick starts at most one round and has no inline repeated-send loop.

The scheduler lock serializes operations; the existing blog lock is only probed and
released before work, and each real browser transaction owns that blog lock itself.
A busy blog is not a completed operating round. Explicit account protection or CAPTCHA
halts the account; question-specific refusal skips only that question. No recovery
or CAPTCHA bypass is attempted.

Measurements use existing GA4 access, with unknown revenue remaining unknown.
Public retention checks cover up to 100 initially verified answers with bounded
requests and a ten-minute budget. An unavailable check is unknown and never erases
the original verification history. Condition-only ticks do not repeatedly collect GA4.

Execution uses local Python and the absolute UNC script path, not mapped drive Y:.
It requires the existing logged-in Windows session and both dedicated account
browsers. Locking the screen preserves the session; signing out, powering off or
closing browsers prevents work. Logs: `dashboard/data/kin-scheduler.log` and private
`kin-scheduler-errors.log`. Configuration/state: `kin-automation.json` and
`kin-automation-state.json`; ledger: `dashboard/data/kin.sqlite3`; public snapshot:
`dashboard/data/kin.json`.

## Manual reviewed answer

1. Discover a narrow topic matched to an existing public article:
   `python -m naver_kin.pipeline --account adinfo0905 --discover --keyword "세탁기 배수 필터"`
   Discovery reserves question IDs globally and updates the dashboard snapshot.
   Check question recency, relevance, existing answers, duplicate publications,
   and the actual logged-in account before selecting a question. Discovery is not
   permission to answer irrelevant questions or reuse the same answer repeatedly.
   Skip questions without a directly relevant, already verified owned guide;
   do not force a destination link or invent service guarantees.
2. Save the browser's captured question JSON privately with `question_url`, `title`,
   `body`, and `captured_at`. Write a substantive standalone answer in a private
   text file, with exactly one `{OUTBOUND_URL}` placeholder for the relevant owned
   article. Include an accurate indication that the linked article is operated by
   the answerer. Do not invent experience, expertise, results, or eligibility.
3. Prepare source evidence and the exact attribution URL:
   `python -m naver_kin.pipeline --account adinfo0905 --prepare --question-json PRIVATE/question.json --article-url https://www.must-good.com/washing-machine-drain-filter-cleaning --answer-file PRIVATE/answer.txt --output PRIVATE/draft.json`
   Use a private directory outside `dashboard`; drafts contain full source bodies.
4. Supervisor checks the captured question, source accuracy, freshness, standalone
   usefulness, affiliation disclosure, and actual linked destination. Only after
   approving that exact content, set `review.approved` to `true` and `review.reviewer`
   to the reviewer identity. Preserve `review.binding`; edits require preparation
   and review again. Import with:
   `python -m naver_kin.pipeline --account adinfo0905 --import-draft PRIVATE/draft.json`
5. The operating scheduler starts the exact reviewed attempt under its active reservation (do not invent or reuse a reservation ID):
   `python -m naver_kin.pipeline --account adinfo0905 --run-once --run-id ACTIVE_RESERVATION_ID`
   Add `--question-id QUESTION_ID` to select the exact reviewed candidate when
   other unapproved drafts are retained in the queue.
   One answer maximum per invocation; the same global ten/account five daily limits
   and authorized experiment dates apply. The reviewed article is fetched again.
6. Verify public publication separately:
   `python -m naver_kin.pipeline --account adinfo0905 --verify QUESTION_ID`
   Exact account, question, answer ID, body, and outbound URL must match in public
   evidence. Login-session visibility alone is insufficient.

`--status` refreshes sanitized `dashboard/data/kin.json`. Private ledger:
`dashboard/data/kin.sqlite3`; per-account locks: `dashboard/data/kin-ACCOUNT.lock`.
The global question key prevents the second account answering the same question.
State is saved as `publishing` immediately before the final click, then remains
`submitted_unverified` until independently verified. A crash, CAPTCHA, moderation,
timeout, or ambiguous outcome after that boundary never permits automatic repost.
Check the existing publication and reconcile evidence instead.

Published answers, referral visits, and revenue are separate measurements.
Inbound visits and attributed revenue remain `null`/`unmeasured` in this pilot
snapshot. Existing GA4 reporting can subsequently report qualified `naver_kin`
referrals, but those do not by themselves establish human visits or incremental
revenue. No new collector or API server deployment is required for the snapshot.

Tests: `python -m unittest naver_kin.test_pipeline`.
