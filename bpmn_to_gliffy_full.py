
import xml.etree.ElementTree as ET
import json
import uuid
import sys
from collections import defaultdict

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI"
}


def uid():
    return str(uuid.uuid4())


class BPMNGraph:

    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.lanes = {}

    def add_node(self, nid, name, ntype, lane=None, x=0, y=0, w=120, h=80):
        self.nodes[nid] = {
            "id": nid,
            "name": name,
            "type": ntype,
            "lane": lane,
            "x": x,
            "y": y,
            "w": w,
            "h": h
        }

    def add_edge(self, source, target, name=""):
        self.edges.append({
            "source": source,
            "target": target,
            "name": name
        })

    def add_lane(self, lid, name):
        self.lanes[lid] = {
            "id": lid,
            "name": name
        }


def parse_bpmn(path):

    tree = ET.parse(path)
    root = tree.getroot()

    process = root.find("bpmn:process", NS)

    g = BPMNGraph()

    for lane in process.findall(".//bpmn:lane", NS):
        lid = lane.attrib["id"]
        name = lane.attrib.get("name", lid)

        g.add_lane(lid, name)

        for ref in lane.findall("bpmn:flowNodeRef", NS):
            g.nodes.setdefault(ref.text, {})["lane"] = lid

    for elem in process:

        tag = elem.tag.split("}")[-1]

        if tag in ["task", "userTask", "serviceTask"]:

            g.add_node(
                elem.attrib["id"],
                elem.attrib.get("name", ""),
                "task"
            )

        elif tag == "startEvent":

            g.add_node(
                elem.attrib["id"],
                elem.attrib.get("name", ""),
                "start",
                w=40,
                h=40
            )

        elif tag == "endEvent":

            g.add_node(
                elem.attrib["id"],
                elem.attrib.get("name", ""),
                "end",
                w=40,
                h=40
            )

        elif "Gateway" in tag:

            g.add_node(
                elem.attrib["id"],
                elem.attrib.get("name", ""),
                "gateway",
                w=50,
                h=50
            )

        elif tag == "sequenceFlow":

            g.add_edge(
                elem.attrib["sourceRef"],
                elem.attrib["targetRef"],
                elem.attrib.get("name", "")
            )

    auto_layout(g)

    return g


def auto_layout(graph):

    levels = defaultdict(int)

    for e in graph.edges:
        levels[e["target"]] = max(levels[e["target"]], levels[e["source"]] + 1)

    for i, node in enumerate(graph.nodes.values()):
        node["x"] = 150 + levels[node["id"]] * 220
        node["y"] = 120 + i * 120


def shape_type(node):

    if node["type"] == "start":
        return "circle"

    if node["type"] == "end":
        return "circle"

    if node["type"] == "gateway":
        return "diamond"

    return "rectangle"


def create_lane(lane):

    return {
        "id": uid(),
        "type": "Swimlane",
        "text": {"text": lane["name"]},
        "x": 40,
        "y": 40,
        "width": 2000,
        "height": 200,
        "uid": uid()
    }


def create_shape(node, parent=None):

    return {
        "id": uid(),
        "uid": uid(),
        "type": "Shape",
        "shape": shape_type(node),
        "x": node["x"],
        "y": node["y"],
        "width": node["w"],
        "height": node["h"],
        "text": {"text": node["name"]},
        "parent": parent
    }


def create_connector(edge, node_map):

    return {
        "id": uid(),
        "uid": uid(),
        "type": "Line",
        "source": node_map[edge["source"]],
        "target": node_map[edge["target"]],
        "text": {"text": edge["name"]}
    }


def build_gliffy(graph, template):

    objects = template["stage"]["objects"]

    node_map = {}
    lane_map = {}

    for lane in graph.lanes.values():

        shape = create_lane(lane)

        objects.append(shape)

        lane_map[lane["id"]] = shape["id"]

    for node in graph.nodes.values():

        parent = None

        if node.get("lane") in lane_map:
            parent = lane_map[node["lane"]]

        shape = create_shape(node, parent)

        objects.append(shape)

        node_map[node["id"]] = shape["id"]

    for edge in graph.edges:

        if edge["source"] not in node_map:
            continue

        if edge["target"] not in node_map:
            continue

        line = create_connector(edge, node_map)

        objects.append(line)

    return template


def convert(bpmn_file, template_file, output_file):

    graph = parse_bpmn(bpmn_file)

    with open(template_file) as f:
        template = json.load(f)

    result = build_gliffy(graph, template)

    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print("Gliffy file written:", output_file)


if __name__ == "__main__":

    if len(sys.argv) != 4:

        print("Usage:")
        print("python bpmn_to_gliffy_full.py input.bpmn template.json output.json")
        sys.exit(1)

    convert(sys.argv[1], sys.argv[2], sys.argv[3])
