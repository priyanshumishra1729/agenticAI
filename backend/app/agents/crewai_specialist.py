"""CrewAI specialist crew (served to the ADK coordinator over A2A).

Verification analyst → Severity & impact analyst → Resolution planner  (Process.sequential)

Context sharing: every tool reads/writes a shared ``CrewRunState`` (keyed by run_id) that
is seeded with the ADK intake context received over A2A, and each Task also receives the
previous tasks' outputs via ``context=[...]``.
Structured output: each Task declares ``output_pydantic``.
Guardrails: each Task has a ``guardrail`` validating its structured output (retries on failure).
Monitoring: Crew ``step_callback`` / ``task_callback`` trace every thought, tool call and result.
"""


import json
import time
import uuid
from threading import Lock
from typing import Any, Dict, List, Tuple

from crewai import Agent, Crew, Process, Task
from crewai.tasks.task_output import TaskOutput
from crewai.tools import tool

from app.guardrails import record_guardrail, validate_model_output
from app.llm.models import crewai_llm
from app.mcp_client import call_tool
from app.observability import tracer
from app.schemas import CrewAnalysis, ResolutionPlan, SeverityResult, VerificationResult

# ------------------------------------------------------------- shared state
_STATE: Dict[str, Dict[str, Any]] = {}
_LOCK = Lock()


def _state(run_id: str) -> Dict[str, Any]:
    with _LOCK:
        if run_id not in _STATE:
            raise KeyError(f"unknown run_id {run_id}")
        return _STATE[run_id]


TEAM_BY_CATEGORY = {
    "transportation_delay": "Logistics", "supplier_failure": "Procurement", "inventory_shortage": "Inventory",
    "damaged_goods": "Warehouse", "warehouse_disruption": "Warehouse", "cold_chain_excursion": "Quality",
    "quality_defect": "Quality", "other": "Operations",
}
BASE_RISK = {
    "cold_chain_excursion": 30, "supplier_failure": 30, "quality_defect": 28, "inventory_shortage": 25,
    "warehouse_disruption": 22, "transportation_delay": 18, "damaged_goods": 15, "other": 12,
}
DEFAULT_DELAY_H = {"transportation_delay": 36, "supplier_failure": 96, "inventory_shortage": 48, "damaged_goods": 24,
                   "warehouse_disruption": 24, "cold_chain_excursion": 12, "quality_defect": 72, "other": 24}
URGENT_TERMS = ["recall", "contamination", "safety", "shutdown", "halted", "line stop", "production stop", "fire",
                "injur", "bankrupt", "insolven", "spoil"]


# -------------------------------------------------------------- tool logic
def _verify(run_id: str) -> Dict[str, Any]:
    st = _state(run_id)
    inc, ctx = st["incident"], st["intake"]
    missing = [f for f in ("supplier", "shipment_id", "product_sku") if not inc.get(f)]
    if not inc.get("quantity_affected"):
        missing.append("quantity_affected")
    conflicts: List[str] = []
    parsed = ctx.get("parsed_document") or {}
    if parsed.get("sku") and inc.get("product_sku") and parsed["sku"] != inc["product_sku"]:
        conflicts.append(f"Report text mentions {parsed['sku']} but form says {inc['product_sku']}")
    shipment = (ctx.get("supplier_shipment") or {}).get("shipment") or {}
    if shipment and inc.get("product_sku") and shipment.get("sku") != inc["product_sku"]:
        conflicts.append(f"Shipment {shipment.get('shipment_id')} carries {shipment.get('sku')}, not {inc['product_sku']}")
    if inc.get("shipment_id") and not shipment:
        conflicts.append(f"Shipment {inc['shipment_id']} not found in the shipment database")

    history = call_tool("historical_incident_search", {
        "category": inc.get("category", ""), "supplier": inc.get("supplier") or "", "location": inc.get("location", ""),
        "exclude_incident_id": inc.get("incident_id", "")}, caller="crewai:verification_analyst")
    st["history"] = history
    dup_score, dup_of = 0, None
    for h in history.get("incidents", []):
        open_case = h.get("status") not in {"closed", "resolved"}
        score = int(h["similarity"] * (0.8 if open_case else 0.4))
        if inc.get("shipment_id") and h.get("shipment_id") == inc["shipment_id"] and open_case:
            score = 95
        if score > dup_score:
            dup_score, dup_of = score, h["incident_id"]
    completeness = max(20, 100 - 15 * len(missing) - 5 * len(conflicts))
    status = "possible_duplicate" if dup_score >= 80 else "needs_more_info" if completeness < 60 else "verified"
    result = {
        "status": status, "completeness_score": completeness, "duplicate_score": dup_score,
        "duplicate_of": dup_of if dup_score >= 80 else None, "missing_fields": missing, "data_conflicts": conflicts,
        "notes": f"{history.get('count', 0)} similar historical incident(s); typical resolution "
                 f"{history.get('avg_resolution_hours') or 'n/a'}h.",
    }
    st["verification"] = result
    return result


