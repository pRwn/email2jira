#!/usr/bin/env python3
"""
bpmn2_to_gliffy.py

A practical starter converter from BPMN 2.0 XML to a Gliffy-style JSON document.

Important:
- This parses common BPMN 2.0 elements (lanes, tasks, events, gateways, sequence flows).
- Gliffy's native JSON format is not publicly standardized in a way that guarantees
  import compatibility across versions/workspaces.
- Because of that, this script supports two output modes:

  1) "intermediate" mode:
     Writes a clean vendor-neutral JSON graph extracted from BPMN.
     This is reliable and useful for testing.

  2) "template" mode:
     Takes a user-supplied Gliffy JSON export as a template and injects shapes/lines
     into that structure using a minimal, easy-to-edit mapping layer.
     This is the recommended way to get to a real Gliffy-importable file, because
     Gliffy exports from your own workspace provide the best schema reference.

Usage:
    python bpmn2_to_gliffy.py input.bpmn output.json
    python bpmn2_to_gliffy.py input.bpmn output.json --template gliffy_template.json

Example:
    python bpmn2_to_gliffy.py employee_onboarding.bpmn gliffy_out.json
    python bpmn2_to_gliffy.py employee_onboarding.bpmn gliffy_out.json --template sample_gliffy.json
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# BPMN namespaces commonly seen in BPMN 2.0 files
NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
}


@dataclass
class Node:
    id: str
    name: str
    kind: str               # startEvent, endEvent, task, gateway, lane, etc.
    lane_id: Optional[str] = None
    x: float = 0.0
    y: float = 0.0
    w: float = 120.0
    h: float = 80.0
    raw_type: str = ""


@dataclass
class Edge:
    id: str
    source: str
    target: str
    name: str = ""


@dataclass
class Lane:
    id: str
    name: str
    flow_node_refs: List[str] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    w: float = 1600.0
    h: float = 200.0


@dataclass
class Graph:
    process_id: str
    process_name: str
    lanes: Dict[str, Lane] = field(default_factory=dict)
    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_bpmn(bpmn_path: Path) -> Graph:
    tree = ET.parse(bpmn_path)
    root = tree.getroot()

    process = root.find("bpmn:process", NS)
    if process is None:
        raise ValueError("No <bpmn:process> found in BPMN file.")

    graph = Graph(
        process_id=process.get("id", "Process_1"),
        process_name=process.get("name", process.get("id", "Unnamed Process")),
    )

    # Parse lanes first
    for lane in process.findall(".//bpmn:lane", NS):
        lane_id = lane.get("id")
        if not lane_id:
            continue
        refs = [ref.text for ref in lane.findall("bpmn:flowNodeRef", NS) if ref.text]
        graph.lanes[lane_id] = Lane(
            id=lane_id,
            name=lane.get("name", lane_id),
            flow_node_refs=refs,
        )

    # Reverse lookup: flowNodeRef -> lane_id
    node_to_lane: Dict[str, str] = {}
    for lane_id, lane in graph.lanes.items():
        for ref in lane.flow_node_refs:
            node_to_lane[ref] = lane_id

    # Parse BPMN DI bounds if present
    di_bounds: Dict[str, Tuple[float, float, float, float]] = {}

    # Map BPMNShape@bpmnElement -> Bounds
    for shape in root.findall(".//bpmndi:BPMNShape", NS):
        bpmn_element = shape.get("bpmnElement")
        bounds = shape.find("dc:Bounds", NS)
        if bpmn_element and bounds is not None:
            di_bounds[bpmn_element] = (
                float(bounds.get("x", 0)),
                float(bounds.get("y", 0)),
                float(bounds.get("width", 120)),
                float(bounds.get("height", 80)),
            )

    # Lane bounds if present
    for lane_id, lane in graph.lanes.items():
        if lane_id in di_bounds:
            lane.x, lane.y, lane.w, lane.h = di_bounds[lane_id]

    # Parse nodes
    supported_node_tags = {
        "startEvent",
        "endEvent",
        "intermediateCatchEvent",
        "intermediateThrowEvent",
        "task",
        "userTask",
        "serviceTask",
        "manualTask",
        "scriptTask",
        "businessRuleTask",
        "sendTask",
        "receiveTask",
        "exclusiveGateway",
        "parallelGateway",
        "inclusiveGateway",
        "eventBasedGateway",
    }

    for elem in process.iter():
        tag = local_name(elem.tag)
        if tag not in supported_node_tags:
            continue

        elem_id = elem.get("id")
        if not elem_id:
            continue

        name = elem.get("name", elem_id)
        lane_id = node_to_lane.get(elem_id)
        x, y, w, h = di_bounds.get(elem_id, (0.0, 0.0, 120.0, 80.0))

        # Reasonable defaults if BPMN DI is missing
        if tag.endswith("Gateway"):
            w, h = 50.0, 50.0
        elif tag.endswith("Event"):
            w, h = 36.0, 36.0

        graph.nodes[elem_id] = Node(
            id=elem_id,
            name=name,
            kind=classify_bpmn_node(tag),
            lane_id=lane_id,
            x=x,
            y=y,
            w=w,
            h=h,
            raw_type=tag,
        )

    # Parse sequence flows
    for flow in process.findall(".//bpmn:sequenceFlow", NS):
        flow_id = flow.get("id")
        source = flow.get("sourceRef")
        target = flow.get("targetRef")
        if flow_id and source and target:
            graph.edges.append(
                Edge(
                    id=flow_id,
                    source=source,
                    target=target,
                    name=flow.get("name", ""),
                )
            )

    # If no coordinates exist, auto-layout.
    if not any((n.x or n.y) for n in graph.nodes.values()):
        auto_layout(graph)

    # If lanes exist but no lane bounds, synthesize them.
    if graph.lanes and not any((lane.x or lane.y) for lane in graph.lanes.values()):
        synthesize_lane_bounds(graph)

    return graph


def classify_bpmn_node(tag: str) -> str:
    if tag == "startEvent":
        return "start"
    if tag == "endEvent":
        return "end"
    if "Gateway" in tag:
        return "gateway"
    if "Event" in tag:
        return "event"
    return "task"


def synthesize_lane_bounds(graph: Graph) -> None:
    lane_order = list(graph.lanes.keys())
    y = 40.0
    for lane_id in lane_order:
        lane_nodes = [n for n in graph.nodes.values() if n.lane_id == lane_id]
        if lane_nodes:
            min_x = min(n.x for n in lane_nodes) - 80
            max_x = max(n.x + n.w for n in lane_nodes) + 80
            min_y = min(n.y for n in lane_nodes) - 40
            max_y = max(n.y + n.h for n in lane_nodes) + 40
            graph.lanes[lane_id].x = min_x
            graph.lanes[lane_id].y = min_y
            graph.lanes[lane_id].w = max(1200.0, max_x - min_x)
            graph.lanes[lane_id].h = max(160.0, max_y - min_y)
        else:
            graph.lanes[lane_id].x = 20
            graph.lanes[lane_id].y = y
            graph.lanes[lane_id].w = 1600
            graph.lanes[lane_id].h = 180
        y += graph.lanes[lane_id].h


def auto_layout(graph: Graph) -> None:
    """
    Very simple flow-based layout:
    - tries to place nodes left-to-right
    - groups by lane if lanes exist
    """
    indegree = {node_id: 0 for node_id in graph.nodes}
    outgoing: Dict[str, List[str]] = {node_id: [] for node_id in graph.nodes}

    for edge in graph.edges:
        if edge.target in indegree:
            indegree[edge.target] += 1
        if edge.source in outgoing:
            outgoing[edge.source].append(edge.target)

    starts = [nid for nid, d in indegree.items() if d == 0]
    if not starts:
        starts = list(graph.nodes.keys())[:1]

    visited = set()
    queue: List[Tuple[str, int]] = [(s, 0) for s in starts]
    level: Dict[str, int] = {}

    while queue:
        nid, l = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        level[nid] = max(level.get(nid, 0), l)
        for nxt in outgoing.get(nid, []):
            queue.append((nxt, l + 1))

    lane_ids = list(graph.lanes.keys()) or ["_default"]
    lane_y_map = {lane_id: 60 + i * 220 for i, lane_id in enumerate(lane_ids)}

    unlaned_next_y = 60 + len(lane_ids) * 220
    lane_counts: Dict[str, int] = {}

    for node in graph.nodes.values():
        lane_id = node.lane_id or "_default"
        lane_counts.setdefault(lane_id, 0)
        node.x = 120 + level.get(node.id, 0) * 220
        node.y = lane_y_map.get(lane_id, unlaned_next_y) + lane_counts[lane_id] * 0
        if node.kind == "gateway":
            node.w = node.h = 50
        elif node.kind in {"start", "end", "event"}:
            node.w = node.h = 36
        else:
            node.w, node.h = 140, 80

    if graph.lanes:
        synthesize_lane_bounds(graph)


def edge_waypoints(graph: Graph, edge: Edge) -> List[Dict[str, float]]:
    src = graph.nodes[edge.source]
    dst = graph.nodes[edge.target]

    sx = src.x + src.w
    sy = src.y + src.h / 2
    tx = dst.x
    ty = dst.y + dst.h / 2

    midx = (sx + tx) / 2
    return [
        {"x": round(sx, 2), "y": round(sy, 2)},
        {"x": round(midx, 2), "y": round(sy, 2)},
        {"x": round(midx, 2), "y": round(ty, 2)},
        {"x": round(tx, 2), "y": round(ty, 2)},
    ]


def to_intermediate_json(graph: Graph) -> dict:
    return {
        "type": "bpmn-graph",
        "process": {
            "id": graph.process_id,
            "name": graph.process_name,
        },
        "lanes": [asdict(l) for l in graph.lanes.values()],
        "nodes": [asdict(n) for n in graph.nodes.values()],
        "edges": [
            {
                **asdict(e),
                "waypoints": edge_waypoints(graph, e),
            }
            for e in graph.edges
        ],
    }


# -----------------------------
# Template-based Gliffy output
# -----------------------------

def make_uuid() -> str:
    return str(uuid.uuid4())


def base_shape_for_node(node: Node) -> dict:
    """
    A minimal Gliffy-like object structure.
    This is intentionally easy to adapt after you inspect a real Gliffy export.
    """
    shape = {
        "id": make_uuid(),
        "type": "shape",
        "shapeType": shape_type_for_node(node),
        "text": node.name,
        "x": round(node.x, 2),
        "y": round(node.y, 2),
        "width": round(node.w, 2),
        "height": round(node.h, 2),
        "metadata": {
            "sourceId": node.id,
            "bpmnType": node.raw_type,
            "laneId": node.lane_id,
        },
    }
    return shape


def base_shape_for_lane(lane: Lane) -> dict:
    return {
        "id": make_uuid(),
        "type": "container",
        "shapeType": "swimlane",
        "text": lane.name,
        "x": round(lane.x, 2),
        "y": round(lane.y, 2),
        "width": round(lane.w, 2),
        "height": round(lane.h, 2),
        "metadata": {
            "sourceId": lane.id,
            "kind": "lane",
        },
    }


def base_line_for_edge(graph: Graph, edge: Edge, node_id_to_gliffy_id: Dict[str, str]) -> dict:
    return {
        "id": make_uuid(),
        "type": "line",
        "lineType": "orthogonal",
        "text": edge.name,
        "source": {
            "graphNodeId": node_id_to_gliffy_id[edge.source],
        },
        "target": {
            "graphNodeId": node_id_to_gliffy_id[edge.target],
        },
        "waypoints": edge_waypoints(graph, edge),
        "metadata": {
            "sourceId": edge.id,
            "kind": "sequenceFlow",
        },
    }


def shape_type_for_node(node: Node) -> str:
    if node.kind == "start":
        return "circle.start"
    if node.kind == "end":
        return "circle.end"
    if node.kind == "gateway":
        return "diamond.gateway"
    if node.kind == "event":
        return "circle.event"
    return "roundedRect.task"


def convert_using_template(graph: Graph, template: dict) -> dict:
    """
    Inject generated objects into a user-provided Gliffy JSON export.

    Assumptions:
    - The template is a Gliffy export or close to it.
    - It contains a top-level object where one of these containers can hold generated objects:
      template["content"], template["stage"]["objects"], or template["objects"]

    This function is intentionally conservative and easy to edit.
    """
    out = copy.deepcopy(template)

    objects_list = None

    if isinstance(out, dict):
        if isinstance(out.get("content"), list):
            objects_list = out["content"]
        elif isinstance(out.get("objects"), list):
            objects_list = out["objects"]
        elif isinstance(out.get("stage"), dict) and isinstance(out["stage"].get("objects"), list):
            objects_list = out["stage"]["objects"]

    if objects_list is None:
        # Fall back to a simple generic envelope
        out = {
            "documentType": "gliffy",
            "version": "template-fallback",
            "title": graph.process_name,
            "objects": [],
        }
        objects_list = out["objects"]

    # Generate lanes first
    lane_gliffy_ids: Dict[str, str] = {}
    for lane in graph.lanes.values():
        lane_shape = base_shape_for_lane(lane)
        lane_gliffy_ids[lane.id] = lane_shape["id"]
        objects_list.append(lane_shape)

    # Generate nodes
    node_gliffy_ids: Dict[str, str] = {}
    for node in graph.nodes.values():
        shape = base_shape_for_node(node)
        node_gliffy_ids[node.id] = shape["id"]

        # Optional parent relationship if your Gliffy export uses it
        if node.lane_id and node.lane_id in lane_gliffy_ids:
            shape["parent"] = lane_gliffy_ids[node.lane_id]

        objects_list.append(shape)

    # Generate connectors
    for edge in graph.edges:
        if edge.source in node_gliffy_ids and edge.target in node_gliffy_ids:
            objects_list.append(base_line_for_edge(graph, edge, node_gliffy_ids))

    # Title if the template has somewhere suitable
    if "title" in out and not out["title"]:
        out["title"] = graph.process_name

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert BPMN 2.0 XML to Gliffy-style JSON.")
    parser.add_argument("input_bpmn", type=Path, help="Path to input BPMN 2.0 XML file")
    parser.add_argument("output_json", type=Path, help="Path to output JSON file")
    parser.add_argument(
        "--template",
        type=Path,
        help="Optional Gliffy JSON export to use as a template for a closer-to-real Gliffy output",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    args = parser.parse_args()

    graph = parse_bpmn(args.input_bpmn)

    if args.template:
        template = json.loads(args.template.read_text(encoding="utf-8"))
        out = convert_using_template(graph, template)
    else:
        out = to_intermediate_json(graph)

    args.output_json.write_text(
        json.dumps(out, indent=2 if args.pretty or True else None, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote {args.output_json}")


if __name__ == "__main__":
    main()
