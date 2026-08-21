"""
WS3 - Build Reference Schematics (Multi-Region Sub-Crop Engine).

This script performs high-resolution regional sub-crop extraction on the
application schematic figures to avoid model hallucinations on full-page images.

Pipeline per figure:
  1. Divide image into 4 logical sub-crops (Power & EMC, Charge Pump, Bridge Driver, Sensors & Peripherals).
  2. Extract components, nodes, and connections from each sub-crop using mistral-large-latest.
  3. Merge and deduplicate objects across regions by label.
  4. Build a Symbol lookup dict from HDG Table 3 (BOM table).
  5. Join each component to Table 3 by exact symbol match.
  6. Save raw and final joined JSON files under data/reference_schematics/.

Usage:
    python scripts/build_reference_schematics.py
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm import call_mistral_vision, safe_print

REPO_ROOT = Path(__file__).parent.parent
FIGURES_DIR = REPO_ROOT / "data" / "figures"
CANONICAL_PATH = REPO_ROOT / "data" / "canonical" / "TLE987x_6x_rev1.1.json"
OUT_DIR = REPO_ROOT / "data" / "reference_schematics"
SCRATCH_DIR = REPO_ROOT / "scratch" / "region_crops"


REGION_PROMPT_TEMPLATE = """You are an expert electrical schematic analyst inspecting a HIGH-RESOLUTION SUB-CROP of a microcontroller application schematic ({region_name}).

Examine ONLY what is visibly drawn in this crop image.

Extract:
1. COMPONENTS (capacitors, resistors, diodes, inductors, ICs, transistors, functional blocks, sensors)
   - Preserve EXACT visible reference labels (e.g., "L_FILT", "C_FILT1", "C_FILT2", "C_VS1", "C_VS2", "C_VDDP1", "C_VDDP2", "C_VDDC1", "C_VDDC2", "C_MON", "C_LIN", "D_VS", "R_MON", "EMC filter", "Rev. polarity protection", "TH1", "TH2", "TH3", "TL1", "TL2", "TL3", "TLE4946-2K", "Temperature sensor", "C_VAREF", "C_VDDEXT").
   - Extract exact values when readable (e.g., "100 nF", "10 nF").
   - DO NOT invent series resistors (such as "R_VS", "R_VDDP", "R_VDDC", "R_VDDEXT", "R_CP1H") if only a capacitor bridges the pin/rail to GND.
   - For MOSFETs in the bridge driver, use the exact printed designators: "TH1", "TH2", "TH3" for High-Side, and "TL1", "TL2", "TL3" for Low-Side.
   - Recognize Hall sensor IC blocks as "TLE4946-2K" (type: "sensor" or "integrated_circuit").
   - Recognize "Temperature sensor" as a functional block or sensor (type: "sensor").
   - Recognize "Rev. polarity protection" and "EMC filter" as functional_block types.

2. NODES / SIGNALS
   - Signal/rail/pin names visible: VBAT, VS, VDDP, VDDC, VDDEXT, VAREF, GND_REF, MON, LIN, IGN, CP1H, CP1L, CP2H, CP2L, VCP, VSD, VDH, GH1..3, SH1..3, GL1..3, SL, P0.3, P1.4, P2.0, P2.2, P2.3, P2.4, P2.5, RESET, GND.

3. CONNECTIONS
   - Trace exact connections. Decoupling capacitors connect between the named rail/pin and GND.

