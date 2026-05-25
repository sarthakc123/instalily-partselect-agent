"""KnowledgeGraph protocol. Production target swaps NetworkX for Neo4j by
implementing this protocol; tool code never imports a concrete class."""

from __future__ import annotations

from typing import Protocol

from app.kg.schema import FitsEdge, FixCandidate


class KnowledgeGraph(Protocol):
    """The minimal surface tools call. New methods are added here as new
    tools need them, never one-offs in concrete implementations."""

    # ----- Structural queries -----

    def fits(self, part_id: str, model_id: str) -> FitsEdge | None:
        """Structured compatibility edge lookup. Source of truth for Tool 2's
        yes/no verdict. Prose inference is a separate, marked path."""
        ...

    def models_fitting_part(self, part_id: str) -> list[str]:
        ...

    def parts_fitting_model(self, model_id: str) -> list[str]:
        ...

    # ----- Brand / appliance traversals -----

    def brand_of_part(self, part_id: str) -> str | None:
        ...

    def brand_of_model(self, model_id: str) -> str | None:
        ...

    def appliance_of_model(self, model_id: str) -> str | None:
        ...

    def appliance_of_part(self, part_id: str) -> str | None:
        ...

    # ----- Symptom traversals -----

    def parts_fixing_symptom(
        self,
        symptom_id: str,
        model_id: str | None = None,
    ) -> list[FixCandidate]:
        """KG traversal: (symptom) -[FIXES]-> (part) -[FITS]-> (model if given).
        Returns FixCandidate rows sorted so model-fitting parts come first,
        then by common_cause_rank ASC, then by likelihood DESC."""
        ...

    def symptoms_occurring_in(self, appliance_type: str) -> list[str]:
        ...

    # ----- Install guide -----

    def install_guide_id_for_part(self, part_id: str) -> str | None:
        ...

    # ----- Stats / introspection -----

    def stats(self) -> dict[str, int]:
        """Counts of nodes by type and edges by type. Used by smoke tests
        and the /health endpoint."""
        ...