def _severity(run_id: str) -> Dict[str, Any]:
    st = _state(run_id)
    inc, ctx = st["incident"], st["intake"]
    cat = inc.get("category", "other")
    inv = ctx.get("inventory") or {}
    sup = (ctx.get("supplier_shipment") or {}).get("supplier") or {}
    shipment = (ctx.get("supplier_shipment") or {}).get("shipment") or {}
    weather = ctx.get("weather") or {}
    qty = int(inc.get("quantity_affected") or 0)
    delay_h = int(shipment.get("eta_hours") or DEFAULT_DELAY_H.get(cat, 24))
    unit_cost = (inv.get("warehouses") or [{}])[0].get("unit_cost_usd", 25) if inv.get("warehouses") else 25
    impact = call_tool("impact_calculator", {
        "quantity_affected": qty, "total_available": int(inv.get("total_available") or 0),
        "daily_demand": int(inv.get("total_daily_demand") or 0), "unit_cost_usd": int(unit_cost),
        "delay_hours": delay_h}, caller="crewai:severity_analyst")

    drivers: List[str] = []
    score = BASE_RISK.get(cat, 12)
    drivers.append(f"Category '{cat}' base risk {score}")
    qpts = 25 if qty >= 1000 else 18 if qty >= 300 else 12 if qty >= 100 else 6 if qty >= 30 else 0
    if qpts:
        score += qpts
        drivers.append(f"{qty} units affected (+{qpts})")
    if inv.get("found"):
        cover = float(impact["days_of_cover"])
        cpts = 25 if cover < 1 else 18 if cover < 2 else 10 if cover < 4 else 4 if cover < 7 else 0
        if cpts:
            score += cpts
            drivers.append(f"Only {cover} days of inventory cover (+{cpts})")
    spts = {"high": 10, "medium": 5}.get(impact["sla_breach_risk"], 0)
    if spts:
        score += spts
        drivers.append(f"SLA breach risk {impact['sla_breach_risk']} (+{spts})")
    wpts = {"high": 10, "moderate": 4}.get(weather.get("risk_level"), 0)
    if wpts:
        score += wpts
        drivers.append(f"Live weather risk {weather.get('risk_level')} at {weather.get('location')} (+{wpts})")
    if sup and sup.get("reliability", 100) < 75:
        score += 6
        drivers.append(f"Supplier reliability {sup['reliability']}% (+6)")
    text = f"{inc.get('title', '')} {inc.get('description', '')}".lower()
    urgent = [t for t in URGENT_TERMS if t in text]
    if urgent:
        score += 12
        drivers.append(f"Safety/continuity terms: {', '.join(urgent)} (+12)")
    score = min(100, score)
    level = "critical" if score >= 75 else "high" if score >= 55 else "medium" if score >= 35 else "low"
    confidence = round(min(0.97, 0.55 + 0.08 * sum(bool(x) for x in (inv.get("found"), sup, shipment,
                                                                      weather.get("source") == "open-meteo", qty))), 2)
    result = {"level": level, "score": score, "drivers": drivers, "impact": impact, "confidence": confidence}
    st["severity"] = result
    return result


