# Hardware Schematic Review Assistant — MVP Recovery Plan
## Phase 1: PDF Ingestion Pipeline and Ingestion-Quality Validation

### 0. Purpose

The current MVP should be restarted from the knowledge-ingestion layer.

The immediate objective is **not retrieval, RAG answering, schematic checking, or rule-engine work**.

The first objective is:

> **Convert the reference hardware-design PDF into a faithful, structured, traceable representation and prove that the representation preserves the information needed for later retrieval and schematic verification.**

Only after ingestion quality is accepted should embeddings, retrieval, or rule-engine integration be added.

The TLE987x/6x Hardware Design Guideline is a good test document because it contains normal prose, section hierarchy, tables, application schematics, block diagrams, formulas, pin mappings, recommendations, conditions, and application-dependent statements.

### 1. Scope of Phase 1

**Input**
- One reference hardware-design PDF initially: `TLE987x_6x Hardware design guideline.pdf`.
- After the pipeline works on this document, validate the same pipeline against a second product document.

**Output**
A canonical intermediate knowledge representation containing:
- document metadata
- pages
- chapters and subsections
- prose blocks
- table objects
- table rows/cells
- figures/images
- figure captions
- equations/formula blocks
- notes/warnings
- source coordinates and page references
- stable object IDs

**Out of scope**
- vector embeddings
- Chroma/vector database
- BM25/hybrid retrieval
- chatbot answering
- schematic-image extraction
- deterministic schematic rule evaluation
- automatic rule generation

### 2. Why the PDF Must Be Treated as a Structured Document

The reference document is not a flat text corpus.

Examples in the supplied guideline show:

1. Application schematic figures are followed by component/BOM information.
2. Tables contain engineering values that must remain associated with their row and table header.
3. A page can contain multiple different tables and surrounding explanatory text.
4. Some design guidance is conditional or application-dependent.
5. Equations require surrounding variable definitions.
6. Figures carry circuit relationships that ordinary PDF text extraction does not preserve.

For example, page 11 contains Table 4 followed by a separate regulator-current table and explanatory text; page 12 contains Table 5 and Table 6 plus their preceding notes. These must not be flattened into generic page chunks. The rendered source shows the visual table boundaries and hierarchy clearly. fileciteturn4file1L351-L383 fileciteturn4file1L391-L426

The bridge-driver section is another useful test case because page 29 contains a circuit figure while page 30 contains a component table followed by explanatory text and equations/constraints. fileciteturn4file2L440-L504 fileciteturn4file2L506-L558

### 3. Candidate Ingestion Approaches

#### Approach A — Plain text extraction + fixed token chunking

```text
PDF
 → text extraction
 → 500–1000 token chunks
 → metadata
```

**Advantages**
- very simple
- fast
- easy to implement

**Problems**
- destroys table boundaries
- mixes unrelated tables on the same page
- loses visual relationships
- formulas can be detached from definitions
- weak traceability

**Decision:** reject as the primary approach.

#### Approach B — Section-aware text ingestion

```text
PDF
 → detect chapter/section hierarchy
 → preserve subsection blocks
 → chunk within sections
```

**Advantages**
- much better context
- simple to maintain
- good for prose

**Problems**
- tables still require special handling
- figures are still weakly represented
- equations need special treatment

**Decision:** useful baseline, but insufficient alone.

#### Approach C — Layout-aware document ingestion

```text
PDF
 → extract text with coordinates
 → detect blocks
 → detect tables
 → detect figures
 → detect headings
 → reconstruct document structure
```

**Advantages**
- preserves page geometry
- enables table/figure boundaries
- supports exact source locations
- better evidence traceability

**Problems**
- more implementation effort
- some PDFs have difficult layouts

**Decision:** use as the foundation.

#### Approach D — Hybrid layout-aware + targeted vision

```text
PDF
 ├─ text/coordinates → deterministic extraction
 ├─ tables → table extraction
 ├─ equations → text + image validation where necessary
 └─ figures → rendered page/region image + caption/OCR/vision metadata
```

