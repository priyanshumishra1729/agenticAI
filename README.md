# SignalChain: Autonomous Multi-Agent Supply Chain Crisis Management

A multi-agent system for supply-chain incident management. A **Google ADK** coordinator takes an incident, gathers context in parallel through **MCP** tools, and delegates specialist analysis to a **CrewAI** crew over the **A2A** protocol. A reflection agent reviews the plan, and a human approves it. Every step is guarded, traced and evaluated.

## Architecture

```
Incident Submission
       |
  ADK Intake Agent ---- MCP document_parser
       |
  ParallelAgent (concurrent)
    |-- Supplier Agent --- MCP supplier_shipment_lookup
    |-- Inventory Agent -- MCP inventory_lookup
    |-- Weather Agent ---- MCP weather_risk (Open-Meteo external API)
       |
  Crew Liaison --------- A2A JSON-RPC message/send (W3C traceparent)
       |
  CrewAI Crew (sequential)
    |-- Verification Analyst --- MCP historical_incident_search
    |-- Severity & Impact ------ MCP impact_calculator
    |-- Resolution Planner
       |
  ADK Reviewer Agent (reflection/critic)
       |
  Pydantic Structured Report (JSON + Markdown)
```

## Technology Stack

| Technology | Role |
|---|---|
| Google ADK | Coordinator framework — SequentialAgent, ParallelAgent, LlmAgent, session state, 6 callbacks |
| CrewAI | Specialist crew — 3 agents, Process.sequential, task context, step/task callbacks, guardrails |
| MCP | Tool server with 6 tools: 3 DB lookups, document parser, impact calculator, weather API |
| A2A Protocol | Agent-to-agent communication — JSON-RPC 2.0, agent cards, traceparent propagation |
| FastAPI | Backend API with SQLAlchemy ORM, SQLite database |
| Pydantic v2 | Structured output for all agent results and the final report |
| React + TypeScript | Frontend SPA with Vite, react-router, recharts |
| Observability | Custom span tree per run, persisted to DB, optional Langfuse export |

## Requirement Coverage

| # | Requirement | Implementation |
|---|---|---|
| 1 | Context sharing & state | ADK session state (`tool_context.state`, `output_key`, `{state}` templating). CrewAI task `context=[...]` plus shared run-state. State travels to CrewAI inside the A2A message. |
| 2 | MCP tools (≥2) | FastMCP server with 6 tools: 3 DB lookups, document parser, impact calculator, Open-Meteo weather (external). Real MCP `ClientSession`. |
| 3 | Structured output (Pydantic) | `output_pydantic` per CrewAI task. `IncidentResolutionReport` rendered as JSON and Markdown. |
| 4 | Agentic design patterns | Sequential, parallel, coordinator/delegation, ReAct tool use, reflection/critic, shared-state blackboard, guardrail + fallback, human-in-the-loop. |
| 5 | Monitoring via callbacks | ADK `before/after_agent`, `before/after_model`, `before/after_tool`. CrewAI `step_callback` and `task_callback`. |
| 6 | A2A interoperability | Agent cards at `/.well-known/agent.json`. JSON-RPC `message/send` + `tasks/get`. ADK calls CrewAI over A2A. |
| 7 | CrewAI + ADK only | No other agent framework. |
| 8 | Guardrails & validation | Injection/toxicity/PII screening at API. ADK `before_model` re-scans prompts. `before_tool` type-checks args. MCP output schema-validated. CrewAI task guardrails with retries and deterministic fallback. |
| 9 | Observability | Span tree per run in `trace_spans` table. W3C `traceparent` across A2A. Optional Langfuse export. |
| 10 | Evaluation, cost & runtime | 12 hand-labelled cases vs rule-based baseline. Stage latency, tokens, cost projections. |
| 11 | Cloud deployment | Dockerfile, Render blueprint (`render.yaml`), Cloud Run instructions. |

## Project Structure

