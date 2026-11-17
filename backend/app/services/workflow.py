"""Incident lifecycle + orchestration of the multi-agent pipeline."""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.guardrails import record_guardrail, redact_pii, screen_text, validate_incident_payload
from app.llm.models import llm_mode
from app.models import (
    ActionItem,
    ActionPlan,
    AgentExecution,
    Escalation,
    Incident,
    IncidentEvent,
    IncidentVerification,
    ResolutionEvidence,
    SeverityAssessment,
    Team,
    WorkflowStateRecord,
)
from app.observability import cost_usd, tracer
from app.schemas import IncidentCreate, IncidentResolutionReport, ResolutionPlan, ReviewResult, SeverityResult, VerificationResult

OPEN_STATES = {"open", "in_review", "assigned", "in_progress", "awaiting_verification", "escalated"}


def _run_async(coro):
    """Run a coroutine from sync code, whether or not an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    ctx = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, asyncio.run, coro).result()


# ------------------------------------------------------------------ CRUD
def create_incident_record(db: Session, payload: IncidentCreate) -> Incident:
    valid, errors = validate_incident_payload(payload.model_dump())
    if not valid:
        raise ValueError("; ".join(errors))
    incident = Incident(
        incident_id=f"INC-{uuid.uuid4().hex[:6].upper()}",
        title=payload.title.strip(), description=payload.description.strip(), category=payload.category,
        incident_type=payload.incident_type, location=payload.location.strip(), supplier=payload.supplier,
        shipment_id=(payload.shipment_id or "").upper() or None, product_sku=(payload.product_sku or "").upper() or None,
        quantity_affected=payload.quantity_affected, reported_time=payload.reported_time or datetime.utcnow(),
        severity=payload.severity, status="open",
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    db.add(IncidentEvent(incident_id=incident.id, event_type="created", message="Incident reported and queued for AI intake."))
    db.commit()
    return incident


def get_incident_by_id(db: Session, incident_id: int) -> Incident | None:
    return db.query(Incident).filter(Incident.id == incident_id).first()


def list_incidents(db: Session, filters: Dict[str, Any]) -> List[Incident]:
    q = db.query(Incident).filter(Incident.incident_type != "evaluation")
    for key in ("severity", "status", "category"):
        if filters.get(key):
            q = q.filter(getattr(Incident, key) == filters[key])
    if filters.get("team"):
        q = q.filter(Incident.assigned_team_id == int(filters["team"]))
    if filters.get("q"):
        like = f"%{filters['q']}%"
        q = q.filter((Incident.title.ilike(like)) | (Incident.incident_id.ilike(like)) | (Incident.supplier.ilike(like)))
    return q.order_by(Incident.created_at.desc()).all()


# --------------------------------------------------------------- pipeline
def run_incident_workflow(db: Session, incident_id: int) -> Dict[str, Any]:
    incident = get_incident_by_id(db, incident_id)
    if not incident:
        raise ValueError("Incident not found")
    t0 = time.perf_counter()
    with tracer.span("workflow:incident_pipeline", kind="workflow", framework="SignalChain", new_trace=True,
                     incident_id=incident.id, input={"incident_id": incident.incident_id}, llm_mode=llm_mode()) as root:
        trace_id = root.trace_id

        # Guardrail: screen + redact PII before anything reaches an LLM.
        verdict = screen_text(f"{incident.title}\n{incident.description}")
        record_guardrail("input_screen", "workflow_start", verdict.allowed,
                         {"violations": verdict.violations, "pii_redactions": verdict.redactions}, incident.id)
        if not verdict.allowed:
            raise ValueError(f"Guardrails blocked this incident: {verdict.violations}")
        description, _ = redact_pii(incident.description)

        payload = {
            "id": incident.id, "incident_id": incident.incident_id, "title": incident.title, "description": description,
            "category": incident.category, "location": incident.location, "supplier": incident.supplier,
            "shipment_id": incident.shipment_id, "product_sku": incident.product_sku,
            "quantity_affected": incident.quantity_affected,
            "reported_time": incident.reported_time.isoformat() if incident.reported_time else None,
        }
        state = _run_async(_pipeline_in_context(payload))
        duration_ms = int((time.perf_counter() - t0) * 1000)
        usage = tracer.usage(trace_id)
        analysis = state["crew_analysis"]
        report = IncidentResolutionReport(
            report_id=f"RPT-{uuid.uuid4().hex[:8].upper()}",
            incident_id=incident.incident_id,
            title=incident.title,
            generated_at=datetime.now(timezone.utc),
            llm_mode=llm_mode(),
            category=state["normalized"]["category"],
            location=incident.location,
            verification=VerificationResult(**analysis["verification"]),
            severity=SeverityResult(**analysis["severity"]),
            plan=ResolutionPlan(**state["final_plan"]),
            review=ReviewResult(**state["review"]),
            context={"normalized": state.get("normalized"), "parsed_document": state.get("parsed_document"),
                     "supplier_shipment": state.get("supplier_shipment"), "inventory": state.get("inventory"),
                     "weather": state.get("weather")},
            provenance={"trace_id": trace_id, "adk_session_id": state.get("adk_session_id"), "a2a": state.get("a2a"),
                        "frameworks": {"coordinator": "Google ADK", "specialist": "CrewAI"},
                        "crew_fallback_used": state.get("crew_fallback_used", False),
                        "mcp_server": "signalchain-tools", "adk_events": len(state.get("adk_events", []))},
            metrics={"duration_ms": duration_ms, "tokens_in": usage["in"], "tokens_out": usage["out"],
                     "llm_calls": usage["llm_calls"], "estimated_cost_usd": cost_usd(usage["in"], usage["out"])},
        )
        root.output = {"severity": report.severity.level, "owner": report.plan.owner_team, "escalate": report.plan.escalate}
        _persist(db, incident, report, state, trace_id, duration_ms, usage)
    tracer.flush()
    return {"report": report.model_dump(mode="json"), "markdown": report.to_markdown(), "trace_id": trace_id,
            "adk_events": state.get("adk_events", []), "crew_monitor": state.get("crew_monitor", [])}


async def _pipeline_in_context(payload: Dict[str, Any]) -> Dict[str, Any]:
    from app.agents.google_adk import run_pipeline

    return await run_pipeline(payload)


def _persist(db: Session, incident: Incident, report: IncidentResolutionReport, state: Dict[str, Any], trace_id: str,
             duration_ms: int, usage: Dict[str, int]) -> None:
    v, s, p = report.verification, report.severity, report.plan
    workflow_id = f"WF-{uuid.uuid4().hex[:8].upper()}"
    db.add(WorkflowStateRecord(
        workflow_id=workflow_id, incident_id=incident.id, trace_id=trace_id, llm_mode=report.llm_mode,
        user_input={"title": incident.title, "description": incident.description},
        normalized_incident=state.get("normalized") or {}, verification_result=v.model_dump(),
        severity_assessment=s.model_dump(), operational_impact=s.impact.model_dump(),
        routing_result={"owner_team": p.owner_team, "priority": p.priority}, resolution_plan=p.model_dump(),
        agent_outputs={k: state.get(k) for k in ("intake_summary", "supplier_summary", "inventory_summary",
                                                  "weather_summary", "crew_summary", "review_summary")},
        monitoring_result={"adk_events": state.get("adk_events"), "crew_monitor": state.get("crew_monitor")},
        final_report=report.model_dump(mode="json"), execution_status="completed",
        tokens_in=usage["in"], tokens_out=usage["out"], cost_usd=str(report.metrics["estimated_cost_usd"]),
        duration_ms=duration_ms,
    ))
    db.add(IncidentVerification(incident_id=incident.id, completeness_score=v.completeness_score,
                                duplicate_score=v.duplicate_score, is_complete=not v.missing_fields,
                                status=v.status, notes=v.notes))
    db.add(SeverityAssessment(incident_id=incident.id, level=s.level, score=s.score, rationale=json.dumps(s.drivers),
                              operational_impact=s.impact.model_dump_json()))
    plan = ActionPlan(incident_id=incident.id, plan_summary=p.summary, suggested_owner=p.owner_team,
                      deadline_hours=p.deadline_hours, approved=False)
    db.add(plan)
    db.flush()
    for a in p.actions:
        db.add(ActionItem(plan_id=plan.id, title=a.title, owner=a.owner, due_hours=a.due_hours))
    team = db.query(Team).filter(Team.name == p.owner_team).first()
    incident.assigned_team_id = team.id if team else incident.assigned_team_id
    incident.severity = s.level
    incident.category = report.category
    incident.verification_status = v.status
    incident.duplicate_of = v.duplicate_of
    incident.approval_status = "pending" if report.review.human_approval_required else "auto_approved"
    incident.status = "in_review" if report.review.human_approval_required else "assigned"
    incident.alert_level = "red" if p.escalate else "normal"
    for fw, name in (("Google ADK", "incident_pipeline"), ("CrewAI", "specialist_crew")):
        db.add(AgentExecution(incident_id=incident.id, framework=fw, agent_name=name, input_summary=incident.incident_id,
                              output_summary=f"severity={s.level} owner={p.owner_team}", status="success",
                              duration_ms=duration_ms))
    db.add(IncidentEvent(incident_id=incident.id, event_type="workflow_ran",
                         message=f"AI pipeline: {s.level.upper()} · routed to {p.owner_team} · {p.priority} ({duration_ms} ms)."))
    if p.escalate:
        incident.escalation_count = (incident.escalation_count or 0) + 1
        db.add(Escalation(incident_id=incident.id, triggered_by="ai_pipeline", reason=p.escalation_reason, severity=s.level))
        db.add(IncidentEvent(incident_id=incident.id, event_type="escalated", message=f"Auto-escalated: {p.escalation_reason}"))
    db.commit()


# ------------------------------------------------------- human-in-the-loop
def latest_report(db: Session, incident_id: int) -> WorkflowStateRecord | None:
    return (db.query(WorkflowStateRecord).filter(WorkflowStateRecord.incident_id == incident_id)
            .order_by(WorkflowStateRecord.id.desc()).first())


def approve_action_plan(db: Session, incident_id: int, approved: bool, notes: str = "") -> Dict[str, Any]:
    incident = get_incident_by_id(db, incident_id)
    plan = db.query(ActionPlan).filter(ActionPlan.incident_id == incident_id).order_by(ActionPlan.id.desc()).first()
    if not incident or not plan:
        raise ValueError("Run the AI pipeline before approving a plan.")
    plan.approved, plan.rejected = approved, not approved
    incident.approval_status = "approved" if approved else "rejected"
    incident.status = "in_progress" if approved else "in_review"
    db.add(IncidentEvent(incident_id=incident.id, event_type="approval",
                         message=f"Plan {'approved' if approved else 'rejected'} by operator. {notes}".strip()))
    db.commit()
    return {"approved": approved, "plan_id": plan.id, "notes": notes}


def update_incident_status(db: Session, incident_id: int, status: str) -> Incident:
    incident = get_incident_by_id(db, incident_id)
    incident.status = status
    db.add(IncidentEvent(incident_id=incident.id, event_type="status_update", message=f"Status changed to {status}"))
    db.commit()
    return incident


def submit_resolution_evidence(db: Session, incident_id: int, summary: str, evidence_url: str | None = None) -> ResolutionEvidence:
    evidence = ResolutionEvidence(incident_id=incident_id, summary=summary, evidence_url=evidence_url)
    db.add(evidence)
    incident = get_incident_by_id(db, incident_id)
    incident.status = "awaiting_verification"
    db.add(IncidentEvent(incident_id=incident_id, event_type="resolution_evidence", message=f"Evidence submitted: {summary[:120]}"))
    db.commit()
    return evidence


def verify_resolution(db: Session, incident_id: int) -> Dict[str, Any]:
    evidence = (db.query(ResolutionEvidence).filter(ResolutionEvidence.incident_id == incident_id)
                .order_by(ResolutionEvidence.id.desc()).first())
    if not evidence:
        raise ValueError("Submit resolution evidence first.")
    incident = get_incident_by_id(db, incident_id)
    evidence.verified = True
    incident.status = "resolved"
    db.add(IncidentEvent(incident_id=incident_id, event_type="resolved", message="Resolution evidence verified."))
    db.commit()
    return {"verified": True, "incident_id": incident_id}


def close_incident(db: Session, incident_id: int) -> Incident:
    incident = get_incident_by_id(db, incident_id)
    incident.status = "closed"
    db.add(IncidentEvent(incident_id=incident.id, event_type="closed", message="Incident closed."))
    db.commit()
    return incident


def create_escalation(db: Session, incident_id: int, reason: str = "Manual escalation") -> Escalation:
    incident = get_incident_by_id(db, incident_id)
    escalation = Escalation(incident_id=incident.id, triggered_by="operator", reason=reason, severity=incident.severity or "high")
    db.add(escalation)
    incident.status = "escalated"
    incident.escalation_count = (incident.escalation_count or 0) + 1
    db.add(IncidentEvent(incident_id=incident.id, event_type="escalated", message=reason))
    db.commit()
    return escalation


# -------------------------------------------------------------- analytics
def compute_analytics(db: Session) -> Dict[str, Any]:
    incidents = db.query(Incident).filter(Incident.incident_type != "evaluation").all()
    total = len(incidents)
    now = datetime.utcnow()
    live_ids = {i.id for i in incidents}
    runs = [r for r in db.query(WorkflowStateRecord).all() if r.incident_id in live_ids]
    sev_order = ["low", "medium", "high", "critical"]
    by_day: Dict[str, int] = {}
    for i in incidents:
        d = i.reported_time.date().isoformat()
        by_day[d] = by_day.get(d, 0) + 1
    teams = {t.id: t.name for t in db.query(Team).all()}
    workload: Dict[str, int] = {n: 0 for n in teams.values()}
    for i in incidents:
        if i.assigned_team_id in teams and i.status in OPEN_STATES:
            workload[teams[i.assigned_team_id]] += 1
    return {
        "total_incidents": total,
        "open_incidents": sum(1 for i in incidents if i.status in OPEN_STATES),
        "critical_incidents": sum(1 for i in incidents if i.severity == "critical" and i.status in OPEN_STATES),
        "escalated_incidents": sum(1 for i in incidents if i.status == "escalated" or i.alert_level == "red"),
        "awaiting_approval": sum(1 for i in incidents if i.approval_status == "pending" and i.status == "in_review"),
        "resolved_incidents": sum(1 for i in incidents if i.status in {"resolved", "closed"}),
        "avg_age_hours": round(sum((now - i.reported_time).total_seconds() / 3600 for i in incidents) / total, 1) if total else 0,
        "pipeline_runs": len(runs),
        "avg_pipeline_ms": int(sum(r.duration_ms or 0 for r in runs) / len(runs)) if runs else 0,
        "total_cost_usd": round(sum(float(r.cost_usd or 0) for r in runs), 5),
        "severity_distribution": [{"name": k, "value": sum(1 for i in incidents if i.severity == k)} for k in sev_order],
        "category_distribution": sorted([{"name": c, "value": sum(1 for i in incidents if i.category == c)}
                                         for c in {i.category for i in incidents}], key=lambda x: -x["value"]),
        "team_workload": [{"team": k, "value": v} for k, v in workload.items()],
        "incident_trend": [{"date": d, "count": c} for d, c in sorted(by_day.items())[-14:]],
        "recent_incidents": [{"id": i.id, "incident_id": i.incident_id, "title": i.title, "severity": i.severity,
                              "status": i.status} for i in sorted(incidents, key=lambda x: x.created_at, reverse=True)[:6]],
    }
