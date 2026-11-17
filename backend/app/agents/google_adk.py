"""Google ADK coordinator.

incident_pipeline (SequentialAgent)
 ├─ intake_agent            parse report via MCP document_parser → state.normalized
 ├─ context_gatherers (ParallelAgent)      ← fan-out pattern
 │   ├─ supplier_agent      MCP supplier_shipment_lookup  → state.supplier_shipment
 │   ├─ inventory_agent     MCP inventory_lookup          → state.inventory
 │   └─ weather_agent       MCP weather_risk (external)   → state.weather
 ├─ crew_liaison_agent      A2A message/send → CrewAI specialist → state.crew_analysis
 └─ reviewer_agent          reflection / critic over the crew plan → state.review, state.final_plan

Context sharing: every intermediate output is written to ADK session state
(``tool_context.state``) and read by downstream agents (instructions are templated
from state, tools read state directly).
Callbacks: before/after agent, model and tool → tracing, guardrails, type checking.
"""


import json
import time
from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext
from google.adk.tools.base_tool import BaseTool
from google.genai import types

from app.a2a.protocol import A2AClient
from app.guardrails import detect_prompt_injection, record_guardrail, validate_tool_args
from app.llm.models import adk_model
from app.mcp_client import call_tool_async
from app.observability import Span, tracer

APP_NAME = "signalchain"
VALID_CATEGORIES = {"transportation_delay", "supplier_failure", "inventory_shortage", "damaged_goods",
                    "warehouse_disruption", "cold_chain_excursion", "quality_defect", "other"}


# =================================================================== tools
async def parse_incident_report(description: str, tool_context: ToolContext) -> Dict[str, Any]:
    """Parse the free-text incident report with the MCP document_parser and normalise the incident record."""
    parsed = await call_tool_async("document_parser", {"description": description}, caller="adk:intake_agent")
    inc = dict(tool_context.state.get("incident") or {})
    normalized = {
        **inc,
        "supplier": inc.get("supplier") or parsed.get("supplier"),
        "shipment_id": inc.get("shipment_id") or parsed.get("shipment_id"),
        "product_sku": inc.get("product_sku") or parsed.get("sku"),
        "quantity_affected": inc.get("quantity_affected") or parsed.get("quantity") or 0,
        "category": inc.get("category") if inc.get("category") in VALID_CATEGORIES - {"other"}
        else (parsed.get("category_hint") or "other"),
    }
    filled = [k for k in ("supplier", "shipment_id", "product_sku", "quantity_affected", "category")
              if normalized.get(k) != inc.get(k)]
    tool_context.state["parsed_document"] = parsed
    tool_context.state["normalized"] = normalized
    tool_context.state["normalized_json"] = json.dumps(
        {k: normalized.get(k) for k in ("supplier", "shipment_id", "product_sku", "location", "category")})
    return {"normalized": normalized, "fields_inferred_from_text": filled}


async def lookup_supplier_and_shipment(supplier: str, shipment_id: str, tool_context: ToolContext) -> Dict[str, Any]:
    """Look up the supplier profile and shipment status in the operational database (MCP)."""
    out = await call_tool_async("supplier_shipment_lookup", {"supplier": supplier or "", "shipment_id": shipment_id or ""},
                                caller="adk:supplier_agent")
    tool_context.state["supplier_shipment"] = out
    return out


async def lookup_inventory(product_sku: str, tool_context: ToolContext) -> Dict[str, Any]:
    """Look up stock, demand and days of cover for the affected SKU (MCP)."""
    out = await call_tool_async("inventory_lookup", {"product_sku": product_sku or ""}, caller="adk:inventory_agent")
    tool_context.state["inventory"] = out
    return out


async def check_weather_risk(location: str, tool_context: ToolContext) -> Dict[str, Any]:
    """Fetch live 48h weather disruption risk for the incident location (MCP → Open-Meteo)."""
    out = await call_tool_async("weather_risk", {"location": location or ""}, caller="adk:weather_agent")
    tool_context.state["weather"] = out
    return out


