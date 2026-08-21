"""
Connectivity Graph Builder for Schematic Crop Review.

Performs union-find grouping of wire segments, junctions, and component
pins to reconstruct electrical nets and assign net names from labels.
"""

import math
import logging
from typing import List, Dict, Any, Set, Tuple, Optional
from src.schematic.schema import (
    SchematicFacts,
    NetFact,
    NetMembershipFact,
    ConnectionUncertainty,
    ComponentFact,
    PinFact,
    WireSegmentFact,
    JunctionFact,
    SchematicObjectType,
    FactState
)

logger = logging.getLogger(__name__)


class UnionFind:
    """Disjoint-set data structure with path compression."""

    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, item: str) -> str:
        if item not in self.parent:
            self.parent[item] = item
            return item
        path = []
        while self.parent[item] != item:
            path.append(item)
            item = self.parent[item]
        for node in path:
            self.parent[node] = item
        return item

    def union(self, item1: str, item2: str):
        root1 = self.find(item1)
        root2 = self.find(item2)
        if root1 != root2:
            self.parent[root1] = root2


def point_to_segment_distance(
    px: float, py: float,
    x1: float, y1: float,
    x2: float, y2: float
) -> float:
    """Calculates the minimum distance from a point to a line segment."""
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return math.hypot(px - x1, py - y1)

    # Project point onto segment
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))

    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


