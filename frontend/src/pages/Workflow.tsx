import { ArrowDown, Bot, Calculator, CloudSun, Database, FileText, GitBranch, Package, ScanSearch, ShieldCheck, Sparkles, Truck, Waypoints } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmt, type IncidentDetail } from '../api'
import { Badge, Card, Empty, JsonView, Skeleton, Spinner } from '../components/ui'

interface AgentStep {
  name: string
  framework: 'ADK' | 'CrewAI' | 'MCP'
  role: string
  icon: React.ReactNode
  stateKey?: string
  tools?: string[]
}

const PIPELINE: AgentStep[] = [
  { name: 'Intake Agent', framework: 'ADK', role: 'Parses free-text via MCP document_parser, normalizes the incident', icon: <FileText size={15} />, stateKey: 'intake_summary', tools: ['document_parser'] },
  { name: 'Supplier Agent', framework: 'ADK', role: 'Looks up supplier and shipment data from the database', icon: <Truck size={15} />, stateKey: 'supplier_summary', tools: ['supplier_shipment_lookup'] },
  { name: 'Inventory Agent', framework: 'ADK', role: 'Checks current inventory levels for the affected SKU', icon: <Package size={15} />, stateKey: 'inventory_summary', tools: ['inventory_lookup'] },
  { name: 'Weather Agent', framework: 'ADK', role: 'Fetches live weather risk from Open-Meteo external API', icon: <CloudSun size={15} />, stateKey: 'weather_summary', tools: ['weather_risk'] },
  { name: 'Crew Liaison (A2A)', framework: 'ADK', role: 'Sends accumulated context to CrewAI specialists via A2A protocol (JSON-RPC message/send)', icon: <Waypoints size={15} /> },
  { name: 'Verification Analyst', framework: 'CrewAI', role: 'Checks completeness, detects duplicates via historical search', icon: <ScanSearch size={15} />, stateKey: 'crew_summary', tools: ['historical_incident_search'] },
  { name: 'Severity & Impact Analyst', framework: 'CrewAI', role: 'Scores severity and calculates operational impact', icon: <Calculator size={15} />, tools: ['impact_calculator'] },
  { name: 'Resolution Planner', framework: 'CrewAI', role: 'Routes to the correct team, builds an action plan', icon: <Sparkles size={15} /> },
  { name: 'Reviewer Agent', framework: 'ADK', role: 'Reflection: critiques the CrewAI plan for consistency', icon: <ShieldCheck size={15} />, stateKey: 'review_summary' },
]

const FW_CLASS: Record<string, string> = { ADK: 'b-accent', CrewAI: 'b-violet', MCP: 'b-teal' }

