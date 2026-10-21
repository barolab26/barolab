# Local memory service

Run from the repository root:

```powershell
python -B -X utf8 -m server.memory_service --port 8792
```

Open `http://127.0.0.1:8792/memory.html`. `/api/status` reports
`mode: memory-only` and `schedulersStarted: false`. This service uses the same
memory router and shared data as production, but does not import `server/main.py`
or start its periodic workers. It binds only to loopback and permits browser
requests from its own origin and the existing NAS dashboard origins.

Keep the process running while using the local page. A foreground process ends
with Ctrl+C. No automatic startup task is installed; start it again after a
Windows restart. For a hidden launch, retain the process ID and separate stdout
and stderr logs. Do not stop a process merely because it owns the chosen port.

For local development, append `--reload` to opt into Python source reload.
Without that flag, code changes require a fresh service process. No shutdown
HTTP endpoint is exposed. Existing preview port 8791 is separate and is not controlled by this
command. Production NAS updates still require the image import/recreate procedure
in [DOCKER.md](DOCKER.md). Running this local service does not update the NAS image.

## Integration and verification scope

The shared engine stores bounded `data/memories/MEMORY.md` and `USER.md`,
progressive procedures under `data/skills/*/SKILL.md`, and durable episodes,
frozen session snapshots and review jobs in ignored `data/memories/state.sqlite3`.
One run keeps one snapshot; a new run sees later edits. Reviewer calls explicitly
skip memory injection and recording to prevent recursive review. The configured
Codex/active API is used; AGY and FreeLLMAPI are disabled.

Review is queued only after an ended CEO conversation, confirmed doctor republish,
verified pipeline recovery, or a complete comparable measured increase. An ended
conversation is review input, not proof that every sentence is a lasting rule.
Traffic and AdSense revenue comparisons retain source timezone, currency,
estimated/final status and revenue scope; measured increases do not prove that
an agent action caused them. Naver reservation recovery requires a prior failed
attempt and a verified post-submit receipt; it never means public publication.
Threads recovery proves authenticated API identity, while a separate public page
check remains a separate claim. KnowledgeIn currently records confirmed public
answer episodes only: it has no explicit verified repair transition from which
to infer a recovery reviewer event. Infrastructure port recovery is likewise not
publication recovery.

Chat generation passes its nine-second provider timeout to active API and Codex
subprocess calls. Local file access and optional signed executable rediscovery
happen outside the model-generation timeout. Other workflows retain their prior
provider defaults.

Validation on 2026-10-19: core 19 tests, frontend 12 tests, and the combined 48-test
integration suite passed (12 integration, 18 provider/Codex, 18 Threads).
Results are recorded in the scratch verification report. The wider KnowledgeIn suite has seven unchanged
baseline failures (daily/account caps, round pacing, and source relevance); the
same failures were reproduced with HEAD pipeline and authoring files in an
isolated external package. Evidence: `C:/Users/baro7/.barolab/scratch/hermes-20261019/kin-baseline-tests.txt`.
This memory change does not claim those existing pipeline issues are repaired.

Current local service operational records (PID, port, logs, HTTP checks) are in
`C:/Users/baro7/.barolab/scratch/hermes-20261019/memory-service-8792*.json` and
matching stdout/stderr logs. The existing 8791 preview was preserved. The 8792
service is loopback-only and is not a deployment to the NAS image; a browser on
another PC cannot use this PC's loopback fallback.

## Final acceptance (2026-10-19)

All 79 scoped checks passed: core 19, frontend 12, integration 12,
provider/Codex 18, and Threads 18. Actual SQLite FTS retrieval measured p95
5.70 ms and maximum 152.20 ms in the recorded local benchmark; these timings
are observations from that sample, not a latency guarantee.

Browser verification on the running loopback 8792 service confirmed 13 core
hubs, 30 nodes and 129 edges. The actual MEMORY and SKILL bodies, parent
relationships and backlinks were visible. A SKILL numbering correction was
saved with PATCH and read back. A temporary node was created, moved to trash,
restored with its original text and edges, then moved to trash again for cleanup.
The final graph viewport and inline deletion confirmation passed frontend checks.
Temporary verification notes, screenshots, database files and runtime snapshots
are excluded from the source commit.


## Operational evidence audit (2026-10-21)

This read-only audit distinguishes implemented paths, stored records, and actual
reuse. It does not replace the historical 2026-10-19 acceptance results above.

- Runtime episodes and frozen session snapshots are accumulating. Existing curated
  MEMORY/USER text and matching skill bodies have a context-injection path. A stored
  snapshot alone does not prove that a particular provider call received or used it.
- No recent operational evidence establishes automatic promotion of the latest
  CF/Naver/KnowledgeIn work into reusable knowledge and its subsequent application.
  The latest observed applied review was the 2026-10-19 dashboard repair; the graph
  currently exposes one skill. Counts and graph visibility are not learning outcomes.
- Automatic retrieval of relevant past episodes is not connected to the generation
  path. Frozen curated context and skill matching must not be described as automatic
  retrieval and reuse of the complete work history.
- Actual recent CF/Naver model-audit requests record call IDs, models and attachment
  hashes, but not the injected memory/skill hashes or a session-to-provider prompt
  receipt. Runtime LLM episodes retain the original pre-injection prompt, not the
  complete provider input. Exact evidence of which memory revision reached which
  call is therefore missing; successful model output does not fill that gap.
- KnowledgeIn and Threads direct `generate_local` calls bypassed the memory boundary.
  That connection is now corrected and tested with a mocked actual subprocess and
  an isolated temporary memory store. Related tests passed on Windows (18) and
  Ubuntu (17; one pre-existing missing `httpx[http2]` dependency prevented a test).
  Four resolution-suite failures were reproduced on HEAD and are separate baseline
  issues. Actual reuse during a new operational task remains unverified; publication
  episodes recorded separately do not prove authoring/reviewer context injection.

Audit sources include existing output/model-audit request/status files, private
KnowledgeIn sources/generation artifacts, and read-only runtime-memory records.
No synthetic production episodes, private Codex memory edits, database writes or
new publication were performed for this audit. Follow-up acceptance should connect
an evidenced work lesson, its approved revision, a later frozen snapshot, and the
actual provider request by IDs/hashes without exposing private prompt content.
