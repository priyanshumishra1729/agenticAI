"""A2A JSON-RPC endpoints (FastAPI router)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.a2a.protocol import agent_cards, rpc_error, task_envelope
from app.database import SessionLocal
from app.models import A2ATaskRecord
from app.observability import tracer

router = APIRouter()


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get("/.well-known/agent.json", include_in_schema=False)
def root_card(request: Request) -> Dict[str, Any]:
    return agent_cards(_base(request))["coordinator"]


@router.get("/a2a/{agent}/.well-known/agent.json")
def card(agent: str, request: Request) -> Dict[str, Any]:
    cards = agent_cards(_base(request))
    return cards.get(agent) or {"error": f"unknown agent {agent}"}


def _save(task_id: str, sender: str, receiver: str, state: str, payload: Dict[str, Any], result: Dict[str, Any],
          incident_id: Any, error: str = "") -> None:
    with SessionLocal() as db:
        rec = db.query(A2ATaskRecord).filter(A2ATaskRecord.task_id == task_id).first()
        if not rec:
            rec = A2ATaskRecord(task_id=task_id, sender=sender, receiver=receiver, task_type="message/send", payload=payload)
            db.add(rec)
        rec.incident_id = incident_id if isinstance(incident_id, int) else None
        rec.status, rec.result, rec.error, rec.updated_at = state, result, error, datetime.utcnow()
        db.commit()


@router.post("/a2a/{agent}")
async def rpc(agent: str, request: Request) -> Dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return rpc_error(None, -32700, "Parse error")
    rpc_id = body.get("id")
    if body.get("jsonrpc") != "2.0" or "method" not in body:
        return rpc_error(rpc_id, -32600, "Invalid Request")
    method, params = body["method"], body.get("params") or {}

    if method == "tasks/get":
        with SessionLocal() as db:
            rec = db.query(A2ATaskRecord).filter(A2ATaskRecord.task_id == params.get("id")).first()
        if not rec:
            return rpc_error(rpc_id, -32001, "Task not found")
        return {"jsonrpc": "2.0", "id": rpc_id, "result": task_envelope(
            rec.task_id, rec.task_id, rec.status, {"role": "user", "kind": "message", "messageId": rec.task_id, "parts": [{"kind": "data", "data": rec.payload}]},
            {"name": "result", "data": rec.result} if rec.result else None, rec.error or None)}

    if method != "message/send":
        return rpc_error(rpc_id, -32601, f"Method not found: {method}")
    message = params.get("message") or {}
    data = next((p.get("data") for p in message.get("parts", []) if p.get("kind") == "data"), None)
    if not isinstance(data, dict):
        return rpc_error(rpc_id, -32602, "Invalid params: message must contain a data part")

    task_id = f"A2A-{uuid.uuid4().hex[:10].upper()}"
    context_id = message.get("contextId") or uuid.uuid4().hex
    incident_db_id = (data.get("incident") or {}).get("id") if agent == "crewai" else data.get("incident_id")
    sender = "adk_coordinator" if agent == "crewai" else "external_client"
    receiver = {"crewai": "crewai_specialist", "coordinator": "adk_coordinator"}.get(agent)
    if receiver is None:
        return rpc_error(rpc_id, -32601, f"Unknown agent: {agent}")
    _save(task_id, sender, receiver, "working", data, {}, incident_db_id)

    def work() -> Dict[str, Any]:
        with tracer.continue_from(request.headers.get("traceparent"), incident_db_id if isinstance(incident_db_id, int) else None):
            with tracer.span(f"a2a:server:{receiver}", kind="a2a", framework="A2A", input={"task_id": task_id}, method=method):
                if agent == "crewai":
                    from app.agents.crewai_specialist import run_crew_analysis

                    return run_crew_analysis(data["incident"], data["intake"])
                from app.services.workflow import run_incident_workflow

                with SessionLocal() as db:
                    return run_incident_workflow(db, int(data["incident_id"]))["report"]

    try:
        result = await run_in_threadpool(work)
        _save(task_id, sender, receiver, "completed", data, result, incident_db_id)
        envelope = task_envelope(task_id, context_id, "completed", message,
                                 {"name": "crew_analysis" if agent == "crewai" else "incident_resolution_report", "data": result})
    except Exception as exc:
        _save(task_id, sender, receiver, "failed", data, {}, incident_db_id, f"{type(exc).__name__}: {exc}")
        envelope = task_envelope(task_id, context_id, "failed", message, error=f"{type(exc).__name__}: {exc}")
    return {"jsonrpc": "2.0", "id": rpc_id, "result": envelope}
