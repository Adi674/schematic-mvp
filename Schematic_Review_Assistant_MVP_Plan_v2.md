# Hardware Schematic Review Assistant — MVP Implementation Plan (v2)

*Supersedes the prior version. Changes in this revision are summarized in Section 0.1.*

## 0. Scope Lock

- **Chip family**: TLE987x/6x only (single hardware design guideline PDF as source KB)
- **Inputs supported**: (a) text-only question, (b) text question + schematic image
- **MVP priority**: build and prove the **schematic-checkable pipeline first** — extraction → normalize → rule engine — since that's the differentiated, harder part. Checklist taxonomy work is explicitly deferred (see Section 11); don't spend MVP time formalizing it yet.
- **Comparison strategy**: deterministic rule engine only — no external fine-tuned model (Volt AI) in the loop for MVP; comparison/verdict logic is 100% manual rules + code
- **Orchestration**: LangGraph (stateful pipeline) + LangChain (retrievers, document loaders, vector store wrappers)
- **LLM**: Mistral Small (multimodal) for extraction + composition only — never for the actual PASS/FAIL comparison
- **Explicitly out of scope for MVP**: Volt AI integration, multi-chip generalization, multi-page hierarchical schematics, fully automated rule extraction without human review, fine-tuning any model, formal checklist taxonomy (Section 11), layout/PCB-level checks (Chapter 15 of the source doc — not verifiable from a schematic image at all)

### 0.1 Changes in this revision

- Router now decides among **three** paths, not two: exact rule lookup, RAG semantic search, schematic extraction (previously RAG vs. extraction only)
- Rules KB and RAG vector store are now explicitly linked via `source_chunk_id` on each rule, so a rule engine verdict can pull its exact explanatory context without a fresh semantic search
- Checklist taxonomy (what complete list of checks a full schematic review runs) is called out as a **deferred, undecided item** — not built into MVP scope
- MVP build order re-prioritized: schematic pipeline (extraction/normalize/rule engine) comes before polishing the RAG-only conversational path
- **Section-Based Vector Chunking & Metadata Filtering**: RAG chunks are partitioned by Document Chapter (Chapters 1–15) and tagged with `domain` (e.g. `PGU`, `GPIO`, `BRIDGE_DRIVER`, `CHARGE_PUMP`). RAG searches use domain metadata filtering to eliminate cross-chapter false retrievals.
- **Multi-Component & Inter-Component Relational Rules**: Rule DB supports 3 categories (`single_static`, `pair_ratio`, `system_budget`) to model dependencies like shared current limits ($I_{DDP} + I_{DDEXT} \le 110\text{ mA}$) and gate cap ratios ($C_{GD} / C_{GS} \le 0.1$).
- **Structured Rule Creation Workflow**: PDF tables + text constraints $\rightarrow$ `data/rules/rules_source.json` $\rightarrow$ Pydantic validation & `seed_rules_db.py` $\rightarrow$ SQLite `rules.db`.

---

## 1. Why Three Routes, Not One Comparison Mechanism

Each route solves a structurally different problem — this isn't a performance optimization, it's a correctness requirement:

| Route | Handles | Why it must be separate |
|---|---|---|
| **Exact rule lookup** | Question names a symbol/pin directly | `rules.db` lookup is deterministic and unambiguous; running this through vector search first risks retrieving an adjacent, similar-but-wrong chunk (e.g. VDDC table instead of VDDP) |
| **RAG semantic search** | Fuzzy or conceptual questions ("why," "what cap near LIN") | `rules.db` has no prose reasoning — only numbers. Any explanatory question structurally requires retrieval over the actual document text |
| **Extraction** | Image attached | A fundamentally different modality — no text-based mechanism can read a schematic. Only route that produces *new* structured data rather than retrieving existing content |

A single question can trigger more than one route (e.g. an uploaded schematic with a "why does this matter" question needs Extraction *and* RAG together) — routes are not mutually exclusive, they merge at the Composer.

---

## 2. Architecture (LangGraph State Graph)

