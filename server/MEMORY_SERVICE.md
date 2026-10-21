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
The findings below describe the initial audit, before the follow-up implementation
and acceptance recorded in the next section.

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

## Verified-work reuse acceptance (2026-10-21)

The follow-up implemented receipt-bound learning intake after existing verified
CF, Naver, KnowledgeIn and Threads outcomes. Learning failures remain separate
from publication/reservation ledgers. Extraction and independent review precede
knowledge admission; ordinary successful logs are not automatically skills.
The graph defines the truthful `project` channel for common operations: 12 seeded
agent/channel hubs plus two bounded context identities, totaling 14. Existing
documents and the owner/channel admission gate are preserved. A fresh process
reading the operational database confirmed 14 core identities, 17 nodes and 56
edges. The older dashboard process (started 00:00:46 KST, before this graph change)
returned 13/16/54 because its imported definition omitted the project hub. After
restarting only the dashboard service, the live 8790 API independently returned
14 core identities, 17 nodes and 56 edges with the project hub present. No gate
relaxation or additional graph source change was needed for this refresh.

One actual Naver follow-up completed the retrieval-to-application check. Private
evidence is under `~/.barolab/memories/work-evidence/naver-followup-check-20261021/`
(`task-prompt.txt`, `plan.json`, `result.json`); these files are not committed.
The natural-language task supplied no learned event ID. The returned plan exactly
matches the plan preserved in the result, and references the learned reservation
procedure. Its bounded checks were then executed by the host, not accepted solely
because the model claimed success.

- Learned event: `learned:historical:naver:224448649049:verified-work:policy:observed-procedure-v2:parser:optional-record-v1`.
  The policy/parser-qualified event retains the earlier candidate reference;
  earlier failed or held attempts were not rewritten as successes.
- `skill-verification.json` confirms the stored skill contains all canonical
  candidate fields, matches the applied audit SHA and source event, and was not
  model-rewritten after the verdict. Its graph node is admitted as
  `verified_knowledge` with three actual edges. Promotion/review receipts remain
  in the separate private `promotion-proof.json`.
- Provider call `llm:6cb72aa25e974a5490a6a17143f0ed8a`, session
  `hermes-followup-nav-reservation-20261021`, has a completed delivery receipt.
  Actual prompt SHA-256 is `df37dd7243dffd284d320226e1238d984022bca86a6f7f7244a2ea83cee83ed5`;
  `memoryPrefixPresent` is true. The same receipt binds snapshot
  `7d97ef152256ee1ff3fd1e004fde95ce43bc895396fc890512e1ef7d996cdfeb`, learned skill
  `ab8e19df29dce38cf9b1f76f4be73ed0a3e504a98c8e95edd7d066ffab84d58a`, and episode
  `165504cdba7726ef89d5af9e55473422c04f6dcfe7360c207b9e854eab76f3a1`.
- Host checks confirmed the historical 11:00 reservation identity and saved
  document SHA `19c6078ce1252457d59c1d3ff503b5ed1f234aa5d62c0c8a6d5b23565df78378`.
  The original receipt still says public=false: reservation proof is not public
  proof. A separate current public HTTP check returned 200 with the exact title
  at `2026-10-21T04:41:32.135247+00:00`.
- Review metadata recorded native/PC/mobile and pixel passes with two image
  groups. Its `categoryMatches:false` remains visible; this follow-up does not
  reinterpret it as a pass or claim a fresh full editorial review.
- Result SHA is `6c657877b24cd0c1b1644f8b2e918dc20eb2e4cdc689996402960e193780e446`.
  New submissions: zero. This proves one evidenced lesson was retrieved, delivered
  to a real provider call, and used for bounded host-verified follow-up checks;
  it does not establish successful learning from every channel or every future run.

Scoped producer/graph/summary checks passed on Windows (69) and Ubuntu (68,
excluding the existing unavailable CORS test dependency). These are separate
from the historical 79-check acceptance and from the live reuse evidence above.
