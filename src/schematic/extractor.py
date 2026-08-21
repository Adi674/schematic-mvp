"""
Two-Pass Multimodal Extraction Engine using Mistral Small 4.

Pass 1: Object Inventory
  - Classifies each visible object using the schematic object taxonomy.
  - Does NOT infer connectivity or net membership.
  - Reports bboxes in canonical [x1, y1, x2, y2] format.
  - Reports per-object model_confidence.
  - Marks values/refs UNKNOWN/UNREADABLE when not legible.

Pass 2: Ambiguity Resolution (geometry-assisted)
  - Given the object inventory + specific uncertain connections from the
    geometry stage, the model resolves CONNECTED / NOT_CONNECTED / UNCERTAIN.
  - The model CANNOT create new nets or new connections.
"""

import json
import re
from typing import Dict, Any, Optional, List
from src.llm import call_mistral_vision, safe_print
from src.schematic.schema import (
    SchematicFacts,
    ImageInputInfo,
    ComponentFact,
    PinFact,
    NetFact,
    NetMembershipFact,
    WireSegmentFact,
    JunctionFact,
    ConnectionUncertainty,
    BoundingBoxEvidence,
    FactState,
    RefState,
    SchematicObjectType,
    ValidationStatus,
    validate_bbox
)


# ---------------------------------------------------------------------------
# Pass 1 Prompt — Object Inventory (NO connectivity reasoning)
# ---------------------------------------------------------------------------

PASS1_INVENTORY_PROMPT = """You are an expert electrical schematic vision parser performing PASS 1: OBJECT INVENTORY.

Rules (STRICT):
1. Report ONLY what is visibly readable in the image. Do NOT guess or infer.
2. Do NOT infer connectivity, net membership, or wire paths. That is Pass 2.
3. Mark values as "UNKNOWN" when unreadable. Mark refs as null when not visibly printed.
4. Classify each object using EXACTLY one of these object_type values:
   - "PHYSICAL_COMPONENT"  (capacitor, resistor, diode, inductor, crystal, transistor)
   - "IC_DEVICE"           (integrated circuit, MCU, microcontroller)
   - "FUNCTIONAL_BLOCK"    (labeled block/box: PMU, PSG, Power-down supply, etc.)
   - "NET_LABEL"           (text label on a wire: VDDP, GND, LIN, VS, VPRE, VDDC, VDDEXT)
   - "POWER_SYMBOL"        (VCC rail arrow, GND triangle symbol)
   - "TERMINAL"            (device pin or connector terminal)
   - "WIRE"                (visible wire line segment)
   - "JUNCTION"            (wire junction dot)
   - "ANNOTATION"          (non-electrical text, dimension, note)
   - "UNKNOWN_OBJECT"      (cannot classify)
5. Bounding boxes MUST be in [x1, y1, x2, y2] pixel format (top-left origin).
6. ref_state must be one of: "VISIBLE", "UNREADABLE", "NOT_VISIBLE", "INFERRED".
   Use "INFERRED" if you are guessing the designator.
7. model_confidence must be a float 0.0-1.0 per object.

Return ONLY a single valid JSON object. No markdown fences. No conversational text.

{
  "device_context": "TLE987x",
  "objects": [
    {
      "object_type": "PHYSICAL_COMPONENT",
      "ref": "C15",
      "ref_state": "VISIBLE",
      "type": "capacitor",
      "value": "100 nF",
      "value_readable": true,
      "bbox": [x1, y1, x2, y2],
      "model_confidence": 0.92
    },
    {
      "object_type": "NET_LABEL",
      "ref": null,
      "ref_state": "NOT_VISIBLE",
      "type": "net_label",
      "value": "VDDP",
      "value_readable": true,
      "bbox": [x1, y1, x2, y2],
      "model_confidence": 0.97
    },
    {
      "object_type": "WIRE",
      "ref": null,
      "ref_state": "NOT_VISIBLE",
      "type": "wire",
      "value": null,
      "value_readable": false,
      "wire_start": [x1, y1],
      "wire_end": [x2, y2],
      "bbox": [x1, y1, x2, y2],
      "model_confidence": 0.85
    }
  ]
}
"""


# ---------------------------------------------------------------------------
# Pass 2 Prompt — Ambiguity Resolution Only
# ---------------------------------------------------------------------------