```
backend/
  app/
    main.py                    # FastAPI app, lifespan, CORS, routers
    core/config.py             # Pydantic settings
    database.py                # SQLAlchemy engine, session
    models.py                  # All database models
    schemas.py                 # Pydantic API and agent output schemas
    guardrails.py              # Injection, toxicity, PII, validation
    observability.py           # Tracer, spans, Langfuse export
    mcp_server.py              # FastMCP server (6 tools)
    mcp_client.py              # MCP client session
    agents/
      google_adk.py            # ADK pipeline, tools, callbacks
      crewai_specialist.py     # CrewAI crew, tools, guardrails
    a2a/
      protocol.py              # Agent cards, A2A client
      server.py                # A2A JSON-RPC server routes
    api/routes.py              # All REST API endpoints
    services/workflow.py       # Incident lifecycle, pipeline orchestration
    db/seed_synthetic_data.py  # Seed data
    llm/models.py              # LLM abstractions (simulated + Gemini)
    evaluation/run_evaluation.py  # E2E evaluation runner
  tests/
    conftest.py
    test_api.py
    test_signalchain.py

frontend/
  src/
    App.tsx                    # Layout, navigation, routes
    api.ts                     # Typed API client
    index.css                  # Design system (light theme)
    components/
      ui.tsx                   # Card, Badge, Kpi, Modal, Toast, etc.
      PipelineFlow.tsx         # Pipeline visualization
      TraceWaterfall.tsx       # Span waterfall view
    pages/
      Dashboard.tsx            # KPIs, recent incidents, charts
      Incidents.tsx            # Incident list, search, create modal
      IncidentDetail.tsx       # Full incident view with tabs
      Workflow.tsx             # Agent workflow visualization
      Architecture.tsx         # Tech stack, agent tree, MCP tools
      ExecutionLogs.tsx        # Traces, span waterfall, A2A tasks
      Guardrails.tsx           # Playground, protection layers, event log
      Evaluation.tsx           # Performance, cost, test results
```

## LLM Modes

- **Gemini** (`GEMINI_API_KEY` set): ADK agents use `gemini-2.5-flash` natively; CrewAI uses `gemini/gemini-2.5-flash` through LiteLLM.
- **Simulated** (default, no key): Deterministic offline policies. The real CrewAI and ADK runtimes, tools, state, callbacks, guardrails, A2A and MCP all execute — only text generation is simulated. Token counts are estimated at ~4 chars/token.

## Run Locally

```bash
# Backend (Python 3.12)
cd backend
python -m venv ../.venv
../.venv/Scripts/pip install -r requirements.txt    # Windows
../.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Frontend (dev server with API proxy)
cd frontend
npm install
npm run dev        # http://localhost:5173

# Or build once and let FastAPI serve it:
npm run build      # http://localhost:8000
```

## Environment Configuration

Copy `.env.example` to `.env` and set:

| Variable | Default | Description |
|---|---|---|
| `LLM_MODE` | `auto` | `auto` / `gemini` / `simulated` |
| `GEMINI_API_KEY` | (empty) | Enables Gemini mode |
| `DATABASE_URL` | `sqlite:///./signalchain.db` | Database connection |
| `A2A_CREWAI_URL` | `inprocess` | URL or `inprocess` for in-process A2A |
| `ENABLE_EXTERNAL_APIS` | `true` | Enable Open-Meteo weather API |
| `LANGFUSE_*` | (empty) | Optional Langfuse observability export |

## Tests

```bash
cd backend
../.venv/Scripts/python -m pytest -q    # 14 tests: isolated DB, offline
```

## Evaluation

```bash
cd backend
../.venv/Scripts/python -m app.evaluation.run_evaluation
```

Or use the Evaluation page in the UI to run and view results.

**Results (simulated mode, 12 cases):**

| Metric | Agents | Rule-based baseline |
|---|---|---|
| Severity (exact) | 75% | 58% |
| Severity (within one level) | 100% | — |
| Routing | 100% | 83% |
| Escalation | 92% | 92% |
| Duplicate detection | 100% | — |
| Schema-valid reports | 100% | — |
| Guardrails | 6/6 attacks blocked, 0/6 false positives | — |

Latency: p50 2.6s, p95 2.8s. Cost: ~$0.006/incident (~$17/month at 100/day on Gemini 2.5 Flash).

Labels are synthetic and hand-assigned — treat these as a regression benchmark, not production accuracy.

## Deploy

**Render** (simplest): Push to GitHub → New → Blueprint → pick this repo. `render.yaml` builds the Dockerfile and mounts a disk for SQLite. Set `GEMINI_API_KEY` in the dashboard.

**Google Cloud Run:**
```bash
gcloud run deploy signalchain --source . --region us-central1 --allow-unauthenticated \
  --set-env-vars LLM_MODE=auto,GEMINI_API_KEY=...
```

**Docker:**
```bash
docker build -t signalchain .
docker run -p 8000:8000 -v signalchain:/data signalchain
```
