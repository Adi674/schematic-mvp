**MVP Phase Plan — Cropped Schematic Image Review**

**Purpose.** Define the next implementation phase after the
reference-ingestion/RAG MVP: review a cropped portion of a schematic,
identify the functional section from extracted electrical facts, obtain
confirmation when needed, run the relevant checklist, retrieve
authoritative hardware-design evidence, and produce traceable findings.
The design must remain reusable for later full-schematic and
multi-section expansion.

**Current baseline:** Canonical hardware-design document + hybrid
retrieval (dense + BM25 + RRF) are already implemented. RAG tuning is
intentionally frozen for this phase except for defects that block the
schematic workflow.

# 1. MVP Decision

- Scope only cropped schematic image input for the first schematic MVP.
  A crop may represent a complete functional sub-circuit or only a
  partial view of one.

- Do not add a request/intent classifier in this phase. The API can
  assume the request is a schematic-review request. Leave a clean
  extension point for an intent/router layer in a later phase.

- Use Mistral Small 4 as the primary multimodal model for visual
  extraction and structured interpretation. It supports image input and
  structured outputs; use low/no reasoning for fast extraction and a
  higher reasoning setting only for ambiguity resolution if needed.

- Use deterministic post-processing and validation around the model. The
  model must not be the sole authority for electrical connectivity.

- Use the existing knowledge/retrieval layer for section candidate
  scoring and reference evidence. Do not hard-code engineering limits
  into the parser.

- Create one generic structural checklist for this MVP. It should define
  what evidence must be extracted and verified, not invent
  product-specific numeric limits. Product/reference-specific
  requirements come from the hardware-design document.

# 2. Target MVP Workflow

> Cropped Schematic Image  
> ↓  
> Image validation / preprocessing  
> ↓  
> Multimodal extraction (Mistral Small 4)  
> ↓  
> Structured schematic facts  
> ↓  
> Deterministic validation + confidence scoring  
> ↓  
> Section candidate generation  
> ↓  
> KB / retrieval-based section evidence  
> ↓  
> High-confidence section OR user confirmation  
> ↓  
> Select section checklist  
> ↓  
> Targeted fact extraction / verification  
> ↓  
> Retrieve hardware-design reference evidence  
> ↓  
> Compare extracted facts against reference  
> ↓  
> Findings + evidence + confidence + coverage

# 3. In-Scope and Out-of-Scope

**In scope**

- PNG/JPG crop as the primary MVP input.

- One crop per review request.

- Component/reference/value extraction where visible.

- Pin and signal-label extraction where visible.

- Basic wire/junction/connectivity interpretation.

- Functional section candidate identification from extracted facts.

- User confirmation for ambiguous section identification.

- Generic checklist-driven evidence collection.

- Reference retrieval from the existing canonical hardware-design
  knowledge base.

- Traceable findings that cite the relevant reference section/table/page
  when available.

- Explicit handling of uncertain or non-observable facts in a crop.

**Out of scope for this phase**

- Full-schematic multi-page orchestration.

- Automatic request/intent classification.

- Native Altium/KiCad/Cadence schematic-file parsing.

- PCB/layout review.

- A complete product-specific rule engine.

- Large-scale deterministic symbol-library recognition for every EDA
  tool.

- Replacing the existing RAG architecture or re-optimizing the full
  retrieval benchmark.

# 4. Architecture Principles

- Facts first, reasoning second: extract observable schematic facts
  before asking the knowledge layer to interpret them.

- Connectivity over proximity: “C15 is near VDDP” is not equivalent to
  “C15 is electrically connected to VDDP.”

- No fabricated components: if extraction fails, return empty/uncertain
  fields rather than dummy components or inferred values presented as
  facts.

- Confidence is first-class data. Every important extracted entity and
  relationship should carry confidence and evidence coordinates when
  possible.

- Partial input is not proof of absence. If a required item is outside
  the crop or not observable, the result should be NOT_CHECKED /
  INSUFFICIENT_INPUT, not FAIL.

- Knowledge is the source of engineering truth. Check definitions say
  what to verify; the hardware-design reference supplies the actual
  requirement, range, condition, recommendation, or exception.

- Keep the schematic layer independent of the knowledge backend so the
  MVP can use RAG and the later product can use Volt AI without
  rewriting the parser.

# 5. Schematic Extraction Contract

The first parser output should be a stable JSON contract. Keep it small
enough to validate manually, but rich enough to support section
detection and checklist execution.

