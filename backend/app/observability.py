"""Tracing for auditability and provenance.

Every workflow, agent, LLM call, MCP tool call, A2A hop and guardrail check is recorded
as a span (trace_id / span_id / parent_span_id), persisted to the ``trace_spans`` table
and, when LANGFUSE_* keys are configured, exported to Langfuse. Trace context crosses
the A2A boundary through the W3C ``traceparent`` header.
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, Iterator, List, Optional

from app.core.config import settings

log = logging.getLogger("signalchain.trace")

_current_trace: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trace_id", default=None)
_current_span: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("span_id", default=None)
_current_incident: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("incident_id", default=None)


def _jsonable(value: Any, limit: int = 6000) -> Any:
    try:
        text = json.dumps(value, default=str)
    except Exception:
        text = json.dumps(str(value))
    if len(text) > limit:
        return {"truncated": True, "preview": text[:limit]}
    return json.loads(text)


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    name: str
    kind: str
    framework: str
    incident_id: Optional[int]
    input: Any = None
    output: Any = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    started: float = field(default_factory=time.perf_counter)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def set(self, **attrs: Any) -> None:
        self.attributes.update(attrs)


class Tracer:
    def __init__(self) -> None:
        self._lock = Lock()
        self._trace_start: Dict[str, float] = {}
        self._usage: Dict[str, Dict[str, int]] = {}
        self._langfuse = None
        if settings.langfuse_public_key and settings.langfuse_secret_key:
            try:
                from langfuse import Langfuse

                self._langfuse = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
                log.info("Langfuse export enabled (%s)", settings.langfuse_host)
            except Exception as exc:  # pragma: no cover
                log.warning("Langfuse unavailable: %s", exc)

    @property
    def langfuse_enabled(self) -> bool:
        return self._langfuse is not None

    # ---------------------------------------------------------------- context
    @staticmethod
    def current_trace_id() -> Optional[str]:
        return _current_trace.get()

    @staticmethod
    def current_incident_id() -> Optional[int]:
        return _current_incident.get()

    def traceparent(self) -> Optional[str]:
        trace_id, span_id = _current_trace.get(), _current_span.get()
        if not trace_id or not span_id:
            return None
        return f"00-{trace_id}-{span_id}-01"

    @contextmanager
    def continue_from(self, traceparent: Optional[str], incident_id: Optional[int] = None) -> Iterator[None]:
        """Adopt a remote parent context (used by the A2A server)."""
        tokens = []
        if traceparent:
            parts = traceparent.split("-")
            if len(parts) == 4 and len(parts[1]) == 32:
                tokens.append((_current_trace, _current_trace.set(parts[1])))
                tokens.append((_current_span, _current_span.set(parts[2])))
        if incident_id is not None:
            tokens.append((_current_incident, _current_incident.set(incident_id)))
        try:
            yield
        finally:
            for var, tok in reversed(tokens):
                var.reset(tok)

    # ------------------------------------------------------------------ spans
    @contextmanager
    def span(
        self,
        name: str,
        kind: str = "span",
        framework: str = "",
        input: Any = None,
        incident_id: Optional[int] = None,
        new_trace: bool = False,
        **attributes: Any,
    ) -> Iterator[Span]:
        trace_id = None if new_trace else _current_trace.get()
        if trace_id is None:
            trace_id = uuid.uuid4().hex
        parent = None if new_trace else _current_span.get()
        inc = incident_id if incident_id is not None else _current_incident.get()
        sp = Span(
            trace_id=trace_id,
            span_id=uuid.uuid4().hex[:16],
            parent_span_id=parent,
            name=name,
            kind=kind,
            framework=framework,
            incident_id=inc,
            input=input,
            attributes=dict(attributes),
        )
        with self._lock:
            self._trace_start.setdefault(trace_id, sp.started)
        t1 = _current_trace.set(trace_id)
        t2 = _current_span.set(sp.span_id)
        t3 = _current_incident.set(inc)
        try:
            yield sp
        except Exception as exc:
            sp.status = "error"
            sp.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            _current_incident.reset(t3)
            _current_span.reset(t2)
            _current_trace.reset(t1)
            self._finish(sp)

    # Manual begin/end for framework callbacks that cannot wrap a ``with`` block.
    def begin(self, name: str, kind: str = "span", framework: str = "", input: Any = None,
              parent: Optional[Span] = None, **attributes: Any) -> Span:
        trace_id = parent.trace_id if parent else (_current_trace.get() or uuid.uuid4().hex)
        parent_id = parent.span_id if parent else _current_span.get()
        sp = Span(trace_id=trace_id, span_id=uuid.uuid4().hex[:16], parent_span_id=parent_id, name=name,
                  kind=kind, framework=framework, incident_id=_current_incident.get(), input=input,
                  attributes=dict(attributes))
        with self._lock:
            self._trace_start.setdefault(trace_id, sp.started)
        _current_trace.set(trace_id)
        _current_span.set(sp.span_id)
        return sp

    def end(self, sp: Optional[Span], output: Any = None, status: Optional[str] = None, error: str = "") -> None:
        if sp is None:
            return
        if output is not None:
            sp.output = output
        if status:
            sp.status = status
        if error:
            sp.error = error
        _current_span.set(sp.parent_span_id)
        self._finish(sp)

    def event(self, name: str, kind: str = "callback", framework: str = "", status: str = "ok", **payload: Any) -> None:
        """Zero-duration span – used by framework callbacks."""
        with self.span(name, kind=kind, framework=framework, input=payload.pop("input", None)) as sp:
            sp.output = payload.pop("output", None)
            sp.status = status
            sp.error = payload.pop("error", "") or ""
            sp.set(**payload)

    def add_usage(self, tokens_in: int, tokens_out: int) -> None:
        trace_id = _current_trace.get()
        if not trace_id:
            return
        with self._lock:
            u = self._usage.setdefault(trace_id, {"in": 0, "out": 0, "llm_calls": 0})
            u["in"] += tokens_in
            u["out"] += tokens_out
            u["llm_calls"] += 1

    def usage(self, trace_id: str) -> Dict[str, int]:
        with self._lock:
            return dict(self._usage.get(trace_id, {"in": 0, "out": 0, "llm_calls": 0}))

    def _finish(self, sp: Span) -> None:
        duration_ms = int((time.perf_counter() - sp.started) * 1000)
        start_ms = int((sp.started - self._trace_start.get(sp.trace_id, sp.started)) * 1000)
        record = {
            "trace_id": sp.trace_id,
            "span_id": sp.span_id,
            "parent_span_id": sp.parent_span_id,
            "incident_id": sp.incident_id,
            "name": sp.name,
            "kind": sp.kind,
            "framework": sp.framework,
            "status": sp.status,
            "input": _jsonable(sp.input),
            "output": _jsonable(sp.output),
            "attributes": _jsonable(sp.attributes),
            "error": sp.error,
            "tokens_in": sp.tokens_in,
            "tokens_out": sp.tokens_out,
            "start_ms": start_ms,
            "duration_ms": duration_ms,
        }
        log.info(json.dumps({k: record[k] for k in ("trace_id", "span_id", "kind", "name", "status", "duration_ms")}))
        try:
            from app.database import SessionLocal
            from app.models import TraceSpan

            with SessionLocal() as db:
                db.add(TraceSpan(**record))
                db.commit()
        except Exception as exc:  # pragma: no cover - never break the workflow on tracing
            log.warning("could not persist span: %s", exc)
        self._export_langfuse(sp, duration_ms)

    def _export_langfuse(self, sp: Span, duration_ms: int) -> None:
        if not self._langfuse:
            return
        try:
            end = datetime.fromtimestamp(sp.started_at.timestamp() + duration_ms / 1000, tz=timezone.utc)
            common = dict(
                trace_id=sp.trace_id,
                id=sp.span_id,
                parent_observation_id=sp.parent_span_id,
                name=sp.name,
                input=_jsonable(sp.input),
                output=_jsonable(sp.output),
                start_time=sp.started_at,
                end_time=end,
                metadata={"kind": sp.kind, "framework": sp.framework, **_jsonable(sp.attributes)},
                level="ERROR" if sp.status == "error" else "DEFAULT",
                status_message=sp.error or None,
            )
            if sp.parent_span_id is None:
                self._langfuse.trace(id=sp.trace_id, name=sp.name, input=common["input"], output=common["output"],
                                     metadata=common["metadata"], tags=["signalchain", sp.framework or "app"])
            if sp.kind == "llm":
                self._langfuse.generation(model=sp.attributes.get("model"),
                                          usage={"input": sp.tokens_in, "output": sp.tokens_out}, **common)
            else:
                self._langfuse.span(**common)
        except Exception as exc:  # pragma: no cover
            log.warning("langfuse export failed: %s", exc)

    def flush(self) -> None:
        if self._langfuse:
            try:
                self._langfuse.flush()
            except Exception:  # pragma: no cover
                pass


tracer = Tracer()


def estimate_tokens(text: str) -> int:
    """~4 characters per token heuristic (used when the provider returns no usage)."""
    return max(1, len(text or "") // 4)


def cost_usd(tokens_in: int, tokens_out: int) -> float:
    return round(tokens_in / 1e6 * settings.price_input_per_m + tokens_out / 1e6 * settings.price_output_per_m, 6)


def spans_for_trace(db, trace_id: str) -> List[Dict[str, Any]]:
    from app.models import TraceSpan

    rows = db.query(TraceSpan).filter(TraceSpan.trace_id == trace_id).order_by(TraceSpan.start_ms, TraceSpan.id).all()
    return [
        {
            "span_id": r.span_id, "parent_span_id": r.parent_span_id, "name": r.name, "kind": r.kind,
            "framework": r.framework, "status": r.status, "input": r.input, "output": r.output,
            "attributes": r.attributes, "error": r.error, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
            "start_ms": r.start_ms, "duration_ms": r.duration_ms,
        }
        for r in rows
    ]
