# Schematic Review MVP — Execution Plan & Status Tracker

Update this file as work lands — flip `[ ]` to `[x]`, move items between
sections, add dated notes under each workstream. This is meant to be the
single place that reflects real state, not the original design doc
(`Schematic_Crop_Review_MVP_Plan.md`), which stays as the architectural
reference and shouldn't need to change.

**Status legend:** `[x]` done · `[~]` in progress · `[ ]` not started · `[!]` blocked / needs decision

---

## MVP goal

Given a customer schematic crop (+ optional question, + optional supporting
document), support two grounded scenarios:

- **Scenario A — Explain this schematic.** Identify every component/net,
  explain its function and specification, cited against the HDG.
- **Scenario B — What's missing.** Diff the extracted schematic against a
  parsed reference schematic (device-level), flag absent required
  components, cited against the HDG.

Both scenarios reuse the same extraction pipeline, the same ingested HDG
knowledge base, and the same net-resolution step. Neither requires new PDF
ingestion work — that layer is already built.

---

## Foundation (already built, confirmed working)

- [x] `SemanticSchematicExtractor` — crop → components/nodes/connections JSON
      (Mistral vision, JSON mode, key-mismatch repair, bbox rescaling)
- [x] Geometry cross-check — OpenCV wire detection validates extracted bboxes
      independently of the LLM (`geometry.py`, tuned Hough params)
- [x] HDG fully ingested into `CanonicalDocument` — sections, prose, tables,
      table rows, figures, equations, all with page/bbox/hash traceability
      (`data/canonical/TLE987x_6x_rev1.1.json`)
- [x] Retrieval units built at row/table/prose/figure/equation granularity,
      domain-tagged per section (`unit_builder.py`), two chunking variants
      benchmarked (`eval/retrieval/retrieval_benchmark_report.json`)
- [x] Hybrid retriever (dense + BM25 + RRF) live over the above
- [x] Pin map — `data/pinout_map/tle987x_pinout.json`: pin_number/name →
      function → domain, for all 48 pins
- [x] Every HDG figure and table already extracted to standalone images
      (`data/figures/*.png`), including the full application schematics
      (`fig_2_application_schemati.png`, `fig_3_application_schemati.png`)

---

## Workstream 1 — Ingestion fixes (small, unblocks accuracy)

- [ ] **Footnote linkage.** `table_extractor.py` doesn't attach trailing
      "Notes:" prose to the table it follows — currently a disconnected
      `ProseBlock`. Fix so footnotes travel with their table's retrieval
      unit(s). *(Needed before Scenario A can reliably surface conditional
      caveats like the VDDP-vs-VDDC ferrite bead note.)*
- [ ] **Exact-symbol/pin lookup path.** `QueryType.exact_symbol` exists in
      `retrieval_schema.py` but `hybrid_retriever.py` has no dedicated
      exact-match index — symbol/pin queries currently ride the same
      fuzzy hybrid path as everything else. Add a direct dict lookup over
      the pinout map + table `Symbol` columns, checked before falling back
      to hybrid search.

**Owner:** _unassigned_ · **Notes:** _—_

---

## Workstream 2 — Net resolution (shared by both scenarios)

- [ ] Build `resolve_net(component, connections, pinout_map) -> (type, function, domain)`
      — for a named device pin, look up `pinout_map`; for a
      customer-created net, walk `connections[]` to the nearest resolvable
      pin/net.
- [ ] Unit test against the VS/VDDP/VDDC crop and the schematic-portion
      block diagram already used in earlier extraction testing.

**Owner:** _unassigned_ · **Notes:** this is the single most load-bearing
piece — both scenarios' retrieval quality depends on it.

---

## Workstream 3 — Reference schematic (structural ground truth)

- [x] Run `semantic_extractor.py` once on `fig_2_application_schemati.png`
      (TLE987x) and once on `fig_3_application_schemati.png`
      (TLE987x-2QX) → structural JSON per device variant.
- [x] Human review pass on both outputs — raw JSONs written to
      `data/reference_schematics/tle987x_raw.json` and `tle987x_2qx_raw.json`.
