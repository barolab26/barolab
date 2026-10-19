# Radar source scouting

`radar_scout.py` reads reviewed public endpoints, stores the fetched URL/date/hash,
and separates policy/marketing candidates (A) from micro-business hypotheses (B).
HTTP errors and unavailable trend/outlier measurements remain unknown. No code
from a feed is executed. Current source coverage includes policy listings, Google
Trends, Search Central updates, Product Hunt and App Store. Indie Hackers RSS and
the Naver realtime endpoint may be unavailable; this is reported, not substituted
with invented search-volume data. YouTube page availability alone cannot establish
an outlier without video/channel baseline measurements.

The shared SQLite state is `server/data/radar/scout.sqlite3` (Git ignored). Each
09:00, 14:00, 20:00 KST slot is claimed transactionally. Only the current 15-minute
window is eligible, so restarts skip missed slots. Concurrent scheduled/manual
calls cannot overlap. Manual calls deduplicate within five minutes. Abandoned
30-minute claims become interrupted and are never replayed automatically.

`POST /api/chat/radar/scout` starts a thread and returns a run ID immediately.
`GET /api/chat/radar/status` exposes actual running/completed/failed state, source
receipts and saved chat IDs. Room/poll endpoints return a compact runtime status.
`POST /api/chat/autonomous/toggle` persists whether scheduled scouting is enabled.
`BAROLAB_DISABLE_BACKGROUND=1` disables startup of the Radar scheduler for tests;
it is not a global switch for every unrelated legacy background task.

The report and three role discussions use stable `radar-{runId}-{role}` message
IDs. A completed run means its internal source report/discussion was persisted,
not that an external post, indexing result or revenue result succeeded. If the
configured LLM fails, the colleague message explicitly records unavailable
discussion instead of fabricated agreement. No external publishing dispatcher is
called. Full engine JSON stays in evidence; chat displays 16 CF sites separately
from the five Naver blog accounts, plus the three priority domains.

`skills/seo-marketing-master/SKILL.md` is the single canonical procedure. The
Hermes production catalog also reads this approved project skills root while
retaining `data/skills` compatibility. Project-root names win collisions. Existing
sessions retain frozen content; a new chat turn gets a new session ID. All six
roles share immutable truth rules and request the actual master body only on
relevant topics. The graph presents the procedure as curated documentation with
real crew/channel parents, not as proven traffic or indexing success.

Validation: `python -B -m unittest server.test_radar_scout` checks durable claims,
restart/dedup, failure/persistence, source freshness, concrete B candidates,
approved skill-root dedup/freeze, actual provider-boundary body injection for all
six roles, 16-CF scope, and timeout/duplicate-browser safeguards. Existing Hermes,
graph, promotion and integration regressions must also pass. `common/llm_client.py`
and provider routing are unchanged.

An explicit indexing action runs one HTTP submission worker and records a GSC
intent with `dashboard.indexing_submissions.enqueue_gsc_request`. The existing
authorized metrics collector consumes that durable queue under its lock, daily
budget and URL deduplication rules. A queued or unavailable request is not a
browser start, submission receipt, or indexing confirmation. SearchAdvisor UI
work remains a separate observed workflow.

2026-10-19 operation evidence: external scratch folder
`C:/Users/baro7/.barolab/scratch/seo-radar-20261019`. The existing local 8790 server
was refreshed after no active chat turn was observed. Two normal Ctrl+C attempts
left its remote idle SSE draining, so the explicitly approved exact old Python
PID was cleaned up; browser/other publishing processes were untouched. Replacement
uses the same bind/port and `--timeout-graceful-shutdown 15`. No new parallel
dashboard service or scheduler was created. NAS deployment is separate; this
refresh targets the existing local server.

First run: `6e2ba74e127f4066ba15601b933b413c`, source/engine observation
`2026-10-19T12:32:01+09:00`. Three A candidates and two B candidates were collected,
then Radar/Trace/Publi/Jarvis messages were persisted. A scope/rendering correction
removed five Naver accounts from the CF denominator and replaced raw JSON with
a concise summary using the same message IDs and original observation timestamp.
No second fetch or duplicate model discussion was performed for that correction.