async def delegate_to_crewai_specialist(tool_context: ToolContext) -> Dict[str, Any]:
    """Send the shared intake context to the CrewAI specialist agent over the A2A protocol and store its analysis."""
    st = tool_context.state
    intake = {k: st.get(k) for k in ("parsed_document", "supplier_shipment", "inventory", "weather")}
    resp = await A2AClient("crewai").send({"incident": st.get("normalized"), "intake": intake},
                                          text="Analyse this incident: verification, severity and resolution plan.")
    data = resp["data"]
    st["crew_analysis"] = data["analysis"]
    st["crew_monitor"] = data.get("monitor", [])
    st["crew_fallback_used"] = data.get("fallback_used", False)
    st["a2a"] = {"task_id": resp["task"]["id"], "remote_agent": resp["card"]["name"],
                 "protocol": resp["card"].get("protocolVersion"), "state": resp["task"]["status"]["state"]}
    a = data["analysis"]
    return {"a2a_task_id": resp["task"]["id"], "severity": a["severity"]["level"], "owner_team": a["plan"]["owner_team"],
            "verification": a["verification"]["status"]}


async def review_resolution_plan(tool_context: ToolContext) -> Dict[str, Any]:
    """Reflection step: critique the CrewAI plan against all gathered context and apply corrections."""
    st = tool_context.state
    analysis = json.loads(json.dumps(st.get("crew_analysis") or {}))
    plan, sev, ver = analysis["plan"], analysis["severity"], analysis["verification"]
    weather = st.get("weather") or {}
    sup = (st.get("supplier_shipment") or {})
    inc = st.get("normalized") or {}
    issues: List[str] = []
    adjustments: List[str] = []

    if sev["level"] == "critical" and not plan["escalate"]:
        issues.append("Critical incident was not escalated.")
        plan["escalate"], plan["escalation_reason"] = True, "critical severity (reviewer)"
        adjustments.append("Enabled escalation for critical severity.")
    if weather.get("risk_level") == "high" and inc.get("category") in {"transportation_delay", "cold_chain_excursion"}:
        plan["actions"].append({"title": f"Weather contingency: pre-book alternate lane around {weather.get('location')}",
                                "owner": plan["owner_team"], "due_hours": plan["deadline_hours"]})
        adjustments.append("Added weather contingency action (live forecast shows high risk).")
    reliability = ((sup.get("supplier") or {}).get("reliability") or 100)
    if reliability < 75 and sup.get("alternates") and not any("alternate supplier" in a["title"].lower() for a in plan["actions"]):
        plan["actions"].append({"title": f"Qualify alternate supplier ({sup['alternates'][0]}) – primary reliability {reliability}%",
                                "owner": "Procurement", "due_hours": plan["deadline_hours"]})
        adjustments.append("Added alternate-supplier action due to low supplier reliability.")
    if ver["status"] == "possible_duplicate":
        issues.append(f"Possible duplicate of {ver.get('duplicate_of')} – confirm before dispatching teams.")
    if ver["data_conflicts"]:
        issues.extend(ver["data_conflicts"])
    if sev["confidence"] < 0.7:
        issues.append(f"Low assessment confidence ({sev['confidence']:.0%}); human validation advised.")
    if any(a["due_hours"] > plan["deadline_hours"] for a in plan["actions"]):
        issues.append("Action due dates exceeded plan deadline – clamped.")
        for a in plan["actions"]:
            a["due_hours"] = min(a["due_hours"], plan["deadline_hours"])

    review = {"approved_by_reviewer": not any("not escalated" in i for i in issues) or bool(adjustments),
              "issues": issues, "adjustments": adjustments,
              "human_approval_required": sev["level"] in {"high", "critical"} or bool(issues)}
    st["review"] = review
    st["final_plan"] = plan
    return review


# =============================================================== callbacks
_open_spans: Dict[str, Span] = {}


def _agent_key(ctx: CallbackContext) -> str:
    return f"{ctx.invocation_id}:{ctx.agent_name}"