PASS2_AMBIGUITY_PROMPT = """You are resolving specific visual ambiguities in a schematic crop.

Context from Pass 1 (objects already extracted):
{inventory_json}

Ambiguous connections to resolve:
{uncertainties_json}

For each ambiguous connection listed, examine the original image carefully and answer ONLY:
- "CONNECTED": the terminal is visibly connected to the wire
- "NOT_CONNECTED": the terminal is visibly NOT connected to the wire
- "UNCERTAIN": you cannot determine connectivity from the image

You may NOT create new nets, new components, or new connections beyond the ones listed.

Return ONLY a valid JSON object. No markdown fences. No conversational text.

{{
  "resolutions": [
    {{
      "uncertainty_id": "U_001",
      "result": "CONNECTED",
      "confidence": 0.85,
      "reason": "Wire clearly terminates at C15 top terminal"
    }}
  ]
}}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_json_response(raw_text: str) -> str:
    """Strips markdown code fences like ```json ... ``` if present."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    return cleaned.strip()


def safe_str(val: Any, fallback: str = "") -> str:
    """Cast value to string safely."""
    if val is None:
        return fallback
    return str(val)


# ---------------------------------------------------------------------------
# SchematicExtractor
# ---------------------------------------------------------------------------

class SchematicExtractor:
    """Two-Pass Extractor for cropped schematic images."""

    def __init__(self, model_name: str = "mistral-small-latest"):
        self.model_name = model_name

    def extract(
        self,
        image_bytes: bytes,
        image_id: str,
        width: int = 800,
        height: int = 600,
        device_hint: Optional[str] = None,
        mime_type: str = "image/png",
        uncertainties_for_pass2: Optional[List[Dict[str, Any]]] = None
    ) -> SchematicFacts:
        """
        Runs Pass 1 (Object Inventory) and optionally Pass 2 (Ambiguity Resolution).
        Connectivity graph is built by ConnectivityBuilder separately, not here.
        """
        # --- Pass 1: Object Inventory ---
        pass1_raw = call_mistral_vision(
            image_bytes, PASS1_INVENTORY_PROMPT,
            model=self.model_name, mime_type=mime_type
        )
        pass1_data = self._parse_json(pass1_raw, fallback={"objects": [], "device_context": None})

        if device_hint:
            pass1_data["device_context"] = device_hint

        # --- Pass 2: Ambiguity Resolution (only if uncertainties provided) ---
        pass2_resolutions: Dict[str, Dict] = {}
        if uncertainties_for_pass2:
            inventory_str = json.dumps(pass1_data, indent=2)
            uncertainties_str = json.dumps(uncertainties_for_pass2, indent=2)
            pass2_prompt = PASS2_AMBIGUITY_PROMPT.format(
                inventory_json=inventory_str,
                uncertainties_json=uncertainties_str
            )
            pass2_raw = call_mistral_vision(
                image_bytes, pass2_prompt,
                model=self.model_name, mime_type=mime_type
            )
            pass2_data = self._parse_json(pass2_raw, fallback={"resolutions": []})
            for res in pass2_data.get("resolutions", []):
                uid = safe_str(res.get("uncertainty_id"))
                if uid:
                    pass2_resolutions[uid] = res

        return self._assemble_facts(
            image_id=image_id,
            width=width,
            height=height,
            mime_type=mime_type,
            pass1=pass1_data,
            pass2_resolutions=pass2_resolutions
        )

    # ------------------------------------------------------------------
    # JSON parsing helpers
    # ------------------------------------------------------------------

    def _parse_json(self, raw_text: Optional[str], fallback: Dict) -> Dict:
        if not raw_text:
            return fallback
        try:
            cleaned = clean_json_response(raw_text)
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
            return fallback
        except Exception as e:
            safe_print(f"[EXTRACTOR] JSON parse error: {e}")
            return fallback

    # ------------------------------------------------------------------
    # Fact assembly
    # ------------------------------------------------------------------

    def _assemble_facts(
        self,
        image_id: str,
        width: int,
        height: int,
        mime_type: str,
        pass1: Dict[str, Any],
        pass2_resolutions: Dict[str, Dict]
    ) -> SchematicFacts:
        input_info = ImageInputInfo(
            image_id=image_id,
            width=width,
            height=height,
            crop_scope="partial",
            mime_type=mime_type
        )

        raw_objects: List[Dict] = pass1.get("objects", [])
        if not isinstance(raw_objects, list):
            raw_objects = []

        components: List[ComponentFact] = []
        pins: List[PinFact] = []
        wires: List[WireSegmentFact] = []
        junctions: List[JunctionFact] = []
        labels: List[Dict[str, Any]] = []

        wire_counter = 0
        junction_counter = 0

        for obj in raw_objects:
            if not isinstance(obj, dict):
                continue

            raw_type = safe_str(obj.get("object_type", "UNKNOWN_OBJECT")).upper()
            obj_type = SchematicObjectType.UNKNOWN_OBJECT
            try:
                obj_type = SchematicObjectType(raw_type)
            except ValueError:
                pass

            raw_bbox = obj.get("bbox")
            bbox = [float(v) for v in raw_bbox] if isinstance(raw_bbox, list) and len(raw_bbox) == 4 else None
            bbox_valid, bbox_reason = validate_bbox(bbox, width, height)
            bbox_vstatus = ValidationStatus.OK if bbox_valid else ValidationStatus.INVALID_GEOMETRY
            if not bbox_valid and bbox is not None:
                safe_print(f"[EXTRACTOR] Invalid bbox for '{obj.get('ref', '?')}': {bbox_reason}")

            model_conf = float(obj.get("model_confidence", 0.0))
            evidence = BoundingBoxEvidence(
                bbox=bbox,
                model_confidence=model_conf,
                validation_status=bbox_vstatus,
                bbox_validated=bbox_valid
            )

            # --- WIRE ---
            if obj_type == SchematicObjectType.WIRE:
                wire_counter += 1
                raw_start = obj.get("wire_start")
                raw_end = obj.get("wire_end")
                start = [float(v) for v in raw_start] if isinstance(raw_start, list) and len(raw_start) == 2 else None
                end = [float(v) for v in raw_end] if isinstance(raw_end, list) and len(raw_end) == 2 else None
                wires.append(WireSegmentFact(
                    wire_id=f"W_{wire_counter:03d}",
                    start=start,
                    end=end,
                    points=[start, end] if start and end else [],
                    source="llm_description",
                    model_confidence=model_conf,
                    validation_status=bbox_vstatus
                ))
                continue

            # --- JUNCTION ---
            if obj_type == SchematicObjectType.JUNCTION:
                junction_counter += 1
                pos = [(bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0] if bbox else None
                junctions.append(JunctionFact(
                    junction_id=f"J_{junction_counter:03d}",
                    position=pos,
                    source="llm_description"
                ))
                continue

            # --- TERMINAL / PIN ---
            if obj_type == SchematicObjectType.TERMINAL:
                pin_name = safe_str(obj.get("value")) or None
                comp_ref = safe_str(obj.get("ref")) or "UNKNOWN"
                pins.append(PinFact(
                    component_ref=comp_ref,
                    pin_name=pin_name,
                    evidence=evidence,
                    model_confidence=model_conf,
                    validation_status=bbox_vstatus
                ))
                continue

            # --- NET_LABEL — collect as labels too ---
            if obj_type == SchematicObjectType.NET_LABEL:
                label_text = safe_str(obj.get("value")) or None
                if label_text:
                    labels.append({"text": label_text, "bbox": bbox, "object_type": "NET_LABEL"})
                # Also add as a minimal component entry for downstream scoring
                components.append(ComponentFact(
                    object_type=SchematicObjectType.NET_LABEL,
                    ref=None,
                    ref_state=RefState.NOT_VISIBLE,
                    type="net_label",
                    value=label_text,
                    value_state=FactState.VALIDATED if obj.get("value_readable") else FactState.UNREADABLE,
                    evidence=evidence,
                    model_confidence=model_conf,
                    validation_status=bbox_vstatus
                ))
                continue

            # --- ANNOTATION ---
            if obj_type == SchematicObjectType.ANNOTATION:
                labels.append({"text": safe_str(obj.get("value")), "bbox": bbox, "object_type": "ANNOTATION"})
                continue

            # --- PHYSICAL_COMPONENT, IC_DEVICE, FUNCTIONAL_BLOCK, POWER_SYMBOL, UNKNOWN ---
            raw_ref = obj.get("ref")
            ref = safe_str(raw_ref) if raw_ref else None

            raw_ref_state = safe_str(obj.get("ref_state", "NOT_VISIBLE")).upper()
            ref_state = RefState.NOT_VISIBLE
            try:
                ref_state = RefState(raw_ref_state)
            except ValueError:
                pass
            if ref_state == RefState.INFERRED and ref:
                safe_print(f"[EXTRACTOR] INFERRED ref '{ref}' — will not be treated as engineering fact.")

            raw_value = obj.get("value")
            value = safe_str(raw_value) if raw_value else None
            value_readable = bool(obj.get("value_readable", False))
            value_state = FactState.UNKNOWN
            if value_readable and value and value.upper() not in ("UNKNOWN", "UNREADABLE", "NULL", "NONE"):
                value_state = FactState.VALIDATED

            comp_type = safe_str(obj.get("type", "unknown"))

            components.append(ComponentFact(
                object_type=obj_type,
                ref=ref,
                ref_state=ref_state,
                type=comp_type,
                value=value,
                value_state=value_state,
                evidence=evidence,
                model_confidence=model_conf,
                validation_status=bbox_vstatus
            ))

        return SchematicFacts(
            input_info=input_info,
            device_context=safe_str(pass1.get("device_context")) or None,
            components=components,
            pins=pins,
            wires=wires,
            junctions=junctions,
            labels=labels
        )
