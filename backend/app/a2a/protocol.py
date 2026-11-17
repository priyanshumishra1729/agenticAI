"""A2A (Agent2Agent) protocol pieces: agent cards, JSON-RPC server and client.

Two interoperable agents are exposed:
* ``crewai``      – SignalChain CrewAI Specialist (verification, severity, planning)
* ``coordinator`` – SignalChain ADK Coordinator   (end-to-end incident pipeline)

Discovery: ``GET /a2a/{agent}/.well-known/agent.json``
Messaging: ``POST /a2a/{agent}`` JSON-RPC 2.0, methods ``message/send`` and ``tasks/get``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.observability import tracer

PROTOCOL_VERSION = "0.2.5"


def agent_cards(base_url: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    base = (base_url or settings.public_base_url).rstrip("/")
    common = {"version": "1.0.0", "protocolVersion": PROTOCOL_VERSION, "preferredTransport": "JSONRPC",
              "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
              "defaultInputModes": ["application/json", "text/plain"], "defaultOutputModes": ["application/json"]}
    return {
        "crewai": {
            "name": "SignalChain CrewAI Specialist",
            "description": "CrewAI crew (3 agents) that verifies incidents, scores severity/impact and plans resolution.",
            "url": f"{base}/a2a/crewai",
            "provider": {"organization": "SignalChain", "framework": "CrewAI"},
            "skills": [
                {"id": "incident_analysis", "name": "Incident analysis",
                 "description": "Input data part {incident, intake}. Returns a CrewAnalysis artifact (verification, severity, plan).",
                 "tags": ["supply-chain", "verification", "severity", "planning"],
                 "examples": ["Analyse incident INC-1234 using the provided intake context"]},
            ],
            **common,
        },
        "coordinator": {
            "name": "SignalChain ADK Coordinator",
            "description": "Google ADK coordinator: intake, parallel context gathering via MCP, delegation to CrewAI over A2A, reflection review.",
            "url": f"{base}/a2a/coordinator",
            "provider": {"organization": "SignalChain", "framework": "Google ADK"},
            "skills": [
                {"id": "resolve_incident", "name": "Resolve incident",
                 "description": "Input data part {incident_id} for an existing incident. Returns an IncidentResolutionReport artifact.",
                 "tags": ["supply-chain", "orchestration"], "examples": ["Run the response pipeline for incident 3"]},
            ],
            **common,
        },
    }


def task_envelope(task_id: str, context_id: str, state: str, message: Dict[str, Any],
                  artifact: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    status: Dict[str, Any] = {"state": state, "timestamp": now}
    if error:
        status["message"] = {"role": "agent", "kind": "message", "messageId": uuid.uuid4().hex,
                             "parts": [{"kind": "text", "text": error}]}
    out = {"id": task_id, "contextId": context_id, "kind": "task", "status": status, "history": [message], "artifacts": []}
    if artifact is not None:
        out["artifacts"].append({"artifactId": uuid.uuid4().hex, "name": artifact.get("name", "result"),
                                 "parts": [{"kind": "data", "data": artifact["data"]}]})
    return out


def rpc_error(rpc_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


# ------------------------------------------------------------------ client
class A2AClient:
    """Minimal A2A client: discovers the remote agent card, then sends ``message/send``."""

    def __init__(self, agent: str = "crewai", base_url: Optional[str] = None) -> None:
        self.agent = agent
        target = base_url or settings.a2a_crewai_url
        if target == "inprocess":
            from app.main import app  # late import: avoids a cycle

            self._transport: Optional[httpx.AsyncBaseTransport] = httpx.ASGITransport(app=app)
            self.base_url = "http://signalchain.internal"
        else:
            self._transport = None
            self.base_url = target.rstrip("/").removesuffix(f"/a2a/{agent}")

    async def send(self, data: Dict[str, Any], text: str = "", timeout: float = 300.0) -> Dict[str, Any]:
        headers = {"content-type": "application/json"}
        tp = tracer.traceparent()
        if tp:
            headers["traceparent"] = tp
        message = {"role": "user", "kind": "message", "messageId": uuid.uuid4().hex,
                   "contextId": tracer.current_trace_id() or uuid.uuid4().hex,
                   "parts": ([{"kind": "text", "text": text}] if text else []) + [{"kind": "data", "data": data}]}
        body = {"jsonrpc": "2.0", "id": uuid.uuid4().hex[:12], "method": "message/send", "params": {"message": message}}
        async with httpx.AsyncClient(transport=self._transport, base_url=self.base_url, timeout=timeout) as client:
            with tracer.span(f"a2a:discover:{self.agent}", kind="a2a", framework="A2A") as sp:
                card = (await client.get(f"/a2a/{self.agent}/.well-known/agent.json")).json()
                sp.output = {"name": card.get("name"), "skills": [s["id"] for s in card.get("skills", [])]}
            with tracer.span(f"a2a:message/send→{card.get('name')}", kind="a2a", framework="A2A",
                             input={"method": "message/send", "messageId": message["messageId"]}) as sp:
                resp = await client.post(f"/a2a/{self.agent}", json=body, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
                if "error" in payload:
                    raise RuntimeError(f"A2A error {payload['error']}")
                task = payload["result"]
                sp.output = {"task_id": task["id"], "state": task["status"]["state"]}
                if task["status"]["state"] != "completed":
                    raise RuntimeError(f"A2A task {task['id']} {task['status']['state']}: {task['status'].get('message')}")
                return {"task": task, "data": task["artifacts"][0]["parts"][0]["data"], "card": card}
