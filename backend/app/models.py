from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), unique=True, nullable=False)
    code = Column(String(20), unique=True, nullable=False)
    owner = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    incidents = relationship("Incident", back_populates="assigned_team")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    role = Column(String(120), default="analyst")
    created_at = Column(DateTime, default=datetime.utcnow)


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(String(50), unique=True, index=True, nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(80), nullable=False)
    incident_type = Column(String(80), default="general")
    location = Column(String(200), nullable=False)
    supplier = Column(String(200), nullable=True)
    shipment_id = Column(String(80), nullable=True)
    product_sku = Column(String(80), nullable=True)
    quantity_affected = Column(Integer, default=0)
    reported_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    severity = Column(String(20), default="medium")
    status = Column(String(40), default="open")
    assigned_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    duplicate_of = Column(String(50), nullable=True)
    verification_status = Column(String(40), default="pending")
    escalation_count = Column(Integer, default=0)
    approval_required = Column(Boolean, default=True)
    approval_status = Column(String(30), default="pending")
    alert_level = Column(String(20), default="normal")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    assigned_team = relationship("Team", back_populates="incidents")
    attachments = relationship("IncidentAttachment", back_populates="incident")
    verification = relationship("IncidentVerification", back_populates="incident")
    duplicate_candidates = relationship("DuplicateCandidate", back_populates="incident")
    severity_assessment = relationship("SeverityAssessment", back_populates="incident")
    action_plans = relationship("ActionPlan", back_populates="incident")
    agent_executions = relationship("AgentExecution", back_populates="incident")
    events = relationship("IncidentEvent", back_populates="incident")
    evidence = relationship("ResolutionEvidence", back_populates="incident")
    escalations = relationship("Escalation", back_populates="incident")


class IncidentAttachment(Base):
    __tablename__ = "incident_attachments"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    file_name = Column(String(200), nullable=False)
    file_type = Column(String(50), nullable=False)
    storage_path = Column(String(300), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    incident = relationship("Incident", back_populates="attachments")


class IncidentVerification(Base):
    __tablename__ = "incident_verification"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    completeness_score = Column(Integer, default=0)
    duplicate_score = Column(Integer, default=0)
    is_complete = Column(Boolean, default=False)
    status = Column(String(30), default="pending")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    incident = relationship("Incident", back_populates="verification")


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    candidate_incident_id = Column(String(50), nullable=False)
    similarity = Column(Integer, default=0)
    reason = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    incident = relationship("Incident", back_populates="duplicate_candidates")


class SeverityAssessment(Base):
    __tablename__ = "severity_assessments"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    level = Column(String(20), default="medium")
    score = Column(Integer, default=0)
    rationale = Column(Text, default="")
    operational_impact = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    incident = relationship("Incident", back_populates="severity_assessment")


class ActionPlan(Base):
    __tablename__ = "action_plans"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    plan_summary = Column(Text, default="")
    suggested_owner = Column(String(120), default="")
    deadline_hours = Column(Integer, default=24)
    approved = Column(Boolean, default=False)
    rejected = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    incident = relationship("Incident", back_populates="action_plans")
    action_items = relationship("ActionItem", back_populates="plan")


class ActionItem(Base):
    __tablename__ = "action_items"
    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("action_plans.id"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    owner = Column(String(120), default="")
    due_hours = Column(Integer, default=12)
    status = Column(String(40), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    plan = relationship("ActionPlan", back_populates="action_items")


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    framework = Column(String(40), default="crewai")
    agent_name = Column(String(120), nullable=False)
    input_summary = Column(Text, default="")
    output_summary = Column(Text, default="")
    status = Column(String(40), default="success")
    duration_ms = Column(Integer, default=0)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    incident = relationship("Incident", back_populates="agent_executions")


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    event_type = Column(String(80), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    incident = relationship("Incident", back_populates="events")


class ResolutionEvidence(Base):
    __tablename__ = "resolution_evidence"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    summary = Column(Text, nullable=False)
    evidence_url = Column(String(300), nullable=True)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    incident = relationship("Incident", back_populates="evidence")


class Escalation(Base):
    __tablename__ = "escalations"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    triggered_by = Column(String(80), default="monitoring")
    reason = Column(Text, default="")
    severity = Column(String(20), default="high")
    acknowledged = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    incident = relationship("Incident", back_populates="escalations")


class WorkflowStateRecord(Base):
    __tablename__ = "workflow_state_records"
    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(String(120), unique=True, nullable=False, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    user_input = Column(JSON, default={})
    normalized_incident = Column(JSON, default={})
    verification_result = Column(JSON, default={})
    duplicate_candidates = Column(JSON, default=[])
    severity_assessment = Column(JSON, default={})
    operational_impact = Column(JSON, default={})
    routing_result = Column(JSON, default={})
    resolution_plan = Column(JSON, default={})
    approval_status = Column(String(30), default="pending")
    monitoring_result = Column(JSON, default={})
    escalation_result = Column(JSON, default={})
    resolution_evidence = Column(JSON, default={})
    agent_outputs = Column(JSON, default={})
    execution_status = Column(String(30), default="initialized")
    errors = Column(JSON, default=[])
    final_report = Column(JSON, default={})
    trace_id = Column(String(64), nullable=True, index=True)
    llm_mode = Column(String(30), default="simulated")
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(String(20), default="0")
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    incident = relationship("Incident", back_populates="workflow_state")


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)
    tool_name = Column(String(120), nullable=False)
    trace_id = Column(String(64), nullable=True, index=True)
    caller = Column(String(120), default="")
    arguments = Column(JSON, default={})
    result = Column(JSON, default={})
    status = Column(String(20), default="ok")
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    incident = relationship("Incident", back_populates="tool_executions")


class A2ATaskRecord(Base):
    __tablename__ = "a2a_tasks"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(120), unique=True, nullable=False, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)
    sender = Column(String(120), nullable=False)
    receiver = Column(String(120), nullable=False)
    task_type = Column(String(120), default="workflow")
    status = Column(String(30), default="queued")
    payload = Column(JSON, default={})
    result = Column(JSON, default={})
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    incident = relationship("Incident", back_populates="a2a_tasks")


class GuardrailEvent(Base):
    __tablename__ = "guardrail_events"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)
    trace_id = Column(String(64), nullable=True, index=True)
    check_name = Column(String(80), default="input")
    stage = Column(String(80), default="input")
    passed = Column(Boolean, default=True)
    details = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    incident = relationship("Incident", back_populates="guardrail_events")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String(120), unique=True, nullable=False, index=True)
    metrics = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemSettings(Base):
    __tablename__ = "system_settings"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(80), unique=True, nullable=False)
    value = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