def before_agent(callback_context: CallbackContext) -> Optional[types.Content]:
    _open_spans[_agent_key(callback_context)] = tracer.begin(f"adk:agent:{callback_context.agent_name}", kind="agent",
                                                             framework="Google ADK")
    return None


def after_agent(callback_context: CallbackContext) -> Optional[types.Content]:
    keys = {"intake_agent": "normalized", "supplier_agent": "supplier_shipment", "inventory_agent": "inventory",
            "weather_agent": "weather", "crew_liaison_agent": "a2a", "reviewer_agent": "review"}
    key = keys.get(callback_context.agent_name)
    out = {"state_key": key, "value": callback_context.state.get(key)} if key else None
    tracer.end(_open_spans.pop(_agent_key(callback_context), None), output=out)
    return None


def before_model(callback_context: CallbackContext, llm_request: LlmRequest) -> Optional[LlmResponse]:
    # Guardrail: scan the text going to the model for prompt-injection (defence in depth).
    text = " ".join(p.text or "" for c in (llm_request.contents or []) for p in (c.parts or []) if p.text and c.role == "user")
    hits = detect_prompt_injection(text)
    if hits:
        record_guardrail("llm_input_injection", callback_context.agent_name, False, hits)
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(
            {"blocked": True, "reason": "prompt injection detected in model input"}))]))
    _open_spans[_agent_key(callback_context) + ":llm"] = tracer.begin(
        f"llm:adk:{callback_context.agent_name}", kind="llm", framework="Google ADK",
        parent=_open_spans.get(_agent_key(callback_context)),
        input={"tools": list((llm_request.tools_dict or {}).keys()), "n_contents": len(llm_request.contents or [])},
        model=getattr(llm_request, "model", None) or "adk-model")
    return None


