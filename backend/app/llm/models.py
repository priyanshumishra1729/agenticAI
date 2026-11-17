"""LLM providers for CrewAI and Google ADK.

* Gemini (``GEMINI_API_KEY`` set, or LLM_MODE=gemini): real model calls.
* Simulated (default without a key): deterministic, offline "policy" models that speak
  each framework's native protocol – ReAct text for CrewAI, function-calling
  ``LlmResponse`` objects for ADK. The real CrewAI and ADK runtimes, tools, callbacks,
  state, guardrails and A2A all execute; only token generation is simulated. Token
  usage is estimated (~4 chars/token) so cost estimates remain meaningful.
"""
from __future__ import annotations

import json
import re
from typing import Any, AsyncGenerator, Dict, List

from app.core.config import settings
from app.observability import estimate_tokens, tracer

SIM_MODEL = "signalchain-sim-1"


def llm_mode() -> str:
    return f"gemini:{settings.gemini_model}" if settings.use_gemini else f"simulated:{SIM_MODEL}"


# ============================================================== CrewAI

def _build_simulated_crew_llm():
    from crewai import BaseLLM

    class SimulatedCrewLLM(BaseLLM):
        """ReAct policy: call the tool named in the task, then return its observation as the Final Answer."""

        def __init__(self) -> None:
            super().__init__(model=SIM_MODEL, temperature=0)

        def call(self, messages, tools=None, callbacks=None, available_functions=None, **kwargs) -> str:  # type: ignore[override]
            msgs: List[Dict[str, str]] = [{"role": "user", "content": messages}] if isinstance(messages, str) else messages
            prompt = "\n".join(str(m.get("content", "")) for m in msgs)
            with tracer.span("llm:crewai", kind="llm", framework="CrewAI", input={"last_message": prompt[-1500:]},
                             model=SIM_MODEL) as sp:
                assistant = "\n".join(str(m.get("content", "")) for m in msgs if m.get("role") == "assistant")
                answer = self._policy(prompt, assistant)
                sp.tokens_in, sp.tokens_out = estimate_tokens(prompt), estimate_tokens(answer)
                tracer.add_usage(sp.tokens_in, sp.tokens_out)
                sp.output = answer
                return answer

        @staticmethod
        def _policy(prompt: str, assistant: str) -> str:
            obs_idx = assistant.rfind("Observation:")
            if obs_idx != -1:
                raw = assistant[obs_idx + len("Observation:"):].strip()
                start = raw.find("{")
                if start != -1:
                    try:
                        obj, _ = json.JSONDecoder().raw_decode(raw[start:])
                        return "Thought: I now know the final answer\nFinal Answer: " + json.dumps(obj)
                    except json.JSONDecodeError:
                        pass
                return "Thought: I now know the final answer\nFinal Answer: " + raw[:2000]
            tool = re.search(r"\[\[use_tool:([a-z_]+)\]\]", prompt)
            run = re.search(r"run_id=([A-Za-z0-9-]+)", prompt)
            if tool and run:
                return (f"Thought: I should use the {tool.group(1)} tool with the shared run state.\n"
                        f"Action: {tool.group(1)}\nAction Input: {json.dumps({'run_id': run.group(1)})}")
            return "Thought: I now know the final answer\nFinal Answer: {}"

        def supports_function_calling(self) -> bool:
            return False

        def supports_stop_words(self) -> bool:
            return True

        def get_context_window_size(self) -> int:
            return 128_000

    return SimulatedCrewLLM()


def crewai_llm() -> Any:
    if settings.use_gemini:
        from crewai import LLM

        return LLM(model=f"gemini/{settings.gemini_model}", api_key=settings.gemini_api_key, temperature=0.1)
    return _build_simulated_crew_llm()


# ================================================================= ADK

def _build_simulated_adk_llm():
    from google.adk.models import BaseLlm, LlmRequest, LlmResponse
    from google.genai import types

    class SimulatedAdkLlm(BaseLlm):
        """Function-calling policy: call each declared tool once (in order), then summarise the results."""

        model: str = SIM_MODEL

        async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
            tools = list((llm_request.tools_dict or {}).keys())
            responses: Dict[str, Any] = {}
            for content in llm_request.contents or []:
                for part in content.parts or []:
                    if part.function_response and part.function_response.name in tools:
                        responses[part.function_response.name] = part.function_response.response
            instruction = str(getattr(llm_request.config, "system_instruction", "") or "")
            prompt_text = instruction + "\n" + "\n".join(
                p.text or "" for c in (llm_request.contents or []) for p in (c.parts or []) if p.text)
            pending = [t for t in tools if t not in responses]
            if pending:
                name = pending[0]
                decl = llm_request.tools_dict[name]._get_declaration()
                params = list((decl.parameters.properties or {}).keys()) if decl and decl.parameters else []
                known = _known_values(prompt_text, responses)
                args = {p: known[p] for p in params if p in known and known[p] not in (None, "")}
                out_text = json.dumps({"call": name, "args": args})
                resp = LlmResponse(content=types.Content(role="model", parts=[
                    types.Part(function_call=types.FunctionCall(name=name, args=args))]))
            else:
                out_text = json.dumps({k: _brief(v) for k, v in responses.items()}, default=str)
                resp = LlmResponse(content=types.Content(role="model", parts=[types.Part(text=out_text)]))
            tin, tout = estimate_tokens(prompt_text), estimate_tokens(out_text)
            resp.usage_metadata = types.GenerateContentResponseUsageMetadata(
                prompt_token_count=tin, candidates_token_count=tout, total_token_count=tin + tout)
            yield resp

    return SimulatedAdkLlm()


def _known_values(prompt: str, responses: Dict[str, Any]) -> Dict[str, Any]:
    known: Dict[str, Any] = {}
    marker = prompt.find("INCIDENT_JSON:")
    if marker != -1:
        start = prompt.find("{", marker)
        try:
            known.update(json.JSONDecoder().raw_decode(prompt[start:])[0])
        except Exception:
            pass
    for resp in responses.values():
        if isinstance(resp, dict):
            for k, v in (resp.get("normalized") or {}).items():
                if v not in (None, ""):
                    known[k] = v
    return known


def _brief(value: Any) -> Any:
    text = json.dumps(value, default=str)
    return value if len(text) < 600 else {"summary": text[:600] + "…"}


def adk_model() -> Any:
    return settings.gemini_model if settings.use_gemini else _build_simulated_adk_llm()
