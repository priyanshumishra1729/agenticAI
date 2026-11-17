import { Activity, ExternalLink, Layers, RefreshCw, Waypoints } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmt, type Span } from '../api'
import { TraceWaterfall } from '../components/TraceWaterfall'
import { Badge, Card, Empty, Skeleton, StatusBadge, Tabs } from '../components/ui'

export default function Observability() {
  const [traces, setTraces] = useState<any[] | null>(null)
  const [lf, setLf] = useState(false)
  const [sel, setSel] = useState<string | null>(null)
  const [spans, setSpans] = useState<Span[] | null>(null)
  const [a2a, setA2a] = useState<any[]>([])
  const [tab, setTab] = useState<'traces' | 'a2a'>('traces')

  const load = () => {
    api.traces().then((t) => { setTraces(t.traces); setLf(t.langfuse_enabled); if (!sel && t.traces[0]) setSel(t.traces[0].trace_id) })
    api.a2aTasks().then((t) => setA2a(t.tasks))
  }
  useEffect(load, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setSpans(null); if (sel) api.trace(sel).then((t) => setSpans(t.spans)) }, [sel])

  const current = traces?.find((t) => t.trace_id === sel)

  return (
    <div className="stack">
      <div className="page-head">
        <div><div className="eyebrow"><Activity size={13} /> Auditability & provenance</div><h2>Observability</h2>
          <p>Every workflow, agent, LLM call, MCP tool, A2A hop, guardrail and callback is recorded as a span. Trace context crosses the A2A boundary via the W3C <span className="mono">traceparent</span> header.</p></div>
        <div className="row">
          <Badge tone={lf ? 'b-ok' : 'b-neutral'}>{lf ? 'Langfuse export on' : 'Langfuse off (set LANGFUSE_* keys)'}</Badge>
          <button className="btn" onClick={load}><RefreshCw size={14} /> Refresh</button>
        </div>
      </div>

      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'traces', label: <><Layers size={13} />Traces</> }, { id: 'a2a', label: <><Waypoints size={13} />A2A tasks</> }]} />

      {tab === 'traces' && (
        traces === null ? <Skeleton h={300} /> : traces.length === 0 ? <Card><Empty title="No traces yet">Run the AI pipeline on an incident to generate a trace.</Empty></Card> : (
          <div className="stack">
            <Card flush>
              <div className="table-wrap" style={{ maxHeight: 300, overflow: 'auto' }}><table>
                <thead><tr><th>Trace</th><th>Workflow</th><th>Status</th><th className="right">Spans</th><th className="right">Tokens</th><th className="right">Duration</th><th className="right">When</th></tr></thead>
                <tbody>{traces.map((t) => (
                  <tr key={t.trace_id} className="click" style={t.trace_id === sel ? { background: 'rgba(124,140,255,.08)' } : undefined} onClick={() => setSel(t.trace_id)}>
                    <td className="id">{t.trace_id.slice(0, 12)}…</td>
                    <td className="small">{t.name}{t.input?.incident_id && <span className="faint"> · {t.input.incident_id}</span>}</td>
                    <td><StatusBadge status={t.status === 'ok' ? 'completed' : 'failed'} /></td>
                    <td className="right mono">{t.spans}</td>
                    <td className="right mono">{fmt.num(t.tokens_in + t.tokens_out)}</td>
                    <td className="right mono">{fmt.ms(t.duration_ms)}</td>
                    <td className="right small muted">{fmt.ago(t.created_at)}</td>
                  </tr>))}</tbody>
              </table></div>
            </Card>
            {current && (
              <Card title="Span waterfall" icon={<Layers size={16} />} sub={<span className="mono">{current.trace_id}</span>}
                actions={current.incident_id && <Link className="btn sm" to={`/incidents/${current.incident_id}`}>Open incident <ExternalLink size={12} /></Link>}>
                {spans ? <TraceWaterfall spans={spans} /> : <Skeleton h={300} />}
              </Card>
            )}
          </div>
        )
      )}

      {tab === 'a2a' && (
        <Card flush title="A2A task log" icon={<Waypoints size={16} />} sub="JSON-RPC message/send tasks between the ADK coordinator and the CrewAI specialist">
          {a2a.length === 0 ? <Empty title="No A2A tasks yet" /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>Task</th><th>Sender → receiver</th><th>State</th><th>Error</th><th className="right">When</th></tr></thead>
              <tbody>{a2a.map((t) => (
                <tr key={t.task_id}>
                  <td className="id">{t.task_id}</td><td className="small">{t.sender} <span className="faint">→</span> {t.receiver}</td>
                  <td><StatusBadge status={t.status} /></td><td className="small muted">{t.error || '—'}</td><td className="right small muted">{fmt.ago(t.created_at)}</td>
                </tr>))}</tbody>
            </table></div>
          )}
        </Card>
      )}
    </div>
  )
}