Incident.workflow_state = relationship("WorkflowStateRecord", back_populates="incident", uselist=False)
Incident.tool_executions = relationship("ToolExecution", back_populates="incident")
Incident.a2a_tasks = relationship("A2ATaskRecord", back_populates="incident")
Incident.guardrail_events = relationship("GuardrailEvent", back_populates="incident")


# --- Reference data used by the MCP database-lookup tools -------------------
class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True)
    supplier_id = Column(String(20), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    country = Column(String(80), default="")
    reliability = Column(Integer, default=80)  # 0-100
    tier = Column(String(10), default="T1")
    alternates = Column(JSON, default=[])


class Shipment(Base):
    __tablename__ = "shipments"
    id = Column(Integer, primary_key=True)
    shipment_id = Column(String(40), unique=True, nullable=False)
    supplier_name = Column(String(200), nullable=False)
    sku = Column(String(40), nullable=False)
    origin = Column(String(120), default="")
    destination = Column(String(120), default="")
    status = Column(String(40), default="in_transit")
    eta_hours = Column(Integer, default=24)
    value_usd = Column(Integer, default=0)


class InventoryRecord(Base):
    __tablename__ = "inventory"
    id = Column(Integer, primary_key=True)
    sku = Column(String(40), nullable=False, index=True)
    product_name = Column(String(200), default="")
    warehouse = Column(String(120), nullable=False)
    on_hand = Column(Integer, default=0)
    reserved = Column(Integer, default=0)
    daily_demand = Column(Integer, default=10)
    capacity = Column(Integer, default=1000)
    unit_cost_usd = Column(Integer, default=10)


class TraceSpan(Base):
    """Locally persisted trace spans (auditability + provenance)."""

    __tablename__ = "trace_spans"
    id = Column(Integer, primary_key=True)
    trace_id = Column(String(64), index=True, nullable=False)
    span_id = Column(String(32), index=True, nullable=False)
    parent_span_id = Column(String(32), nullable=True)
    incident_id = Column(Integer, nullable=True, index=True)
    name = Column(String(200), nullable=False)
    kind = Column(String(40), default="span")  # workflow|agent|llm|tool|a2a|guardrail|callback
    framework = Column(String(40), default="")
    status = Column(String(20), default="ok")
    input = Column(JSON, default={})
    output = Column(JSON, default={})
    attributes = Column(JSON, default={})
    error = Column(Text, default="")
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    start_ms = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
