import { assertAttributes, assertEmptyElement, createMarkupSurfaceFacet, textAttribute } from "@hypit/hypit/markup";
import { canonicalize, sameType } from "@hypit/hypit/protocol";
import { blobTypes } from "@hypit/hypit/blob";
import { sealGraphFragment } from "@hypit/hypit/author";
import { createAdmissionPackageFacet } from "@hypit/hypit/admission";
import { createProducerPackageFacet } from "@hypit/hypit/producer";
import { compositionTypes } from "@hypit/composition";
import { mediaTypes } from "@hypit/media";
import { timelineTypes } from "@hypit/timeline";
import { spatialTypes } from "@hypit/spatial";
import { assertTemporalInstantFor, temporalTypes } from "@hypit/temporal";
import {
  resolveTemporalInstantReference,
  resolveTemporalWindowReference,
  resolveTemporalContext,
  temporalContextAttributeVocabulary,
  temporalInstantAttributeNames,
  temporalInstantAttributeVocabulary,
  temporalWindowAttributeNames,
  temporalWindowAttributeVocabulary,
} from "@hypit/temporal/markup";
import { renderShortsScene } from "./render.js";

const module = { name: "@barolab/shorts-scene", version: "1" };

const types = Object.fromEntries(
  ["Options", "Step", "Steps", "Caption", "Captions", "Beats"].map((name) => [name, { module, name }])
);

const producers = Object.fromEntries(
  ["emptySteps", "appendStep", "emptyCaptions", "appendCaption", "packBeats", "render"].map((name) => [
    name,
    { module, name },
  ])
);

export const manifest = {
  format: "hypit.module@1",
  ...module,
  dependencies: [
    compositionTypes.visualTrack,
    mediaTypes.fontStack,
    blobTypes.blob,
    timelineTypes.timeline,
    spatialTypes.frame,
    temporalTypes.instant,
  ].map((type) => ({ module: type.module })),
  types: Object.values(types).map((type) => ({ name: type.name })),
  capabilities: [],
  producers: [
    { name: "emptySteps", inputs: [], outputs: [{ name: "steps", type: types.Steps }], needs: [] },
    {
      name: "appendStep",
      inputs: [
        { name: "steps", type: types.Steps },
        { name: "step", type: types.Step },
        { name: "at", type: temporalTypes.instant },
        { name: "timeline", type: timelineTypes.timeline },
      ],
      outputs: [{ name: "steps", type: types.Steps }],
      needs: [],
    },
    { name: "emptyCaptions", inputs: [], outputs: [{ name: "captions", type: types.Captions }], needs: [] },
    {
      name: "appendCaption",
      inputs: [
        { name: "captions", type: types.Captions },
        { name: "caption", type: types.Caption },
        { name: "at", type: temporalTypes.instant },
        { name: "timeline", type: timelineTypes.timeline },
      ],
      outputs: [{ name: "captions", type: types.Captions }],
      needs: [],
    },
    {
      name: "packBeats",
      inputs: [
        { name: "compare", type: temporalTypes.instant },
        { name: "steps", type: temporalTypes.instant },
        { name: "rule", type: temporalTypes.instant },
        { name: "closing", type: temporalTypes.instant },
      ],
      outputs: [{ name: "beats", type: types.Beats }],
      needs: [],
    },
    {
      name: "render",
      inputs: [
        { name: "timeline", type: timelineTypes.timeline },
        { name: "within", type: spatialTypes.frame },
        { name: "window", type: temporalTypes.window },
        { name: "fontBold", type: mediaTypes.fontStack },
        { name: "fontRegular", type: mediaTypes.fontStack },
        { name: "bgBeat1", type: blobTypes.blob },
        { name: "bgBeat2", type: blobTypes.blob },
        { name: "bgBeat3", type: blobTypes.blob },
        { name: "bgBeat4", type: blobTypes.blob },
        { name: "bgBeat5", type: blobTypes.blob },
        { name: "steps", type: types.Steps },
        { name: "captions", type: types.Captions },
        { name: "beats", type: types.Beats },
        { name: "options", type: types.Options },
      ],
      outputs: [{ name: "visual", type: compositionTypes.visualTrack }],
      needs: [],
    },
  ],
};

const inline = (record) => {
  if (record?.value.kind !== "inline") throw new Error("ShortsScene inputs must be inline values.");
  return record.value.value;
};

const blob = (record) => {
  if (record?.value.kind !== "blob") throw new Error("ShortsScene bgImage must be a Blob.");
  return record.value;
};

const value = (data) => ({ kind: "inline", value: canonicalize(data) });

