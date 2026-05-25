"""NetworkX in-memory knowledge graph. Prototype implementation of the
KnowledgeGraph protocol. Production target is Neo4j.

The KG is built from Postgres on startup (or from a JSON snapshot for fast
restart). Postgres remains source of truth; this is a derived view that
makes multi-hop traversals trivial.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import networkx as nx

from app.kg.base import KnowledgeGraph
from app.kg.schema import (
    EdgeType,
    FitsEdge,
    FixCandidate,
    NodeType,
    appliance_id,
    brand_id,
)


class NetworkXKG(KnowledgeGraph):
    """One DiGraph for everything. Each edge carries a 'kind' attribute set
    to an EdgeType value. Each node carries a 'node_type' attribute set to a
    NodeType value plus a 'data' dict for entity metadata.

    Node-ID conventions:
      - Part:           bare PS-id, e.g. 'PS11752778'
      - Model:          bare model id, e.g. 'WDT780SAEM1'
      - Symptom:        bare SY-id
      - InstallGuide:   bare IG-id
      - Brand:          'brand:<name>'        (prefixed; collisions impossible)
      - ApplianceType:  'appliance:<name>'    (prefixed; collisions impossible)
    """

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()

    # ------------------------------------------------------------------
    # Builders (used by app.kg.builder)
    # ------------------------------------------------------------------

    def add_part(self, *, id: str, **data: Any) -> None:
        self._g.add_node(id, node_type=NodeType.PART, data=data)

    def add_model(self, *, id: str, **data: Any) -> None:
        self._g.add_node(id, node_type=NodeType.MODEL, data=data)

    def add_symptom(self, *, id: str, **data: Any) -> None:
        self._g.add_node(id, node_type=NodeType.SYMPTOM, data=data)

    def add_install_guide(self, *, id: str, **data: Any) -> None:
        self._g.add_node(id, node_type=NodeType.INSTALL_GUIDE, data=data)

    def add_brand(self, name: str) -> str:
        nid = brand_id(name)
        if nid not in self._g:
            self._g.add_node(nid, node_type=NodeType.BRAND, data={"name": name})
        return nid

    def add_appliance(self, name: str) -> str:
        nid = appliance_id(name)
        if nid not in self._g:
            self._g.add_node(nid, node_type=NodeType.APPLIANCE_TYPE, data={"name": name})
        return nid

    def add_fits(
        self,
        part_id: str,
        model_id: str,
        *,
        sub_assembly_only: bool = False,
        requires_adapter: bool = False,
        supersedes: str | None = None,
    ) -> None:
        self._g.add_edge(
            part_id,
            model_id,
            kind=EdgeType.FITS,
            sub_assembly_only=sub_assembly_only,
            requires_adapter=requires_adapter,
            supersedes=supersedes,
        )

    def add_made_by(self, src: str, brand: str) -> None:
        bid = self.add_brand(brand)
        self._g.add_edge(src, bid, kind=EdgeType.MADE_BY)

    def add_belongs_to(self, model_id: str, appliance: str) -> None:
        aid = self.add_appliance(appliance)
        self._g.add_edge(model_id, aid, kind=EdgeType.BELONGS_TO)

    def add_fixes(
        self,
        part_id: str,
        symptom_id: str,
        *,
        likelihood: float,
        common_cause_rank: int,
    ) -> None:
        self._g.add_edge(
            part_id,
            symptom_id,
            kind=EdgeType.FIXES,
            likelihood=likelihood,
            common_cause_rank=common_cause_rank,
        )

    def add_occurs_in(self, symptom_id: str, appliance: str) -> None:
        aid = self.add_appliance(appliance)
        self._g.add_edge(symptom_id, aid, kind=EdgeType.OCCURS_IN)

    def add_installed_via(self, part_id: str, guide_id: str) -> None:
        self._g.add_edge(part_id, guide_id, kind=EdgeType.INSTALLED_VIA)

    # ------------------------------------------------------------------
    # KnowledgeGraph protocol (queries)
    # ------------------------------------------------------------------

    def fits(self, part_id: str, model_id: str) -> FitsEdge | None:
        if not self._g.has_edge(part_id, model_id):
            return None
        attrs = self._g.edges[part_id, model_id]
        if attrs.get("kind") != EdgeType.FITS:
            return None
        return FitsEdge(
            part_id=part_id,
            model_id=model_id,
            sub_assembly_only=bool(attrs.get("sub_assembly_only", False)),
            requires_adapter=bool(attrs.get("requires_adapter", False)),
            supersedes=attrs.get("supersedes"),
        )

    def models_fitting_part(self, part_id: str) -> list[str]:
        if part_id not in self._g:
            return []
        return [
            target
            for target in self._g.successors(part_id)
            if self._g.edges[part_id, target].get("kind") == EdgeType.FITS
        ]

    def parts_fitting_model(self, model_id: str) -> list[str]:
        if model_id not in self._g:
            return []
        return [
            source
            for source in self._g.predecessors(model_id)
            if self._g.edges[source, model_id].get("kind") == EdgeType.FITS
        ]

    def brand_of_part(self, part_id: str) -> str | None:
        return self._first_brand_neighbor(part_id)

    def brand_of_model(self, model_id: str) -> str | None:
        return self._first_brand_neighbor(model_id)

    def _first_brand_neighbor(self, source: str) -> str | None:
        if source not in self._g:
            return None
        for target in self._g.successors(source):
            if self._g.edges[source, target].get("kind") == EdgeType.MADE_BY:
                return self._g.nodes[target]["data"]["name"]
        return None

    def appliance_of_model(self, model_id: str) -> str | None:
        if model_id not in self._g:
            return None
        for target in self._g.successors(model_id):
            if self._g.edges[model_id, target].get("kind") == EdgeType.BELONGS_TO:
                return self._g.nodes[target]["data"]["name"]
        return None

    def appliance_of_part(self, part_id: str) -> str | None:
        if part_id not in self._g:
            return None
        return self._g.nodes[part_id]["data"].get("appliance_type")

    def parts_fixing_symptom(
        self,
        symptom_id: str,
        model_id: str | None = None,
    ) -> list[FixCandidate]:
        if symptom_id not in self._g:
            return []
        candidates: list[FixCandidate] = []
        # Symptoms are FIX targets: walk predecessors (Part -[FIXES]-> Symptom).
        for part_id in self._g.predecessors(symptom_id):
            edge = self._g.edges[part_id, symptom_id]
            if edge.get("kind") != EdgeType.FIXES:
                continue
            part_data = self._g.nodes[part_id]["data"]
            fits_model: bool | None
            if model_id is None:
                fits_model = None
            else:
                fits_model = self.fits(part_id, model_id) is not None
            candidates.append(
                FixCandidate(
                    part_id=part_id,
                    part_name=part_data.get("name", ""),
                    price_cents=int(part_data.get("price_cents", 0)),
                    in_stock=bool(part_data.get("in_stock", True)),
                    likelihood=float(edge.get("likelihood", 0.5)),
                    common_cause_rank=int(edge.get("common_cause_rank", 99)),
                    fits_model=fits_model,
                    appliance_type=str(part_data.get("appliance_type", "")),
                    brand=str(part_data.get("manufacturer", "")),
                )
            )

        # Sort: fitting parts first (when model given), then by rank ASC, then by likelihood DESC.
        candidates.sort(
            key=lambda c: (
                0 if c.fits_model is True else 1 if c.fits_model is False else 2,
                c.common_cause_rank,
                -c.likelihood,
            )
        )
        return candidates

    def symptoms_occurring_in(self, appliance_type: str) -> list[str]:
        target = appliance_id(appliance_type)
        if target not in self._g:
            return []
        return [
            source
            for source in self._g.predecessors(target)
            if self._g.edges[source, target].get("kind") == EdgeType.OCCURS_IN
        ]

    def install_guide_id_for_part(self, part_id: str) -> str | None:
        if part_id not in self._g:
            return None
        for target in self._g.successors(part_id):
            if self._g.edges[part_id, target].get("kind") == EdgeType.INSTALLED_VIA:
                return target
        return None

    def stats(self) -> dict[str, int]:
        node_counts: dict[str, int] = defaultdict(int)
        for _, attrs in self._g.nodes(data=True):
            node_counts[str(attrs.get("node_type", "Unknown"))] += 1
        edge_counts: dict[str, int] = defaultdict(int)
        for _, _, attrs in self._g.edges(data=True):
            edge_counts[str(attrs.get("kind", "Unknown"))] += 1
        return {
            **{f"node_{k}": v for k, v in sorted(node_counts.items())},
            **{f"edge_{k}": v for k, v in sorted(edge_counts.items())},
            "total_nodes": self._g.number_of_nodes(),
            "total_edges": self._g.number_of_edges(),
        }

    # ------------------------------------------------------------------
    # Snapshot persistence (fast restart without re-querying Postgres)
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        """Serialize the graph to a JSON string. Node-link format is the
        NetworkX standard and survives round-trips of our edge attributes."""
        # node_link_data emits enums as their str() values, which is fine for
        # our str-enum subclasses; on load we map them back.
        data = nx.node_link_data(self._g, edges="edges")
        # Coerce enums -> their .value strings for clean JSON.
        for node in data["nodes"]:
            if isinstance(node.get("node_type"), NodeType):
                node["node_type"] = node["node_type"].value
        for edge in data["edges"]:
            if isinstance(edge.get("kind"), EdgeType):
                edge["kind"] = edge["kind"].value
        return json.dumps(data)

    @classmethod
    def from_json(cls, raw: str) -> "NetworkXKG":
        data = json.loads(raw)
        for node in data["nodes"]:
            if isinstance(node.get("node_type"), str):
                node["node_type"] = NodeType(node["node_type"])
        for edge in data["edges"]:
            if isinstance(edge.get("kind"), str):
                edge["kind"] = EdgeType(edge["kind"])
        kg = cls()
        kg._g = nx.node_link_graph(data, edges="edges", directed=True)
        return kg

    def save_snapshot(self, path: Path | str) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load_snapshot(cls, path: Path | str) -> "NetworkXKG":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