- [x] Join reference JSON components to HDG Table 3 by exact `Symbol` match.
      TLE987x: 68 components, 5 matched · TLE987x-2QX: 48 components, 8 matched.
- [x] Stored as `data/reference_schematics/tle987x.json` /
      `tle987x_2qx.json`, versioned alongside HDG rev 1.1.

**Owner:** _Aditya_ · **Notes:** Script: `scripts/build_reference_schematics.py`.
Low match count on full TLE987x schematic expected — gate-drive MOSFETs and
gate resistors (R_GH*, T1-T6) are not in Table 3 BOM.

---

## Workstream 4 — Scenario A: "Explain this schematic"

- [x] Wire: crop → extraction → net resolution (WS2) → one retrieval query
      per resolved `(type, function, domain)` → domain-filtered hybrid
      search for `table_row` + `section_prose` units.
- [ ] Compose per-component explanation with citation (section/page).
- [ ] Roll individual component explanations into one coherent narrative
      response.
- [ ] Test against the VS/VDDP/VDDC crop end-to-end.

**Owner:** _unassigned_ · **Notes:** _—_

---

## Workstream 5 — Scenario B: "What's missing"

- [ ] Depends on WS3 (reference JSON) and WS2 (net resolution).
- [ ] Build required-nets diff: for each node in the reference, check the
      extracted schematic has a matching component type present.
- [ ] Wire in customer supporting-document scoping (skip flagging nets the
      customer's doc says aren't used) — read per-request, not ingested
      into the shared KB.
- [ ] Compose findings with citation to the specific table row that
      justified each "required" flag.
- [ ] Test against a deliberately incomplete crop (e.g. remove one cap
      from a known-good crop) to confirm true positives.

**Owner:** _unassigned_ · **Notes:** structural topology checks (is the
block in the right *order*) stay explicitly out of MVP scope — this
workstream is presence-only.

---

## Explicitly out of scope for this MVP pass

- Full topology/placement ordering checks (FR-017) — presence-only diff
  for now.
- Multi-page / full-schematic orchestration.
- Intent/request classifier.
- Native EDA file (Altium/KiCad/Cadence) parsing.
- Volt AI integration.

---

## Open questions still needing an answer (see prior discussion for full context)

- [ ] Confidence threshold for FR-016 escalation to a human reviewer —
      not yet defined.
- [ ] Does Decision Logging (FR-015) need to redact customer schematic
      content, per the data-isolation NFR?
- [ ] Canonical document list per device family beyond this one HDG
      (datasheet, other app notes) — who maintains it?
- [ ] Pilot success metric that gates expansion beyond TLE987x.

---

## Update log

| Date | Workstream | Change |
|---|---|---|
| 2026-08-21 | WS3 | `scripts/build_reference_schematics.py` written and run. All 4 reference files written to `data/reference_schematics/`. TLE987x: 68 comps / 5 HDG-matched. TLE987x-2QX: 48 comps / 8 HDG-matched. |

2. Log the ingestion bug, don't chase it today

The Table 6 → wrong-section (2.3 instead of 2.4) issue is a table_extractor.py/unit_builder.py problem, not a WS4 problem — it's actually the same class of bug as the footnote-linkage issue you already flagged under Workstream 1 ("table boundaries not tracked correctly"). Add a line to WS1 or Open Questions rather than fixing it right now — fixing ingestion mid-demo-prep is a rabbit hole, and WS4's job (compose + cite) is doing exactly what it should with the evidence it was given.

| 2026-08-21 | WS4 | explain_service.py + explain_crop wired end-to-end. Validated
against PMU block-diagram crop (VDDP/VDDC/VDDEXT decoupling): correct direct_pin
resolution, correct citations, correctly declined VDDEXT capacitor spec (not in
HDG). Found: (1) Table 6 section-number mislabeled 2.3 vs 2.4 in ingestion — logged
under WS1; (2) reference_evidence source_text truncation too aggressive for
auditing — fixed. |