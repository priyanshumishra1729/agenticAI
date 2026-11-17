import { Activity, ExternalLink, Layers, ListChecks, RefreshCw, Waypoints } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmt, type Span } from '../api'
import { TraceWaterfall } from '../components/TraceWaterfall'
import { Badge, Card, Empty, Skeleton, StatusBadge, Tabs } from '../components/ui'

export default function ExecutionLogs() {
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
  useEffect(load, [])
  useEffect(() => { setSpans(null); if (sel) api.trace(sel).then((t) => setSpans(t.spans)) }, [sel])

  const current = traces?.find((t) => t.trace_id === sel)

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow"><ListChecks size={12} /> Monitoring</div>
          <h2>Execution Logs</h2>
          <p>Callback-based monitoring of every agent, LLM call, MCP tool and A2A hop. Each workflow produces a span tree with timestamps, status and intermediate outputs.</p>
        </div>
        <div className="row">
          <Badge tone={lf ? 'b-ok' : 'b-neutral'}>{lf ? 'Langfuse export on' : 'Local spans only'}</Badge>
          <button className="btn" onClick={load}><RefreshCw size={13} /> Refresh</button>
        </div>
      </div>

      <Tabs value={tab} onChange={setTab} tabs={[
        { id: 'traces', label: <><Layers size={13} />Execution traces</> },
        { id: 'a2a', label: <><Waypoints size={13} />A2A task log</> },
      ]} />

      {tab === 'traces' && (
        traces === null ? <Skeleton h={300} /> : traces.length === 0 ? <Card><Empty title="No traces yet">Run the AI pipeline on an incident to generate execution logs.</Empty></Card> : (
          <div className="stack">
            <Card flush>
              <div className="table-wrap" style={{ maxHeight: 280, overflow: 'auto' }}><table>
                <thead><tr><th>Execution ID</th><th>Agent / workflow</th><th>Status</th><th className="right">Spans</th><th className="right">Tokens</th><th className="right">Duration</th><th className="right">Timestamp</th></tr></thead>
                <tbody>{traces.map((t) => (
                  <tr key={t.trace_id} className="click" style={t.trace_id === sel ? { background: '#eff6ff' } : undefined} onClick={() => setSel(t.trace_id)}>
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
              <Card title="Span waterfall" icon={<Layers size={15} />} sub={<span className="mono small">{current.trace_id}</span>}
                actions={current.incident_id && <Link className="btn sm" to={`/incidents/${current.incident_id}`}>Open incident <ExternalLink size={11} /></Link>}>
                {spans ? <TraceWaterfall spans={spans} /> : <Skeleton h={300} />}
              </Card>
            )}
          </div>
        )
      )}

      {tab === 'a2a' && (
        <Card flush title="A2A task log" icon={<Waypoints size={15} />} sub="JSON-RPC message/send between ADK coordinator and CrewAI specialist">
          {a2a.length === 0 ? <Empty title="No A2A tasks yet" /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>Task ID</th><th>Sender → Receiver</th><th>State</th><th>Error</th><th className="right">Timestamp</th></tr></thead>
              <tbody>{a2a.map((t) => (
                <tr key={t.task_id}>
                  <td className="id">{t.task_id}</td>
                  <td className="small">{t.sender} <span className="faint">→</span> {t.receiver}</td>
                  <td><StatusBadge status={t.status} /></td>
                  <td className="small muted">{t.error || '—'}</td>
                  <td className="right small muted">{fmt.ago(t.created_at)}</td>
                </tr>))}</tbody>
            </table></div>
          )}
        </Card>
      )}
    </div>
  )
}
