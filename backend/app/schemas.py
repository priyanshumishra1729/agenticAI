"""Pydantic contracts: API payloads, MCP tool outputs, agent outputs and the final report."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["low", "medium", "high", "critical"]
Category = Literal[
    "transportation_delay",
    "supplier_failure",
    "inventory_shortage",
    "damaged_goods",
    "warehouse_disruption",
    "cold_chain_excursion",
    "quality_defect",
    "other",
]
TEAMS = ["Logistics", "Procurement", "Warehouse", "Inventory", "Quality", "Operations"]


# --------------------------------------------------------------------------- API
class TeamSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    owner: Optional[str] = None


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=5000)
    category: str = "other"
    location: str = Field(min_length=2, max_length=200)
    supplier: Optional[str] = Field(default=None, max_length=200)
    shipment_id: Optional[str] = Field(default=None, max_length=80)
    product_sku: Optional[str] = Field(default=None, max_length=80)
    quantity_affected: int = Field(default=0, ge=0, le=10_000_000)
    reported_time: Optional[datetime] = None
    incident_type: str = "general"
    severity: str = "medium"
    status: str = "open"


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    incident_id: str
    title: str
    description: str
    category: str
    incident_type: str
    location: str
    supplier: Optional[str]
    shipment_id: Optional[str]
    product_sku: Optional[str]
    quantity_affected: int
    reported_time: datetime
    severity: str
    status: str
    duplicate_of: Optional[str]
    verification_status: str
    escalation_count: int
    approval_status: str
    created_at: datetime
    updated_at: datetime
    assigned_team_id: Optional[int] = None
    assigned_team: Optional[TeamSchema] = None


class WorkflowStartRequest(BaseModel):
    reason: str = "manual"


class ApprovalRequest(BaseModel):
    approved: bool
    notes: Optional[str] = Field(default=None, max_length=1000)


class EvidenceRequest(BaseModel):
    summary: str = Field(min_length=5, max_length=2000)
    evidence_url: Optional[str] = Field(default=None, max_length=300)


class GuardrailCheckRequest(BaseModel):
    text: str = Field(max_length=10000)


# ---------------------------------------------------------- MCP tool outputs
class SupplierShipmentResult(BaseModel):
    found: bool
    supplier: Optional[Dict[str, Any]] = None
    shipment: Optional[Dict[str, Any]] = None
    alternates: List[str] = Field(default_factory=list)


class InventoryResult(BaseModel):
    found: bool
    sku: Optional[str] = None
    total_available: int = 0
    total_daily_demand: int = 0
    days_of_cover: float = 0.0
    warehouses: List[Dict[str, Any]] = Field(default_factory=list)


class HistoricalSearchResult(BaseModel):
    count: int
    incidents: List[Dict[str, Any]] = Field(default_factory=list)
    avg_resolution_hours: Optional[float] = None


class ParsedDocument(BaseModel):
    supplier: Optional[str] = None
    shipment_id: Optional[str] = None
    sku: Optional[str] = None
    quantity: Optional[int] = None
    location: Optional[str] = None
    category_hint: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)


class ImpactCalculation(BaseModel):
    shortage_units: int
    days_of_cover: float
    revenue_at_risk_usd: int
    expedite_cost_usd: int
    sla_breach_risk: Literal["low", "medium", "high"]


class WeatherRisk(BaseModel):
    location: str
    source: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    max_wind_kmh: Optional[float] = None
    precipitation_mm: Optional[float] = None
    risk_level: Literal["low", "moderate", "high", "unknown"] = "unknown"
    summary: str = ""


# ------------------------------------------------------------- agent outputs
class IntakeContext(BaseModel):
    """Produced by the ADK intake agent and shared via ADK session state."""

    normalized: Dict[str, Any]
    parsed_document: ParsedDocument
    supplier_shipment: SupplierShipmentResult
    inventory: InventoryResult
    weather: WeatherRisk


class VerificationResult(BaseModel):
    status: Literal["verified", "needs_more_info", "possible_duplicate"]
    completeness_score: int = Field(ge=0, le=100)
    duplicate_score: int = Field(ge=0, le=100)
    duplicate_of: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)
    data_conflicts: List[str] = Field(default_factory=list)
    notes: str = ""


class SeverityResult(BaseModel):
    level: Severity
    score: int = Field(ge=0, le=100)
    drivers: List[str] = Field(default_factory=list)
    impact: ImpactCalculation
    confidence: float = Field(ge=0, le=1)


class ActionStep(BaseModel):
    title: str
    owner: str
    due_hours: int = Field(ge=1, le=720)


class ResolutionPlan(BaseModel):
    owner_team: str
    priority: Literal["P1", "P2", "P3", "P4"]
    deadline_hours: int = Field(ge=1, le=720)
    summary: str
    actions: List[ActionStep] = Field(min_length=1)
    escalate: bool = False
    escalation_reason: str = ""

    @field_validator("owner_team")
    @classmethod
    def known_team(cls, v: str) -> str:
        if v not in TEAMS:
            raise ValueError(f"owner_team must be one of {TEAMS}")
        return v


class CrewAnalysis(BaseModel):
    """Returned by the CrewAI specialist over A2A."""

    verification: VerificationResult
    severity: SeverityResult
    plan: ResolutionPlan


class ReviewResult(BaseModel):
    approved_by_reviewer: bool
    issues: List[str] = Field(default_factory=list)
    adjustments: List[str] = Field(default_factory=list)
    human_approval_required: bool = True


class IncidentResolutionReport(BaseModel):
    """Final structured output of the multi-agent pipeline."""

    report_id: str
    incident_id: str
    title: str
    generated_at: datetime
    llm_mode: str
    category: str
    location: str
    verification: VerificationResult
    severity: SeverityResult
    plan: ResolutionPlan
    review: ReviewResult
    context: Dict[str, Any]
    provenance: Dict[str, Any]
    metrics: Dict[str, Any]

    def to_markdown(self) -> str:
        s, p, v = self.severity, self.plan, self.verification
        lines = [
            f"# Incident Resolution Report — {self.incident_id}",
            f"**{self.title}**  ·  {self.location}  ·  `{self.category}`",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Severity | **{s.level.upper()}** (score {s.score}/100, confidence {s.confidence:.0%}) |",
            f"| Owner team | {p.owner_team} |",
            f"| Priority / deadline | {p.priority} · {p.deadline_hours}h |",
            f"| Verification | {v.status} (completeness {v.completeness_score}%, duplicate risk {v.duplicate_score}%) |",
            f"| Shortage units | {s.impact.shortage_units} |",
            f"| Days of cover | {s.impact.days_of_cover} |",
            f"| Revenue at risk | ${s.impact.revenue_at_risk_usd:,} |",
            f"| Escalate | {'Yes — ' + p.escalation_reason if p.escalate else 'No'} |",
            "",
            "## Severity drivers",
            *[f"- {d}" for d in s.drivers],
            "",
            "## Action plan",
            "| # | Action | Owner | Due |",
            "|---|---|---|---|",
            *[f"| {i} | {a.title} | {a.owner} | {a.due_hours}h |" for i, a in enumerate(p.actions, 1)],
            "",
            "## Reviewer (reflection) notes",
            *([f"- {i}" for i in self.review.issues + self.review.adjustments] or ["- No issues found."]),
            "",
            f"_Generated {self.generated_at.isoformat()} · mode `{self.llm_mode}` · trace `{self.provenance.get('trace_id')}`_",
        ]
        return "\n".join(lines)


# ------------------------------------------------------------------- A2A
class A2APart(BaseModel):
    kind: Literal["text", "data"] = "data"
    text: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class A2AMessage(BaseModel):
    role: Literal["user", "agent"]
    parts: List[A2APart]
    messageId: str
    contextId: Optional[str] = None
    kind: Literal["message"] = "message"


class JsonRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)
