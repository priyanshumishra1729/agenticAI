from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.a2a.protocol import agent_cards
from app.core.config import settings
from app.database import get_db
from app.guardrails import record_guardrail, screen_text, validate_file_upload, validate_incident_payload
from app.llm.models import llm_mode
from app.models import (
    A2ATaskRecord, ActionItem, ActionPlan, EvaluationRun, GuardrailEvent, Incident, IncidentEvent, Team, ToolExecution,
    TraceSpan,
)
from app.observability import spans_for_trace, tracer
from app.schemas import ApprovalRequest, EvidenceRequest, GuardrailCheckRequest, IncidentCreate, IncidentOut
from app.services import workflow as wf

router = APIRouter()


@router.get("/health")
def api_health():
    return {"status": "ok", "llm_mode": llm_mode()}


@router.get("/system")
def system_info():
    from app.agents.google_adk import describe_pipeline

    return {
        "llm_mode": llm_mode(),
        "gemini_configured": bool(settings.gemini_api_key),
        "langfuse_enabled": tracer.langfuse_enabled,
        "a2a_crewai_url": settings.a2a_crewai_url,
        "external_apis": settings.enable_external_apis,
        "pipeline": describe_pipeline(),
        "agent_cards": agent_cards(settings.public_base_url),
        "pricing": {"input_per_m": settings.price_input_per_m, "output_per_m": settings.price_output_per_m},
    }


# ------------------------------------------------------------ incidents
@router.get("/incidents", response_model=list[IncidentOut])
def get_incidents(severity: Optional[str] = None, status: Optional[str] = None, category: Optional[str] = None,
                  team: Optional[int] = None, q: Optional[str] = None, db: Session = Depends(get_db)):
    return wf.list_incidents(db, {"severity": severity, "status": status, "category": category, "team": team, "q": q})


@router.post("/incidents", response_model=IncidentOut)
def create_incident(payload: IncidentCreate, db: Session = Depends(get_db)):
    valid, errors = validate_incident_payload(payload.model_dump())
    record_guardrail("incident_input", "api:create_incident", valid, errors or "clean")
    if not valid:
        raise HTTPException(status_code=400, detail={"errors": errors})
    return wf.create_incident_record(db, payload)