Return ONLY a valid JSON object:
{{
  "components": [
    {{"label": "C_VS1", "type": "capacitor", "value": null, "function": "VS decoupling capacitor"}}
  ],
  "nodes": [
    {{"name": "VS"}}
  ],
  "connections": [
    {{"source": "C_VS1", "target": "VS", "relationship": "connected_to"}},
    {{"source": "C_VS1", "target": "GND", "relationship": "connected_to"}}
  ]
}}
"""


FIGURES = [
    {
        "path": FIGURES_DIR / "fig_2_application_schemati.png",
        "device": "TLE987x",
        "raw_out": "tle987x_raw.json",
        "final_out": "tle987x.json",
        "source_figure": "fig_2_application_schemati.png",
        "regions": [
            {"name": "Power & EMC", "bbox": (0, 100, 850, 850)},
            {"name": "Charge Pump & Supplies", "bbox": (650, 100, 1496, 850)},
            {"name": "3-Phase Inverter Bridge", "bbox": (650, 700, 1496, 1550)},
            {"name": "Sensors & Peripherals", "bbox": (0, 700, 850, 1550)},
        ]
    },
    {
        "path": FIGURES_DIR / "fig_3_application_schemati.png",
        "device": "TLE987x-2QX",
        "raw_out": "tle987x_2qx_raw.json",
        "final_out": "tle987x_2qx.json",
        "source_figure": "fig_3_application_schemati.png",
        "regions": [
            {"name": "Power & EMC", "bbox": (0, 100, 850, 750)},
            {"name": "Charge Pump & Supplies", "bbox": (650, 100, 1496, 750)},
            {"name": "2-Phase / Inverter Bridge", "bbox": (650, 600, 1496, 1348)},
            {"name": "Sensors & Peripherals", "bbox": (0, 600, 850, 1348)},
        ]
    }
]


def extract_region(img, region_info, device_hint, fig_stem):
    name = region_info["name"]
    crop_box = region_info["bbox"]
    safe_print(f"  -> Processing Region: {name} (crop box: {crop_box})")

    cropped = img.crop(crop_box)
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    crop_path = SCRATCH_DIR / f"{fig_stem}_{name.lower().replace(' ', '_')}.png"
    cropped.save(crop_path)

    image_bytes = crop_path.read_bytes()
    prompt = REGION_PROMPT_TEMPLATE.format(region_name=name)

    raw = call_mistral_vision(
        image_bytes=image_bytes,
        prompt=prompt,
        model="mistral-large-latest",
        mime_type="image/png",
        response_format={"type": "json_object"}
    )

    if not raw:
        safe_print(f"  [WARN] No response for region {name}")
        return {"components": [], "nodes": [], "connections": []}

    try:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        return data if isinstance(data, dict) else {"components": [], "nodes": [], "connections": []}
    except Exception as e:
        safe_print(f"  [ERROR] JSON parse error in region {name}: {e}")
        return {"components": [], "nodes": [], "connections": []}


def merge_region_extractions(region_results):
    merged_components = {}
    merged_nodes = {}
    merged_connections = []
    seen_conns = set()

    for res in region_results:
        for comp in res.get("components", []):
            label = comp.get("label")
            if not label:
                continue
            if label not in merged_components:
                merged_components[label] = comp
            else:
                existing = merged_components[label]
                if not existing.get("value") and comp.get("value"):
                    existing["value"] = comp.get("value")
                if not existing.get("function") and comp.get("function"):
                    existing["function"] = comp.get("function")

        for node in res.get("nodes", []):
            name = node.get("name")
            if name and name not in merged_nodes:
                merged_nodes[name] = node

        for conn in res.get("connections", []):
            src = conn.get("source")
            tgt = conn.get("target")
            rel = conn.get("relationship", "connected_to")
            if src and tgt:
                key = (min(src, tgt), max(src, tgt), rel)
                if key not in seen_conns:
                    seen_conns.add(key)
                    merged_connections.append({
                        "source": src,
                        "target": tgt,
                        "relationship": rel
                    })

    return {
        "components": list(merged_components.values()),
        "nodes": list(merged_nodes.values()),
        "connections": merged_connections
    }


def _normalize_symbol(raw):
    if not raw:
        return ""
    normed = re.sub(r"\s+", "_", raw.strip())
    normed = re.sub(r"_+", "_", normed)
    return normed.upper()


def build_symbol_lookup(canonical_path):
    safe_print(f"\n[LOOKUP] Building HDG Table 3 symbol lookup from {canonical_path.name}")
    data = json.loads(canonical_path.read_text(encoding="utf-8"))
    sections = data.get("sections", [])

    def collect_tables(sections):
        tables = []
        for s in sections:
            for b in s.get("content_blocks", []):
                if b.get("block_type", b.get("type")) == "table":
                    tables.append(b)
            tables.extend(collect_tables(s.get("subsections", [])))
        return tables

    all_tables = collect_tables(sections)

    table3 = None
    for t in all_tables:
        caption = t.get("caption", t.get("title", ""))
        headers_raw = t.get("headers_raw", {})
        header_keys = list(headers_raw.keys()) if isinstance(headers_raw, dict) else []
        if "Symbol" in header_keys or "External components" in caption:
            table3 = t
            break

    if table3 is None:
        safe_print("  [WARN] Table 3 BOM table not found!")
        return {}

    lookup = {}
    rows = table3.get("rows", [])
    for row in rows:
        cells = row.get("normalized_cells", row.get("raw_cells", {}))
        symbol_raw = cells.get("Symbol", "")
        if not symbol_raw or symbol_raw == "Symbol":
            continue
        function = cells.get("Function", "")
        component_typical = cells.get("Component (typical)", "")
        norm_key = _normalize_symbol(symbol_raw)
        if norm_key:
            lookup[norm_key] = {
                "hdg_function": function.strip() if function else None,
                "hdg_component_typical": component_typical.strip() if component_typical else None,
                "hdg_symbol_raw": symbol_raw,
            }

    safe_print(f"  Built BOM lookup with {len(lookup)} symbols")
    return lookup


def _derive_nodes_for_component(label, connections):
    if not label:
        return []
    connected = set()
    for conn in connections:
        src = conn.get("source", "")
        tgt = conn.get("target", "")
        if src == label and tgt:
            connected.add(tgt)
        elif tgt == label and src:
            connected.add(src)
    return sorted(connected)


def join_to_hdg(extraction, symbol_lookup):
    connections = extraction.get("connections", [])
    enriched = []
    for comp in extraction.get("components", []):
        label = comp.get("label") or ""
        norm_label = _normalize_symbol(label)
        hdg_match = symbol_lookup.get(norm_label, {})
        entry = {
            "label": label if label else None,
            "type": comp.get("type"),
            "function": comp.get("function"),
            "value": comp.get("value"),
            "hdg_function": hdg_match.get("hdg_function"),
            "hdg_component_typical": hdg_match.get("hdg_component_typical"),
            "hdg_symbol_raw": hdg_match.get("hdg_symbol_raw"),
            "hdg_matched": bool(hdg_match),
            "nodes": _derive_nodes_for_component(label, connections),
        }
        enriched.append(entry)
    matched = sum(1 for e in enriched if e["hdg_matched"])
    safe_print(f"  Join result: {matched}/{len(enriched)} components matched to HDG Table 3 BOM")
    return enriched


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    symbol_lookup = build_symbol_lookup(CANONICAL_PATH)

    for fig in FIGURES:
        path = fig["path"]
        if not path.exists():
            safe_print(f"\n[SKIP] Figure not found: {path}")
            continue

        safe_print(f"\n==================================================")
        safe_print(f"Processing Figure: {fig['source_figure']} ({fig['device']}) via Multi-Region Extraction")
        safe_print(f"==================================================")

        img = Image.open(path)
        region_results = []
        for reg_info in fig["regions"]:
            reg_data = extract_region(img, reg_info, fig["device"], path.stem)
            region_results.append(reg_data)

        merged_extraction = merge_region_extractions(region_results)
        merged_extraction["image_id"] = path.stem
        merged_extraction["width"] = img.width
        merged_extraction["height"] = img.height
        merged_extraction["device_context"] = fig["device"]

        raw_path = OUT_DIR / fig["raw_out"]
        raw_path.write_text(json.dumps(merged_extraction, indent=2, ensure_ascii=False), encoding="utf-8")
        safe_print(f"  [WRITE] Raw merged extraction -> {raw_path}")

        safe_print(f"[JOIN] {fig['device']}")
        enriched = join_to_hdg(merged_extraction, symbol_lookup)

        final_path = OUT_DIR / fig["final_out"]
        final_reference = {
            "schema_version": "1.0",
            "device": fig["device"],
            "hdg_version": "1.1",
            "source_figure": fig["source_figure"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "components": enriched,
            "nodes": merged_extraction.get("nodes", []),
            "connections": merged_extraction.get("connections", []),
        }
        final_path.write_text(json.dumps(final_reference, indent=2, ensure_ascii=False), encoding="utf-8")
        safe_print(f"  [WRITE] Final reference -> {final_path}")

    safe_print("\n[DONE] Multi-region reference schematic extraction complete!")


if __name__ == "__main__":
    main()
