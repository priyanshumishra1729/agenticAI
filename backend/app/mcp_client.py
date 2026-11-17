"""MCP client used by both CrewAI and ADK agents.

Each call opens an MCP ``ClientSession`` against the SignalChain FastMCP server over an
in-memory transport (real MCP JSON-RPC: initialize → tools/call), validates the tool's
return value with Pydantic (guardrail), records a ToolExecution row and a trace span.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from mcp.shared.memory import create_connected_server_and_client_session

from app.guardrails import record_guardrail, validate_model_output
from app.mcp_server import mcp
from app.observability import tracer
from app.schemas import (
    HistoricalSearchResult,
    ImpactCalculation,
    InventoryResult,
    ParsedDocument,
    SupplierShipmentResult,
    WeatherRisk,
)

OUTPUT_MODELS = {
    "supplier_shipment_lookup": SupplierShipmentResult,
    "inventory_lookup": InventoryResult,
    "historical_incident_search": HistoricalSearchResult,
    "document_parser": ParsedDocument,
    "impact_calculator": ImpactCalculation,
    "weather_risk": WeatherRisk,
}


class MCPToolError(RuntimeError):
    pass


def _extract(result: Any) -> Dict[str, Any]:
    if getattr(result, "isError", False):
        text = " ".join(getattr(c, "text", "") for c in result.content)
        raise MCPToolError(text or "MCP tool error")
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured.get("result", structured) if set(structured.keys()) == {"result"} else structured
    for c in result.content:
        if getattr(c, "type", "") == "text":
            return json.loads(c.text)
    return {}


async def list_tools() -> List[Dict[str, Any]]:
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        tools = await session.list_tools()
    return [{"name": t.name, "description": t.description, "input_schema": t.inputSchema} for t in tools.tools]


async def call_tool_async(name: str, arguments: Dict[str, Any], caller: str = "") -> Dict[str, Any]:
    started = time.perf_counter()
    with tracer.span(f"mcp:{name}", kind="tool", framework="MCP", input=arguments, caller=caller) as sp:
        status, data = "ok", {}
        try:
            async with create_connected_server_and_client_session(mcp._mcp_server) as session:
                result = await session.call_tool(name, arguments)
            data = _extract(result)
            model = OUTPUT_MODELS.get(name)
            if model:
                ok, _, errors = validate_model_output(model, data)
                if not ok:
                    record_guardrail("tool_output_schema", f"mcp:{name}", False, errors)
                    status = "invalid_output"
                    raise MCPToolError(f"{name} returned invalid output: {errors}")
            sp.output = data
            return data
        except Exception as exc:
            status = "error" if status == "ok" else status
            sp.status = "error"
            sp.error = str(exc)
            raise
        finally:
            _record(name, arguments, data, int((time.perf_counter() - started) * 1000), status, caller)


def call_tool(name: str, arguments: Dict[str, Any], caller: str = "") -> Dict[str, Any]:
    """Sync helper (used from CrewAI tools, which execute in a worker thread)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(call_tool_async(name, arguments, caller))
    # Called from inside a running loop: run in a dedicated thread with its own loop.
    import concurrent.futures
    import contextvars

    ctx = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, asyncio.run, call_tool_async(name, arguments, caller)).result()


def _record(name: str, arguments: Dict[str, Any], result: Dict[str, Any], duration_ms: int, status: str, caller: str) -> None:
    try:
        from app.database import SessionLocal
        from app.models import ToolExecution

        with SessionLocal() as db:
            db.add(ToolExecution(incident_id=tracer.current_incident_id(), trace_id=tracer.current_trace_id(), caller=caller,
                                 tool_name=name, arguments=arguments, result=result, duration_ms=duration_ms, status=status))
            db.commit()
    except Exception:  # pragma: no cover
        pass