def _plan(run_id: str) -> Dict[str, Any]:
    st = _state(run_id)
    inc, ctx = st["incident"], st["intake"]
    sev = st.get("severity") or _severity(run_id)
    ver = st.get("verification") or _verify(run_id)
    cat, level = inc.get("category", "other"), sev["level"]
    team = TEAM_BY_CATEGORY.get(cat, "Operations")
    priority = {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4"}[level]
    deadline = {"critical": 4, "high": 12, "medium": 24, "low": 72}[level]
    alternates = (ctx.get("supplier_shipment") or {}).get("alternates") or []
    sku = inc.get("product_sku") or "affected SKU"
    templates = {
        "transportation_delay": [f"Confirm revised ETA for {inc.get('shipment_id') or 'shipment'} with carrier", "Evaluate alternate route / mode (expedite or reroute)", "Notify downstream customers of revised delivery window"],
        "supplier_failure": [f"Activate alternate supplier ({', '.join(alternates[:2]) or 'approved vendor list'})", "Place bridge purchase order for critical volume", "Open supplier corrective-action request"],
        "inventory_shortage": [f"Rebalance {sku} stock from other DCs", "Allocate available units to priority customers", "Expedite replenishment order"],
        "damaged_goods": ["Quarantine and photograph damaged units", "File carrier / supplier damage claim", "Ship replacement units from safety stock"],
        "warehouse_disruption": ["Activate site contingency plan and safety check", "Divert inbound receipts to secondary DC", "Restore WMS / dock operations and backlog plan"],
        "cold_chain_excursion": ["Quarantine affected lot pending QA disposition", "Download reefer temperature log and assess product viability", "Arrange replacement shipment under validated cold chain"],
        "quality_defect": ["Place quality hold on affected lots", "Run root-cause analysis with supplier quality", "Assess customer exposure and recall need"],
        "other": ["Triage incident with operations lead", "Assign owner and define recovery steps", "Communicate status to stakeholders"],
    }[cat if cat in TEAM_BY_CATEGORY else "other"]
    actions = [{"title": t, "owner": team, "due_hours": max(1, int(deadline * (i + 1) / len(templates)))}
               for i, t in enumerate(templates)]
    if ver["status"] == "needs_more_info":
        actions.insert(0, {"title": f"Collect missing data: {', '.join(ver['missing_fields'])}", "owner": "Operations", "due_hours": 1})
    reasons = []
    if level == "critical":
        reasons.append("critical severity")
    if sev["impact"]["sla_breach_risk"] == "high" and level in {"high", "critical"}:
        reasons.append("high SLA-breach risk")
    if ver["status"] == "possible_duplicate":
        reasons.append(f"possible duplicate of {ver['duplicate_of']}")
    result = {
        "owner_team": team, "priority": priority, "deadline_hours": deadline,
        "summary": f"{priority} response led by {team}: {templates[0].lower()} and contain impact "
                   f"(${sev['impact']['revenue_at_risk_usd']:,} revenue at risk).",
        "actions": actions, "escalate": bool(reasons), "escalation_reason": "; ".join(reasons),
    }
    st["plan"] = result
    return result


# -------------------------------------------------------------- CrewAI tools
@tool("verify_incident")
def verify_incident(run_id: str) -> str:
    """Check completeness, data conflicts and duplicate risk for the incident in the shared run state (uses MCP historical search)."""
    return json.dumps(_verify(run_id))


@tool("assess_severity")
def assess_severity(run_id: str) -> str:
    """Score severity and operational impact for the incident in the shared run state (uses MCP impact calculator)."""
    return json.dumps(_severity(run_id))


@tool("plan_resolution")
def plan_resolution(run_id: str) -> str:
    """Route the incident to an owner team and build a prioritised action plan from the shared run state."""
    return json.dumps(_plan(run_id))


# ------------------------------------------------------------- guardrails
def _guard(model, rules=None):
    def guardrail(output: TaskOutput) -> Tuple[bool, Any]:
        data = output.pydantic.model_dump() if output.pydantic else None
        if data is None:
            try:
                data = json.loads(output.raw)
            except Exception:
                record_guardrail("crewai_task_output", model.__name__, False, "output is not JSON")
                return False, f"Return ONLY a JSON object matching {model.__name__}."
        ok, _, errors = validate_model_output(model, data)
        if ok and rules:
            errors = rules(data)
            ok = not errors
        record_guardrail("crewai_task_output", model.__name__, ok, errors or "valid")
        return (True, output) if ok else (False, f"Fix these problems and return valid JSON: {errors}")
    guardrail.__name__ = f"guard_{model.__name__}"
    return guardrail


def _severity_rules(d: Dict[str, Any]) -> List[str]:
    bands = {"critical": 75, "high": 55, "medium": 35, "low": 0}
    return [] if d["score"] >= bands[d["level"]] else [f"score {d['score']} inconsistent with level {d['level']}"]


def _plan_rules(d: Dict[str, Any]) -> List[str]:
    errs = []
    if d["priority"] == "P1" and d["deadline_hours"] > 8:
        errs.append("P1 plans must have deadline <= 8h")
    if any(a["due_hours"] > d["deadline_hours"] for a in d["actions"]):
        errs.append("action due later than plan deadline")
    return errs


# -------------------------------------------------------------- crew build
def build_crew(run_id: str, monitor: List[Dict[str, Any]]) -> Crew:
    llm = crewai_llm()
    common = dict(llm=llm, verbose=False, allow_delegation=False, max_iter=4)
    verifier = Agent(role="Verification Analyst", goal="Validate completeness, consistency and duplicate risk of incident reports",
                     backstory="A meticulous data-quality analyst for a global supply-chain control tower.",
                     tools=[verify_incident], **common)
    severity = Agent(role="Severity & Impact Analyst", goal="Quantify severity and operational/financial impact",
                     backstory="A risk analyst who turns inventory, supplier and weather signals into a severity score.",
                     tools=[assess_severity], **common)
    planner = Agent(role="Resolution Planner", goal="Route incidents to the right team with a time-boxed action plan",
                    backstory="A seasoned crisis manager who writes crisp, owner-assigned recovery plans.",
                    tools=[plan_resolution], **common)
    instr = ("Shared state handle: run_id={run_id}. [[use_tool:{tool}]] Call the `{tool}` tool with this run_id, "
             "then return the tool's JSON output exactly as your Final Answer (no prose).")
    t1 = Task(description="Verify the incident report. " + instr.format(run_id=run_id, tool="verify_incident"),
              expected_output="JSON VerificationResult", agent=verifier, output_pydantic=VerificationResult,
              guardrail=_guard(VerificationResult), max_retries=2)
    t2 = Task(description="Assess severity and impact using the verified context. " + instr.format(run_id=run_id, tool="assess_severity"),
              expected_output="JSON SeverityResult", agent=severity, output_pydantic=SeverityResult, context=[t1],
              guardrail=_guard(SeverityResult, _severity_rules), max_retries=2)
    t3 = Task(description="Build the routing decision and action plan. " + instr.format(run_id=run_id, tool="plan_resolution"),
              expected_output="JSON ResolutionPlan", agent=planner, output_pydantic=ResolutionPlan, context=[t1, t2],
              guardrail=_guard(ResolutionPlan, _plan_rules), max_retries=2)

    def step_callback(step: Any) -> None:
        kind = type(step).__name__
        payload: Dict[str, Any] = {"step": kind}
        for attr in ("thought", "tool", "tool_input", "result", "output"):
            if hasattr(step, attr):
                payload[attr] = str(getattr(step, attr))[:800]
        monitor.append({"type": "step", "ts": time.time(), **payload})
        tracer.event(f"crewai:step:{kind}", kind="callback", framework="CrewAI", output=payload)

    def task_callback(out: TaskOutput) -> None:
        item = {"type": "task", "ts": time.time(), "agent": out.agent, "task": out.description[:80],
                "structured": bool(out.pydantic)}
        monitor.append(item)
        tracer.event(f"crewai:task_done:{out.agent}", kind="callback", framework="CrewAI",
                     output={"agent": out.agent, "pydantic": out.pydantic.model_dump() if out.pydantic else out.raw[:500]})

    return Crew(agents=[verifier, severity, planner], tasks=[t1, t2, t3], process=Process.sequential,
                step_callback=step_callback, task_callback=task_callback, verbose=False)


def run_crew_analysis(incident: Dict[str, Any], intake: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point used by the A2A server. Returns CrewAnalysis + monitoring log."""
    run_id = f"CREW-{uuid.uuid4().hex[:8].upper()}"
    with _LOCK:
        _STATE[run_id] = {"incident": incident, "intake": intake}
    monitor: List[Dict[str, Any]] = []
    fallback = False
    with tracer.span("crewai:specialist_crew", kind="agent", framework="CrewAI", input={"run_id": run_id},
                     process="sequential", agents=3) as sp:
        try:
            crew = build_crew(run_id, monitor)
            result = crew.kickoff()
            outs = [t.pydantic for t in result.tasks_output]
            analysis = CrewAnalysis(verification=outs[0], severity=outs[1], plan=outs[2])
            usage = result.token_usage
            if usage and usage.total_tokens:
                tracer.add_usage(usage.prompt_tokens, usage.completion_tokens)
        except Exception as exc:
            # Guardrail fallback: deterministic analysis from the shared state so the workflow never stalls.
            fallback = True
            record_guardrail("crew_fallback", "crewai", False, f"{type(exc).__name__}: {exc}")
            analysis = CrewAnalysis(verification=VerificationResult(**_verify(run_id)),
                                    severity=SeverityResult(**_severity(run_id)), plan=ResolutionPlan(**_plan(run_id)))
        sp.output = analysis.model_dump()
        sp.set(fallback_used=fallback, steps=len(monitor))
    with _LOCK:
        _STATE.pop(run_id, None)
    return {"run_id": run_id, "analysis": analysis.model_dump(), "monitor": monitor, "fallback_used": fallback}