const component = {
  producers: [
    { producer: producers.emptySteps, handler: () => ({ outputs: { steps: value([]) }, needs: {} }) },
    {
      producer: producers.appendStep,
      handler: ({ inputs }) => {
        const step = inline(inputs.step);
        const at = inline(inputs.at);
        const steps = inline(inputs.steps);
        assertTemporalInstantFor(at, { subjectId: step.id, timeline: inline(inputs.timeline) });
        return { outputs: { steps: value([...steps, { ...step, at }]) }, needs: {} };
      },
    },
    { producer: producers.emptyCaptions, handler: () => ({ outputs: { captions: value([]) }, needs: {} }) },
    {
      producer: producers.appendCaption,
      handler: ({ inputs }) => {
        const caption = inline(inputs.caption);
        const at = inline(inputs.at);
        const captions = inline(inputs.captions);
        assertTemporalInstantFor(at, { subjectId: caption.id, timeline: inline(inputs.timeline) });
        return { outputs: { captions: value([...captions, { ...caption, at }]) }, needs: {} };
      },
    },
    {
      producer: producers.packBeats,
      handler: ({ inputs }) => {
        const compare = inline(inputs.compare);
        const steps = inline(inputs.steps);
        const rule = inline(inputs.rule);
        const closing = inline(inputs.closing);
        return {
          outputs: {
            beats: value({
              compareFrame: compare.frame,
              stepsFrame: steps.frame,
              ruleFrame: rule.frame,
              closingFrame: closing.frame,
            }),
          },
          needs: {},
        };
      },
    },
    {
      producer: producers.render,
      handler: ({ inputs }) => ({
        outputs: {
          visual: value(
            renderShortsScene(
              inline(inputs.timeline),
              inline(inputs.within),
              inline(inputs.window),
              inline(inputs.fontBold),
              inline(inputs.fontRegular),
              [
                blob(inputs.bgBeat1),
                blob(inputs.bgBeat2),
                blob(inputs.bgBeat3),
                blob(inputs.bgBeat4),
                blob(inputs.bgBeat5),
              ],
              inline(inputs.steps),
              inline(inputs.captions),
              inline(inputs.beats),
              inline(inputs.options)
            )
          ),
        },
        needs: {},
      }),
    },
  ],
};

const optionAttrMap = {
  "theme-mode": "themeMode",
  "channel-name": "channelName",
  "category-pill": "categoryPill",
  "accent-color": "accentColor",
  "scene1-caption": "scene1Caption",
  "scene2-caption": "scene2Caption",
  "scene3-caption": "scene3Caption",
  "scene4-caption": "scene4Caption",
  "scene5-caption": "scene5Caption",
  "hook-badge": "hookBadge",
  "hook-stat": "hookStat",
  "hook-unit": "hookUnit",
  "hook-title": "hookTitle",
  "hook-sub": "hookSub",
  "compare-title": "compareTitle",
  "wrong-label": "wrongLabel",
  "wrong-title": "wrongTitle",
  "wrong-desc": "wrongDesc",
  "right-label": "rightLabel",
  "right-title": "rightTitle",
  "right-desc": "rightDesc",
  "steps-title": "stepsTitle",
  "rule-badge": "ruleBadge",
  "rule-title": "ruleTitle",
  "rule-desc": "ruleDesc",
  "rule-pill1": "rulePill1",
  "rule-pill2": "rulePill2",
  "closing-title": "closingTitle",
  "check1": "check1",
  "check2": "check2",
  "check3": "check3",
  "cta-banner": "ctaBanner",
};