> {  
> "schema_version": "0.1",  
> "input": {  
> "image_id": "...",  
> "width": 0,  
> "height": 0,  
> "crop_scope": "partial"  
> },  
> "device_context": {  
> "device": "TLE987x",  
> "confidence": 0.0  
> },  
> "components": \[  
> {  
> "ref": "C15",  
> "type": "capacitor",  
> "value": "100 nF",  
> "bbox": \[x1, y1, x2, y2\],  
> "confidence": 0.0  
> }  
> \],  
> "pins": \[  
> {  
> "component_ref": "U1",  
> "pin_number": "...",  
> "pin_name": "VDDP",  
> "bbox": \[...\],  
> "confidence": 0.0  
> }  
> \],  
> "nets": \[  
> {  
> "name": "VDDP",  
> "confidence": 0.0  
> }  
> \],  
> "connections": \[  
> {  
> "from": "C15.1",  
> "to_net": "VDDP",  
> "evidence": {"bbox": \[...\], "confidence": 0.0}  
> }  
> \],  
> "labels": \[\],  
> "uncertainties": \[\]  
> }

# 6. Multimodal Extraction Strategy

Primary model: Mistral Small 4. Mistral states that Small 4 accepts text
and image inputs, supports structured outputs, and provides a 256k
context window. It is available through the Mistral API and has an open
Apache 2.0 release. These capabilities make it a reasonable primary
model for the first extraction pipeline. (Source: Mistral AI,
Introducing Mistral Small 4; Mistral Small 4 model card.)

Recommended extraction sequence

- Pass the crop image plus a strict extraction schema.

- Instruct the model to report only visible evidence and to use
  null/unknown when information is not readable.

- Require bounding boxes for components, labels, pins, and other
  evidence-bearing objects whenever the model can provide them.

- Separate observation from interpretation. Example: “text VDDP is
  visible” is an observation; “this is the VDDP supply section” is an
  interpretation and belongs to the next stage.

- Run deterministic validation on the JSON: duplicate references,
  impossible pin references, malformed values, missing required fields,
  and contradictory connections.

- Optionally run a second multimodal verification call on only ambiguous
  regions instead of reprocessing the whole crop.

**Optional OCR augmentation.** Mistral OCR can process images and return
structured blocks, bounding boxes and confidence information; its
annotation capability can also produce schema-constrained JSON. This
makes it a useful optional text/coordinate layer if Small 4 misses small
labels or values. Do not add it to the mandatory path until the base
extractor is benchmarked.

Source note: Mistral OCR documentation and Mistral Document Annotations
documentation.

**Optional external challenger.** If API access is available, benchmark
one vision-capable Gemini API model as a challenger on the same fixed
crop set. Gemini supports image input and structured visual tasks,
including object-detection/segmentation capabilities on supported
models. Keep this as an evaluation branch, not a production dependency
for the MVP.

# 7. Section Identification from Extracted Facts

Do not classify the section directly from the raw image as the primary
method. First build a compact “section evidence packet” from the
extraction output.

> Section evidence packet  
> - device / part number  
> - high-confidence component refs and types  
> - visible values  
> - named pins  
> - named nets / labels  
> - high-confidence connections  
> - local component neighborhood  
> - unresolved / uncertain objects

Send this packet to the existing knowledge layer with a constrained
task: rank likely functional sections and explain the evidence for each
candidate. The output should be structured.

> {  
> "candidates": \[  
> {  
> "section": "VDDP supply / decoupling",  
> "confidence": 0.94,  
> "evidence": \[  
> "U1.VDDP visible",  
> "C15 and C16 connected to VDDP/GND"  
> \]  
> }  
> \],  
> "needs_confirmation": false  
> }

Suggested MVP decision policy: high confidence may be auto-selected;
medium confidence requires confirmation; low confidence requires user
selection or more input. Thresholds must be calibrated from the
evaluation set rather than treated as permanent engineering limits.

# 8. General MVP Checklist

For this phase, create one generic checklist that is product-agnostic at
the structural level. Its job is to define the evidence to collect and
the questions to route to the reference knowledge base. It must not
invent numeric requirements.

