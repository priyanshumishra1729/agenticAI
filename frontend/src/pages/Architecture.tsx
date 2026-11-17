import { Bot, Boxes, CircleCheck, Database, GitBranch, Network, Play, Waypoints, Wrench } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { Badge, Card, JsonView, Skeleton, Spinner } from '../components/ui'

const STACK = [
  ['Google ADK', 'Coordinator agent framework — SequentialAgent, ParallelAgent, LlmAgent, session state, 6 callbacks'],
  ['CrewAI', 'Specialist crew — 3 agents with Process.sequential, task context, step/task callbacks, guardrails'],
  ['MCP (Model Context Protocol)', 'Tool server with 6 tools: 3 DB lookups, document parser, impact calculator, weather API'],
  ['A2A Protocol', 'Agent-to-agent communication — JSON-RPC 2.0, agent cards, W3C traceparent propagation'],
  ['FastAPI', 'Backend API with SQLAlchemy ORM, SQLite database, Pydantic v2 schemas'],
  ['React + TypeScript', 'Frontend SPA with Vite, react-router, recharts for data visualization'],
  ['Pydantic v2', 'Structured output for all agent results and the final IncidentResolutionReport'],
  ['Observability', 'Custom span tree per run, persisted to DB, optional Langfuse export'],
]

const PATTERNS = [
  ['Sequential pipeline', 'ADK SequentialAgent chains intake, gathering, delegation and review in order'],
  ['Parallel fan-out', 'ADK ParallelAgent runs supplier, inventory and weather lookups concurrently'],
  ['Coordinator / delegation', 'ADK coordinator delegates specialist analysis to CrewAI over A2A'],
  ['Tool use (ReAct)', 'CrewAI agents reason then act through MCP tools'],
  ['Reflection / critic', 'Reviewer agent critiques and corrects the CrewAI resolution plan'],
  ['Shared-state blackboard', 'ADK session state and CrewAI run-state carry context between agents'],
  ['Guardrail + fallback', 'Task guardrails retry on failure; deterministic fallback keeps the pipeline live'],
  ['Human-in-the-loop', 'High and critical plans require operator approval before execution'],
]

const REQS = [
  ['1. Context sharing & state', 'ADK session state (tool_context.state, output_key) + CrewAI task context + A2A state transfer'],
  ['2. MCP tool integration', 'FastMCP server with 6 tools including Open-Meteo external API'],
  ['3. Structured output (Pydantic)', 'output_pydantic per CrewAI task; IncidentResolutionReport as JSON + Markdown'],
  ['4. Agentic design patterns', 'Sequential, parallel, delegation, ReAct, reflection, human-in-the-loop'],
  ['5. Monitoring via callbacks', 'ADK before/after agent/model/tool callbacks + CrewAI step/task callbacks'],
  ['6. A2A interoperability', 'JSON-RPC message/send + tasks/get, agent cards, ADK calls CrewAI over A2A'],
  ['7. CrewAI + ADK only', 'ADK coordinator + CrewAI specialist crew; no other agent framework'],
  ['8. Guardrails & validation', 'Injection/toxicity/PII screens, tool arg type checks, output schemas, task guardrails'],
  ['9. Observability', 'Span tree per run with W3C traceparent across A2A; optional Langfuse export'],
  ['10. Evaluation & cost', 'Labelled e2e eval vs baseline, stage latency, tokens and cost projections'],
  ['11. Cloud deployment', 'Dockerfile, Render blueprint, Cloud Run instructions'],
]

function Tree({ n, depth = 0 }: { n: any; depth?: number }) {
  const icon = n.type === 'SequentialAgent' ? <GitBranch size={13} /> : n.type === 'ParallelAgent' ? <Boxes size={13} /> : <Bot size={13} />
  return (
    <div style={{ marginLeft: depth ? 16 : 0, borderLeft: depth ? '1px solid var(--border)' : 'none', paddingLeft: depth ? 10 : 0 }}>
      <div className="row wrap" style={{ padding: '5px 0', gap: 6 }}>
        <span style={{ color: 'var(--accent)' }}>{icon}</span>
        <b className="mono" style={{ fontSize: 12 }}>{n.name}</b>
        <Badge tone={n.type === 'LlmAgent' ? 'b-accent' : 'b-violet'}>{n.type}</Badge>
        {n.tools?.map((t: string) => <Badge key={t} tone="b-teal"><Wrench size={9} />{t}</Badge>)}
        {n.output_key && <span className="tiny faint">→ state.{n.output_key}</span>}
      </div>
      {n.children?.map((c: any) => <Tree key={c.name} n={c} depth={depth + 1} />)}
    </div>
  )
}

