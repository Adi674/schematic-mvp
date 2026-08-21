"""
Hierarchical Section Catalog & Section Identifier.

Section scoring uses a two-level taxonomy (parent → child).
match_score is an additive heuristic, NOT a calibrated probability.
confidence_calibrated is always False until real-image benchmarks are run.
"""

from typing import List, Tuple, Optional
from src.schematic.schema import (
    SchematicFacts,
    SchematicObjectType,
    SectionDefinition,
    SectionCandidate,
    SectionEvidencePacket,
    FactState,
    RefState
)


# ---------------------------------------------------------------------------
# Two-Level Section Catalog
# ---------------------------------------------------------------------------
# Parent sections
PARENT_POWER = "POWER"
PARENT_INTERFACE = "INTERFACE"
PARENT_CLOCK = "CLOCK"
PARENT_DRIVER = "DRIVER"
PARENT_OTHER = "OTHER"

DEFAULT_SECTION_CATALOG: List[SectionDefinition] = [
    # --- Parent Entries (for primary classification) ---
    SectionDefinition(
        section_id=PARENT_POWER,
        name="Power Management",
        key_pins=["VDDP", "VDDC", "VDDEXT", "VS", "VDH", "VPRE", "BAT"],
        typical_components=["capacitor", "resistor", "diode"],
        typical_nets=["VDDP", "VDDC", "VDDEXT", "VS", "GND", "VPRE"],
        keywords=["power", "supply", "pmu", "psg", "vdd", "regulation"]
    ),
    SectionDefinition(
        section_id=PARENT_INTERFACE,
        name="Interface",
        key_pins=["LIN", "SPI", "SCL", "SDA", "TX", "RX"],
        typical_components=["diode", "resistor", "capacitor"],
        typical_nets=["LIN", "VBAT", "GND"],
        keywords=["lin", "bus", "spi", "i2c", "uart", "transceiver", "esd"]
    ),
    SectionDefinition(
        section_id=PARENT_CLOCK,
        name="Clock / Oscillator",
        key_pins=["XTAL1", "XTAL2", "EXCLK"],
        typical_components=["crystal", "capacitor", "resistor"],
        typical_nets=["XTAL1", "XTAL2", "GND"],
        keywords=["xtal", "crystal", "oscillator", "clock"]
    ),
    SectionDefinition(
        section_id=PARENT_DRIVER,
        name="Power Stage / Gate Driver",
        key_pins=["SH1", "SH2", "GH1", "GH2", "GL1", "GL2", "PVDD"],
        typical_components=["mosfet", "resistor", "diode", "transistor"],
        typical_nets=["SH1", "GH1", "GL1", "GND", "PVDD"],
        keywords=["bridge", "driver", "mosfet", "inverter", "gate", "phase", "half-bridge"]
    ),

    # --- Child: POWER sub-sections ---
    SectionDefinition(
        section_id="POWER_SUPPLY_GENERATION",
        parent_section_id=PARENT_POWER,
        name="Power Supply Generation (PSG)",
        key_pins=["VS", "VPRE", "VDDP", "VDDC", "VDDEXT"],
        typical_components=["capacitor", "functional_block"],
        typical_nets=["VS", "VPRE", "VDDP", "VDDC", "VDDEXT", "GND"],
        keywords=["psg", "power supply generation", "pmu", "vpre", "vddext"]
    ),
    SectionDefinition(
        section_id="VDDP_DECOUPLING",
        parent_section_id=PARENT_POWER,
        name="VDDP Decoupling Network",
        key_pins=["VDDP"],
        typical_components=["capacitor"],
        typical_nets=["VDDP", "GND"],
        keywords=["vddp", "decoupling", "bypass", "ceramic"]
    ),
    SectionDefinition(
        section_id="VDDC_DECOUPLING",
        parent_section_id=PARENT_POWER,
        name="VDDC Decoupling Network",
        key_pins=["VDDC"],
        typical_components=["capacitor"],
        typical_nets=["VDDC", "GND"],
        keywords=["vddc", "decoupling", "bypass"]
    ),
    SectionDefinition(
        section_id="VDH_SUPPLY",
        parent_section_id=PARENT_POWER,
        name="VDH High-Voltage Supply",
        key_pins=["VDH", "BAT", "VS"],
        typical_components=["capacitor", "resistor", "diode"],
        typical_nets=["VDH", "BAT", "VS", "GND"],
        keywords=["vdh", "battery", "high-voltage"]
    ),

    # --- Child: INTERFACE sub-sections ---
    SectionDefinition(
        section_id="LIN_INTERFACE",
        parent_section_id=PARENT_INTERFACE,
        name="LIN Bus Physical Interface",
        key_pins=["LIN"],
        typical_components=["diode", "resistor", "capacitor"],
        typical_nets=["LIN", "VBAT", "GND"],
        keywords=["lin", "bus", "transceiver", "esd", "termination"]
    ),

    # --- Child: CLOCK sub-sections ---
    SectionDefinition(
        section_id="CRYSTAL_OSCILLATOR",
        parent_section_id=PARENT_CLOCK,
        name="Crystal Oscillator Circuit",
        key_pins=["XTAL1", "XTAL2", "EXCLK"],
        typical_components=["crystal", "capacitor", "resistor"],
        typical_nets=["XTAL1", "XTAL2", "GND"],
        keywords=["xtal", "crystal", "oscillator", "clock", "resonator"]
    ),

    # --- Child: DRIVER sub-sections ---
    SectionDefinition(
        section_id="BRIDGE_DRIVER",
        parent_section_id=PARENT_DRIVER,
        name="Bridge Gate Driver Circuit",
        key_pins=["SH1", "SH2", "GH1", "GH2", "GL1", "GL2"],
        typical_components=["mosfet", "resistor", "diode"],
        typical_nets=["SH1", "GH1", "GL1", "GND"],
        keywords=["bridge", "driver", "gate", "mosfet", "phase", "half-bridge"]
    ),

    # --- Fallback ---
    SectionDefinition(
        section_id="OTHER_UNKNOWN",
        parent_section_id=PARENT_OTHER,
        name="Other / Unspecified Sub-circuit",
        key_pins=[],
        typical_components=[],
        typical_nets=[],
        keywords=[]
    )
]


