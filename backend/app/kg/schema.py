"""Knowledge graph schema. Typed node and edge representations.

The KG is a mirror of structured Postgres data, just in a representation
that makes multi-hop traversals trivial. Postgres remains source of truth;
the KG is derived. See architecture.md section 4 for full schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    PART = "Part"
    MODEL = "Model"
    BRAND = "Brand"
    APPLIANCE_TYPE = "ApplianceType"
    SYMPTOM = "Symptom"
    INSTALL_GUIDE = "InstallGuide"


class EdgeType(str, Enum):
    FITS = "FITS"                  # Part -> Model    (sub_assembly_only, requires_adapter, supersedes)
    MADE_BY = "MADE_BY"            # Part|Model -> Brand
    BELONGS_TO = "BELONGS_TO"      # Model -> ApplianceType
    FIXES = "FIXES"                # Part -> Symptom  (likelihood, common_cause_rank)
    OCCURS_IN = "OCCURS_IN"        # Symptom -> ApplianceType
    INSTALLED_VIA = "INSTALLED_VIA"  # Part -> InstallGuide


def brand_id(name: str) -> str:
    """Prefix-namespaced brand node id, e.g. 'brand:Whirlpool'.
    Avoids collisions with part / model IDs which are bare strings."""
    return f"brand:{name}"


def appliance_id(name: str) -> str:
    return f"appliance:{name}"


@dataclass(slots=True)
class FitsEdge:
    part_id: str
    model_id: str
    sub_assembly_only: bool = False
    requires_adapter: bool = False
    supersedes: str | None = None


@dataclass(slots=True)
class FixesEdge:
    part_id: str
    symptom_id: str
    likelihood: float = 0.5
    common_cause_rank: int = 99


@dataclass(slots=True)
class FixCandidate:
    """Tool 5 + troubleshoot output row: a part that fixes a symptom,
    optionally annotated with whether it fits a particular model."""

    part_id: str
    part_name: str
    price_cents: int
    in_stock: bool
    likelihood: float
    common_cause_rank: int
    fits_model: bool | None = None  # None when no model_id was supplied
    appliance_type: str = ""
    brand: str = ""


@dataclass(slots=True)
class NodeAttrs:
    """Container we attach to every NetworkX node for fast type-aware lookup."""

    node_type: NodeType
    data: dict[str, Any] = field(default_factory=dict)