**Advantages**
- preserves structure
- uses deterministic extraction where possible
- reserves multimodal processing for genuinely visual content
- reduces cost and hallucination risk

**Problems**
- more components
- requires confidence and validation logic

**Decision:** recommended approach for this project.

### 4. Recommended Phase-1 Architecture

```text
                         Reference PDF
                              │
                              ▼
                    PDF Inspection Layer
                              │
                  ┌───────────┼───────────┐
                  ▼           ▼           ▼
               Text       Tables       Visuals
             + coords    + structure    / Figures
                  │           │           │
                  └───────────┼───────────┘
                              ▼
                    Structure Reconstruction
                              │
                              ▼
                     Canonical Knowledge Model
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
          Raw JSON        Quality Report    Rendered evidence
```

The canonical model is the source of truth for all later phases.

### 5. Canonical Knowledge Model

Do not create vector chunks first.

Create semantic document objects first.

#### 5.1 Document

```json
{
  "document_id": "TLE987X_HW_GUIDE_R1_1",
  "title": "TLE987x/6x Hardware design guideline",
  "revision": "1.1",
  "date": "2022-04-01",
  "page_count": 70
}
```

#### 5.2 Section

```json
{
  "object_id": "sec_2_3",
  "type": "section",
  "chapter": 2,
  "section": "2.3",
  "title": "VDDP voltage regulator 5.0 V",
  "page_start": 12,
  "page_end": 12
}
```

#### 5.3 Prose block

```json
{
  "object_id": "text_p12_b03",
  "type": "text",
  "section_id": "sec_2_3",
  "page": 12,
  "text": "...",
  "bbox": [x1, y1, x2, y2]
}
```

#### 5.4 Table

```json
{
  "object_id": "table_5",
  "type": "table",
  "title": "Capacitor selection for VDDP",
  "section_id": "sec_2_3",
  "page": 12,
  "headers": ["Symbol", "Function", "Recommended component"],
  "rows": ["table_5_row_1"]
}
```

#### 5.5 Table row

```json
{
  "object_id": "table_5_row_1",
  "type": "table_row",
  "table_id": "table_5",
  "cells": {
    "Symbol": "CVDDP",
    "Function": "Output capacitor at VDDP",
    "Recommended component": "Min. 470 nF + 1 µF; Max. 2.2 µF + 2.2 µF; X7R; >=10 V"
  },
  "page": 12
}
```

#### 5.6 Figure

```json
{
  "object_id": "fig_16",
  "type": "figure",
  "caption": "Gate drivers for one half-bridge with external components",
  "section_id": "sec_9_1",
  "page": 29,
  "image_path": "figures/fig_16.png",
  "bbox": [x1, y1, x2, y2]
}
```

#### 5.7 Equation/formula

```json
{
  "object_id": "eq_05",
  "type": "equation",
  "section_id": "sec_10_2",
  "page": 37,
  "expression_text": "...",
  "variable_definitions": ["..."]
}
```

### 6. Ingestion Strategy by Content Type

#### 6.1 Normal prose

Use layout-aware text extraction.

Group adjacent lines into paragraphs using:
- page coordinates
- line spacing
- font information where available
- indentation
- heading boundaries

Do not split paragraphs solely because a page has a fixed token count.

#### 6.2 Headings

Detect document hierarchy from:
- numbered headings such as `2`, `2.3`, `2.3.1`
- font size/style differences
- TOC alignment
- repeated page header/footer patterns

The TOC in the guideline already exposes a strong hierarchy such as PGU, CGU, GPIO, LIN, ADC, bridge driver, charge pump, current sense, SWD, unused pins, and layout sections. fileciteturn3file0L33-L50

#### 6.3 Tables

Tables get their own extraction path.

Required behavior:
- identify table bounding box
- identify caption/title
- identify header rows
- identify all body rows
- preserve column relationships
- preserve units and symbols
- preserve multi-line cell content
- preserve row-to-page relationship