```
                         ┌───────────────────────┐
                         │   Entry: User Input     │
                         │ (question, image?)      │
                         └───────────┬─────────────┘
                                     │
                         ┌───────────▼─────────────┐
                         │  Node: Router             │
                         │  (exact match, search,    │
                         │   or extract — can be     │
                         │   more than one)          │
                         └──┬───────────┬─────────┬──┘
                            │           │         │
              named symbol  │  fuzzy/why│         │ image present
                            │           │         │
                 ┌──────────▼──┐ ┌──────▼──────┐ ┌▼──────────────────┐
                 │ Exact rule    │ │ RAG retrieve │ │ Extract components  │
                 │ lookup        │ │ (semantic    │ │ (Mistral Small       │
                 │ (rules.db)    │ │  search, KB) │ │  vision)             │
                 └──────────┬──┘ └──────┬──────┘ └┬──────────────────┘
                            │           │           │
                            │           │  ┌────────▼────────────┐
                            │           │  │ Normalize + map        │
                            │           │  │ (units, pinout          │
                            │           │  │  resolution, confidence)│
                            │           │  └────────┬────────────┘
                            │           │           │
                            │           │  ┌────────▼────────────┐
                            │           │  │ Rule engine check       │
                            │           │  │ (static/computed,       │
                            │           │  │  tolerance-banded)      │
                            │           │  └────────┬────────────┘
                            │           │           │
                            └─────┬─────┴───────────┘
                                  │
                       ┌──────────▼───────────┐
                       │  Node: Composer         │
                       │  (Mistral Small merges   │
                       │   all available results   │
                       │   into final answer)       │
                       └──────────┬───────────┘
                                  │
                       ┌──────────▼───────────┐
                       │  Node: Sanity Check      │
                       │  (verify NL answer matches│
                       │   structured verdicts)    │
                       └──────────┬───────────┘
                                  │
                             Final Response
```

---

## 3. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Orchestration | **LangGraph** | State graph for router → (exact lookup / RAG / extraction) → rule engine → compose → sanity check |
| RAG components | **LangChain** | Document loaders, text splitters, retriever interface, vector store wrapper |
| Vector store | Chroma (local, swappable later) | Wrapped via LangChain's Chroma integration |
| Embeddings | Mistral embeddings API (or local `bge-small` fallback) | Keep consistent across dev/prod |
| Extraction + Composition LLM | Mistral Small (multimodal) | Vision extraction + final NL answer generation only |
| Comparison reasoning | **Deterministic rule engine (Python)** | The actual verdict engine for MVP — no external model |
| Exact lookup store | SQLite (`rules.db`) | Symbol-keyed table, doubles as the rule engine's source |
| Rules ↔ RAG linkage | `source_chunk_id` field on each rule row | Lets a verdict pull its exact source chunk without a fresh semantic search |
| Backend | FastAPI | Wraps the LangGraph app as an endpoint |
| Frontend (MVP) | Streamlit | File upload + chat + checklist-style result table rendering |

---

## 4. LangGraph State Definition

```python
class PipelineState(TypedDict):
    question: str
    image: Optional[bytes]
    routes: List[Literal["exact_lookup", "rag", "extraction"]]  # can be >1

    # Exact lookup path
    exact_match_result: Optional[RuleRecord]

    # RAG path
    retrieved_chunks: List[Chunk]

    # Extraction path
    extracted_components: List[RawComponent]
    normalized_components: List[NormalizedComponent]
    rule_engine_results: List[CheckResult]

    # Final
    final_answer: str
    checklist_report: List[CheckResult]
    sanity_flags: List[str]
```

`routes` is a list, not a single value — the Router can activate more than one path per question, and state accumulates whatever each active path produces.

---

## 5. Rules KB Schema (with RAG linkage & Relational Support)

```json
{
  "rule_id": "R-VDDP-CAP",
  "domain": "PGU",
  "rule_category": "single_static",
  "symbol": "C_VDDP",
  "pin": "VDDP",
  "min_value_SI": 1.47e-6,
  "max_value_SI": 4.4e-6,
  "unit": "F",
  "dielectric_required": "X7R",
  "voltage_rating_min_V": 10,
  "related_symbols": [],
  "formula_expression": null,
  "source_table": "Table 5",
  "source_page": 12,
  "source_chunk_id": "chunk_ch2_table5",
  "approved_by": "Human Reviewer",
  "source_doc_version": "TLE987x_HW_Guideline_Rev1.1",
  "supersedes": null
}
```

Support for `rule_category`:
1. `single_static`: Direct component tolerance range ($C_{VDDP}$ min/max/dielectric).
2. `pair_ratio`: Inter-component constraints (e.g. $C_{GD} / C_{GS} \le 0.1$).
3. `system_budget`: Shared system limits (e.g. $I_{DDP} + I_{DDEXT} \le 110\text{ mA}$).

`source_chunk_id` matters for two reasons:
1. When the Rule Engine produces a verdict, the Composer can fetch the *exact* right explanatory chunk directly — no similarity-search uncertainty for something we already know the answer to.
2. It keeps the two KB representations (structured rules, RAG chunks) traceable to the same source, which matters when the doc gets revised later.

---

## 6. Phase-by-Phase Build Plan

