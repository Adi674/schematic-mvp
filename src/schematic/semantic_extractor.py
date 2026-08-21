import json
import os
import re
from io import BytesIO
from typing import Optional, Tuple

from PIL import Image

from src.llm import call_mistral_vision
from src.schematic.semantic_schema import SemanticSchematic, SemanticUncertainty
from src.schematic.geometry import GeometryExtractor


SEMANTIC_EXTRACTION_PROMPT = """
You are an expert electrical schematic analyst.

Analyze ONLY what is visibly present in the supplied schematic image.

Your goal is to describe the visible electrical structure as semantic JSON.

Extract:

1. COMPONENTS
- physical components such as capacitor, resistor, diode, inductor, crystal, IC
- preserve the exact visible label/reference if readable, in the "label" field
- extract the visible value only when readable, in the "value" field
- set "label_state" to one of: VISIBLE, UNREADABLE, NOT_VISIBLE, UNKNOWN
- set "value_state" to one of: VISIBLE, UNREADABLE, NOT_VISIBLE, UNKNOWN
- provide a "function" only when it is reasonably supported by the visible circuit context
- provide "evidence": {"bbox": [x1, y1, x2, y2], "model_confidence": 0.0-1.0}
  giving the tight pixel bounding box of the component's symbol, in the
  coordinate space of the image dimensions given below

2. NODES / SIGNALS
- visible names such as VS, VDDP, VDDC, VDDEXT, GND, LIN
- supply rails and signal nodes
- functional electrical nodes when clearly visible
- Standard schematic symbols count as visible nodes even without adjacent text:
  the ground symbol (triangle or hatched lines) is always node "GND"
  a horizontal/vertical bus bar at the top or side of the crop is a supply rail node —
  infer its name from the nearest labeled pin if one is visibly connected to it (e.g. "VDDP"),
  otherwise call it "SUPPLY_RAIL"
- Do NOT skip a node just because it has no text label; ground and rail symbols are
  self-identifying by shape, not by text.

3. CONNECTIONS
Represent clearly visible relationships between components and nodes.
Each connection MUST use these exact keys: "source", "target", "relationship".
"relationship" MUST be exactly one of: connected_to, feeds, connected_between, supplies, unknown
- A component's two leads/terminals connect to whatever node or rail is actually
  drawn touching that lead — trace the wire, don't assume.
- Two components of the same type sitting next to each other (e.g. two decoupling
  capacitors) are usually each independently bridging the same two nodes — they are
  in parallel, not chained to each other. Only connect two components directly if a
  wire visibly runs between them with no other node in between.
- Each two-terminal component (capacitor, resistor, inductor) has exactly ONE
  supply-side/signal-side connection and ONE ground/return connection — never
  connect the same component to two different supply nodes.
- Every capacitor/resistor/inductor generally has two ends: represent it with two
  "connected_between" entries naming both ends.

4. UNCERTAINTIES
Explicitly report anything that is unclear or cannot safely be determined.

STRICT RULES:

- NEVER invent a component reference.
- NEVER invent a component value.
- NEVER invent a signal/net name.
- Preserve visible labels exactly.
- Do NOT infer objects outside the supplied crop.
- Do NOT create dummy components to satisfy the schema.
- If a reference cannot be read, return null.
- If a value cannot be read, return null.
- If a bounding box cannot be determined, omit "evidence" rather than guessing.
- If a connection is visually ambiguous, either omit it or mark it in uncertainties.
- Do not assume two objects are electrically connected merely because they are close.
- Do not assume a wire exists when it is not visibly present.
- Return ONLY valid JSON, matching the field names below exactly.
- Do not return markdown fences.
- Use the EXACT field names shown in the JSON structure below. Do not substitute
  synonyms (e.g. use "description" not "issue" or "note"; use "source"/"target"
  not "from"/"to"; use "label" not "reference").

Required JSON structure:

{
  "device_context": null,
  "components": [
    {"label": "C1", "label_state": "VISIBLE", "type": "capacitor", "function": null,
     "value": null, "value_state": "NOT_VISIBLE",
     "evidence": {"bbox": [120, 40, 160, 90], "model_confidence": 0.9}}
  ],
  "nodes": [
    {"name": "VS", "description": null}
  ],
  "connections": [
    {"source": "D_VS", "target": "VS", "relationship": "connected_to"}
  ],
  "uncertainties": []
}
"""


def _upscale_if_small(image_bytes: bytes, min_dim: int = 900) -> Tuple[bytes, float]:
    """Upscales small crops so tiny schematic text is legible to the vision model.
    Returns (possibly-upscaled bytes, scale factor applied)."""
    img = Image.open(BytesIO(image_bytes))
    scale = max(1.0, min_dim / min(img.width, img.height))
    if scale > 1.0:
        new_size = (int(img.width * scale), int(img.height * scale))
        img = img.resize(new_size, Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), scale
    return image_bytes, 1.0