Primary representation:

```text
Table
 ├── header
 ├── row 1
 ├── row 2
 └── row N
```

Each row inherits:
- document ID
- chapter
- section
- table ID
- page

#### 6.4 Figures and schematics

Do not force figure content into the normal text corpus.

Store:
- figure image
- caption
- page
- section
- bounding box
- nearby explanatory text

Optional later enrichment:
- OCR labels
- detected symbols
- detected nets
- visual description

For Phase 1 the important requirement is **preservation and traceability**, not complete visual interpretation.

The source guideline contains circuit figures whose topology is visually meaningful; the bridge-driver figure is a clear example. fileciteturn4file2L451-L504

#### 6.5 Equations

Keep:
- equation itself
- surrounding explanatory paragraph
- variable definitions
- page/section

Do not create an isolated equation chunk with no context.

#### 6.6 Notes / warnings / conditions

Preserve notes as first-class objects or strongly linked blocks.

Examples of important semantics in the source include:
- necessary
- optional
- application related
- depends on MOSFET
- depends on application
- must be placed

These qualifiers are part of the engineering meaning and cannot be discarded.

### 7. Chunking Strategy: Do Not Choose One Chunk Size Yet

Phase 1 should produce the canonical document representation.

Only after that should we benchmark different retrieval-unit strategies.

Candidate retrieval units:

**Strategy 1 — Paragraph chunks**

Good for explanatory questions.

**Strategy 2 — Section + paragraph chunks**

Good for maintaining chapter context.

**Strategy 3 — Table-row chunks with table metadata**

Best candidate for component/value lookups.

**Strategy 4 — Figure + caption + surrounding explanation**

Useful for visual/application-circuit questions.

**Strategy 5 — Composite evidence chunks**

Example:

```text
Section context
+ explanatory note
+ table row
+ related note
```

This may be the strongest final retrieval representation, but it should be generated from canonical objects rather than used during raw ingestion.

### 8. Recommended Final Retrieval-Unit Design

Keep **canonical objects** and **retrieval chunks** separate.

```text
Canonical document objects
        │
        ├── text block
        ├── table row
        ├── figure
        ├── equation
        └── note
               │
               ▼
       Retrieval-unit builder
               │
               ▼
        retrieval_chunk
```

A retrieval chunk can contain multiple canonical objects while retaining their IDs.

Example:

```json
{
  "chunk_id": "ret_2_3_table5_cvddp",
  "object_ids": ["sec_2_3", "table_5", "table_5_row_1", "text_p12_b03"],
  "text": "...",
  "page": 12,
  "section": "2.3",
  "domain": "PGU"
}
```

This solves the current project's major traceability problem: the retrieval chunk is assembled from known source objects rather than assigning the same page text to multiple logical IDs.

### 9. Ingestion Quality Evaluation

Before RAG, define a gold-set of source facts.

The first evaluation should be **document reconstruction quality**, not answer quality.

#### 9.1 Structural checks

Verify:
- 70 pages are discovered
- page numbers are preserved
- section hierarchy is reconstructed
- chapter titles are present
- table count is captured
- figure count is captured
- captions are captured
- no large text regions are silently dropped

#### 9.2 Text fidelity checks

For sampled pages:
- extracted text matches source
- reading order is correct
- symbols are preserved
- units are preserved
- Greek/math symbols are not silently corrupted
- headers/footers can be separated from body text

#### 9.3 Table fidelity checks

For every selected table:
- correct number of rows
- correct number of columns
- header/column association preserved
- multi-line cells preserved
- units preserved
- symbols preserved

Use representative tables such as:
- Table 4: VS component selection
- Table 5: VDDP capacitor selection
- Table 6: VDDC capacitor selection
- Bridge-driver external components table

The source pages provide visually distinct tables that can be manually compared against extraction output. fileciteturn4file1L357-L383 fileciteturn4file1L400-L426 fileciteturn4file2L512-L540

#### 9.4 Figure fidelity checks