**Reordered from v1**: schematic-checkable pipeline (Phases 1, 3, 4) comes first since it's the harder, more differentiated part. RAG (Phase 2) still runs in parallel but isn't the priority to polish first.

### Phase 1 — Rule Engine KB (Week 1)

1.1. Extract all ~18 component tables + text constraints from the PDF into master JSON `data/rules/rules_source.json` with fields: `rule_id | domain | rule_category | symbol | pin | min_value_SI | max_value_SI | unit | dielectric_required | voltage_rating_min_V | related_symbols | formula_expression | source_table | source_page | source_chunk_id`.

1.2. Review every row against the PDF directly — ground truth lock, audited by hand.

1.3. Build `src/data/seed_rules_db.py` to validate `rules_source.json` via Pydantic (`RuleRecord`) and populate SQLite `rules.db`. Include versioning fields from day one.

1.4. Build `src/graph/nodes/normalize.py`: parses engineering value strings into canonical SI floats. Write unit tests covering every literal value string in the doc's tables (~80 test cases).

**Deliverable**: `data/rules/rules.db` + `src/graph/nodes/normalize.py` with passing tests, zero LLM involvement.

---

### Phase 2 — RAG Store via LangChain & Section Filtering (Week 1, parallel with Phase 1)

2.1. Load PDF with a LangChain document loader; chunk strictly by Chapter headings (Chapters 1–15). Keep tables and formula+definition blocks atomic.

2.2. Attach section metadata per chunk: `{chapter_num, chapter_name, domain, pins_mentioned, symbols_mentioned, chunk_id}` — `chunk_id` must match `source_chunk_id` in Phase 1.

2.3. Embed and load into Chroma via LangChain's vector store wrapper. Enable Hybrid Search (BM25 + Dense vector similarity) with `domain` metadata filtering capability.

2.4. Wrap as a LangChain retriever, used by both the RAG route and the Composer's direct chunk-fetch for exact-lookup/rule-engine results.

**Deliverable**: working hybrid retriever + section metadata filter + `get_chunk_by_id()` direct-fetch function, validated against ~15-20 sample questions.

---

### Phase 3 — Schematic Extraction (Week 2)

3.1. Define strict JSON output schema for extraction. Few-shot prompt using crops from the doc's own figures (known ground truth).

3.2. Multi-pass extraction (2-3 calls per component region), derive confidence from cross-pass agreement.

3.3. Build the canonical TLE987x/6x pinout map by hand.

3.4. Normalize extracted components: resolve net → canonical pin, parse value, attach confidence.

**Deliverable**: `extract_schematic(image) -> List[NormalizedComponent]`, validated against the doc's own figures first.

---

### Phase 4 — Deterministic Rule Engine (Week 2)

4.1. Implement static_range and computed branches, `NO_RULE_FOUND`, `NEEDS_INPUT` states.

4.2. Tolerance-banded verdicts: `PASS`, `MARGINAL_LOW`, `MARGINAL_HIGH`, `FAIL`, `FAIL_LOW_CONFIDENCE`.

4.3. Output contract:
```python
{
  "component": "C15", "pin": "VDDP", "status": "MARGINAL_LOW",
  "expected": "1.47uF - 4.4uF, X7R", "actual": "1.2uF",
  "confidence": "high", "reason": "below minimum by ~18%",
  "source": {"table": "Table 5", "page": 12, "chunk_id": "chunk_ch2_table5"}
}
```

4.4. Broad hand-crafted test coverage — every status branch, every rule type, tolerance-boundary edge cases.

**Deliverable**: `run_rule_engine(normalized_components) -> List[CheckResult]`.

---

### Phase 5 — Router (Three-Way) + Composer + Sanity Check (Week 2-3)

5.1. **Router node**: rule-based. Decide `exact_lookup` if the question names a known symbol (fuzzy-match against the ~60-80 symbol list); decide `rag` if it's conceptual or doesn't name a symbol; decide `extraction` if an image is present. More than one can fire.

5.2. **Composer node**: merges whatever's populated in state (exact match, retrieved chunks, rule engine results) into a final answer + structured checklist. System prompt forbids inventing or overriding verdicts.

5.3. **Sanity check node**: verifies the composed answer doesn't contradict the structured verdicts it was given.

5.4. Assemble the full graph, test end-to-end across all three route combinations (single-route and multi-route cases).

**Deliverable**: `graph.invoke({"question": ..., "image": ...}) -> final response`, working end-to-end for all route combinations.

---

### Phase 6 — API + Minimal UI (Week 3)

6.1. FastAPI endpoint: `POST /ask` accepting `{question, image?}`.

6.2. Streamlit frontend: file upload + chat box + checklist table (status color-coded).

