"""Guardrails for the agentic system.

Layers
1. API input  – prompt-injection, toxicity/abuse, PII redaction, schema checks.
2. LLM input  – ADK ``before_model_callback`` re-scans every prompt sent to a model.
3. Tool input – ADK ``before_tool_callback`` type-checks arguments against the signature.
4. Tool output– ADK ``after_tool_callback`` / MCP client validate returns with Pydantic.
5. Agent output – CrewAI task ``guardrail`` functions validate each structured output.
Every decision is persisted as a ``GuardrailEvent`` and traced.
"""
from __future__ import annotations

import inspect
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, ValidationError

from app.observability import tracer

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) (instructions|prompts|rules)",
    r"disregard (all |the )?(previous|prior|above|system)",
    r"forget (everything|all|your) (instructions|rules|above)",
    r"\b(reveal|print|show|leak|repeat) (me )?(the |your )?(system|developer|hidden) (prompt|instructions|message)",
    r"\byou are now\b",
    r"\bact as (an? )?(unrestricted|jailbroken|dan|developer mode)",
    r"\bpretend (to be|you are)\b",
    r"\b(jailbreak|do anything now|dan mode)\b",
    r"\bbypass (the )?(guardrails?|safety|filters?|restrictions)",
    r"\b(drop|truncate|delete from|overwrite)\s+(table|db|database)\b",
    r"<\s*/?\s*(system|assistant|im_start|im_end)\s*>",
    r"\breveal (the )?(api[_ ]?key|secrets?|credentials|password)",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

# Small, explicit lexicon – abusive language aimed at people. Matched on word boundaries.
TOXIC_TERMS = [
    "idiot", "idiots", "stupid", "moron", "morons", "imbecile", "dumbass", "retard", "retarded",
    "shut up", "kill you", "kill yourself", "i will hurt", "hate you", "worthless", "loser", "losers",
    "fuck", "fucking", "shit", "bitch", "bastard", "asshole", "crap",
]
_TOXIC_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in TOXIC_TERMS) + r")\b", re.IGNORECASE)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\w)")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")


@dataclass
class GuardrailVerdict:
    allowed: bool
    violations: List[str] = field(default_factory=list)
    redacted_text: str = ""
    redactions: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"allowed": self.allowed, "violations": self.violations, "redactions": self.redactions,
                "redacted_text": self.redacted_text}


def detect_prompt_injection(text: str) -> List[str]:
    return [p.pattern for p in _INJECTION_RE if p.search(text or "")]


def check_prompt_injection(text: str) -> bool:
    return bool(detect_prompt_injection(text))


def detect_toxicity(text: str) -> List[str]:
    return sorted({m.group(0).lower() for m in _TOXIC_RE.finditer(text or "")})


def redact_pii(text: str) -> Tuple[str, Dict[str, int]]:
    counts: Dict[str, int] = {}
    out = text or ""
    for label, rx in (("card", _CARD_RE), ("email", _EMAIL_RE), ("phone", _PHONE_RE)):
        out, n = rx.subn(f"[REDACTED_{label.upper()}]", out)
        if n:
            counts[label] = n
    return out, counts


def screen_text(text: str) -> GuardrailVerdict:
    violations: List[str] = []
    inj = detect_prompt_injection(text)
    if inj:
        violations.append("prompt_injection")
    tox = detect_toxicity(text)
    if tox:
        violations.append("toxic_language:" + ",".join(tox))
    redacted, counts = redact_pii(text)
    return GuardrailVerdict(allowed=not violations, violations=violations, redacted_text=redacted, redactions=counts)


def record_guardrail(check: str, stage: str, passed: bool, details: Any, incident_id: Optional[int] = None) -> None:
    """Persist + trace a guardrail decision. Never raises."""
    tracer.event(f"guardrail:{check}", kind="guardrail", status="ok" if passed else "blocked",
                 input={"stage": stage}, output={"passed": passed, "details": details})
    try:
        from app.database import SessionLocal
        from app.models import GuardrailEvent

        with SessionLocal() as db:
            db.add(GuardrailEvent(incident_id=incident_id if incident_id is not None else tracer.current_incident_id(),
                                  trace_id=tracer.current_trace_id(), check_name=check, stage=stage,
                                  passed=passed, details=str(details)[:2000]))
            db.commit()
    except Exception:  # pragma: no cover
        pass


def validate_incident_payload(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if not payload.get("title") or len(str(payload["title"]).strip()) < 3:
        errors.append("Title is required and must be descriptive.")
    if not payload.get("description") or len(str(payload["description"]).strip()) < 10:
        errors.append("Description is required (min 10 characters).")
    if not payload.get("location") or len(str(payload["location"]).strip()) < 2:
        errors.append("Location is required.")
    try:
        if payload.get("quantity_affected") is not None and int(payload["quantity_affected"]) < 0:
            errors.append("Quantity affected cannot be negative.")
    except (TypeError, ValueError):
        errors.append("Quantity affected must be an integer.")
    for key in ("title", "description", "supplier", "location"):
        verdict = screen_text(str(payload.get(key) or ""))
        for v in verdict.violations:
            errors.append(f"{key}: {v.replace('_', ' ')} detected")
    return not errors, errors


# ----------------------------------------------------------- tool validation
_PY_TYPES = {"str": str, "int": int, "float": (int, float), "bool": bool, "dict": dict, "list": list}


def validate_tool_args(func: Any, args: Dict[str, Any]) -> List[str]:
    """Type-check arguments for a python tool against its annotations."""
    problems: List[str] = []
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return problems
    for name, value in args.items():
        if name not in sig.parameters:
            problems.append(f"unexpected argument '{name}'")
            continue
        ann = sig.parameters[name].annotation
        ann_name = ann if isinstance(ann, str) else getattr(ann, "__name__", str(ann))
        base = str(ann_name).replace("Optional[", "").split("|")[0].split("[")[0].strip(" ]")
        expected = _PY_TYPES.get(base)
        if value is None or expected is None:
            continue
        if expected is int and isinstance(value, float) and value.is_integer():
            continue
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            problems.append(f"argument '{name}' expected {base}, got {type(value).__name__}")
        if isinstance(value, str) and check_prompt_injection(value):
            problems.append(f"argument '{name}' contains a prompt-injection pattern")
    return problems


def validate_model_output(model: Type[BaseModel], data: Any) -> Tuple[bool, Any, List[str]]:
    try:
        obj = model.model_validate(data)
        return True, obj, []
    except ValidationError as exc:
        return False, None, [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]


# -------------------------------------------------------------- file uploads
def sanitize_filename(filename: str) -> str:
    cleaned = os.path.basename(filename or "upload.bin")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", cleaned)
    return cleaned[:200] or "upload.bin"


def validate_file_upload(filename: str, size_bytes: int, max_mb: int = 10) -> Tuple[bool, str]:
    safe_name = sanitize_filename(filename)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".pdf", ".csv", ".txt"}:
        return False, "Unsupported file type."
    if size_bytes <= 0:
        return False, "Uploaded file is empty."
    if size_bytes / (1024 * 1024) > max_mb:
        return False, f"Uploaded file exceeds the {max_mb} MB limit."
    return True, safe_name