export const decodeSurface = ({ element, resolveReference }) => {
  const allowedAttrs = [
    "id",
    "timeline",
    "within",
    "font-bold",
    "font-regular",
    "bg-beat1",
    "bg-beat2",
    "bg-beat3",
    "bg-beat4",
    "bg-beat5",
    "beat-compare",
    "beat-steps",
    "beat-rule",
    "beat-closing",
    ...Object.keys(optionAttrMap),
    ...temporalWindowAttributeNames,
  ];
  assertAttributes(element, allowedAttrs);
  const id = textAttribute(element, "id");
  const context = resolveTemporalContext({ element, resolveReference });
  const window = resolveTemporalWindowReference({ element, resolveReference });

  const reference = (name, type) => {
    const raw = element.attributes[name];
    if (typeof raw !== "object" || raw.kind !== "reference") throw new Error(`${name} must be a reference.`);
    const found = resolveReference(raw.path);
    if (found === undefined || !sameType(found.type, type)) throw new Error(`${name} has the wrong Type.`);
    return found;
  };

  const beatCompare = resolveTemporalInstantReference({ element, resolveReference, attribute: "beat-compare" });
  const beatSteps = resolveTemporalInstantReference({ element, resolveReference, attribute: "beat-steps" });
  const beatRule = resolveTemporalInstantReference({ element, resolveReference, attribute: "beat-rule" });
  const beatClosing = resolveTemporalInstantReference({ element, resolveReference, attribute: "beat-closing" });

  const options = { id };
  for (const [attr, prop] of Object.entries(optionAttrMap)) {
    options[prop] = element.attributes[attr] ? textAttribute(element, attr) : "";
  }

  const records = [{ id: `${id}.options`, type: types.Options, value: value(options), range: element.range }];
  const inputs = [
    { name: "timeline", type: timelineTypes.timeline },
    { name: "within", type: spatialTypes.frame },
    { name: "window", type: temporalTypes.window },
    { name: "fontBold", type: mediaTypes.fontStack },
    { name: "fontRegular", type: mediaTypes.fontStack },
    { name: "bgBeat1", type: blobTypes.blob },
    { name: "bgBeat2", type: blobTypes.blob },
    { name: "bgBeat3", type: blobTypes.blob },
    { name: "bgBeat4", type: blobTypes.blob },
    { name: "bgBeat5", type: blobTypes.blob },
    { name: "beatCompare", type: temporalTypes.instant },
    { name: "beatSteps", type: temporalTypes.instant },
    { name: "beatRule", type: temporalTypes.instant },
    { name: "beatClosing", type: temporalTypes.instant },
    { name: "options", type: types.Options },
  ];

  const bindings = {
    timeline: context.timeline.ref,
    within: reference("within", spatialTypes.frame).ref,
    window: window.ref,
    fontBold: reference("font-bold", mediaTypes.fontStack).ref,
    fontRegular: reference("font-regular", mediaTypes.fontStack).ref,
    bgBeat1: reference("bg-beat1", blobTypes.blob).ref,
    bgBeat2: reference("bg-beat2", blobTypes.blob).ref,
    bgBeat3: reference("bg-beat3", blobTypes.blob).ref,
    bgBeat4: reference("bg-beat4", blobTypes.blob).ref,
    bgBeat5: reference("bg-beat5", blobTypes.blob).ref,
    beatCompare: beatCompare.ref,
    beatSteps: beatSteps.ref,
    beatRule: beatRule.ref,
    beatClosing: beatClosing.ref,
    options: { kind: "record", id: `${id}.options` },
  };

  const input = (name) => ({ kind: "fragment-input", name });
  const operation = (name) => ({ kind: "fragment-operation", operation: name });

  const operations = [
    { id: "emptySteps", producer: producers.emptySteps, inputs: {}, result: { kind: "output", name: "steps" } },
    { id: "emptyCaptions", producer: producers.emptyCaptions, inputs: {}, result: { kind: "output", name: "captions" } },
    {
      id: "packBeats",
      producer: producers.packBeats,
      inputs: {
        compare: input("beatCompare"),
        steps: input("beatSteps"),
        rule: input("beatRule"),
        closing: input("beatClosing"),
      },
      result: { kind: "output", name: "beats" },
    },
  ];

  let prevSteps = "emptySteps";
  let prevCaptions = "emptyCaptions";
  let stepIdx = 0;
  let capIdx = 0;

  for (const child of element.children) {
    if (child.kind === "text") {
      if (child.value.trim()) throw new Error("Shorts Scene accepts Step and Caption children only.");
      continue;
    }
    const tag = child.name.split(":").at(-1);
    if (tag === "Step") {
      assertAttributes(child, ["id", "badge", "title", "detail", ...temporalInstantAttributeNames]);
      assertEmptyElement(child);
      const at = resolveTemporalInstantReference({ element: child, resolveReference });
      const key = `step-${++stepIdx}`;
      records.push({
        id: `${id}.${key}`,
        type: types.Step,
        value: value({
          id: textAttribute(child, "id"),
          badge: textAttribute(child, "badge"),
          title: textAttribute(child, "title"),
          detail: textAttribute(child, "detail"),
        }),
        range: child.range,
      });
      inputs.push({ name: key, type: types.Step }, { name: `${key}-at`, type: temporalTypes.instant });
      bindings[key] = { kind: "record", id: `${id}.${key}` };
      bindings[`${key}-at`] = at.ref;
      operations.push({
        id: key,
        producer: producers.appendStep,
        inputs: {
          steps: operation(prevSteps),
          step: input(key),
          at: input(`${key}-at`),
          timeline: input("timeline"),
        },
        result: { kind: "output", name: "steps" },
      });
      prevSteps = key;
    } else if (tag === "Caption") {
      assertAttributes(child, ["id", "text", "highlight", ...temporalInstantAttributeNames]);
      assertEmptyElement(child);
      const at = resolveTemporalInstantReference({ element: child, resolveReference });
      const key = `caption-${++capIdx}`;
      records.push({
        id: `${id}.${key}`,
        type: types.Caption,
        value: value({
          id: textAttribute(child, "id"),
          text: textAttribute(child, "text"),
          highlight: textAttribute(child, "highlight"),
        }),
        range: child.range,
      });
      inputs.push({ name: key, type: types.Caption }, { name: `${key}-at`, type: temporalTypes.instant });
      bindings[key] = { kind: "record", id: `${id}.${key}` };
      bindings[`${key}-at`] = at.ref;
      operations.push({
        id: key,
        producer: producers.appendCaption,
        inputs: {
          captions: operation(prevCaptions),
          caption: input(key),
          at: input(`${key}-at`),
          timeline: input("timeline"),
        },
        result: { kind: "output", name: "captions" },
      });
      prevCaptions = key;
    } else {
      throw new Error(`Unsupported child tag ${tag} in Shorts Scene.`);
    }
  }

  operations.push({
    id: "render",
    producer: producers.render,
    inputs: {
      timeline: input("timeline"),
      within: input("within"),
      window: input("window"),
      fontBold: input("fontBold"),
      fontRegular: input("fontRegular"),
      bgBeat1: input("bgBeat1"),
      bgBeat2: input("bgBeat2"),
      bgBeat3: input("bgBeat3"),
      bgBeat4: input("bgBeat4"),
      bgBeat5: input("bgBeat5"),
      steps: operation(prevSteps),
      captions: operation(prevCaptions),
      beats: operation("packBeats"),
      options: input("options"),
    },
    result: { kind: "output", name: "visual" },
  });

  const fragment = sealGraphFragment({
    inputs,
    operations,
    exports: [{ name: "visual", type: compositionTypes.visualTrack, root: operation("render") }],
  });

  return {
    records,
    fragments: [fragment],
    components: [
      {
        id,
        fragment: fragment.id,
        inputs: bindings,
        outputs: { visual: `${id}.visual` },
        range: element.range,
      },
    ],
    exports: [`${id}.visual`],
  };
};