| **Area**                          | **What to verify from crop**                                        | **Reference/KB question**                                            | **Typical result states**               |
|-----------------------------------|---------------------------------------------------------------------|----------------------------------------------------------------------|-----------------------------------------|
| 1\. Input & scope                 | Is the crop readable? Are all needed boundaries/evidence visible?   | What can/cannot be assessed from the supplied scope?                 | PASS / NOT_CHECKED / INSUFFICIENT_INPUT |
| 2\. Component identity            | Reference designator, type/symbol, visible value/part number        | Is this component the expected component for the identified section? | PASS / FAIL / NEEDS_REVIEW              |
| 3\. Pin identity                  | Pin number/name and associated device pin                           | What is the reference requirement for this pin in this section?      | PASS / FAIL / NEEDS_REVIEW              |
| 4\. Connectivity                  | Pin-to-net and component-to-net relationships                       | What connections are required or prohibited?                         | PASS / FAIL / NOT_CHECKED               |
| 5\. Power / ground                | Visible supply and ground relationships                             | What supply/ground topology is required?                             | PASS / FAIL / NOT_CHECKED               |
| 6\. Supporting passives           | Resistors, capacitors, inductors, protection parts and values       | What supporting component types/ranges/recommendations apply?        | PASS / FAIL / WARNING                   |
| 7\. Section-specific requirements | Evidence needed for the selected functional section                 | What conditions, exceptions and recommendations apply?               | PASS / FAIL / WARNING / N/A             |
| 8\. Evidence & confidence         | Does every finding have source/evidence coordinates and confidence? | Can the reference requirement and schematic evidence be traced?      | PASS / NEEDS_REVIEW                     |

Important: this checklist is the MVP framework. Once the target section
is confirmed, the system can narrow it to the checks that actually
apply. A future product/device-specific checklist layer will map these
generic check concepts to exact TLE987x/6x requirements and conditions
extracted from the hardware-design guideline.

# 9. Reference Comparison Contract

The review engine should pass a normalized packet to the
knowledge/reasoning layer rather than the raw image.

> {  
> "section": "VDDP supply / decoupling",  
> "device": "TLE987x",  
> "check": "supporting capacitor requirement",  
> "observed_facts": {  
> "components": \[...\],  
> "connections": \[...\],  
> "values": \[...\]  
> },  
> "input_scope": "partial",  
> "confidence": 0.93  
> }

The knowledge layer should return:

- authoritative requirement text or normalized requirement statement;

- applicability conditions and exceptions;

- source section/table/page;

- comparison interpretation: PASS / FAIL / WARNING / NOT_CHECKED /
  NOT_APPLICABLE;

- a concise engineering explanation grounded in the returned evidence.

# 10. Partial-Crop Safety Rules

- Never infer absence from the crop boundary. The missing object may
  simply be outside the supplied image.

- Never fabricate components, values, pins, or connections when
  extraction fails.

- A low-confidence connection must not become a hard FAIL without
  verification.

- If a checklist item requires evidence not visible in the crop, return
  NOT_CHECKED or INSUFFICIENT_INPUT.

- Every finding should include: check_id, observed facts, result state,
  confidence, schematic evidence location, and reference evidence
  location.

- Keep the raw multimodal response for debugging/evaluation, but use
  only validated JSON downstream.

# 11. Evaluation Dataset and Metrics

Create a small golden dataset before tuning prompts. Start with 15–25
cropped regions covering easy, medium and ambiguous cases. Each crop
should have manually verified ground truth.

| **Metric**                     | **Definition**                                            | **MVP target**                       |
|--------------------------------|-----------------------------------------------------------|--------------------------------------|
| Component precision / recall   | Correct visible components detected                       | ≥ 95% on curated golden set          |
| Value accuracy                 | Correct reading/normalization of visible values           | ≥ 95%                                |
| Pin identity accuracy          | Correct pin number/name association                       | ≥ 95% where visible                  |
| Connectivity accuracy          | Correct pin/net/component relationships                   | ≥ 90% initially; improve iteratively |
| Section top-1 accuracy         | Correct section selected or ranked first                  | ≥ 90%                                |
| Section confirmation precision | High-confidence auto-selections that are actually correct | ≥ 95%                                |
| Hallucination rate             | Facts reported without visible evidence                   | Target near 0%                       |
| Traceability coverage          | Findings with schematic + reference evidence              | 100%                                 |

These are engineering targets for the MVP benchmark, not guaranteed
performance claims. The golden set should be expanded before using any
threshold as a release gate.

# 12. Implementation Phases for Antigravity

## Phase 0 — Repo reconnaissance

- Locate the current FastAPI/RAG service, schemas, configuration, and
  existing document/reference APIs.

- Identify how image files are currently uploaded or mounted.

- Do not modify the existing RAG ingestion/retrieval path unless
  required for integration.

- Create a dedicated schematic module/package so the implementation
  remains separable.

## Phase 1 — Crop ingestion + preprocessing

- Accept one PNG/JPG crop.

- Validate size, format, readability heuristics, and orientation.

- Store image_id, dimensions, hash, and original file reference.

- Optionally create a resized working copy while preserving the original
  image.

## Phase 2 — Mistral Small 4 extraction