6.3. Log every request: question, routes taken, verdicts, final answer, latency per node.

---

### Phase 7 — Evaluation (Week 3-4)

1. **RAG accuracy** — 20 questions, manually verified answers/citations
2. **Rule engine + extraction accuracy** — synthetic component sets (rule engine), doc-figure crops (extraction)
3. **Router accuracy** — does it pick the right route(s) for a sample of mixed question types, including multi-route cases

---

## 7. Things to Explicitly Flag for Stakeholders

- **No second opinion on comparisons.** A wrong or missing rule in `rules.db` goes straight to the user unchecked — Phase 1's manual review needs real rigor.
- **Checklist completeness is not yet defined** (see Section 11) — MVP answers whatever rules happen to match, not a guaranteed-complete review. This is an intentional scope decision, not an oversight, but should be stated plainly to anyone expecting a full audit tool on day one.
- **Layout-level checks (source doc Chapter 15) are entirely out of scope** — not verifiable from a schematic image, would need PCB/gerber input.
- **False negatives are the priority risk.** Bias every ambiguous rule interpretation toward flagging, not clearing.

---

## 8. Repo Structure

```
/data
  /rules              -> rules.db, rules_source.xlsx
  /pinout_map         -> tle987x_pinout.json
  /raw_doc            -> original PDF, chunked JSON (chunk_ids shared with rules.db)
/src
  /graph
    state.py
    nodes/
      router.py          -> three-way routing logic
      exact_lookup.py
      rag_retrieve.py
      extract.py
      normalize.py
      rule_engine.py
      composer.py
      sanity_check.py
    build_graph.py
  /rag.py
  /api.py
/tests
  /test_normalize.py
  /test_rule_engine.py
  /test_router.py         -> route selection accuracy, including multi-route cases
  /test_rag_eval.py
  /test_extraction_eval.py
  /test_graph_e2e.py
/eval
  rag_test_set.json
  rule_engine_test_set.json
  extraction_test_set.json
  router_test_set.json
```

---

## 9. Suggested Timeline

| Week | Focus |
|---|---|
| 1 | Phase 1 (Rule engine KB) + Phase 2 (RAG store, incl. chunk-id linkage) in parallel |
| 2 | Phase 3 (Extraction) + Phase 4 (Rule engine) + start Phase 5 |
| 3 | Finish Phase 5 (three-way Router/Composer/Sanity) + Phase 6 (API/UI) |
| 4 | Phase 7 (Evaluation, incl. router accuracy) + polish for demo |

---

## 10. Path Back to Volt AI (once access is granted — not built now)

- Add a `voltai_compare` node parallel to `rule_engine`, both feeding a merge step
- On agreement → high-confidence verdict passes through unchanged
- On disagreement → surface both explicitly as `DISPUTED`, log as tuning signal
- Use the MVP's rule engine as the trusted baseline to evaluate Volt AI against

---

## 11. Deferred: Checklist Taxonomy (not decided, not built for MVP)

We've defined the *mechanics* of a single check (`CheckResult` schema, rule types, verdict bands) but **not** the complete, organized list of what a full schematic review should check. Explicitly deferred — noted here so it isn't lost, not because it's unimportant:

- Organizing checks by category (mirrors doc chapters: power supply, clock gen, GPIO, LIN, MON, ADCs, bridge driver, charge pump, CSA, unused pins)
- Distinguishing check *types*: presence checks (is the component there at all), value/range checks (already designed), cross-component consistency checks (e.g. total gate charge budget across a bridge leg), unused-pin termination checks
- Explicitly scoping out layout-level items (Chapter 15) that aren't schematic-checkable at all
- Deciding how "coverage" gets reported (e.g. "N of M schematic-checkable items covered") once a defined list exists

Revisit this once the schematic pipeline (Phases 1, 3, 4) is working end-to-end — building the taxonomy now, before the underlying mechanics are proven, risks designing around assumptions that change once real extraction/rule-engine behavior is observed.

---

## 12. Key Design Principles to Hold Onto

1. **Three routes exist because they solve three different problems, not for performance — don't collapse them into one mechanism.**
2. **The rule engine is the only verdict source for MVP — build and review it with real rigor.**
3. **Ambiguous or context-dependent cases resolve to `NEEDS_INPUT`, never a guessed verdict.**
4. **Low-confidence extraction must never produce a confidently-worded FAIL in the UI.**
5. **Rules are versioned and auditable like code, and linked to their RAG source chunk.**
6. **Checklist completeness is an explicit, stated open question — not a silent gap.**
7. **LangGraph state stays explicit and typed, shaped so Volt AI can be added later as a node, not a redesign.**
