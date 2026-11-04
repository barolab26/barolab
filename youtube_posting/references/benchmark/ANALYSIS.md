# Reference Benchmark Analysis (`19uwljYI5r8` · 국민건강보험·국민연금 환급금 정리 기간 운영)

## 1. Whole-Piece Model & Why It Works
- **Source**: `references/benchmark/source.mp4` (`57.554s`, `29.97fps`, `11,555+` views)
- **Visual Evidence Grid**: `references/benchmark/overview.jpg` (`0s ~ 52s` @ `4s` interval)
- **Spoken Spine & Pacing**:
  - A full-length (`38~57s`) continuous spoken narration explains:
    1. **0~12s (Opening Hook & Context)**: Why unclaimed refunds happen right now and the total scale of unclaimed money.
    2. **12~28s (Institutional Proof & Eligibility)**: Real B-roll of the National Health Insurance Service (`h-well 국민건강보험`) headquarters (`16s`, `20s`, `24s`, `28s`) establishes immediate visual authority while narration explains who qualifies (`본인부담상한액 초과금`, `이중납부 환급금`).
    3. **28~44s (Step-by-Step Verification & Anti-Smishing Warning)**: How to check via official app/website (`The건강보험` / `국민건강보험 홈페이지`) and why SMS URL links must be avoided.
    4. **44~57s (Expiration Deadline & Action Payoff)**: The 3-year statute of limitations (`3년 소멸시효`) and immediate deposit timeline after account registration.

## 2. Why Our Earlier 12s/14s Static Draft Failed (Root Cause Diagnosis)
1. **Truncated Duration (12~14s)**: Cut off mid-sentence before delivering the actual steps or payoff. A Short on policy/finance needs **38~48 seconds** to complete the Hook → Mechanism → Comparison/Proof → Step-by-Step Action → Payoff arc.
2. **Everything Crammed Into One Static Frame**:
   - Placed debug meta-labels (`SCENE 02 · 5.0s ~ 12.0s`, `CUT 2/2`, `SVML WORD-ANCHORED KARAOKE CAPTION`) directly on the viewer's screen.
   - Stacked a 3-column table with fixed pixel coordinates (`[96, 380, 710]`) so long Korean strings collided horizontally (`국민건강보험 홈페이지 / 앱 로그인` overlapping `민원여기요 → 환급금 조회`).
   - Showed Caption box + Table + Header + CTA box simultaneously with zero hierarchy.
3. **Zero Motion & Zero Real B-Roll**: Only 2 static PNG slides over 12 seconds instead of 30fps frame-driven HTML/CSS/SVG motion graphics + real B-roll backdrop.

## 3. Target Production Architecture (`@barolab/shorts-scene@1` on `@hypit/hypit 0.3.1`)
- **Canvas & Clock**: `1080×1920` (9:16 vertical), `30fps` (`@hypit/timeline-author@1`, `@hypit/spatial@1`).
- **Duration**: Driven 100% by the full normalized narration audio (`38~46 seconds` per Short, `1,140 ~ 1,380 frames` at 30fps) via `@hypit/media-operations@1` `Normalize` and `@hypit/audio-track@1`.
- **5-Beat Visual Progression (Beat changes every 6~9 seconds, one clear focal visual per beat)**:
  - **Beat 1 (Hook & Impact Number)**: Full-bleed atmospheric B-roll + giant animated counter/stat card (`3년 지나면 국고 귀속`, `1분 통합 조회`) that scales in with spring physics.
  - **Beat 2 (Before vs After / Myth vs Fact Split)**: Two stacked high-contrast comparison cards (`기존 방식 vs 바뀐 방식`) where the wrong way dims (`opacity: 0.45`) and the right way expands with a glowing emerald accent border.
  - **Beat 3 (Progressive Vertical Step Cards — NEVER horizontal colliding columns)**: 3 clean full-width horizontal step cards (`STEP 01`, `STEP 02`, `STEP 03`) stacked vertically with CSS Flexbox (`display: flex; flex-direction: column; gap: 22px`), where each card enters sequentially on its exact spoken cue and highlights when active.
  - **Beat 4 (Key Checkpoint / Pitfall Warning)**: Focused spotlight card with animated SVG progress ring / check badge showing the exact numerical threshold or anti-smishing verification rule.
  - **Beat 5 (Final Verdict & Action Summary)**: Clean checklist summary card + subtle bottom reference bar (`댓글 체크리스트에서 원문 표 확인`).
- **Clean Word-Synced Subtitle Bar**:
  - Positioned in the dedicated lower safe zone (`bottom: 240px`, above YouTube Shorts UI overlay), rendering only the currently spoken phrase in crisp Korean typography (`Malgun Gothic Bold`, `46px`) with active keyword highlight—no meta-labels or boxes around debug text.