class SemanticSchematicExtractor:

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or os.getenv(
            "SCHEMATIC_VISION_MODEL",
            "mistral-small-latest"
        )
        self.geometry_extractor = GeometryExtractor(proximity_tolerance_pixels=18.0)

    def extract(
        self,
        image_bytes: bytes,
        image_id: str,
        width: int,
        height: int,
        mime_type: str = "image/png",
        device_hint: Optional[str] = None,
    ) -> SemanticSchematic:

        original_bytes = image_bytes
        model_bytes, scale = _upscale_if_small(image_bytes)
        model_width = int(round(width * scale))
        model_height = int(round(height * scale))

        prompt = SEMANTIC_EXTRACTION_PROMPT + f"""

Image dimensions:
width = {model_width}
height = {model_height}
"""

        raw = call_mistral_vision(
            image_bytes=model_bytes,
            prompt=prompt,
            model=self.model_name,
            mime_type=mime_type,
            response_format={"type": "json_object"},
        )

        if not raw:
            raise RuntimeError("Vision model returned no response.")

        data = self._parse_json(raw)
        self._normalize_semantic_output(data)
        self._rescale_bboxes(data, scale)

        if device_hint:
            data["device_context"] = device_hint

        semantic = SemanticSchematic(
            image_id=image_id,
            width=width,
            height=height,
            **data,
        )

        self._validate(semantic)
        self._run_geometry_check(original_bytes, semantic)

        return semantic

    @staticmethod
    def _parse_json(raw: str) -> dict:
        text = raw.strip()

        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Vision model returned invalid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise RuntimeError("Vision model response is not a JSON object.")

        return data

    @staticmethod
    def _normalize_semantic_output(data: dict) -> None:
        """Repairs common key-name mismatches from the model before pydantic validation."""

        normalized_components = []
        for comp in data.get("components", []):
            if not isinstance(comp, dict):
                continue
            comp["label"] = comp.get("label", comp.get("reference"))
            normalized_components.append(comp)
        data["components"] = normalized_components

        normalized_connections = []
        for conn in data.get("connections", []):
            if not isinstance(conn, dict):
                continue
            source = conn.get("source", conn.get("from"))
            target = conn.get("target", conn.get("to"))
            if not source or not target:
                continue
            normalized_connections.append({
                "source": source,
                "target": target,
                "relationship": conn.get("relationship", conn.get("type", "unknown")),
                "confidence": conn.get("confidence", 0.8),
                "evidence": conn.get("evidence"),
            })
        data["connections"] = normalized_connections

        normalized_uncertainties = []
        for item in data.get("uncertainties", []):
            if isinstance(item, str):
                normalized_uncertainties.append({"description": item, "related_objects": []})
            elif isinstance(item, dict):
                description = (
                    item.get("description")
                    or item.get("issue")
                    or item.get("note")
                    or item.get("text")
                )
                if not description:
                    continue  # unusable entry, drop rather than crash
                normalized_uncertainties.append({
                    "description": description,
                    "related_objects": item.get("related_objects", []),
                })
        data["uncertainties"] = normalized_uncertainties

    @staticmethod
    def _rescale_bboxes(data: dict, scale: float) -> None:
        """Maps bboxes the model returned (in upscaled pixel space) back to the
        original crop's coordinate space."""
        if scale == 1.0:
            return
        for comp in data.get("components", []):
            ev = comp.get("evidence")
            if ev and ev.get("bbox"):
                ev["bbox"] = [round(v / scale, 1) for v in ev["bbox"]]
        for node in data.get("nodes", []):
            ev = node.get("evidence")
            if ev and ev.get("bbox"):
                ev["bbox"] = [round(v / scale, 1) for v in ev["bbox"]]

    @staticmethod
    def _validate(result: SemanticSchematic) -> None:
        width = result.width
        height = result.height

        for component in result.components:
            if component.evidence and component.evidence.bbox:
                component.evidence.bbox = SemanticSchematicExtractor._validate_bbox(
                    component.evidence.bbox, width, height
                )

        for node in result.nodes:
            if node.evidence and node.evidence.bbox:
                node.evidence.bbox = SemanticSchematicExtractor._validate_bbox(
                    node.evidence.bbox, width, height
                )

    @staticmethod
    def _validate_bbox(bbox, width, height):
        if len(bbox) != 4:
            return None
        x1, y1, x2, y2 = bbox
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            return None
        return bbox

    def _run_geometry_check(self, image_bytes: bytes, semantic: SemanticSchematic) -> None:
        """Cross-checks each component's bbox against OpenCV-detected wire traces.
        Purely advisory: never fails or drops data, just flags mismatches so you
        can see which components the model may have mis-positioned or hallucinated."""

        has_any_bbox = any(c.evidence and c.evidence.bbox for c in semantic.components)
        if not has_any_bbox:
            return  # model didn't return bboxes this round; nothing to verify

        wires, _junctions, success = self.geometry_extractor.extract_geometry(
            image_bytes, components=[]
        )
        if not success or not wires:
            return  # can't verify without detected wires; don't penalize the extraction

        tol = self.geometry_extractor.proximity_tolerance

        for comp in semantic.components:
            if not (comp.evidence and comp.evidence.bbox):
                continue

            x1, y1, x2, y2 = comp.evidence.bbox
            cx1, cy1, cx2, cy2 = x1 - tol, y1 - tol, x2 + tol, y2 + tol

            has_close_wire = any(
                (cx1 <= w.start[0] <= cx2 and cy1 <= w.start[1] <= cy2)
                or (cx1 <= w.end[0] <= cx2 and cy1 <= w.end[1] <= cy2)
                for w in wires
            )

            comp.geometry_verified = has_close_wire

            if not has_close_wire:
                semantic.uncertainties.append(
                    SemanticUncertainty(
                        description=(
                            f"Component '{comp.label or comp.type}' bounding box has "
                            "no detected wire nearby — bbox may be misplaced."
                        ),
                        related_objects=[comp.label] if comp.label else []
                    )
                )