import { sealVisualTrack } from "@hypit/composition";
import { htmlVisual } from "@hypit/html-program";
import { assertTemporalWindowFor } from "@hypit/temporal";

export function renderShortsScene(
  timeline,
  within,
  window,
  fontBold,
  fontRegular,
  bgImages,
  steps,
  captions,
  beats,
  options
) {
  assertTemporalWindowFor(window, { subjectId: options.id, timeline });
  const startFrame = window.span.startFrame;
  const totalFrames = Math.max(1, window.span.endFrameExclusive - startFrame);
  const themeMode = options.themeMode || "tech-cyber";
  const isSenior = themeMode === "senior-editorial";
  const isVibe = themeMode === "vibe-terminal";

  let order = 0;
  const textEl = (id, value, size, color, isBold = true, lineHeight = 1.3, align = "left") => ({
    id,
    kind: "text",
    parent: "shorts-root",
    order: ++order,
    text: String(value || ""),
    fonts: isBold ? fontBold.faces : fontRegular.faces,
    style: [
      { name: "font-size", value: `${size}px` },
      { name: "line-height", value: lineHeight },
      { name: "color", value: color },
      { name: "text-align", value: align },
      { name: "word-break", value: "keep-all" },
    ],
  });

  const brollElements = (bgImages || []).map((blobRef, idx) => ({
    id: `broll-${idx}`,
    kind: "image",
    parent: "shorts-root",
    order: ++order,
    artifact: blobRef,
    style: [
      { name: "width", value: "100%" },
      { name: "height", value: "100%" },
      { name: "object-fit", value: "cover" },
    ],
  }));

  const sceneCaptions = options.sceneCaptions || [
    options.scene1Caption || "SCENE 01 · 핵심 훅 & 실측 지표",
    options.scene2Caption || "SCENE 02 · 기존 방식 vs 자동화 비교",
    options.scene3Caption || "SCENE 03 · 3단계 실행 파이프라인",
    options.scene4Caption || "SCENE 04 · 핵심 수익·성능 기준선",
    options.scene5Caption || "SCENE 05 · 실전 적용 3대 체크리스트",
  ];

  // Theme-specific typography palette so each reference style has authentic contrast
  const colors = isSenior
    ? {
        channelName: "#ffffff",
        categoryPill: "#fef08a",
        sceneCap: "#ffffff",
        hookBadge: "#92400e",
        hookStat: "#065f46",
        hookUnit: "#047857",
        hookTitle: "#0f172a",
        hookSub: "#334155",
        sectionHead: "#064e3b",
        wrongLabel: "#991b1b",
        wrongTitle: "#1e293b",
        wrongDesc: "#475569",
        rightLabel: "#065f46",
        rightTitle: "#064e3b",
        rightDesc: "#1e293b",
        stepBadge: "#ffffff",
        stepTitle: "#0f172a",
        stepDetail: "#047857",
        ruleBadge: "#92400e",
        ruleTitle: "#0f172a",
        ruleDesc: "#334155",
        rulePill1: "#065f46",
        rulePill2: "#1e40af",
        checkText: "#0f172a",
        ctaBanner: "#ffffff",
        capTag: "#0f172a",
        capText: "#ffffff",
      }
    : isVibe
    ? {
        channelName: "#f8fafc",
        categoryPill: "#e879f9",
        sceneCap: "#e9d5ff",
        hookBadge: "#f0abfc",
        hookStat: "#ffffff",
        hookUnit: "#38bdf8",
        hookTitle: "#ffffff",
        hookSub: "#e2e8f0",
        sectionHead: "#f0abfc",
        wrongLabel: "#fda4af",
        wrongTitle: "#f1f5f9",
        wrongDesc: "#cbd5e1",
        rightLabel: "#6ee7b7",
        rightTitle: "#ffffff",
        rightDesc: "#d1fae5",
        stepBadge: "#0f172a",
        stepTitle: "#ffffff",
        stepDetail: "#c4b5fd",
        ruleBadge: "#fde047",
        ruleTitle: "#ffffff",
        ruleDesc: "#e2e8f0",
        rulePill1: "#6ee7b7",
        rulePill2: "#e879f9",
        checkText: "#f8fafc",
        ctaBanner: "#fde047",
        capTag: "#0f172a",
        capText: "#ffffff",
      }
    : {
        channelName: "#f8fafc",
        categoryPill: "#38bdf8",
        sceneCap: "#f8fafc",
        hookBadge: "#fde047",
        hookStat: "#ffffff",
        hookUnit: "#38bdf8",
        hookTitle: "#ffffff",
        hookSub: "#cbd5e1",
        sectionHead: "#ffffff",
        wrongLabel: "#fca5a5",
        wrongTitle: "#f1f5f9",
        wrongDesc: "#94a3b8",
        rightLabel: "#6ee7b7",
        rightTitle: "#ffffff",
        rightDesc: "#d1fae5",
        stepBadge: "#0f172a",
        stepTitle: "#ffffff",
        stepDetail: "#7dd3fc",
        ruleBadge: "#fde047",
        ruleTitle: "#ffffff",
        ruleDesc: "#e2e8f0",
        rulePill1: "#6ee7b7",
        rulePill2: "#93c5fd",
        checkText: "#f8fafc",
        ctaBanner: "#fde047",
        capTag: "#0f172a",
        capText: "#ffffff",
      };

  const textChildren = [
    // Top bar
    textEl("channel-name", options.channelName, isSenior ? 26 : 24, colors.channelName, true, 1.2),
    textEl("category-pill", options.categoryPill, isSenior ? 22 : 21, colors.categoryPill, true, 1.2),

    // Scene captions
    ...sceneCaptions.map((sc, idx) =>
      textEl(`scene-cap-${idx}`, sc, 21, colors.sceneCap, true, 1.2)
    ),

    // Beat 1: Hook & Core Number
    textEl("hook-badge", options.hookBadge, isSenior ? 26 : 24, colors.hookBadge, true, 1.2),
    textEl("hook-stat", options.hookStat, isSenior ? 48 : 34, colors.hookStat, true, 1.12, "center"),
    textEl("hook-unit", options.hookUnit, isSenior ? 26 : 24, colors.hookUnit, true, 1.2, "center"),
    textEl("hook-title", options.hookTitle, isSenior ? 46 : 44, colors.hookTitle, true, 1.26, "center"),
    textEl("hook-sub", options.hookSub, isSenior ? 28 : 26, colors.hookSub, false, 1.38, "center"),

    // Beat 2: Myth vs Fact / Before vs After Comparison
    textEl("compare-heading", options.compareTitle, isSenior ? 40 : 38, colors.sectionHead, true, 1.24),
    textEl("wrong-label", options.wrongLabel, 22, colors.wrongLabel, true, 1.2),
    textEl("wrong-title", options.wrongTitle, isSenior ? 35 : 33, colors.wrongTitle, true, 1.26),
    textEl("wrong-desc", options.wrongDesc, isSenior ? 26 : 24, colors.wrongDesc, false, 1.35),
    textEl("right-label", options.rightLabel, 22, colors.rightLabel, true, 1.2),
    textEl("right-title", options.rightTitle, isSenior ? 36 : 34, colors.rightTitle, true, 1.26),
    textEl("right-desc", options.rightDesc, isSenior ? 26 : 25, colors.rightDesc, false, 1.35),

    // Beat 3: 3-Step Progressive Action Walkthrough
    textEl("steps-heading", options.stepsTitle, isSenior ? 40 : 38, colors.sectionHead, true, 1.24),
    ...steps.flatMap((step, idx) => [
      textEl(`step-badge-${idx}`, step.badge, 22, colors.stepBadge, true, 1.1, "center"),
      textEl(`step-title-${idx}`, step.title, isSenior ? 33 : 31, colors.stepTitle, true, 1.24),
      textEl(`step-detail-${idx}`, step.detail, isSenior ? 25 : 24, colors.stepDetail, false, 1.32),
    ]),

    // Beat 4: Core Numeric Criterion / Safety Spotlight
    textEl("rule-badge", options.ruleBadge, isSenior ? 26 : 24, colors.ruleBadge, true, 1.2, "center"),
    textEl("rule-title", options.ruleTitle, isSenior ? 44 : 42, colors.ruleTitle, true, 1.28, "center"),
    textEl("rule-desc", options.ruleDesc, isSenior ? 28 : 26, colors.ruleDesc, false, 1.38, "center"),
    textEl("rule-pill1", options.rulePill1, isSenior ? 26 : 25, colors.rulePill1, true, 1.28, "center"),
    textEl("rule-pill2", options.rulePill2, isSenior ? 26 : 25, colors.rulePill2, true, 1.28, "center"),

    // Beat 5: Final 3-Point Checklist & Action Payoff
    textEl("closing-heading", options.closingTitle, isSenior ? 40 : 38, colors.sectionHead, true, 1.24),
    textEl("check-1", options.check1, isSenior ? 30 : 28, colors.checkText, true, 1.3),
    textEl("check-2", options.check2, isSenior ? 30 : 28, colors.checkText, true, 1.3),
    textEl("check-3", options.check3, isSenior ? 30 : 28, colors.checkText, true, 1.3),
    textEl("cta-banner", options.ctaBanner, isSenior ? 26 : 25, colors.ctaBanner, true, 1.3, "center"),

    // Spoken Captions (Word-Synced Subtitle Bar)
    ...captions.flatMap((cap, idx) => [
      textEl(`cap-tag-${idx}`, cap.highlight, 22, colors.capTag, true, 1.1, "center"),
      textEl(`cap-text-${idx}`, cap.text, isSenior ? 37 : 35, colors.capText, true, 1.34, "center"),
    ]),
  ];

  const beat2Frame = Math.max(30, beats.compareFrame - startFrame);
  const beat3Frame = Math.max(beat2Frame + 30, beats.stepsFrame - startFrame);
  const beat4Frame = Math.max(beat3Frame + 30, beats.ruleFrame - startFrame);
  const beat5Frame = Math.max(beat4Frame + 30, beats.closingFrame - startFrame);

  const stepFrames = steps.map((s) => Math.max(0, s.at.frame - startFrame));
  const captionSpans = captions.map((c, idx) => {
    const start = Math.max(0, c.at.frame - startFrame);
    const end =
      idx + 1 < captions.length
        ? Math.max(start + 10, captions[idx + 1].at.frame - startFrame)
        : totalFrames;
    return { start, end };
  });

  // Build HTML & CSS tailored to each of the 3 distinct viral reference styles
  let html = "";
  let css = "";

  if (isSenior) {
    // =========================================================================
    // STYLE B: SENIOR-EDITORIAL (@숨은지원금 — Toss / 14F / 4060 Financial Brief)
    // Warm Ivory Paper Canvas + Top Emerald Breaking Masthead + Upper-Middle
    // High-Contrast White Passbook Cards + Lower Panoramic Photo + Broadcast Ticker
    // =========================================================================
    html = `
      <div class="paper-bg"></div>
      <div class="paper-pattern"></div>

      <!-- Top Breaking Policy Masthead -->
      <header class="topbar">
        <div class="brand-chip">
          <span class="live-badge">특보</span>
          <div class="brand-name">{{channel-name}}</div>
        </div>
        <div class="cat-chip">{{category-pill}}</div>
        <div class="progress-track"><div class="progress-fill"></div></div>
      </header>

      <div class="beat-dots">
        <span class="bdot" data-b="0"></span>
        <span class="bdot" data-b="1"></span>
        <span class="bdot" data-b="2"></span>
        <span class="bdot" data-b="3"></span>
        <span class="bdot" data-b="4"></span>
      </div>

      <!-- UPPER-MIDDLE EYE-LEVEL STAGE (Top 148px .. 1016px: High-Contrast White Financial Cards) -->
      <main class="stage">
        <!-- BEAT 1: PASSBOOK STAMP & HEADLINE -->
        <section class="beat beat-0">
          <div class="hero-card">
            <div class="hero-top-row">
              <div class="hero-badge-pill">{{hook-badge}}</div>
              <div class="hero-stamp-box">
                <svg class="ring-svg" viewBox="0 0 180 180">
                  <circle class="ring-bg" cx="90" cy="90" r="78" />
                  <circle class="ring-fg" cx="90" cy="90" r="78" />
                </svg>
                <div class="stat-main">{{hook-stat}}</div>
              </div>
            </div>
            <div class="stat-unit-bar">{{hook-unit}}</div>
            <div class="hero-title-wrap">{{hook-title}}</div>
            <div class="hero-sub-wrap">{{hook-sub}}</div>
          </div>
        </section>

        <!-- BEAT 2: BANKBOOK RECEIPT COMPARISON -->
        <section class="beat beat-1">
          <div class="section-head">{{compare-heading}}</div>
          <div class="compare-stack">
            <div class="comp-card wrong-card">
              <div class="comp-pill wrong-pill">주의 · {{wrong-label}}</div>
              <div class="comp-title">{{wrong-title}}</div>
              <div class="comp-desc">{{wrong-desc}}</div>
            </div>
            <div class="comp-card right-card">
              <div class="comp-pill right-pill">핵심 혜택 · {{right-label}}</div>
              <div class="comp-title">{{right-title}}</div>
              <div class="comp-desc">{{right-desc}}</div>
            </div>
          </div>
        </section>

        <!-- BEAT 3: TOSS-STYLE NUMBERED GUIDE CARDS -->
        <section class="beat beat-2">
          <div class="section-head">{{steps-heading}}</div>
          <div class="steps-stack">
            ${steps
              .map(
                (_, idx) => `
              <div class="step-card" data-step="${idx}">
                <div class="step-badge">{{step-badge-${idx}}}</div>
                <div class="step-body">
                  <div class="step-title">{{step-title-${idx}}}</div>
                  <div class="step-detail">{{step-detail-${idx}}}</div>
                </div>
              </div>`
              )
              .join("")}
          </div>
        </section>

        <!-- BEAT 4: OFFICIAL GUARANTEE CERTIFICATE CARD -->
        <section class="beat beat-3">
          <div class="spotlight-card">
            <div class="shield-row">
              <div class="shield-wrap">
                <svg viewBox="0 0 120 120" class="shield-svg">
                  <path class="shield-path" d="M60 12 L102 28 V58 C102 86 82 104 60 112 C38 104 18 86 18 58 V28 Z"/>
                  <path class="shield-check" d="M42 60 L55 73 L80 46"/>
                </svg>
              </div>
              <div class="rule-badge-pill">{{rule-badge}}</div>
            </div>
            <div class="rule-title-wrap">{{rule-title}}</div>
            <div class="rule-desc-wrap">{{rule-desc}}</div>
            <div class="rule-pills">
              <div class="rpill rpill-1">{{rule-pill1}}</div>
              <div class="rpill rpill-2">{{rule-pill2}}</div>
            </div>
          </div>
        </section>

        <!-- BEAT 5: 3-POINT SENIOR SUMMARY SHEET -->
        <section class="beat beat-4">
          <div class="section-head">{{closing-heading}}</div>
          <div class="checklist-stack">
            <div class="check-row" data-check="0">
              <div class="check-icon">1</div>
              <div class="check-text">{{check-1}}</div>
            </div>
            <div class="check-row" data-check="1">
              <div class="check-icon">2</div>
              <div class="check-text">{{check-2}}</div>
            </div>
            <div class="check-row" data-check="2">
              <div class="check-icon">3</div>
              <div class="check-text">{{check-3}}</div>
            </div>
          </div>
          <div class="cta-box">{{cta-banner}}</div>
        </section>
      </main>

      <!-- LOWER-MIDDLE PANORAMIC PHOTO WINDOW (top: 1034px, height: 420px) -->
      <section class="cinema-viewport">
        ${brollElements
          .map(
            (_, idx) => `
          <div class="broll-slide" data-broll="${idx}">
            <div class="broll-img-wrap">{{broll-${idx}}}</div>
            <div class="broll-caption-pill">
              <span class="broll-dot"></span>
              {{scene-cap-${idx}}}
            </div>
          </div>`
          )
          .join("")}
        <div class="cinema-vignette"></div>
        <div class="cinema-top-tag">4060 정책·연금 현장 리포트</div>
      </section>

      <!-- BOTTOM BROADCAST NEWS TICKER SUBTITLE BAR -->
      <footer class="subtitle-zone">
        ${captions
          .map(
            (_, idx) => `
          <div class="caption-card" data-cap="${idx}">
            <div class="cap-chip">{{cap-tag-${idx}}}</div>
            <div class="cap-line">{{cap-text-${idx}}}</div>
          </div>`
          )
          .join("")}
      </footer>
    `;

    css = `
      :scope {
        background: #F4F1EA;
        overflow: hidden;
        font-family: "Malgun Gothic", sans-serif;
      }
      .paper-bg {
        position: absolute;
        inset: 0;
        background: linear-gradient(180deg, #F7F4ED 0%, #EFECE4 60%, #E7E2D8 100%);
      }
      .paper-pattern {
        position: absolute;
        inset: 0;
        background-image: radial-gradient(rgba(6, 78, 59, 0.06) 1.5px, transparent 1.5px);
        background-size: 36px 36px;
        pointer-events: none;
      }
      .topbar {
        position: absolute;
        top: 36px;
        left: 48px;
        right: 48px;
        height: 76px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 26px;
        background: #064E3B;
        border: 2px solid #047857;
        border-radius: 22px;
        box-shadow: 0 12px 28px rgba(6, 78, 59, 0.25);
      }
      .brand-chip {
        display: flex;
        align-items: center;
        gap: 14px;
      }
      .live-badge {
        padding: 5px 14px;
        border-radius: 8px;
        background: #DC2626;
        color: #FFFFFF;
        font-size: 19px;
        font-weight: 900;
      }
      .cat-chip {
        padding: 8px 18px;
        border-radius: 999px;
        background: rgba(254, 240, 138, 0.18);
        border: 1.5px solid #FDE047;
      }
      .progress-track {
        position: absolute;
        left: 20px;
        right: 20px;
        bottom: 0;
        height: 5px;
        background: rgba(255, 255, 255, 0.2);
        border-radius: 4px;
        overflow: hidden;
      }
      .progress-fill {
        height: 100%;
        width: 0%;
        background: linear-gradient(90deg, #FDE047, #34D399);
      }
      .beat-dots {
        position: absolute;
        top: 124px;
        left: 0;
        right: 0;
        display: flex;
        justify-content: center;
        gap: 12px;
      }
      .bdot {
        width: 46px;
        height: 8px;
        border-radius: 999px;
        background: rgba(6, 78, 59, 0.2);
      }

      /* Upper-Middle White Editorial Stage */
      .stage {
        position: absolute;
        top: 146px;
        left: 48px;
        right: 48px;
        height: 868px;
      }
      .beat {
        position: absolute;
        inset: 0;
        display: flex;
        flex-direction: column;
        justify-content: center;
        opacity: 0;
      }
      .hero-card {
        background: #FFFFFF;
        border: 3px solid #059669;
        border-radius: 34px;
        padding: 36px 38px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 20px;
        box-shadow: 0 20px 45px rgba(15, 23, 42, 0.12);
      }
      .hero-top-row {
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 10px;
      }
      .hero-badge-pill {
        padding: 12px 26px;
        border-radius: 16px;
        background: #FEF3C7;
        border: 2px solid #F59E0B;
      }
      .hero-stamp-box {
        position: relative;
        width: 176px;
        height: 176px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: #ECFDF5;
        border-radius: 50%;
      }
      .ring-svg {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        transform: rotate(-90deg);
      }
      .ring-bg {
        fill: none;
        stroke: rgba(5, 150, 105, 0.18);
        stroke-width: 13;
      }
      .ring-fg {
        fill: none;
        stroke: #059669;
        stroke-width: 13;
        stroke-linecap: round;
        stroke-dasharray: 616;
        stroke-dashoffset: 616;
      }
      .stat-unit-bar {
        width: 100%;
        padding: 12px 24px;
        border-radius: 16px;
        background: #ECFDF5;
        border: 1.5px solid #6EE7B7;
      }
      .hero-title-wrap {
        width: 100%;
        padding: 4px 10px;
      }
      .hero-sub-wrap {
        width: 100%;
        padding: 18px 24px;
        background: #F8FAFC;
        border: 1.5px solid #CBD5E1;
        border-radius: 18px;
      }
      .section-head {
        margin-bottom: 18px;
        padding: 10px 22px;
        background: #ECFDF5;
        border-left: 9px solid #059669;
        border-radius: 0 16px 16px 0;
      }
      .compare-stack {
        display: flex;
        flex-direction: column;
        gap: 18px;
      }
      .comp-card {
        width: 100%;
        box-sizing: border-box;
        border-radius: 28px;
        padding: 28px 32px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        box-shadow: 0 14px 32px rgba(15, 23, 42, 0.1);
      }
      .wrong-card {
        background: #FFF5F5;
        border: 2.5px solid #F87171;
      }
      .right-card {
        background: #FFFFFF;
        border: 3.5px solid #059669;
      }
      .comp-pill {
        align-self: flex-start;
        padding: 8px 20px;
        border-radius: 12px;
      }
      .wrong-pill {
        background: #FEE2E2;
        border: 1.5px solid #EF4444;
      }
      .right-pill {
        background: #D1FAE5;
        border: 1.5px solid #059669;
      }
      .steps-stack {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      .step-card {
        width: 100%;
        box-sizing: border-box;
        background: #FFFFFF;
        border: 2.5px solid #CBD5E1;
        border-radius: 26px;
        padding: 24px 28px;
        display: flex;
        align-items: center;
        gap: 24px;
        box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
      }
      .step-badge {
        width: 124px;
        flex-shrink: 0;
        padding: 16px 0;
        border-radius: 16px;
        background: #064E3B;
      }
      .step-body {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .spotlight-card {
        background: #FFFFFF;
        border: 3.5px solid #D97706;
        border-radius: 34px;
        padding: 34px 36px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 18px;
        box-shadow: 0 20px 45px rgba(15, 23, 42, 0.12);
      }
      .shield-row {
        display: flex;
        align-items: center;
        gap: 18px;
      }
      .shield-wrap {
        width: 78px;
        height: 78px;
      }
      .shield-svg {
        width: 100%;
        height: 100%;
      }
      .shield-path {
        fill: #FEF3C7;
        stroke: #D97706;
        stroke-width: 6;
      }
      .shield-check {
        fill: none;
        stroke: #059669;
        stroke-width: 8;
        stroke-linecap: round;
        stroke-linejoin: round;
        stroke-dasharray: 100;
        stroke-dashoffset: 100;
      }
      .rule-badge-pill {
        padding: 10px 24px;
        border-radius: 14px;
        background: #FEF3C7;
        border: 2px solid #F59E0B;
      }
      .rule-pills {
        width: 100%;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .rpill {
        width: 100%;
        box-sizing: border-box;
        padding: 16px 24px;
        border-radius: 16px;
      }
      .rpill-1 {
        background: #ECFDF5;
        border: 2px solid #059669;
      }
      .rpill-2 {
        background: #EFF6FF;
        border: 2px solid #2563EB;
      }
      .checklist-stack {
        display: flex;
        flex-direction: column;
        gap: 14px;
        margin-bottom: 18px;
      }
      .check-row {
        width: 100%;
        box-sizing: border-box;
        background: #FFFFFF;
        border: 2.5px solid #059669;
        border-radius: 22px;
        padding: 20px 26px;
        display: flex;
        align-items: center;
        gap: 20px;
        box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
      }
      .check-icon {
        width: 48px;
        height: 48px;
        border-radius: 14px;
        background: #064E3B;
        color: #FEF08A;
        font-size: 25px;
        font-weight: 900;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }
      .check-text {
        flex: 1;
      }
      .cta-box {
        width: 100%;
        box-sizing: border-box;
        padding: 20px 28px;
        border-radius: 20px;
        background: #064E3B;
        border: 2.5px solid #D97706;
      }

      /* Lower Panoramic Photo Window */
      .cinema-viewport {
        position: absolute;
        top: 1030px;
        left: 48px;
        right: 48px;
        height: 406px;
        border-radius: 26px;
        overflow: hidden;
        border: 3.5px solid #D97706;
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.22);
        background: #1E293B;
      }
      .broll-slide {
        position: absolute;
        inset: 0;
        opacity: 0;
      }
      .broll-img-wrap {
        position: absolute;
        inset: 0;
        transform-origin: center center;
      }
      .cinema-vignette {
        position: absolute;
        inset: 0;
        background: linear-gradient(180deg, rgba(0,0,0,0.22) 0%, transparent 35%, rgba(0,0,0,0.68) 100%);
        pointer-events: none;
      }
      .cinema-top-tag {
        position: absolute;
        top: 14px;
        right: 16px;
        padding: 6px 16px;
        border-radius: 10px;
        background: rgba(6, 78, 59, 0.92);
        border: 1.5px solid #FDE047;
        color: #FEF08A;
        font-size: 16px;
        font-weight: 800;
      }
      .broll-caption-pill {
        position: absolute;
        bottom: 14px;
        left: 16px;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 18px;
        border-radius: 12px;
        background: rgba(15, 23, 42, 0.88);
        border: 1.5px solid #FDE047;
        z-index: 4;
      }
      .broll-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: #FDE047;
      }

      /* Bottom Broadcast News Ticker Subtitle Bar */
      .subtitle-zone {
        position: absolute;
        left: 48px;
        right: 48px;
        bottom: 126px;
        height: 230px;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .caption-card {
        position: absolute;
        inset: 0;
        background: #052E24;
        border: 3.5px solid #F59E0B;
        border-radius: 26px;
        padding: 22px 34px;
        display: none;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 12px;
        box-shadow: 0 20px 44px rgba(0, 0, 0, 0.45);
      }
      .cap-chip {
        padding: 7px 22px;
        border-radius: 10px;
        background: #FDE047;
      }
      .cap-line {
        width: 100%;
      }
    `;
  } else if (isVibe) {
    // =========================================================================
    // STYLE C: VIBE-TERMINAL (Part 3 · @yoon_autolab — Full-Bleed Cinema +
    // Floating Frosted-Glass macOS IDE / Terminal Window Overlay)
    // =========================================================================
    html = `
      <!-- FULL-SCREEN (1080x1920) GOOGLE FLOW CINEMA BACKGROUND -->
      <section class="fullscreen-cinema">
        ${brollElements
          .map(
            (_, idx) => `
          <div class="broll-slide" data-broll="${idx}">
            <div class="broll-img-wrap">{{broll-${idx}}}</div>
            <div class="broll-caption-pill">
              <span class="broll-dot"></span>
              {{scene-cap-${idx}}}
            </div>
          </div>`
          )
          .join("")}
        <div class="fullscreen-scrim"></div>
      </section>

      <!-- Top Floating macOS Terminal Bar -->
      <header class="topbar">
        <div class="mac-dots">
          <span class="mdot mdot-red"></span>
          <span class="mdot mdot-yellow"></span>
          <span class="mdot mdot-green"></span>
        </div>
        <div class="brand-name">{{channel-name}}</div>
        <div class="cat-chip">{{category-pill}}</div>
        <div class="progress-track"><div class="progress-fill"></div></div>
      </header>

      <div class="beat-dots">
        <span class="bdot" data-b="0"></span>
        <span class="bdot" data-b="1"></span>
        <span class="bdot" data-b="2"></span>
        <span class="bdot" data-b="3"></span>
        <span class="bdot" data-b="4"></span>
      </div>

      <!-- FLOATING FROSTED-GLASS macOS IDE WINDOW (top: 540px .. bottom: 378px) -->
      <main class="stage">
        <div class="ide-window-chrome">
          <div class="ide-dots">
            <span class="idot"></span><span class="idot"></span><span class="idot"></span>
          </div>
          <div class="ide-tab">⚡ hypit build main.svml --engine=google-flow-v2.1</div>
        </div>

        <!-- BEAT 1: TERMINAL HERO -->
        <section class="beat beat-0">
          <div class="hero-card">
            <div class="hero-badge-pill">{{hook-badge}}</div>
            <div class="hero-stat-ring">
              <svg class="ring-svg" viewBox="0 0 210 210">
                <circle class="ring-bg" cx="105" cy="105" r="88" />
                <circle class="ring-fg" cx="105" cy="105" r="88" />
              </svg>
              <div class="hero-stat-inner">
                <div class="stat-main">{{hook-stat}}</div>
              </div>
            </div>
            <div class="stat-unit-bar">{{hook-unit}}</div>
            <div class="hero-title-wrap">{{hook-title}}</div>
            <div class="hero-sub-wrap">{{hook-sub}}</div>
          </div>
        </section>

        <!-- BEAT 2: GIT DIFF STYLE COMPARISON (- LEGACY vs + VIBE CODING) -->
        <section class="beat beat-1">
          <div class="section-head">{{compare-heading}}</div>
          <div class="compare-stack">
            <div class="comp-card wrong-card">
              <div class="comp-pill wrong-pill">− {{wrong-label}}</div>
              <div class="comp-title">{{wrong-title}}</div>
              <div class="comp-desc">{{wrong-desc}}</div>
            </div>
            <div class="comp-card right-card">
              <div class="comp-pill right-pill">+ {{right-label}}</div>
              <div class="comp-title">{{right-title}}</div>
              <div class="comp-desc">{{right-desc}}</div>
            </div>
          </div>
        </section>

        <!-- BEAT 3: 3-STEP COMPILER PIPELINE -->
        <section class="beat beat-2">
          <div class="section-head">{{steps-heading}}</div>
          <div class="steps-stack">
            ${steps
              .map(
                (_, idx) => `
              <div class="step-card" data-step="${idx}">
                <div class="step-badge">{{step-badge-${idx}}}</div>
                <div class="step-body">
                  <div class="step-title">{{step-title-${idx}}}</div>
                  <div class="step-detail">{{step-detail-${idx}}}</div>
                </div>
              </div>`
              )
              .join("")}
          </div>
        </section>

        <!-- BEAT 4: 3-LAYER ARCHITECTURE HUD -->
        <section class="beat beat-3">
          <div class="spotlight-card">
            <div class="shield-row">
              <div class="shield-wrap">
                <svg viewBox="0 0 120 120" class="shield-svg">
                  <path class="shield-path" d="M60 12 L102 28 V58 C102 86 82 104 60 112 C38 104 18 86 18 58 V28 Z"/>
                  <path class="shield-check" d="M42 60 L55 73 L80 46"/>
                </svg>
              </div>
              <div class="rule-badge-pill">{{rule-badge}}</div>
            </div>
            <div class="rule-title-wrap">{{rule-title}}</div>
            <div class="rule-desc-wrap">{{rule-desc}}</div>
            <div class="rule-pills">
              <div class="rpill rpill-1">{{rule-pill1}}</div>
              <div class="rpill rpill-2">{{rule-pill2}}</div>
            </div>
          </div>
        </section>

        <!-- BEAT 5: DEPLOYMENT CHECKLIST -->
        <section class="beat beat-4">
          <div class="section-head">{{closing-heading}}</div>
          <div class="checklist-stack">
            <div class="check-row" data-check="0">
              <div class="check-icon">01</div>
              <div class="check-text">{{check-1}}</div>
            </div>
            <div class="check-row" data-check="1">
              <div class="check-icon">02</div>
              <div class="check-text">{{check-2}}</div>
            </div>
            <div class="check-row" data-check="2">
              <div class="check-icon">03</div>
              <div class="check-text">{{check-3}}</div>
            </div>
          </div>
          <div class="cta-box">{{cta-banner}}</div>
        </section>
      </main>

      <!-- BOTTOM NEON POP KARAOKE DOCK -->
      <footer class="subtitle-zone">
        ${captions
          .map(
            (_, idx) => `
          <div class="caption-card" data-cap="${idx}">
            <div class="cap-chip">{{cap-tag-${idx}}}</div>
            <div class="cap-line">{{cap-text-${idx}}}</div>
          </div>`
          )
          .join("")}
      </footer>
    `;

    css = `
      :scope {
        background: #080514;
        overflow: hidden;
        font-family: "Malgun Gothic", sans-serif;
      }
      .fullscreen-cinema {
        position: absolute;
        inset: 0;
        width: 1080px;
        height: 1920px;
        overflow: hidden;
      }
      .broll-slide {
        position: absolute;
        inset: 0;
        opacity: 0;
      }
      .broll-img-wrap {
        position: absolute;
        inset: 0;
        height: 680px;
        transform-origin: center center;
      }
      .fullscreen-scrim {
        position: absolute;
        inset: 0;
        background: linear-gradient(
          180deg,
          rgba(10, 6, 24, 0.48) 0%,
          rgba(10, 6, 24, 0.08) 18%,
          rgba(10, 6, 24, 0.22) 28%,
          rgba(12, 7, 28, 0.92) 36%,
          rgba(8, 5, 20, 0.98) 100%
        );
        pointer-events: none;
      }
      .broll-caption-pill {
        position: absolute;
        top: 472px;
        left: 52px;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 9px 22px;
        border-radius: 999px;
        background: rgba(18, 10, 38, 0.9);
        border: 1.5px solid rgba(232, 121, 249, 0.65);
        z-index: 6;
      }
      .broll-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: #E879F9;
        box-shadow: 0 0 10px #E879F9;
      }

      .topbar {
        position: absolute;
        top: 38px;
        left: 48px;
        right: 48px;
        height: 70px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 26px;
        background: rgba(15, 10, 34, 0.86);
        border: 1.5px solid rgba(168, 85, 247, 0.5);
        border-radius: 20px;
        backdrop-filter: blur(14px);
      }
      .mac-dots {
        display: flex;
        align-items: center;
        gap: 9px;
      }
      .mdot {
        width: 14px;
        height: 14px;
        border-radius: 50%;
      }
      .mdot-red { background: #FF5F56; }
      .mdot-yellow { background: #FFBD2E; }
      .mdot-green { background: #27C93F; }
      .cat-chip {
        padding: 7px 18px;
        border-radius: 999px;
        background: rgba(168, 85, 247, 0.24);
        border: 1px solid rgba(232, 121, 249, 0.55);
      }
      .progress-track {
        position: absolute;
        left: 18px;
        right: 18px;
        bottom: 0;
        height: 4px;
        background: rgba(255, 255, 255, 0.12);
        border-radius: 4px;
        overflow: hidden;
      }
      .progress-fill {
        height: 100%;
        width: 0%;
        background: linear-gradient(90deg, #E879F9, #38BDF8, #34D399);
      }
      .beat-dots {
        position: absolute;
        top: 120px;
        right: 54px;
        display: flex;
        gap: 10px;
      }
      .bdot {
        width: 34px;
        height: 7px;
        border-radius: 999px;
        background: rgba(232, 121, 249, 0.25);
      }

      /* Floating macOS IDE Window Stage */
      .stage {
        position: absolute;
        top: 540px;
        left: 48px;
        right: 48px;
        bottom: 376px;
        background: rgba(15, 11, 32, 0.88);
        border: 2px solid rgba(168, 85, 247, 0.55);
        border-radius: 32px;
        box-shadow: 0 26px 64px rgba(0, 0, 0, 0.75), 0 0 40px rgba(168, 85, 247, 0.2);
        overflow: hidden;
      }
      .ide-window-chrome {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 52px;
        background: rgba(28, 20, 56, 0.95);
        border-bottom: 1px solid rgba(168, 85, 247, 0.35);
        display: flex;
        align-items: center;
        padding: 0 24px;
        gap: 16px;
        z-index: 5;
      }
      .ide-dots {
        display: flex;
        gap: 7px;
      }
      .idot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: rgba(232, 121, 249, 0.5);
      }
      .ide-tab {
        color: #C4B5FD;
        font-size: 18px;
        font-weight: 700;
        font-family: Consolas, monospace;
      }
      .beat {
        position: absolute;
        top: 56px;
        left: 30px;
        right: 30px;
        bottom: 24px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        opacity: 0;
      }
      .hero-card {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        padding: 18px 20px;
      }
      .hero-badge-pill {
        padding: 9px 24px;
        border-radius: 999px;
        background: rgba(232, 121, 249, 0.16);
        border: 1.5px solid rgba(232, 121, 249, 0.55);
      }
      .hero-stat-ring {
        position: relative;
        width: 196px;
        height: 196px;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .ring-svg {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        transform: rotate(-90deg);
      }
      .ring-bg {
        fill: none;
        stroke: rgba(168, 85, 247, 0.2);
        stroke-width: 13;
      }
      .ring-fg {
        fill: none;
        stroke: #E879F9;
        stroke-width: 13;
        stroke-linecap: round;
        stroke-dasharray: 616;
        stroke-dashoffset: 616;
      }
      .stat-unit-bar {
        padding: 8px 22px;
        border-radius: 12px;
        background: rgba(56, 189, 248, 0.16);
        border: 1px solid rgba(56, 189, 248, 0.45);
      }
      .hero-title-wrap {
        width: 100%;
        padding: 0 8px;
      }
      .hero-sub-wrap {
        width: 100%;
        padding: 16px 22px;
        background: rgba(30, 22, 58, 0.85);
        border: 1px solid rgba(168, 85, 247, 0.35);
        border-radius: 18px;
      }
      .section-head {
        margin-bottom: 18px;
        padding-left: 18px;
        border-left: 7px solid #E879F9;
      }
      .compare-stack {
        display: flex;
        flex-direction: column;
        gap: 18px;
      }
      .comp-card {
        width: 100%;
        box-sizing: border-box;
        border-radius: 24px;
        padding: 24px 28px;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .wrong-card {
        background: rgba(58, 16, 34, 0.82);
        border: 2px solid rgba(251, 113, 133, 0.48);
      }
      .right-card {
        background: rgba(12, 52, 48, 0.9);
        border: 2.5px solid rgba(52, 211, 153, 0.72);
      }
      .comp-pill {
        align-self: flex-start;
        padding: 6px 18px;
        border-radius: 8px;
      }
      .wrong-pill {
        background: rgba(244, 63, 94, 0.24);
      }
      .right-pill {
        background: rgba(16, 185, 129, 0.26);
      }
      .steps-stack {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      .step-card {
        width: 100%;
        box-sizing: border-box;
        background: rgba(26, 18, 52, 0.92);
        border: 2px solid rgba(168, 85, 247, 0.38);
        border-radius: 22px;
        padding: 22px 26px;
        display: flex;
        align-items: center;
        gap: 22px;
      }
      .step-badge {
        width: 118px;
        flex-shrink: 0;
        padding: 14px 0;
        border-radius: 14px;
        background: linear-gradient(135deg, #E879F9, #38BDF8);
      }
      .step-body {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .spotlight-card {
        background: rgba(26, 18, 52, 0.9);
        border: 2px solid rgba(232, 121, 249, 0.55);
        border-radius: 28px;
        padding: 30px 30px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 18px;
      }
      .shield-row {
        display: flex;
        align-items: center;
        gap: 16px;
      }
      .shield-wrap {
        width: 74px;
        height: 74px;
      }
      .shield-svg {
        width: 100%;
        height: 100%;
      }
      .shield-path {
        fill: rgba(232, 121, 249, 0.16);
        stroke: #E879F9;
        stroke-width: 5;
      }
      .shield-check {
        fill: none;
        stroke: #38BDF8;
        stroke-width: 7;
        stroke-linecap: round;
        stroke-linejoin: round;
        stroke-dasharray: 100;
        stroke-dashoffset: 100;
      }
      .rule-badge-pill {
        padding: 9px 22px;
        border-radius: 999px;
        background: rgba(250, 204, 21, 0.18);
        border: 1.5px solid rgba(250, 204, 21, 0.55);
      }
      .rule-pills {
        width: 100%;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .rpill {
        width: 100%;
        box-sizing: border-box;
        padding: 16px 22px;
        border-radius: 16px;
      }
      .rpill-1 {
        background: rgba(16, 185, 129, 0.18);
        border: 1.5px solid rgba(52, 211, 153, 0.5);
      }
      .rpill-2 {
        background: rgba(232, 121, 249, 0.18);
        border: 1.5px solid rgba(232, 121, 249, 0.5);
      }
      .checklist-stack {
        display: flex;
        flex-direction: column;
        gap: 14px;
        margin-bottom: 16px;
      }
      .check-row {
        width: 100%;
        box-sizing: border-box;
        background: rgba(26, 18, 52, 0.92);
        border: 1.5px solid rgba(232, 121, 249, 0.45);
        border-radius: 20px;
        padding: 18px 24px;
        display: flex;
        align-items: center;
        gap: 18px;
      }
      .check-icon {
        width: 48px;
        height: 44px;
        border-radius: 12px;
        background: linear-gradient(135deg, #A855F7, #EC4899);
        color: #FFFFFF;
        font-size: 21px;
        font-weight: 900;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }
      .check-text {
        flex: 1;
      }
      .cta-box {
        width: 100%;
        box-sizing: border-box;
        padding: 18px 24px;
        border-radius: 18px;
        background: linear-gradient(90deg, rgba(88, 28, 135, 0.88), rgba(30, 58, 138, 0.88));
        border: 2px solid rgba(250, 204, 21, 0.6);
      }

      /* Bottom Neon Pop Karaoke Dock */
      .subtitle-zone {
        position: absolute;
        left: 48px;
        right: 48px;
        bottom: 128px;
        height: 224px;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .caption-card {
        position: absolute;
        inset: 0;
        background: rgba(12, 8, 28, 0.95);
        border: 2.5px solid #E879F9;
        border-radius: 28px;
        padding: 22px 34px;
        display: none;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 12px;
        box-shadow: 0 20px 50px rgba(0, 0, 0, 0.78), 0 0 28px rgba(232, 121, 249, 0.25);
      }
      .cap-chip {
        padding: 6px 20px;
        border-radius: 999px;
        background: linear-gradient(90deg, #F0ABFC, #38BDF8);
      }
      .cap-line {
        width: 100%;
      }
    `;
  } else {
    // =========================================================================
    // STYLE A: TECH-CYBER (Part 1 · @yoon_autolab — AI Agent Architecture Studio)
    // Deep Space Navy + Top Widescreen Cinema Viewport + Node Pipeline Stage
    // =========================================================================
    html = `
      <div class="ambient-glow"></div>
      <div class="bg-grid"></div>

      <header class="topbar">
        <div class="brand-chip">
          <span class="live-dot"></span>
          <div class="brand-name">{{channel-name}}</div>
        </div>
        <div class="cat-chip">{{category-pill}}</div>
        <div class="progress-track"><div class="progress-fill"></div></div>
      </header>

      <div class="beat-dots">
        <span class="bdot" data-b="0"></span>
        <span class="bdot" data-b="1"></span>
        <span class="bdot" data-b="2"></span>
        <span class="bdot" data-b="3"></span>
        <span class="bdot" data-b="4"></span>
      </div>

      <!-- GOOGLE FLOW AI MULTI-SCENE CINEMA VIEWPORT (top: 146px, height: 454px) -->
      <section class="cinema-viewport">
        ${brollElements
          .map(
            (_, idx) => `
          <div class="broll-slide" data-broll="${idx}">
            <div class="broll-img-wrap">{{broll-${idx}}}</div>
            <div class="broll-caption-pill">
              <span class="broll-dot"></span>
              {{scene-cap-${idx}}}
            </div>
          </div>`
          )
          .join("")}
        <div class="cinema-vignette"></div>
        <div class="cinema-top-tag">GOOGLE FLOW AI · NANO BANANA 2.1</div>
      </section>

      <!-- INTERACTIVE MOTION GRAPHIC STAGE (top: 618px .. bottom: 378px) -->
      <main class="stage">
        <section class="beat beat-0">
          <div class="hero-card">
            <div class="hero-badge-pill">{{hook-badge}}</div>
            <div class="hero-stat-ring">
              <svg class="ring-svg" viewBox="0 0 230 230">
                <circle class="ring-bg" cx="115" cy="115" r="98" />
                <circle class="ring-fg" cx="115" cy="115" r="98" />
              </svg>
              <div class="hero-stat-inner">
                <div class="stat-main">{{hook-stat}}</div>
              </div>
            </div>
            <div class="stat-unit-bar">{{hook-unit}}</div>
            <div class="hero-title-wrap">{{hook-title}}</div>
            <div class="hero-sub-wrap">{{hook-sub}}</div>
          </div>
        </section>

        <section class="beat beat-1">
          <div class="section-head">{{compare-heading}}</div>
          <div class="compare-stack">
            <div class="comp-card wrong-card">
              <div class="comp-pill wrong-pill">✕ {{wrong-label}}</div>
              <div class="comp-title">{{wrong-title}}</div>
              <div class="comp-desc">{{wrong-desc}}</div>
            </div>
            <div class="comp-card right-card">
              <div class="comp-pill right-pill">✓ {{right-label}}</div>
              <div class="comp-title">{{right-title}}</div>
              <div class="comp-desc">{{right-desc}}</div>
            </div>
          </div>
        </section>

        <section class="beat beat-2">
          <div class="section-head">{{steps-heading}}</div>
          <div class="steps-stack">
            ${steps
              .map(
                (_, idx) => `
              <div class="step-card" data-step="${idx}">
                <div class="step-badge">{{step-badge-${idx}}}</div>
                <div class="step-body">
                  <div class="step-title">{{step-title-${idx}}}</div>
                  <div class="step-detail">{{step-detail-${idx}}}</div>
                </div>
              </div>`
              )
              .join("")}
          </div>
        </section>

        <section class="beat beat-3">
          <div class="spotlight-card">
            <div class="shield-row">
              <div class="shield-wrap">
                <svg viewBox="0 0 120 120" class="shield-svg">
                  <path class="shield-path" d="M60 12 L102 28 V58 C102 86 82 104 60 112 C38 104 18 86 18 58 V28 Z"/>
                  <path class="shield-check" d="M42 60 L55 73 L80 46"/>
                </svg>
              </div>
              <div class="rule-badge-pill">{{rule-badge}}</div>
            </div>
            <div class="rule-title-wrap">{{rule-title}}</div>
            <div class="rule-desc-wrap">{{rule-desc}}</div>
            <div class="rule-pills">
              <div class="rpill rpill-1">{{rule-pill1}}</div>
              <div class="rpill rpill-2">{{rule-pill2}}</div>
            </div>
          </div>
        </section>

        <section class="beat beat-4">
          <div class="section-head">{{closing-heading}}</div>
          <div class="checklist-stack">
            <div class="check-row" data-check="0">
              <div class="check-icon">1</div>
              <div class="check-text">{{check-1}}</div>
            </div>
            <div class="check-row" data-check="1">
              <div class="check-icon">2</div>
              <div class="check-text">{{check-2}}</div>
            </div>
            <div class="check-row" data-check="2">
              <div class="check-icon">3</div>
              <div class="check-text">{{check-3}}</div>
            </div>
          </div>
          <div class="cta-box">{{cta-banner}}</div>
        </section>
      </main>

      <footer class="subtitle-zone">
        ${captions
          .map(
            (_, idx) => `
          <div class="caption-card" data-cap="${idx}">
            <div class="cap-chip">{{cap-tag-${idx}}}</div>
            <div class="cap-line">{{cap-text-${idx}}}</div>
          </div>`
          )
          .join("")}
      </footer>
    `;

    css = `
      :scope {
        background: #040814;
        overflow: hidden;
        font-family: "Malgun Gothic", sans-serif;
      }
      .ambient-glow {
        position: absolute;
        width: 820px;
        height: 820px;
        left: 130px;
        top: 520px;
        border-radius: 50%;
        background: radial-gradient(circle, ${options.accentColor || "rgba(56,189,248,0.22)"} 0%, rgba(15,23,42,0) 70%);
        pointer-events: none;
      }
      .bg-grid {
        position: absolute;
        inset: 0;
        background-image:
          linear-gradient(rgba(148, 163, 184, 0.04) 1px, transparent 1px),
          linear-gradient(90deg, rgba(148, 163, 184, 0.04) 1px, transparent 1px);
        background-size: 54px 54px;
        pointer-events: none;
      }
      .topbar {
        position: absolute;
        top: 40px;
        left: 52px;
        right: 52px;
        height: 70px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 26px;
        background: rgba(15, 23, 42, 0.9);
        border: 1.5px solid rgba(148, 163, 184, 0.28);
        border-radius: 20px;
      }
      .brand-chip {
        display: flex;
        align-items: center;
        gap: 12px;
      }
      .live-dot {
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: #10b981;
        box-shadow: 0 0 12px #10b981;
      }
      .cat-chip {
        padding: 7px 18px;
        border-radius: 999px;
        background: rgba(56, 189, 248, 0.16);
        border: 1px solid rgba(56, 189, 248, 0.42);
      }
      .progress-track {
        position: absolute;
        left: 18px;
        right: 18px;
        bottom: 0;
        height: 4px;
        background: rgba(255, 255, 255, 0.1);
        border-radius: 4px;
        overflow: hidden;
      }
      .progress-fill {
        height: 100%;
        width: 0%;
        background: linear-gradient(90deg, #38bdf8, #34d399, #fde047);
      }
      .beat-dots {
        position: absolute;
        top: 124px;
        left: 0;
        right: 0;
        display: flex;
        justify-content: center;
        gap: 12px;
      }
      .bdot {
        width: 42px;
        height: 7px;
        border-radius: 999px;
        background: rgba(148, 163, 184, 0.25);
      }
      .cinema-viewport {
        position: absolute;
        top: 146px;
        left: 52px;
        right: 52px;
        height: 454px;
        border-radius: 28px;
        overflow: hidden;
        border: 2.5px solid rgba(56, 189, 248, 0.55);
        box-shadow: 0 22px 52px rgba(0, 0, 0, 0.68), 0 0 34px rgba(37, 99, 235, 0.25);
        background: #091224;
      }
      .broll-slide {
        position: absolute;
        inset: 0;
        opacity: 0;
      }
      .broll-img-wrap {
        position: absolute;
        inset: 0;
        transform-origin: center center;
      }
      .cinema-vignette {
        position: absolute;
        inset: 0;
        background: linear-gradient(
          180deg,
          rgba(4, 8, 20, 0.35) 0%,
          rgba(4, 8, 20, 0.0) 30%,
          rgba(4, 8, 20, 0.0) 62%,
          rgba(4, 8, 20, 0.78) 100%
        );
        pointer-events: none;
      }
      .cinema-top-tag {
        position: absolute;
        top: 16px;
        right: 18px;
        padding: 6px 16px;
        border-radius: 999px;
        background: rgba(15, 23, 42, 0.86);
        border: 1.5px solid rgba(56, 189, 248, 0.55);
        color: #7dd3fc;
        font-size: 16px;
        font-weight: 800;
        letter-spacing: 0.05em;
      }
      .broll-caption-pill {
        position: absolute;
        bottom: 16px;
        left: 18px;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 20px;
        border-radius: 999px;
        background: rgba(15, 23, 42, 0.88);
        border: 1.5px solid rgba(250, 204, 21, 0.6);
        z-index: 4;
      }
      .broll-dot {
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: #fde047;
        box-shadow: 0 0 8px #fde047;
      }
      .stage {
        position: absolute;
        top: 618px;
        left: 52px;
        right: 52px;
        bottom: 378px;
      }
      .beat {
        position: absolute;
        inset: 0;
        display: flex;
        flex-direction: column;
        justify-content: center;
        opacity: 0;
      }
      .hero-card {
        background: rgba(15, 23, 42, 0.92);
        border: 2px solid rgba(56, 189, 248, 0.45);
        border-radius: 34px;
        padding: 34px 38px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 18px;
        box-shadow: 0 24px 54px rgba(0, 0, 0, 0.55);
      }
      .hero-badge-pill {
        padding: 10px 26px;
        border-radius: 999px;
        background: rgba(250, 204, 21, 0.16);
        border: 1.5px solid rgba(250, 204, 21, 0.5);
      }
      .hero-stat-ring {
        position: relative;
        width: 210px;
        height: 210px;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .ring-svg {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        transform: rotate(-90deg);
      }
      .ring-bg {
        fill: none;
        stroke: rgba(148, 163, 184, 0.16);
        stroke-width: 13;
      }
      .ring-fg {
        fill: none;
        stroke: #38bdf8;
        stroke-width: 13;
        stroke-linecap: round;
        stroke-dasharray: 616;
        stroke-dashoffset: 616;
      }
      .hero-stat-inner {
        display: flex;
        flex-direction: column;
        align-items: center;
      }
      .stat-unit-bar {
        padding: 8px 22px;
        border-radius: 999px;
        background: rgba(37, 99, 235, 0.22);
        border: 1px solid rgba(56, 189, 248, 0.42);
      }
      .hero-title-wrap {
        width: 100%;
        padding: 0 10px;
      }
      .hero-sub-wrap {
        width: 100%;
        padding: 16px 22px;
        background: rgba(30, 41, 59, 0.76);
        border-radius: 18px;
      }
      .section-head {
        margin-bottom: 20px;
        padding-left: 18px;
        border-left: 7px solid #38bdf8;
      }
      .compare-stack {
        display: flex;
        flex-direction: column;
        gap: 20px;
      }
      .comp-card {
        width: 100%;
        box-sizing: border-box;
        border-radius: 28px;
        padding: 28px 32px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        box-shadow: 0 18px 42px rgba(0, 0, 0, 0.45);
      }
      .wrong-card {
        background: rgba(42, 18, 28, 0.9);
        border: 2px solid rgba(248, 113, 113, 0.45);
      }
      .right-card {
        background: rgba(10, 46, 42, 0.94);
        border: 2.5px solid rgba(52, 211, 153, 0.68);
      }
      .comp-pill {
        align-self: flex-start;
        padding: 7px 18px;
        border-radius: 999px;
      }
      .wrong-pill {
        background: rgba(239, 68, 68, 0.22);
        border: 1px solid rgba(248, 113, 113, 0.5);
      }
      .right-pill {
        background: rgba(16, 185, 129, 0.24);
        border: 1px solid rgba(52, 211, 153, 0.58);
      }
      .steps-stack {
        display: flex;
        flex-direction: column;
        gap: 18px;
      }
      .step-card {
        width: 100%;
        box-sizing: border-box;
        background: rgba(15, 23, 42, 0.92);
        border: 2px solid rgba(148, 163, 184, 0.28);
        border-radius: 26px;
        padding: 24px 28px;
        display: flex;
        align-items: center;
        gap: 24px;
        box-shadow: 0 14px 34px rgba(0, 0, 0, 0.42);
      }
      .step-badge {
        width: 122px;
        flex-shrink: 0;
        padding: 14px 0;
        border-radius: 16px;
        background: linear-gradient(135deg, #38bdf8, #34d399);
      }
      .step-body {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .spotlight-card {
        background: rgba(15, 23, 42, 0.94);
        border: 2.5px solid rgba(250, 204, 21, 0.55);
        border-radius: 34px;
        padding: 36px 36px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 20px;
        box-shadow: 0 24px 54px rgba(0, 0, 0, 0.55);
      }
      .shield-row {
        display: flex;
        align-items: center;
        gap: 18px;
      }
      .shield-wrap {
        width: 82px;
        height: 82px;
      }
      .shield-svg {
        width: 100%;
        height: 100%;
      }
      .shield-path {
        fill: rgba(56, 189, 248, 0.16);
        stroke: #38bdf8;
        stroke-width: 5;
      }
      .shield-check {
        fill: none;
        stroke: #fde047;
        stroke-width: 7;
        stroke-linecap: round;
        stroke-linejoin: round;
        stroke-dasharray: 100;
        stroke-dashoffset: 100;
      }
      .rule-badge-pill {
        padding: 10px 24px;
        border-radius: 999px;
        background: rgba(250, 204, 21, 0.18);
        border: 1.5px solid rgba(250, 204, 21, 0.52);
      }
      .rule-pills {
        width: 100%;
        display: flex;
        flex-direction: column;
        gap: 14px;
      }
      .rpill {
        width: 100%;
        box-sizing: border-box;
        padding: 18px 24px;
        border-radius: 18px;
      }
      .rpill-1 {
        background: rgba(16, 185, 129, 0.18);
        border: 1.5px solid rgba(52, 211, 153, 0.48);
      }
      .rpill-2 {
        background: rgba(56, 189, 248, 0.18);
        border: 1.5px solid rgba(56, 189, 248, 0.48);
      }
      .checklist-stack {
        display: flex;
        flex-direction: column;
        gap: 16px;
        margin-bottom: 20px;
      }
      .check-row {
        width: 100%;
        box-sizing: border-box;
        background: rgba(15, 23, 42, 0.92);
        border: 2px solid rgba(52, 211, 153, 0.45);
        border-radius: 24px;
        padding: 22px 28px;
        display: flex;
        align-items: center;
        gap: 20px;
      }
      .check-icon {
        width: 46px;
        height: 46px;
        border-radius: 50%;
        background: linear-gradient(135deg, #10b981, #059669);
        color: #ffffff;
        font-size: 24px;
        font-weight: 800;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }
      .check-text {
        flex: 1;
      }
      .cta-box {
        width: 100%;
        box-sizing: border-box;
        padding: 20px 28px;
        border-radius: 22px;
        background: linear-gradient(90deg, rgba(30,58,138,0.88), rgba(15,23,42,0.92));
        border: 2px solid rgba(250, 204, 21, 0.58);
      }
      .subtitle-zone {
        position: absolute;
        left: 52px;
        right: 52px;
        bottom: 132px;
        height: 224px;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .caption-card {
        position: absolute;
        inset: 0;
        background: rgba(7, 12, 24, 0.94);
        border: 2px solid rgba(56, 189, 248, 0.52);
        border-radius: 28px;
        padding: 22px 34px;
        display: none;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 12px;
        box-shadow: 0 20px 48px rgba(0, 0, 0, 0.68);
      }
      .cap-chip {
        padding: 6px 20px;
        border-radius: 999px;
        background: linear-gradient(90deg, #fde047, #38bdf8);
      }
      .cap-line {
        width: 100%;
      }
    `;
  }

  const program = htmlVisual({
    html,
    css,
    data: {
      totalFrames,
      beatFrames: [0, beat2Frame, beat3Frame, beat4Frame, beat5Frame],
      stepFrames,
      captionSpans,
      themeMode,
    },
    setup: `
      const brollSlides = [...root.querySelectorAll('.broll-slide')];
      const brollWraps = [...root.querySelectorAll('.broll-img-wrap')];
      const progFill = root.querySelector('.progress-fill');
      const bdots = [...root.querySelectorAll('.bdot')];
      const beats = [0, 1, 2, 3, 4].map(i => root.querySelector('.beat-' + i));
      const ringFg = root.querySelector('.ring-fg');
      const wrongCard = root.querySelector('.wrong-card');
      const rightCard = root.querySelector('.right-card');
      const stepCards = [...root.querySelectorAll('.step-card')];
      const shieldCheck = root.querySelector('.shield-check');
      const checkRows = [...root.querySelectorAll('.check-row')];
      const capCards = [...root.querySelectorAll('.caption-card')];

      const isSenior = data.themeMode === 'senior-editorial';
      const isVibe = data.themeMode === 'vibe-terminal';
      const easeOutCubic = t => 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 3);

      return frame => {
        const progress = Math.max(0, Math.min(1, frame / data.totalFrames));
        progFill.style.width = (progress * 100).toFixed(2) + '%';

        // Determine active Beat (0..4)
        let activeBeat = 0;
        for (let i = 0; i < data.beatFrames.length; i++) {
          if (frame >= data.beatFrames[i]) activeBeat = i;
        }

        // Google Flow Cinema Viewport: Crossfade + Ken Burns per Beat
        brollSlides.forEach((slide, idx) => {
          if (idx !== activeBeat) {
            slide.style.opacity = '0';
          } else {
            const bStart = data.beatFrames[idx];
            const bEnd = idx + 1 < data.beatFrames.length ? data.beatFrames[idx + 1] : data.totalFrames;
            const bSpan = Math.max(30, bEnd - bStart);
            const localAge = Math.max(0, frame - bStart);
            const fade = easeOutCubic(localAge / 12);
            const kb = Math.min(1, localAge / bSpan);
            const scale = 1.0 + kb * 0.11;
            const panX = (idx % 2 === 0 ? -1 : 1) * kb * 16;
            const panY = -kb * 10;
            slide.style.opacity = String(fade);
            if (brollWraps[idx]) {
              brollWraps[idx].style.transform =
                'scale(' + scale.toFixed(4) + ') translate(' + panX.toFixed(1) + 'px, ' + panY.toFixed(1) + 'px)';
            }
          }
        });

        const activeDotColor = isSenior ? '#059669' : (isVibe ? '#E879F9' : '#38bdf8');
        const pastDotColor = isSenior ? '#D97706' : (isVibe ? 'rgba(56,189,248,0.7)' : 'rgba(52,211,153,0.65)');
        const idleDotColor = isSenior ? 'rgba(6,78,59,0.2)' : 'rgba(148,163,184,0.25)';

        bdots.forEach((dot, idx) => {
          dot.style.background = idx === activeBeat ? activeDotColor : (idx < activeBeat ? pastDotColor : idleDotColor);
          dot.style.transform = idx === activeBeat ? 'scaleX(1.3)' : 'scaleX(1)';
        });

        beats.forEach((el, idx) => {
          if (idx !== activeBeat) {
            el.style.opacity = '0';
            el.style.pointerEvents = 'none';
            el.style.transform = 'translateY(-16px) scale(0.97)';
          } else {
            const localAge = frame - data.beatFrames[idx];
            const p = easeOutCubic(localAge / 14);
            el.style.opacity = String(p);
            el.style.transform = 'translateY(' + ((1 - p) * 24).toFixed(1) + 'px) scale(' + (0.96 + 0.04 * p).toFixed(3) + ')';
          }
        });

        // Beat 0: Animated SVG ring progress
        if (activeBeat === 0 && ringFg) {
          const rp = easeOutCubic((frame - data.beatFrames[0]) / 36);
          ringFg.style.strokeDashoffset = String((616 * (1 - rp * 0.86)).toFixed(1));
        }

        // Beat 1: Myth vs Fact staggered comparison
        if (activeBeat === 1) {
          const age = frame - data.beatFrames[1];
          const p1 = easeOutCubic(age / 14);
          const p2 = easeOutCubic((age - 34) / 16);
          wrongCard.style.opacity = String(age >= 34 ? (isSenior ? 0.85 : 0.68) : p1);
          wrongCard.style.transform = 'translateY(' + ((1 - p1) * 18).toFixed(1) + 'px) scale(' + (age >= 34 ? 0.98 : 1).toFixed(3) + ')';
          rightCard.style.opacity = String(p2);
          rightCard.style.transform = 'translateY(' + ((1 - p2) * 24).toFixed(1) + 'px) scale(' + (0.95 + 0.05 * p2).toFixed(3) + ')';
        }

        // Beat 2: 3-Step progressive reveal & active glow
        if (activeBeat === 2) {
          let currentStep = 0;
          stepCards.forEach((card, idx) => {
            const sFrame = data.stepFrames[idx] ?? data.beatFrames[2] + idx * 45;
            if (frame >= sFrame) currentStep = idx;
          });
          stepCards.forEach((card, idx) => {
            const sFrame = data.stepFrames[idx] ?? data.beatFrames[2] + idx * 45;
            const age = frame - sFrame;
            if (age < 0) {
              card.style.opacity = isSenior ? '0.32' : '0.18';
              card.style.transform = 'translateX(-18px) scale(0.96)';
              card.style.borderColor = isSenior ? '#CBD5E1' : 'rgba(148,163,184,0.18)';
            } else {
              const p = easeOutCubic(age / 14);
              const isCurrent = idx === currentStep;
              card.style.opacity = String(isCurrent ? 1 : (isSenior ? 0.9 : 0.82));
              card.style.transform = 'translateX(' + ((1 - p) * 20).toFixed(1) + 'px) scale(' + (isCurrent ? 1.02 : 0.98).toFixed(3) + ')';
              card.style.borderColor = isCurrent
                ? (isSenior ? '#059669' : (isVibe ? '#E879F9' : '#38bdf8'))
                : (isSenior ? '#94A3B8' : 'rgba(52,211,153,0.48)');
            }
          });
        }

        // Beat 3: Shield checkmark draw animation
        if (activeBeat === 3 && shieldCheck) {
          const sp = easeOutCubic((frame - data.beatFrames[3] - 8) / 24);
          shieldCheck.style.strokeDashoffset = String((100 * (1 - sp)).toFixed(1));
        }

        // Beat 4: Staggered 3-point checklist
        if (activeBeat === 4) {
          const bAge = frame - data.beatFrames[4];
          checkRows.forEach((row, idx) => {
            const cp = easeOutCubic((bAge - idx * 14) / 14);
            row.style.opacity = String(cp);
            row.style.transform = 'translateX(' + ((1 - cp) * 22).toFixed(1) + 'px)';
          });
        }

        // Active Spoken Subtitle Card
        let activeCap = 0;
        for (let i = 0; i < data.captionSpans.length; i++) {
          const span = data.captionSpans[i];
          if (frame >= span.start && frame < span.end) {
            activeCap = i;
            break;
          }
          if (frame >= span.start) activeCap = i;
        }
        capCards.forEach((card, idx) => {
          if (idx !== activeCap) {
            card.style.display = 'none';
          } else {
            card.style.display = 'flex';
            const cAge = frame - data.captionSpans[idx].start;
            const cp = easeOutCubic(cAge / 8);
            card.style.opacity = String(cp);
            card.style.transform = 'translateY(' + ((1 - cp) * 10).toFixed(1) + 'px)';
          }
        });
      };
    `,
  });

  return sealVisualTrack({
    id: options.id,
    timelineId: timeline.id,
    visualIr: "hypit.visual-ir@1",
    presents: [
      {
        id: options.id,
        order: 0,
        z: 0,
        span: window.span,
        elements: [
          {
            id: "shorts-root",
            kind: "program",
            order: 0,
            program,
            style: [
              { name: "position", value: "absolute" },
              { name: "left", value: `${within.xPx}px` },
              { name: "top", value: `${within.yPx}px` },
              { name: "width", value: `${within.widthPx}px` },
              { name: "height", value: `${within.heightPx}px` },
            ],
          },
          ...brollElements,
          ...textChildren,
        ],
      },
    ],
  });
}