For sampled figures:
- figure is detected
- correct page
- correct bounding box
- image saved
- caption linked
- nearby explanatory text linked

#### 9.5 Traceability checks

Every extracted object must answer:

> Where did this come from?

Required fields:
- document ID
- page
- section
- object ID
- bounding box where applicable
- source type

### 10. Ingestion Quality Scorecard

Create an ingestion report such as:

```text
Document: TLE987x/6x Hardware Design Guideline
Pages processed: 70 / 70
Sections detected: XX
Tables detected: XX
Figures detected: XX
Equations detected: XX

Text fidelity:       PASS / REVIEW
Table fidelity:      PASS / REVIEW
Figure preservation: PASS / REVIEW
Hierarchy fidelity:  PASS / REVIEW
Traceability:        PASS / REVIEW

Critical errors: 0
```

Do not proceed to retrieval if there are critical ingestion failures.

### 11. Golden Test Set for Ingestion

Create a fixed test set of pages covering different document patterns.

Recommended sample set:

```text
Page 5   → product comparison table
Page 6   → large application schematic
Page 7   → schematic + BOM table
Page 11  → table + secondary current table + paragraph
Page 12  → two adjacent tables + notes
Page 17  → numerical recommendation table
Page 19  → GPIO configuration table
Page 29  → circuit figure
Page 30  → component table + explanatory text
Page 59  → unused-pin table
```

The goal is not to test every page manually. The goal is to test every **layout pattern**.

### 12. Tooling Experiment Plan

Do not commit immediately to one PDF parser.

Run a small comparison on the golden pages.

Candidate stack A:

```text
PyMuPDF / pdfplumber
+ table extraction
+ custom layout reconstruction
```

Candidate stack B:

```text
PyMuPDF / pdfplumber
+ Camelot/Tabula-style table extraction
+ custom structure reconstruction
```

Candidate stack C:

```text
layout-aware parser
+ targeted vision for difficult pages/tables/figures
```

Compare them on:
- table fidelity
- reading order
- heading detection
- formula preservation
- implementation complexity
- runtime
- reproducibility

Do not choose the most sophisticated parser by default. Choose the simplest approach that reaches the required fidelity.

### 13. Phase-1 Deliverables

1. `document_parser.py`
2. `structure_builder.py`
3. `table_parser.py`
4. `figure_extractor.py`
5. `canonical_schema.py`
6. `canonical_document.json`
7. `retrieval_units.json` (generated only after canonical ingestion passes)
8. `ingestion_report.json`
9. rendered/source comparison samples
10. `test_ingestion.py`

### 14. Acceptance Gate Before Retrieval

Phase 1 is complete only when all of the following are true:

- No page is silently dropped.
- Sections are correctly associated with their content.
- Tables are represented separately from surrounding page text.
- Table rows retain header context.
- Figures are preserved as image objects with source metadata.
- Equations retain their surrounding definitions.
- Every object has deterministic source traceability.
- Sample extraction is manually verified against rendered PDF pages.
- The same ingestion logic can process the second product PDF without document-specific hardcoded chunk IDs.

### 15. What We Should NOT Do Yet

Do not implement:

```text
PDF → embeddings
PDF → Chroma
PDF → RAG
PDF → LLM summarization
PDF → automatic rules
```

until the canonical ingestion layer passes the quality gate.

### 16. Next Phase After This Gate

Only after ingestion is accepted:

```text
Canonical document
       ↓
Retrieval-unit builder
       ↓
Dense embeddings + lexical index
       ↓
Hybrid retrieval
       ↓
Retrieval evaluation set
       ↓
Recall@1 / Recall@3 / Recall@5 / MRR
       ↓
failure analysis
```

The retrieval phase will then compare multiple retrieval-unit strategies using the same canonical source data.

### 17. Key Design Principle

> **Ingestion should preserve meaning before retrieval tries to find meaning.**

The PDF parser is therefore not a preprocessing utility. It is the foundation of the entire schematic-review knowledge base.