- Implement the multimodal call with a strict JSON schema.

- Prompt for visible facts only.

- Require null/unknown rather than guessing.

- Capture raw response, parsed JSON, latency, and model metadata for
  evaluation.

- Add deterministic JSON validation and confidence normalization.

## Phase 3 — Extraction verification

- Run consistency checks on duplicate refs, pin formats, values, and
  impossible connections.

- Add an optional second vision call for ambiguous regions only.

- Do not auto-correct uncertain facts silently; mark them uncertain.

## Phase 4 — Section candidate generation

- Build the section evidence packet.

- Query the existing KB/reference retrieval layer for likely section
  concepts.

- Return ranked candidates, confidence, and evidence.

- Apply provisional confidence policy for auto-select vs confirmation.

## Phase 5 — Confirmation

- For ambiguous cases, expose the top section candidates and evidence to
  the caller/UI.

- Accept explicit section selection.

- Persist the selected section in the review context.

## Phase 6 — Generic checklist execution

- Implement the eight-area MVP checklist defined in this plan.

- Generate only the evidence requests/checks applicable to the selected
  section and visible scope.

- Return NOT_CHECKED / INSUFFICIENT_INPUT rather than false failures.

## Phase 7 — Reference comparison

- Pass normalized observed facts + check definition to the existing
  retrieval layer.

- Generate grounded findings with source section/table/page.

- Keep reference evidence separate from extracted schematic evidence.

## Phase 8 — Evaluation and freeze

- Run the golden crop benchmark.

- Compare component, value, pin, connectivity, section-classification,
  hallucination, and traceability metrics.

- Freeze the MVP extraction contract and do not expand scope until the
  baseline is stable.

# 13. Suggested API Shape

> POST /schematic/review/crop  
>   
> Request  
> - image  
> - optional device_hint  
> - optional selected_section  
>   
> Response  
> {  
> "review_id": "...",  
> "extraction": {...},  
> "section_candidates": \[...\],  
> "selected_section": null,  
> "needs_confirmation": true,  
> "check_results": \[\],  
> "findings": \[\]  
> }

Keep selected_section optional. When omitted, the system performs
section candidate generation. When supplied, the system skips candidate
confirmation and proceeds with the selected section.

# 14. Future Expansion Hooks (Do Not Implement Now)

- Intent/request classifier before the schematic review route.

- Full-schematic multi-page parsing.

- Hierarchical sheet and cross-page net resolution.

- Native EDA file parsers.

- Product/device/variant-specific checklist registry.

- Volt AI as a pluggable knowledge/reasoning backend.

- Cross-checking schematic facts against PCB/layout facts.

- Review coverage dashboards and batch processing.

# 15. Definition of Done for This MVP Phase

- A single cropped schematic image can be submitted through an API.

- The system returns validated structured schematic facts with
  confidence and evidence locations.

- The system can produce ranked functional-section candidates from those
  facts.

- Ambiguous section classification can be explicitly confirmed by the
  caller.

- The confirmed section activates the generic MVP checklist rather than
  a full-device checklist.

- The system retrieves relevant hardware-design reference evidence for
  the active checks.

- Findings explicitly distinguish PASS, FAIL, WARNING, NOT_CHECKED,
  NOT_APPLICABLE, and INSUFFICIENT_INPUT.

- No fabricated schematic facts are emitted as confirmed observations.

- Every finding is traceable to both schematic evidence and reference
  evidence.

- A golden crop benchmark exists and establishes the baseline
  extraction/section-classification quality.

- No intent classifier is required or implemented in this phase, but the
  API/module boundaries do not prevent adding one later.

# 16. Recommended Model Strategy Summary

| **Role**                 | **MVP choice**                        | **Optional challenger**   | **When to use**                                                  |
|--------------------------|---------------------------------------|---------------------------|------------------------------------------------------------------|
| Primary visual extractor | Mistral Small 4                       | Gemini vision-capable API | Default path for crop → structured facts                         |
| OCR / text augmentation  | Mistral OCR                           | Other OCR only if needed  | Use when small labels/values are missed by the primary extractor |
| Section reasoning        | Existing KB + current reasoning model | Alternative model later   | Rank section candidates from structured facts                    |
| Reference comparison     | Existing RAG baseline                 | Volt AI later             | Use authoritative hardware-design evidence for findings          |

**Current-source verification:** Mistral Small 4 is an active 2026 model
with native image input and structured-output support; Mistral OCR
supports image/PDF OCR, bounding boxes, confidence scores, and
schema-constrained annotations. Gemini provides a viable external vision
benchmark if API access is available.