export default function Workflow() {
  const [incidents, setIncidents] = useState<any[] | null>(null)
  const [selId, setSelId] = useState<number | null>(null)
  const [detail, setDetail] = useState<IncidentDetail | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => { api.incidents().then((list) => { setIncidents(list); if (list.length) setSelId(list[0].id) }) }, [])
  useEffect(() => {
    if (!selId) return
    setLoading(true)
    api.detail(selId).then(setDetail).finally(() => setLoading(false))
  }, [selId])

  const report = detail?.report
  const ctx = report?.context ?? {}
  const outputs = detail?.agent_outputs ?? {}

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow"><GitBranch size={12} /> Multi-agent pipeline</div>
          <h2>Agent Workflow</h2>
          <p>Execution flow for one incident, showing each agent's framework, responsibility, state updates and context sharing between agents.</p>
        </div>
      </div>

      {/* Incident selector */}
      <Card>
        <div className="row wrap" style={{ gap: 8 }}>
          <span className="small muted">Select an incident to inspect:</span>
          {incidents === null ? <Skeleton h={28} w={200} /> :
            <select className="select" style={{ width: 320 }} value={selId ?? ''} onChange={(e) => setSelId(Number(e.target.value))}>
              {incidents.map((i) => <option key={i.id} value={i.id}>{i.incident_id} — {i.title}</option>)}
            </select>}
          {selId && <Link to={`/incidents/${selId}`} className="btn sm">Open detail</Link>}
        </div>
        {loading && <div className="row mt-8"><Spinner size={14} /> <span className="small muted">Loading workflow data…</span></div>}
      </Card>

      {!report && !loading && (
        <Card>
          <Empty icon={<Bot size={24} />} title="No pipeline run yet">
            {selId ? 'Run the AI pipeline on this incident to see the workflow.' : 'Select an incident above.'}
          </Empty>
        </Card>
      )}

      {report && (
        <>
          {/* Pipeline visualization */}
          <Card title="Execution flow" icon={<GitBranch size={15} />} sub={`${report.llm_mode} · ${fmt.ms(report.metrics.duration_ms)} · ${fmt.num(report.metrics.tokens_in + report.metrics.tokens_out)} tokens`}>
            <div className="stack" style={{ gap: 0 }}>
              {PIPELINE.map((step, i) => {
                const isParallelStart = i === 1
                const isParallelEnd = i === 3
                const isParallel = i >= 1 && i <= 3
                return (
                  <div key={step.name}>
                    {isParallelStart && <div style={{ padding: '4px 0 2px' }}><span className="tiny muted" style={{ marginLeft: 48 }}>PARALLEL (ADK ParallelAgent)</span></div>}
                    <div className="row" style={{ gap: 12, padding: '8px 0', borderLeft: isParallel ? '2px dashed var(--border-2)' : 'none', marginLeft: isParallel ? 24 : 0, paddingLeft: isParallel ? 20 : 0 }}>
                      <div style={{ width: 32, height: 32, borderRadius: 6, background: step.framework === 'ADK' ? '#eff6ff' : step.framework === 'CrewAI' ? '#f5f3ff' : '#f0fdfa', display: 'grid', placeItems: 'center', flexShrink: 0, color: step.framework === 'ADK' ? 'var(--accent)' : step.framework === 'CrewAI' ? 'var(--violet)' : 'var(--teal)' }}>
                        {step.icon}
                      </div>
                      <div className="grow" style={{ minWidth: 0 }}>
                        <div className="row" style={{ gap: 6 }}>
                          <b className="small">{step.name}</b>
                          <Badge tone={FW_CLASS[step.framework]}>{step.framework}</Badge>
                          {step.tools?.map((t) => <Badge key={t} tone="b-teal">{t}</Badge>)}
                        </div>
                        <div className="tiny muted">{step.role}</div>
                      </div>
                      {step.stateKey && outputs[step.stateKey] && (
                        <div className="small muted" style={{ maxWidth: 200, textAlign: 'right' }} title={outputs[step.stateKey]}>
                          <span className="mono tiny">state.{step.stateKey}</span>
                        </div>
                      )}
                    </div>
                    {isParallelEnd && <div style={{ padding: '2px 0 4px' }}><span className="tiny muted" style={{ marginLeft: 48 }}>END PARALLEL</span></div>}
                    {i < PIPELINE.length - 1 && !isParallelEnd && !(isParallel && i < 3) && (
                      <div style={{ display: 'flex', justifyContent: 'center', padding: '2px 0', marginLeft: isParallel ? 44 : 0 }}>
                        <ArrowDown size={14} color="var(--faint)" />
                      </div>
                    )}
                  </div>
                )
              })}
              <div className="row" style={{ gap: 12, padding: '8px 0', borderTop: '1px solid var(--border)', marginTop: 4 }}>
                <div style={{ width: 32, height: 32, borderRadius: 6, background: '#f0fdf4', display: 'grid', placeItems: 'center', flexShrink: 0, color: 'var(--ok)' }}>
                  <FileText size={15} />
                </div>
                <div>
                  <b className="small">Pydantic Structured Report</b>
                  <div className="tiny muted">IncidentResolutionReport — JSON + Markdown output</div>
                </div>
              </div>
            </div>
          </Card>

          {/* Context sharing demonstration */}
          <Card title="Context sharing & state updates" icon={<Database size={15} />} sub="ADK session state passed between agents and across A2A to CrewAI">
            <div className="alert info small" style={{ marginBottom: 12 }}>
              <Database size={14} />
              Each ADK agent writes to shared session state via output_key. The crew liaison sends this state over A2A (JSON-RPC) to the CrewAI crew, which reads it as task context.
            </div>
            <div className="grid g-2">
              {Object.entries(ctx).filter(([, v]) => v != null).map(([k, v]) => (
                <Card key={k} title={<span className="mono small">state.{k}</span>}>
                  <JsonView data={v} maxHeight={200} />
                </Card>
              ))}
            </div>
            {detail?.agent_outputs && Object.keys(detail.agent_outputs).length > 0 && (
              <div className="mt-16">
                <h3 className="small bold" style={{ marginBottom: 8 }}>Agent output_keys (ADK session state)</h3>
                <JsonView data={detail.agent_outputs} maxHeight={240} />
              </div>
            )}
          </Card>

          {/* A2A communication */}
          {report.provenance?.a2a && (
            <Card title="A2A communication" icon={<Waypoints size={15} />} sub="ADK coordinator delegates to CrewAI crew">
              <dl className="kv">
                <dt>Protocol</dt><dd>A2A v0.2.5 (JSON-RPC 2.0)</dd>
                <dt>Method</dt><dd className="mono">message/send</dd>
                <dt>Task ID</dt><dd className="mono">{report.provenance.a2a.task_id}</dd>
                <dt>Remote agent</dt><dd>{report.provenance.a2a.remote_agent}</dd>
                <dt>State</dt><dd><Badge tone="b-ok">{report.provenance.a2a.state}</Badge></dd>
                <dt>Trace propagation</dt><dd className="mono">W3C traceparent</dd>
                {report.provenance.crew_fallback_used && <><dt>Fallback</dt><dd><Badge tone="b-warn">CrewAI guardrail fallback used</Badge></dd></>}
              </dl>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