def after_model(callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
    sp = _open_spans.pop(_agent_key(callback_context) + ":llm", None)
    usage = llm_response.usage_metadata
    tin = int(getattr(usage, "prompt_token_count", 0) or 0)
    tout = int(getattr(usage, "candidates_token_count", 0) or 0)
    tracer.add_usage(tin, tout)
    parts = (llm_response.content.parts if llm_response.content else None) or []
    out = [{"function_call": p.function_call.name, "args": p.function_call.args} if p.function_call else {"text": (p.text or "")[:400]}
           for p in parts]
    if sp:
        sp.tokens_in, sp.tokens_out = tin, tout
    tracer.end(sp, output=out, status="error" if llm_response.error_code else None, error=llm_response.error_message or "")
    return None


def before_tool(tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext) -> Optional[Dict[str, Any]]:
    func = getattr(tool, "func", None)
    problems = validate_tool_args(func, args) if func else []
    if problems:
        record_guardrail("tool_input_types", tool.name, False, problems)
        return {"error": "guardrail rejected tool call", "problems": problems}
    _open_spans[f"tool:{tool_context.function_call_id}"] = tracer.begin(
        f"adk:tool:{tool.name}", kind="tool", framework="Google ADK", input=args,
        parent=_open_spans.get(_agent_key(tool_context)))
    return None


def after_tool(tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext, tool_response: Any) -> Optional[Dict[str, Any]]:
    sp = _open_spans.pop(f"tool:{tool_context.function_call_id}", None)
    if not isinstance(tool_response, dict):
        record_guardrail("tool_output_type", tool.name, False, f"expected dict, got {type(tool_response).__name__}")
        tracer.end(sp, output=str(tool_response)[:500], status="error", error="non-dict tool response")
        return {"error": "tool returned an unexpected type"}
    tracer.end(sp, output=tool_response)
    return None


CALLBACKS = dict(before_agent_callback=before_agent, after_agent_callback=after_agent,
                 before_model_callback=before_model, after_model_callback=after_model,
                 before_tool_callback=before_tool, after_tool_callback=after_tool)


# =============================================================== pipeline
def build_pipeline() -> SequentialAgent:
    model = adk_model()

    def agent(name: str, desc: str, instruction: str, tools: list, output_key: str) -> LlmAgent:
        return LlmAgent(name=name, model=model, description=desc, instruction=instruction, tools=tools,
                        output_key=output_key, **CALLBACKS)

    intake = agent("intake_agent", "Normalises raw incident reports.",
                   "You are the intake agent of a supply-chain control tower. Call parse_incident_report with the "
                   "incident description, then summarise the normalised record in one sentence.\n"
                   "INCIDENT_JSON: {incident_json}", [parse_incident_report], "intake_summary")
    supplier = agent("supplier_agent", "Supplier and shipment lookups.",
                     "Call lookup_supplier_and_shipment for the supplier and shipment below, then summarise.\n"
                     "INCIDENT_JSON: {normalized_json}", [lookup_supplier_and_shipment], "supplier_summary")
    inventory = agent("inventory_agent", "Inventory position lookups.",
                      "Call lookup_inventory for the product_sku below, then summarise stock cover.\n"
                      "INCIDENT_JSON: {normalized_json}", [lookup_inventory], "inventory_summary")
    weather = agent("weather_agent", "Live weather risk.",
                    "Call check_weather_risk for the location below, then summarise the risk.\n"
                    "INCIDENT_JSON: {normalized_json}", [check_weather_risk], "weather_summary")
    gatherers = ParallelAgent(name="context_gatherers", description="Fan-out context gathering",
                              sub_agents=[supplier, inventory, weather])
    liaison = agent("crew_liaison_agent", "Delegates analysis to the CrewAI specialist via A2A.",
                    "Call delegate_to_crewai_specialist (it reads the shared session state) and report the outcome.",
                    [delegate_to_crewai_specialist], "crew_summary")
    reviewer = agent("reviewer_agent", "Critiques and corrects the resolution plan (reflection).",
                     "Call review_resolution_plan to critique the plan against the gathered context, then list the issues found.",
                     [review_resolution_plan], "review_summary")
    return SequentialAgent(name="incident_pipeline", description="SignalChain incident response pipeline",
                           sub_agents=[intake, gatherers, liaison, reviewer])


async def run_pipeline(incident: Dict[str, Any]) -> Dict[str, Any]:
    """Run the ADK pipeline for one incident and return the final session state + event log."""
    pipeline = build_pipeline()
    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name=APP_NAME, user_id="signalchain", state={
        "incident": incident, "incident_json": json.dumps(incident, default=str), "normalized_json": "{}"})
    runner = Runner(agent=pipeline, app_name=APP_NAME, session_service=sessions)
    events: List[Dict[str, Any]] = []
    message = types.Content(role="user", parts=[types.Part(text=f"Resolve supply-chain incident {incident.get('incident_id')}.")])
    t0 = time.perf_counter()
    async for ev in runner.run_async(user_id="signalchain", session_id=session.id, new_message=message):
        kinds = []
        for p in (ev.content.parts if ev.content else None) or []:
            if p.function_call:
                kinds.append(f"call:{p.function_call.name}")
            elif p.function_response:
                kinds.append(f"result:{p.function_response.name}")
            elif p.text:
                kinds.append("text")
        events.append({"author": ev.author, "t_ms": int((time.perf_counter() - t0) * 1000), "parts": kinds,
                       "state_delta": sorted((ev.actions.state_delta or {}).keys()) if ev.actions else []})
    final = await sessions.get_session(app_name=APP_NAME, user_id="signalchain", session_id=session.id)
    state = dict(final.state)
    state["adk_events"] = events
    state["adk_session_id"] = session.id
    return state


def describe_pipeline() -> Dict[str, Any]:
    p = build_pipeline()

    def node(a: Any) -> Dict[str, Any]:
        return {"name": a.name, "type": type(a).__name__, "description": a.description,
                "tools": [getattr(t, "__name__", getattr(t, "name", str(t))) for t in getattr(a, "tools", [])],
                "output_key": getattr(a, "output_key", None),
                "children": [node(c) for c in getattr(a, "sub_agents", [])]}
    return node(p)