def _incident_or_404(db: Session, incident_id: int) -> Incident:
    incident = wf.get_incident_by_id(db, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.get("/incidents/{incident_id}", response_model=IncidentOut)
def incident_detail(incident_id: int, db: Session = Depends(get_db)):
    return _incident_or_404(db, incident_id)


@router.get("/incidents/{incident_id}/detail")
def incident_full(incident_id: int, db: Session = Depends(get_db)):
    inc = _incident_or_404(db, incident_id)
    run = wf.latest_report(db, incident_id)
    plan = db.query(ActionPlan).filter(ActionPlan.incident_id == incident_id).order_by(ActionPlan.id.desc()).first()
    report = run.final_report if run else None
    markdown = None
    if report:
        from app.schemas import IncidentResolutionReport

        markdown = IncidentResolutionReport.model_validate(report).to_markdown()
    return {
        "incident": IncidentOut.model_validate(inc).model_dump(mode="json"),
        "report": report,
        "markdown": markdown,
        "trace_id": run.trace_id if run else None,
        "monitoring": run.monitoring_result if run else None,
        "agent_outputs": run.agent_outputs if run else None,
        "plan": None if not plan else {"id": plan.id, "approved": plan.approved, "rejected": plan.rejected,
                                       "items": [{"title": a.title, "owner": a.owner, "due_hours": a.due_hours, "status": a.status}
                                                 for a in db.query(ActionItem).filter(ActionItem.plan_id == plan.id)]},
        "events": [{"type": e.event_type, "message": e.message, "at": e.created_at.isoformat()}
                   for e in db.query(IncidentEvent).filter(IncidentEvent.incident_id == incident_id).order_by(IncidentEvent.id.desc())],
        "tool_calls": [{"tool": t.tool_name, "caller": t.caller, "status": t.status, "duration_ms": t.duration_ms,
                        "arguments": t.arguments, "result": t.result}
                       for t in db.query(ToolExecution).filter(ToolExecution.trace_id == run.trace_id).order_by(ToolExecution.id)] if run else [],
        "guardrails": [{"check": g.check_name, "stage": g.stage, "passed": g.passed, "details": g.details,
                        "at": g.created_at.isoformat()}
                       for g in db.query(GuardrailEvent).filter(GuardrailEvent.trace_id == run.trace_id).order_by(GuardrailEvent.id)] if run else [],
    }


@router.post("/incidents/{incident_id}/workflow")
def start_workflow(incident_id: int, db: Session = Depends(get_db)):
    _incident_or_404(db, incident_id)
    try:
        return {"status": "ok", **wf.run_incident_workflow(db, incident_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/incidents/{incident_id}/report.md")
def report_markdown(incident_id: int, db: Session = Depends(get_db)):
    from fastapi.responses import PlainTextResponse

    from app.schemas import IncidentResolutionReport

    run = wf.latest_report(db, incident_id)
    if not run:
        raise HTTPException(status_code=404, detail="No report yet")
    return PlainTextResponse(IncidentResolutionReport.model_validate(run.final_report).to_markdown(), media_type="text/markdown")


def _action(fn, *args):
    try:
        return fn(*args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/incidents/{incident_id}/approve")
def approve_plan(incident_id: int, body: ApprovalRequest, db: Session = Depends(get_db)):
    return _action(wf.approve_action_plan, db, incident_id, body.approved, body.notes or "")


@router.patch("/incidents/{incident_id}/status")
def change_status(incident_id: int, status: str, db: Session = Depends(get_db)):
    _incident_or_404(db, incident_id)
    incident = wf.update_incident_status(db, incident_id, status)
    return {"status": "updated", "incident_id": incident.id, "new_status": incident.status}


@router.post("/incidents/{incident_id}/evidence")
def add_evidence(incident_id: int, payload: EvidenceRequest, db: Session = Depends(get_db)):
    _incident_or_404(db, incident_id)
    verdict = screen_text(payload.summary)
    if not verdict.allowed:
        record_guardrail("evidence_input", "api:evidence", False, verdict.violations, incident_id)
        raise HTTPException(status_code=400, detail={"errors": verdict.violations})
    evidence = wf.submit_resolution_evidence(db, incident_id, verdict.redacted_text, payload.evidence_url)
    return {"status": "stored", "evidence_id": evidence.id}


@router.post("/incidents/{incident_id}/verify-resolution")
def resolve_incident(incident_id: int, db: Session = Depends(get_db)):
    return _action(wf.verify_resolution, db, incident_id)


@router.post("/incidents/{incident_id}/close")
def close_incident_endpoint(incident_id: int, db: Session = Depends(get_db)):
    _incident_or_404(db, incident_id)
    return {"status": "closed", "incident_id": wf.close_incident(db, incident_id).id}


@router.post("/incidents/{incident_id}/escalate")
def escalate(incident_id: int, reason: str = "Manual escalation", db: Session = Depends(get_db)):
    _incident_or_404(db, incident_id)
    return {"status": "escalated", "escalation_id": wf.create_escalation(db, incident_id, reason).id}


@router.post("/incidents/{incident_id}/upload")
def upload_file(incident_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _incident_or_404(db, incident_id)
    data = file.file.read()
    valid, safe_name = validate_file_upload(file.filename or "upload.bin", len(data), settings.max_upload_size_mb)
    if not valid:
        raise HTTPException(status_code=400, detail=safe_name)
    os.makedirs(settings.upload_dir, exist_ok=True)
    destination = os.path.join(settings.upload_dir, f"{incident_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{safe_name}")
    with open(destination, "wb") as handle:
        handle.write(data)
    return {"status": "uploaded", "file": os.path.basename(destination)}


# ------------------------------------------------------------ analytics
@router.get("/analytics/summary")
def analytics_summary(db: Session = Depends(get_db)):
    return wf.compute_analytics(db)


@router.get("/teams")
def read_teams(db: Session = Depends(get_db)):
    return [{"id": t.id, "name": t.name, "code": t.code, "owner": t.owner} for t in db.query(Team).all()]


# ------------------------------------------------------------ guardrails
@router.post("/guardrails/check")
def guardrail_check(body: GuardrailCheckRequest):
    verdict = screen_text(body.text)
    record_guardrail("playground", "api:guardrails/check", verdict.allowed, verdict.violations or "clean")
    return verdict.as_dict()


@router.get("/guardrails/events")
def guardrail_events(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(GuardrailEvent).order_by(GuardrailEvent.id.desc()).limit(limit).all()
    total = db.query(func.count(GuardrailEvent.id)).scalar()
    blocked = db.query(func.count(GuardrailEvent.id)).filter(GuardrailEvent.passed.is_(False)).scalar()
    return {"total": total, "blocked": blocked,
            "events": [{"check": g.check_name, "stage": g.stage, "passed": g.passed, "details": g.details,
                        "incident_id": g.incident_id, "trace_id": g.trace_id, "at": g.created_at.isoformat()} for g in rows]}


# ------------------------------------------------------------------- MCP
@router.get("/mcp/tools")
async def list_mcp_tools():
    from app.mcp_client import list_tools

    return {"server": "signalchain-tools", "transport": "MCP (in-memory session; stdio via `python -m app.mcp_server`)",
            "tools": await list_tools()}


@router.post("/mcp/tools/{tool_name}")
async def execute_mcp_tool(tool_name: str, payload: Dict[str, Any]):
    from app.mcp_client import call_tool_async

    try:
        with tracer.span(f"api:mcp:{tool_name}", kind="workflow", framework="MCP", new_trace=True):
            return {"tool": tool_name, "status": "ok", "result": await call_tool_async(tool_name, payload or {}, caller="api")}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ------------------------------------------------------------------- A2A
@router.get("/a2a/agent-cards")
def a2a_cards():
    return {"cards": agent_cards(settings.public_base_url)}


@router.get("/a2a/tasks")
def a2a_tasks(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(A2ATaskRecord).order_by(A2ATaskRecord.id.desc()).limit(limit).all()
    return {"tasks": [{"task_id": r.task_id, "sender": r.sender, "receiver": r.receiver, "status": r.status,
                       "incident_id": r.incident_id, "error": r.error, "created_at": r.created_at.isoformat(),
                       "updated_at": r.updated_at.isoformat() if r.updated_at else None} for r in rows]}


# ---------------------------------------------------------------- traces
@router.get("/traces")
def list_traces(limit: int = 30, db: Session = Depends(get_db)):
    roots = (db.query(TraceSpan).filter(TraceSpan.parent_span_id.is_(None), TraceSpan.kind == "workflow")
             .order_by(TraceSpan.id.desc()).limit(limit).all())
    out = []
    for r in roots:
        agg = db.query(func.count(TraceSpan.id), func.sum(TraceSpan.tokens_in), func.sum(TraceSpan.tokens_out)).filter(
            TraceSpan.trace_id == r.trace_id).one()
        out.append({"trace_id": r.trace_id, "name": r.name, "status": r.status, "duration_ms": r.duration_ms,
                    "incident_id": r.incident_id, "input": r.input, "output": r.output, "spans": agg[0],
                    "tokens_in": agg[1] or 0, "tokens_out": agg[2] or 0, "created_at": r.created_at.isoformat()})
    return {"traces": out, "langfuse_enabled": tracer.langfuse_enabled}


@router.get("/traces/{trace_id}")
def trace_detail(trace_id: str, db: Session = Depends(get_db)):
    spans = spans_for_trace(db, trace_id)
    if not spans:
        raise HTTPException(status_code=404, detail="Trace not found")
    return {"trace_id": trace_id, "spans": spans}


# ------------------------------------------------------------ evaluation
@router.post("/evaluation/run")
def start_evaluation(background: BackgroundTasks, limit: Optional[int] = None):
    from app.evaluation.run_evaluation import new_run_id, run_evaluation

    run_id = new_run_id()
    background.add_task(run_evaluation, run_id=run_id, limit=limit)
    return {"status": "started", "run_id": run_id}


@router.get("/evaluation/runs")
def evaluation_runs(db: Session = Depends(get_db)):
    rows = db.query(EvaluationRun).order_by(EvaluationRun.id.desc()).limit(20).all()
    return {"runs": [{"run_id": r.run_id, "created_at": r.created_at.isoformat(), **(r.metrics or {})} for r in rows]}