class ConnectivityBuilder:
    """Reconstructs the connectivity graph and groups net memberships."""

    def __init__(self, proximity_tolerance_pixels: float = 12.0):
        self.tolerance = proximity_tolerance_pixels

    def build_connectivity(self, facts: SchematicFacts):
        """
        Builds the netlist from wires, junctions, pins, and labels.
        Modifies facts in-place to populate nets, net_memberships, and uncertainties.
        """
        uf = UnionFind()

        # Gather active geometry elements
        wires: List[WireSegmentFact] = facts.wires
        junctions: List[JunctionFact] = facts.junctions
        pins: List[PinFact] = facts.pins
        components: List[ComponentFact] = facts.components

        # Filter out net labels and power symbols from components for label correlation
        labels_info: List[Tuple[str, List[float]]] = []
        for comp in components:
            if comp.object_type == SchematicObjectType.NET_LABEL and comp.value and comp.evidence and comp.evidence.bbox:
                labels_info.append((comp.value, comp.evidence.bbox))

        # Also get labels from labels dict list if they have bboxes
        for lbl in facts.labels:
            txt = lbl.get("text")
            bbox = lbl.get("bbox")
            if txt and bbox:
                labels_info.append((txt, bbox))

        # 1. Connect wires to other wires (by endpoint proximity)
        for i in range(len(wires)):
            for j in range(i + 1, len(wires)):
                w1 = wires[i]
                w2 = wires[j]
                # Compare endpoints
                pts1 = [w1.start, w1.end]
                pts2 = [w2.start, w2.end]
                connected = False
                for p1 in pts1:
                    if not p1: continue
                    for p2 in pts2:
                        if not p2: continue
                        if math.hypot(p1[0] - p2[0], p1[1] - p2[1]) <= self.tolerance:
                            connected = True
                            break
                if connected:
                    uf.union(w1.wire_id, w2.wire_id)

        # 2. Connect wires to junctions
        for junc in junctions:
            if not junc.position:
                continue
            jp = junc.position
            for wire in wires:
                # If junction is close to wire start, end, or segment
                d = point_to_segment_distance(jp[0], jp[1], wire.start[0], wire.start[1], wire.end[0], wire.end[1])
                if d <= self.tolerance:
                    uf.union(wire.wire_id, junc.junction_id)
                    # Link junction facts too
                    if wire.wire_id not in junc.connected_wires:
                        junc.connected_wires.append(wire.wire_id)

        # 3. Connect pins/terminals to wires
        pin_nodes: List[str] = []
        uncertainties: List[ConnectionUncertainty] = []

        for idx, pin in enumerate(pins):
            pin_ref = pin.pin_name or pin.pin_number or f"pin_{idx+1}"
            pin_node_id = f"{pin.component_ref}.{pin_ref}"
            pin_nodes.append(pin_node_id)

            if not pin.evidence or not pin.evidence.bbox:
                continue

            px1, py1, px2, py2 = pin.evidence.bbox
            pcx = (px1 + px2) / 2.0
            pcy = (py1 + py2) / 2.0

            matching_wires = []
            for wire in wires:
                d = point_to_segment_distance(pcx, pcy, wire.start[0], wire.start[1], wire.end[0], wire.end[1])
                if d <= self.tolerance:
                    matching_wires.append(wire.wire_id)

            if len(matching_wires) == 1:
                uf.union(pin_node_id, matching_wires[0])
            elif len(matching_wires) > 1:
                # Ambiguous connection! Flag it.
                uf.union(pin_node_id, matching_wires[0])  # Connect to first as initial guess
                uncertainties.append(
                    ConnectionUncertainty(
                        description=f"Pin {pin_node_id} is close to multiple wires: {matching_wires}",
                        related_pins=[pin_node_id],
                        related_wires=matching_wires,
                        reason=FactState.AMBIGUOUS
                    )
                )

        # 4. Map net labels to wires/nets
        # Find which wire is closest to each label's bounding box
        label_assignments: Dict[str, Set[str]] = {}  # root_id -> set of label texts
        for lbl_text, bbox in labels_info:
            lx1, ly1, lx2, ly2 = bbox
            lcx = (lx1 + lx2) / 2.0
            lcy = (ly1 + ly2) / 2.0

            closest_wire = None
            min_dist = float("inf")
            for wire in wires:
                d = point_to_segment_distance(lcx, lcy, wire.start[0], wire.start[1], wire.end[0], wire.end[1])
                if d < min_dist:
                    min_dist = d
                    closest_wire = wire.wire_id

            if closest_wire and min_dist <= self.tolerance * 2:  # Labels can be slightly further away
                root = uf.find(closest_wire)
                if root not in label_assignments:
                    label_assignments[root] = set()
                label_assignments[root].add(lbl_text)

        # 5. Extract connected components and populate Nets / NetMemberships
        net_groups: Dict[str, List[str]] = {}  # root -> list of pin node IDs
        # Include wires too, in case we need to know wire components
        wire_groups: Dict[str, List[str]] = {}  # root -> list of wire IDs

        for pin_node in pin_nodes:
            root = uf.find(pin_node)
            if root not in net_groups:
                net_groups[root] = []
            net_groups[root].append(pin_node)

        for wire in wires:
            root = uf.find(wire.wire_id)
            if root not in wire_groups:
                wire_groups[root] = []
            wire_groups[root].append(wire.wire_id)

        # Re-assemble net facts
        net_facts: List[NetFact] = []
        net_memberships: List[NetMembershipFact] = []
        net_counter = 0

        # Iterate over all components in the union-find graph
        all_roots = set(uf.find(node) for node in uf.parent.keys())

        for root in all_roots:
            group_pins = net_groups.get(root, [])
            group_wires = wire_groups.get(root, [])

            # Skip empty nets (no pins and no wires)
            if not group_pins and not group_wires:
                continue

            net_counter += 1
            net_id = f"NET_{net_counter:03d}"

            # Determine net name from associated labels
            labels_found = label_assignments.get(root, set())
            net_name = None
            if labels_found:
                # Deterministic pick: shortest/cleanest or alphabetical
                sorted_labels = sorted(list(labels_found))
                net_name = sorted_labels[0]

            # Assign net ID to wires in this net
            for w_id in group_wires:
                for wire in wires:
                    if wire.wire_id == w_id:
                        wire.connected_net_id = net_id

            # Create NetFact
            net_facts.append(
                NetFact(
                    net_id=net_id,
                    name=net_name,
                    source="geometry",
                    model_confidence=1.0
                )
            )

            # Create NetMembershipFact
            net_memberships.append(
                NetMembershipFact(
                    net_id=net_id,
                    members=group_pins,
                    source="geometry",
                    model_confidence=1.0
                )
            )

        facts.nets = net_facts
        facts.net_memberships = net_memberships
        facts.uncertainties = uncertainties
        facts.geometry_stage_applied = True