class SectionIdentifier:
    """Classifies schematic facts against a hierarchical catalog."""

    def __init__(self, catalog: Optional[List[SectionDefinition]] = None):
        self.catalog = catalog or DEFAULT_SECTION_CATALOG

    def build_evidence_packet(self, facts: SchematicFacts) -> SectionEvidencePacket:
        """Builds a structured evidence packet from validated high-confidence facts."""
        # Only use components that are NOT inferred
        high_conf_comps = [
            {"ref": str(c.ref or ""), "type": str(c.type)}
            for c in facts.components
            if c.ref_state != RefState.INFERRED and c.model_confidence >= 0.60
        ]

        # Only use VALIDATED values
        values = [
            str(c.value) for c in facts.components
            if c.value and c.value_state == FactState.VALIDATED
        ]

        # Named pins
        pins = [str(p.pin_name).upper() for p in facts.pins if p.pin_name]

        # Nets from net facts
        nets = [str(n.name).upper() for n in facts.nets if n.name]

        # NET_LABEL objects — these are high-signal for section ID
        net_labels = [
            str(c.value).upper()
            for c in facts.components
            if c.object_type == SchematicObjectType.NET_LABEL
            and c.value and c.value_state == FactState.VALIDATED
        ]

        # Also collect from labels dict list
        for label in facts.labels:
            txt = str(label.get("text", "")).upper().strip()
            if txt and txt not in net_labels:
                net_labels.append(txt)

        memberships = [{"net_id": m.net_id, "members": m.members} for m in facts.net_memberships]

        return SectionEvidencePacket(
            device_context=facts.device_context,
            high_confidence_components=high_conf_comps,
            visible_values=values,
            named_pins=pins,
            named_nets=nets,
            net_memberships=memberships,
            net_labels=net_labels
        )

    def identify_sections(self, facts: SchematicFacts) -> List[SectionCandidate]:
        """Scores all child catalog sections against extracted evidence."""
        packet = self.build_evidence_packet(facts)
        candidates: List[SectionCandidate] = []

        comp_types = set(str(c.get("type", "")).lower() for c in packet.high_confidence_components if c.get("type"))
        pin_names = set(str(p).upper() for p in packet.named_pins if p)
        net_names = set(str(n).upper() for n in packet.named_nets if n)
        net_label_names = set(str(l).upper() for l in packet.net_labels if l)

        # Combine all observable net/pin signals
        all_signals = pin_names | net_names | net_label_names

        for sec in self.catalog:
            # Score only leaf sections (those with a parent)
            if sec.parent_section_id is None:
                continue
            if sec.section_id == "OTHER_UNKNOWN":
                continue

            matched_evidence = []
            score = 0.0

            # Key pins/nets: highest signal (+0.35 each, capped at 3)
            key_hits = 0
            for kp in sec.key_pins:
                if kp.upper() in all_signals:
                    score += 0.35
                    matched_evidence.append(f"Key signal visible: {kp}")
                    key_hits += 1
                    if key_hits >= 3:
                        break

            # Typical nets: secondary signal (+0.20 each, capped at 4)
            net_hits = 0
            for tn in sec.typical_nets:
                if tn.upper() in all_signals:
                    score += 0.20
                    matched_evidence.append(f"Typical net/label visible: {tn}")
                    net_hits += 1
                    if net_hits >= 4:
                        break

            # Typical components: tertiary signal (+0.10 each, capped at 2)
            comp_hits = 0
            for tc in sec.typical_components:
                if tc.lower() in comp_types:
                    score += 0.10
                    matched_evidence.append(f"Component type visible: {tc}")
                    comp_hits += 1
                    if comp_hits >= 2:
                        break

            # Keywords in validated values/labels (+0.08 per keyword, capped at 3)
            kw_hits = 0
            for kw in sec.keywords:
                for val in packet.visible_values:
                    if kw in str(val).lower():
                        score += 0.08
                        matched_evidence.append(f"Keyword in value '{val}': {kw}")
                        kw_hits += 1
                        break
                # Also check net labels
                for lbl in packet.net_labels:
                    if kw in str(lbl).lower():
                        score += 0.08
                        matched_evidence.append(f"Keyword in label '{lbl}': {kw}")
                        kw_hits += 1
                        break
                if kw_hits >= 3:
                    break

            match_score = min(round(score, 3), 1.0)
            if match_score > 0.0:
                candidates.append(SectionCandidate(
                    section_id=sec.section_id,
                    name=sec.name,
                    match_score=match_score,
                    confidence_calibrated=False,  # Always False until benchmarked
                    matched_evidence=matched_evidence,
                    parent_section_id=sec.parent_section_id
                ))

        candidates.sort(key=lambda x: x.match_score, reverse=True)

        if not candidates:
            candidates.append(SectionCandidate(
                section_id="OTHER_UNKNOWN",
                name="Other / Unspecified Sub-circuit",
                match_score=0.0,
                confidence_calibrated=False,
                matched_evidence=["No catalog section matched observed signals"],
                parent_section_id=PARENT_OTHER
            ))

        return candidates

    def determine_confirmation_needed(
        self, candidates: List[SectionCandidate]
    ) -> Tuple[bool, Optional[str]]:
        """
        Determines if user confirmation is required.
        Since confidence_calibrated is always False, we are conservative:
        - Only auto-select if top score >= 0.70 AND margin over second >= 0.25.
        - Otherwise always require confirmation.
        Returns (needs_confirmation, suggested_section_id).
        """
        if not candidates:
            return True, None

        top = candidates[0]
        second_score = candidates[1].match_score if len(candidates) > 1 else 0.0

        if top.match_score >= 0.70 and (top.match_score - second_score) >= 0.25:
            return False, top.section_id

        # Default: always confirm until calibrated
        return True, top.section_id