const declaration = {
  name: "scene",
  tag: "Scene",
  mode: "structured",
  outputs: [compositionTypes.visualTrack, ...Object.values(types)],
  vocabulary: {
    summary: "5-Beat Korean Vertical Shorts Scene with 5 Google Flow Cinema Visuals, Comparison, Progressive Steps, Spotlight, and Word-Synced Captions.",
    attributes: [
      ...temporalContextAttributeVocabulary,
      ...temporalWindowAttributeVocabulary,
      ...[
        "id",
        "within",
        "font-bold",
        "font-regular",
        "bg-beat1",
        "bg-beat2",
        "bg-beat3",
        "bg-beat4",
        "bg-beat5",
        "beat-compare",
        "beat-steps",
        "beat-rule",
        "beat-closing",
      ].map((name) => ({ name, kind: "expression", required: true, summary: name })),
      ...Object.keys(optionAttrMap).map((name) => ({ name, kind: "literal", required: false, summary: name })),
    ],
    children: [
      {
        tag: "Step",
        cardinality: "many",
        summary: "One progressive action step card.",
        attributes: [
          ...["id", "badge", "title", "detail"].map((name) => ({ name, kind: "literal", required: true, summary: name })),
          ...temporalInstantAttributeVocabulary,
        ],
      },
      {
        tag: "Caption",
        cardinality: "many",
        summary: "One spoken subtitle phrase synced to an authored Instant.",
        attributes: [
          ...["id", "text", "highlight"].map((name) => ({ name, kind: "literal", required: true, summary: name })),
          ...temporalInstantAttributeVocabulary,
        ],
      },
    ],
    ports: [{ name: "visual", type: compositionTypes.visualTrack, summary: "The complete 5-beat vertical Short VisualTrack." }],
    example: '<shorts:Scene id="scene" timeline={animation.timeline} within={canvas.bounds} during={animation.window} ... />',
  },
};

export const hypitPackage = {
  format: "hypit.package@1",
  modules: [{ manifest }],
  facets: [
    createProducerPackageFacet(component),
    createAdmissionPackageFacet(component),
    createMarkupSurfaceFacet({ module, declaration, handler: decodeSurface }),
  ],
};

export default hypitPackage;
