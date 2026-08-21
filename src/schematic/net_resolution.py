"""
Net resolution — bridges a customer's arbitrary component label (e.g. "C29")
to a stable, KB-lookupable identity: which net it sits on, and that net's
function/domain per the device's pin map.

This is the step both Scenario A (explain) and Scenario B (what's missing)
depend on. A component's *label* is never a safe retrieval key (customers
name things arbitrarily); the *net* it's connected to is, because net names
on device pins (VDDP, VS, GND, MON, ...) are stable and already indexed in
data/pinout_map/tle987x_pinout.json.

Usage:
    pin_index = load_pin_index("data/pinout_map/tle987x_pinout.json")
    resolved = resolve_component_net("C_VDDP1", semantic_schematic, pin_index)
    # resolved.primary is the best (type, function, domain) match to query the KB with
"""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from src.schematic.semantic_schema import SemanticSchematic


# Net names that are electrically real but never functionally distinguishing
# on their own — a component connected to GND tells you nothing about *why*
# it's there. Used to de-prioritize, never to discard.
NON_DISTINGUISHING_NETS = {"GND", "GROUND", "VSS"}


@dataclass
class PinInfo:
    pin_number: str
    name: str
    function: str
    domain: str


@dataclass
class ResolvedNet:
    net_name: str
    function: Optional[str]
    domain: Optional[str]
    resolution: str  # "direct_pin" | "graph_walk" | "unresolved"


@dataclass
class ComponentResolution:
    component_label: str
    candidates: list[ResolvedNet] = field(default_factory=list)

    @property
    def primary(self) -> Optional[ResolvedNet]:
        """Best net to key a KB query on: prefer a resolved, functionally
        distinguishing net over GND/VSS, and prefer a direct pin match over
        a graph-walked one."""
        if not self.candidates:
            return None

        def rank(c: ResolvedNet) -> tuple:
            return (
                0 if c.resolution != "unresolved" else 1,
                0 if c.net_name.upper() not in NON_DISTINGUISHING_NETS else 1,
                0 if c.resolution == "direct_pin" else 1,
            )

        return sorted(self.candidates, key=rank)[0]


def load_pin_index(pinout_map_path: str) -> dict[str, PinInfo]:
    """Loads data/pinout_map/tle987x_pinout.json into a name-keyed index
    (uppercased) for direct net-name lookup. Load once, reuse across requests."""
    path = Path(pinout_map_path)
    if not path.is_absolute():
        cwd_candidate = Path.cwd() / path
        if cwd_candidate.exists():
            path = cwd_candidate
        else:
            # Fallback for servers launched from outside repo root.
            repo_root = Path(__file__).resolve().parents[2]
            path = repo_root / path

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    index: dict[str, PinInfo] = {}
    for pin in raw.get("pins", {}).values():
        name = pin.get("name", "").strip().upper()
        if not name:
            continue
        index[name] = PinInfo(
            pin_number=str(pin.get("pin_number", "")),
            name=pin.get("name", ""),
            function=pin.get("function", ""),
            domain=pin.get("domain", "GENERAL"),
        )
    return index


def _component_touches(component_label: str, semantic: SemanticSchematic) -> list[str]:
    """Every net/node name a component is connected to, from either side
    of a connection edge."""
    touches: list[str] = []
    for conn in semantic.connections:
        if conn.source == component_label:
            touches.append(conn.target)
        elif conn.target == component_label:
            touches.append(conn.source)
    return touches


def _graph_walk(
    start_net: str,
    semantic: SemanticSchematic,
    pin_index: dict[str, PinInfo],
    component_labels: set[str],
    max_hops: int = 3,
) -> Optional[PinInfo]:
    """Fallback for block-diagram-style crops where a component connects to
    an intermediate/customer-named net rather than directly to a device pin
    name. Walks the connection graph (breadth-first, skipping other
    components) up to max_hops looking for a name that resolves in pin_index."""
    visited = {start_net}
    frontier = [start_net]

    for _ in range(max_hops):
        next_frontier = []
        for net in frontier:
            for conn in semantic.connections:
                for candidate in (conn.source, conn.target):
                    other = conn.target if conn.source == net else (
                        conn.source if conn.target == net else None
                    )
                    if other is None or other in visited or other in component_labels:
                        continue
                    if other.upper() in pin_index:
                        return pin_index[other.upper()]
                    visited.add(other)
                    next_frontier.append(other)
        frontier = next_frontier
        if not frontier:
            break

    return None


def resolve_component_net(
    component_label: str,
    semantic: SemanticSchematic,
    pin_index: dict[str, PinInfo],
) -> ComponentResolution:
    """Resolves a single component's connections to KB-lookupable net
    identities. Never raises on an unresolvable net — returns it with
    resolution="unresolved" so the caller can fall back to plain-text
    search on the component's raw label/type instead of failing outright."""

    component_labels = {c.label for c in semantic.components if c.label}
    touched_nets = _component_touches(component_label, semantic)

    result = ComponentResolution(component_label=component_label)

    for net_name in touched_nets:
        pin = pin_index.get(net_name.upper())
        if pin is not None:
            result.candidates.append(
                ResolvedNet(
                    net_name=pin.name,
                    function=pin.function,
                    domain=pin.domain,
                    resolution="direct_pin",
                )
            )
            continue

        walked = _graph_walk(net_name, semantic, pin_index, component_labels)
        if walked is not None:
            result.candidates.append(
                ResolvedNet(
                    net_name=walked.name,
                    function=walked.function,
                    domain=walked.domain,
                    resolution="graph_walk",
                )
            )
        else:
            result.candidates.append(
                ResolvedNet(
                    net_name=net_name,
                    function=None,
                    domain=None,
                    resolution="unresolved",
                )
            )

    return result


def resolve_all_components(
    semantic: SemanticSchematic,
    pin_index: dict[str, PinInfo],
) -> dict[str, ComponentResolution]:
    """Convenience wrapper: resolves every component in an extracted
    schematic in one pass. Used by both Scenario A and Scenario B."""
    return {
        c.label: resolve_component_net(c.label, semantic, pin_index)
        for c in semantic.components
        if c.label
    }