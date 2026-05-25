"""Pydantic entities mirroring the SQL schema.

Used both for repository return types (rows -> models) and for tool
return payloads serialized to the frontend.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Entity(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Part(_Entity):
    id: str
    name: str
    manufacturer: str
    appliance_type: str
    part_type: str
    price_cents: int
    in_stock: bool = True
    image_url: str = ""
    description: str = ""
    created_at: datetime | None = None


class Model(_Entity):
    id: str
    brand: str
    appliance_type: str
    year: int | None = None
    series: str | None = None
    manual_url: str = ""
    created_at: datetime | None = None


class Compatibility(_Entity):
    part_id: str
    model_id: str
    sub_assembly_only: bool = False
    requires_adapter: bool = False
    supersedes: str | None = None


class Symptom(_Entity):
    id: str
    description: str
    canonical_label: str
    appliance_type: str


class SymptomFix(_Entity):
    symptom_id: str
    part_id: str
    likelihood: float = 0.5
    common_cause_rank: int = 99


class InstallGuide(_Entity):
    id: str
    part_id: str
    difficulty: str = "Easy"
    estimated_minutes: int = 20
    tools_required: str = ""
    safety_warnings: str = ""
    steps: str
    video_url: str = ""
    series_fitment_hint: str | None = None


class RepairStory(_Entity):
    id: str
    appliance_type: str
    brand: str
    symptom_id: str | None = None
    title: str
    body: str
    fixing_part_id: str | None = None