export default function Architecture() {
  const [sys, setSys] = useState<any>(null)
  const [tools, setTools] = useState<any>(null)
  const [cards, setCards] = useState<Record<string, any>>({})
  const [tool, setTool] = useState('document_parser')
  const [args, setArgs] = useState('{\n  "description": "BlueHarbor Logistics container SHIP-1042 with 90 units of SKU-1178 delayed at Houston, TX"\n}')
  const [result, setResult] = useState<any>(null)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    api.system().then(setSys)
    api.mcpTools().then(setTools)
    Promise.all(['coordinator', 'crewai'].map((a) => api.agentCard(a).then((c) => [a, c]))).then((x) => setCards(Object.fromEntries(x)))
  }, [])

  const example = (name: string) => {
    const ex: Record<string, any> = {
      document_parser: { description: 'BlueHarbor Logistics container SHIP-1042 with 90 units of SKU-1178 delayed at Houston, TX' },
      supplier_shipment_lookup: { supplier: 'Shenzhen Apex Electronics', shipment_id: 'SHIP-3310' },
      inventory_lookup: { product_sku: 'SKU-2204' },
      historical_incident_search: { category: 'transportation_delay', location: 'Houston, TX' },
      impact_calculator: { quantity_affected: 400, total_available: 110, daily_demand: 95, unit_cost_usd: 65, delay_hours: 96 },
      weather_risk: { location: 'Rotterdam' },
    }
    setTool(name); setArgs(JSON.stringify(ex[name] ?? {}, null, 2)); setResult(null)
  }
  const call = async () => {
    setRunning(true)
    try { setResult((await api.callTool(tool, JSON.parse(args))).result) } catch (e) { setResult({ error: (e as Error).message }) } finally { setRunning(false) }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow"><Network size={12} /> System design</div>
          <h2>Architecture</h2>
          <p>Technology stack, agent structure and design patterns used in the system.</p>
        </div>
      </div>

      {/* Section 1: Technology Stack */}
      <Card title="Technology stack" icon={<Database size={15} />}>
        <div className="table-wrap"><table>
          <thead><tr><th>Technology</th><th>Role</th></tr></thead>
          <tbody>{STACK.map(([t, d]) => <tr key={t}><td className="bold" style={{ whiteSpace: 'nowrap' }}>{t}</td><td className="small muted">{d}</td></tr>)}</tbody>
        </table></div>
      </Card>

      {/* Section 2: Agent Architecture */}
      <div className="grid g-main">
        <Card title="ADK agent tree" icon={<GitBranch size={15} />} sub="Introspected from build_pipeline()">
          {sys ? <Tree n={sys.pipeline} /> : <Skeleton h={200} />}
          <div className="divider" />
          <div className="row wrap small" style={{ gap: 6 }}>
            <span className="muted">CrewAI crew (via A2A):</span>
            {['Verification Analyst', 'Severity & Impact Analyst', 'Resolution Planner'].map((a) => <Badge key={a} tone="b-violet"><Bot size={9} />{a}</Badge>)}
          </div>
        </Card>

        <div className="stack">
          {/* A2A Agent Cards */}
          {Object.entries(cards).map(([k, c]) => (
            <Card key={k} title={c.name} icon={<Waypoints size={15} />}
              actions={<Badge tone={k === 'crewai' ? 'b-violet' : 'b-accent'}>{c.provider?.framework}</Badge>}>
              <p className="small muted">{c.description}</p>
              <div className="row wrap mt-8" style={{ gap: 4 }}>
                <Badge tone="b-teal">A2A v{c.protocolVersion}</Badge>
                {c.skills?.map((s: any) => <Badge key={s.id} tone="b-accent">{s.id}</Badge>)}
              </div>
            </Card>
          ))}
        </div>
      </div>

      {/* Section 3: Design Patterns */}
      <Card title="Design patterns" icon={<Boxes size={15} />}>
        <div className="grid g-2">
          {PATTERNS.map(([t, d]) => (
            <div key={t} style={{ padding: '8px 0' }}>
              <div className="bold small row" style={{ gap: 5 }}><CircleCheck size={13} color="var(--ok)" />{t}</div>
              <div className="tiny muted" style={{ marginLeft: 18 }}>{d}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* MCP Tool Explorer */}
      <Card title="MCP tools" icon={<Database size={15} />} sub={tools?.transport}>
        <div className="grid g-main">
          <div className="stack" style={{ gap: 6 }}>
            {(tools?.tools ?? []).map((t: any) => (
              <button key={t.name} onClick={() => example(t.name)} className="btn" style={{ justifyContent: 'flex-start', textAlign: 'left', whiteSpace: 'normal', padding: '8px 10px', borderColor: tool === t.name ? 'var(--accent)' : undefined }}>
                <Wrench size={13} color="var(--teal)" />
                <span className="grow"><span className="mono bold" style={{ fontSize: 12 }}>{t.name}</span>{t.name === 'weather_risk' && <Badge tone="b-warn">external API</Badge>}<span className="tiny muted" style={{ display: 'block', fontWeight: 400 }}>{t.description}</span></span>
              </button>
            ))}
            {!tools && <Skeleton h={200} />}
          </div>
          <div className="stack" style={{ gap: 8 }}>
            <div className="row between"><b className="mono small">{tool}</b><button className="btn primary sm" onClick={call} disabled={running}>{running ? <Spinner size={12} /> : <Play size={12} />} Run</button></div>
            <textarea className="textarea mono" style={{ minHeight: 100 }} value={args} onChange={(e) => setArgs(e.target.value)} spellCheck={false} />
            {result && <JsonView data={result} maxHeight={280} />}
          </div>
        </div>
      </Card>

      {/* Requirement Coverage */}
      <Card title="Requirement coverage" icon={<CircleCheck size={15} />} flush>
        <div className="table-wrap"><table>
          <thead><tr><th>Requirement</th><th>Implementation</th></tr></thead>
          <tbody>{REQS.map(([r, how]) => <tr key={r}><td className="bold" style={{ whiteSpace: 'nowrap' }}>{r}</td><td className="small muted">{how}</td></tr>)}</tbody>
        </table></div>
      </Card>
    </div>
  )
}
