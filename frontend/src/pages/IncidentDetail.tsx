import { ArrowLeft, Bot, Braces, CircleCheck, Coins, Cpu, Database, FileText, Layers, ListChecks, MapPin, Play, RefreshCw, Send, ShieldAlert, ShieldCheck, Sparkles, ThumbsDown, ThumbsUp, Timer, TriangleAlert, Waypoints } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, fmt, type IncidentDetail as Detail, type Span } from '../api'
import { PipelineFlow, STAGES } from '../components/PipelineFlow'
import { TraceWaterfall } from '../components/TraceWaterfall'
import { Badge, Card, Empty, JsonView, Markdown, SeverityGauge, SevBadge, Skeleton, Spinner, StatusBadge, Tabs, useToast } from '../components/ui'

type Tab = 'summary' | 'markdown' | 'json' | 'state' | 'trace' | 'tools' | 'log'

function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--panel-2)' }}>
      <div className="tiny muted" style={{ textTransform: 'uppercase', letterSpacing: '.06em' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, marginTop: 3, color: tone }}>{value}</div>
    </div>
  )
}

const LIFECYCLE = ['open', 'in_review', 'in_progress', 'awaiting_verification', 'resolved', 'closed']

export default function IncidentDetail() {
  const id = Number(useParams().id)
  const [params, setParams] = useSearchParams()
  const [d, setD] = useState<Detail | null>(null)
  const [progress, setProgress] = useState(-1)
  const [running, setRunning] = useState(false)
  const [tab, setTab] = useState<Tab>('summary')
  const [spans, setSpans] = useState<Span[] | null>(null)
  const [notes, setNotes] = useState('')
  const [evidence, setEvidence] = useState('')
  const [busy, setBusy] = useState(false)
  const timer = useRef<number | null>(null)
  const toast = useToast()

  const load = useCallback(async () => {
    const data = await api.detail(id)
    setD(data)
    if (data.report) setProgress(STAGES.length)
    return data
  }, [id])

  useEffect(() => { load().catch(() => setD(null)) }, [load])
  useEffect(() => {
    setSpans(null)
    if (d?.trace_id && tab === 'trace') api.trace(d.trace_id).then((t) => setSpans(t.spans)).catch(() => setSpans([]))
  }, [d?.trace_id, tab])

  const run = useCallback(async () => {
    setRunning(true); setProgress(0)
    let p = 0
    timer.current = window.setInterval(() => { p = Math.min(p + 1, STAGES.length - 2); setProgress(p) }, 520)
    try {
      const out = await api.runWorkflow(id)
      await load()
      toast.ok(`Pipeline complete — ${out.report.severity.level.toUpperCase()} → ${out.report.plan.owner_team} in ${fmt.ms(out.report.metrics.duration_ms)}`)
      setTab('summary')
    } catch (e) {
      toast.bad((e as Error).message)
      setProgress(-1)
    } finally {
      if (timer.current) clearInterval(timer.current)
      setRunning(false)
      setProgress((x) => (x >= 0 ? STAGES.length : x))
    }
  }, [id, load, toast])

  useEffect(() => {
    if (params.get('run') === '1' && d && !running) { setParams({}, { replace: true }); run() }
  }, [params, d, running, run, setParams])
  useEffect(() => () => { if (timer.current) clearInterval(timer.current) }, [])

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true)
    try { await fn(); await load(); toast.ok(msg) } catch (e) { toast.bad((e as Error).message) } finally { setBusy(false) }
  }

  if (!d) return <div className="stack"><Skeleton h={28} w="40%" /><Skeleton h={140} /><Skeleton h={280} /></div>
  const { incident: inc, report: r } = d
  const stageIdx = LIFECYCLE.indexOf(inc.status)

  return (
    <div className="stack">
      <div>
        <Link to="/incidents" className="btn ghost sm" style={{ marginLeft: -6 }}><ArrowLeft size={13} /> Incidents</Link>
        <div className="page-head" style={{ marginTop: 4, marginBottom: 0 }}>
          <div>
            <div className="row wrap" style={{ gap: 6 }}>
              <span className="id" style={{ fontSize: 12 }}>{inc.incident_id}</span>
              <SevBadge level={inc.severity} /><StatusBadge status={inc.status} />
              <Badge>{fmt.label(inc.category)}</Badge>
              {inc.duplicate_of && <Badge tone="b-warn">possible duplicate of {inc.duplicate_of}</Badge>}
            </div>
            <h2 className="mt-8">{inc.title}</h2>
            <p className="row wrap muted small" style={{ gap: 12, marginTop: 4 }}>
              <span className="row" style={{ gap: 4 }}><MapPin size={12} />{inc.location}</span>
              {inc.supplier && <span>{inc.supplier}</span>}
              {inc.shipment_id && <span className="mono">{inc.shipment_id}</span>}
              {inc.product_sku && <span className="mono">{inc.product_sku}</span>}
              <span>{inc.quantity_affected} units</span>
              <span className="faint">reported {fmt.ago(inc.reported_time)}</span>
            </p>
          </div>
          <div className="row">
            {inc.status !== 'closed' && inc.status !== 'escalated' && <button className="btn danger" disabled={busy} onClick={() => act(() => api.escalate(id, 'Manual escalation'), 'Incident escalated')}><ShieldAlert size={14} /> Escalate</button>}
            <button className="btn primary lg" disabled={running || inc.status === 'closed'} onClick={run}>
              {running ? <><Spinner /> Running…</> : r ? <><RefreshCw size={14} /> Re-run pipeline</> : <><Play size={14} /> Run AI pipeline</>}
            </button>
          </div>
        </div>
      </div>

      <Card title="Pipeline" icon={<Bot size={15} />} className={running ? 'glow' : ''}
        sub={running ? 'Processing…' : r ? `Completed · ${r.llm_mode}` : 'Not run yet'}
        actions={r && <div className="row wrap" style={{ gap: 4 }}>
          <Badge tone="b-accent"><Timer size={10} />{fmt.ms(r.metrics.duration_ms)}</Badge>
          <Badge tone="b-violet"><Cpu size={10} />{r.metrics.llm_calls} LLM</Badge>
          <Badge tone="b-teal"><Layers size={10} />{fmt.num(r.metrics.tokens_in + r.metrics.tokens_out)} tok</Badge>
          <Badge tone="b-ok"><Coins size={10} />{fmt.usd(r.metrics.estimated_cost_usd)}</Badge>
        </div>}>
        <PipelineFlow progress={progress} />
        {r?.provenance?.a2a && (
          <div className="row wrap small muted mt-8" style={{ gap: 12 }}>
            <span className="row" style={{ gap: 4 }}><Waypoints size={12} /> A2A: <span className="mono">{r.provenance.a2a.task_id}</span> → {r.provenance.a2a.remote_agent}</span>
            {r.provenance.crew_fallback_used && <Badge tone="b-warn">fallback used</Badge>}
          </div>
        )}
      </Card>

      {!r ? (
        <div className="grid g-main">
          <Card title="Description" icon={<FileText size={15} />}>
            <p className="muted small">{inc.description}</p>
            <Empty icon={<Sparkles size={24} />} title="No AI analysis yet">Run the pipeline to process this incident.</Empty>
          </Card>
          <Timeline d={d} />
        </div>
      ) : (
        <div className="grid g-main">
          <div className="stack" style={{ minWidth: 0 }}>
            <Tabs<Tab> value={tab} onChange={setTab} tabs={[
              { id: 'summary', label: <><Sparkles size={12} />Summary</> },
              { id: 'markdown', label: <><FileText size={12} />Markdown</> },
              { id: 'json', label: <><Braces size={12} />JSON</> },
              { id: 'state', label: <><Database size={12} />Shared state</> },
              { id: 'trace', label: <><Layers size={12} />Trace</> },
              { id: 'tools', label: <><ShieldCheck size={12} />Tools</> },
              { id: 'log', label: <><ListChecks size={12} />Agent log</> },
            ]} />

            {tab === 'summary' && (
              <div className="stack fade-in">
                <div className="grid g-2">
                  <Card title="Severity" icon={<ShieldAlert size={15} />} actions={<SevBadge level={r.severity.level} />}>
                    <SeverityGauge score={r.severity.score} level={r.severity.level} />
                    <div className="tiny muted" style={{ textAlign: 'center' }}>confidence {(r.severity.confidence * 100).toFixed(0)}%</div>
                    <ul className="small mt-8" style={{ paddingLeft: 16, margin: 0, color: '#475569' }}>{r.severity.drivers.map((x) => <li key={x}>{x}</li>)}</ul>
                  </Card>
                  <Card title="Impact" icon={<Coins size={15} />} sub="MCP impact_calculator">
                    <div className="grid g-2" style={{ gap: 8 }}>
                      <Stat label="Revenue at risk" value={`$${fmt.num(r.severity.impact.revenue_at_risk_usd)}`} tone="var(--high)" />
                      <Stat label="Days of cover" value={r.severity.impact.days_of_cover} tone={r.severity.impact.days_of_cover < 2 ? 'var(--critical)' : undefined} />
                      <Stat label="Shortage units" value={r.severity.impact.shortage_units} />
                      <Stat label="Expedite cost" value={`$${fmt.num(r.severity.impact.expedite_cost_usd)}`} />
                    </div>
                  </Card>
                </div>

                <Card title="Resolution plan" icon={<ListChecks size={15} />} sub={r.plan.summary}
                  actions={<><Badge tone="b-accent">{r.plan.priority}</Badge><Badge tone="b-teal">{r.plan.owner_team}</Badge></>}>
                  {r.plan.escalate && <div className="alert bad" style={{ marginBottom: 10 }}><TriangleAlert size={14} /><span><b>Escalation:</b> {r.plan.escalation_reason}</span></div>}
                  <div className="table-wrap"><table>
                    <thead><tr><th>#</th><th>Action</th><th>Owner</th><th className="right">Due</th></tr></thead>
                    <tbody>{r.plan.actions.map((a, i) => <tr key={i}><td className="faint">{i + 1}</td><td>{a.title}</td><td><Badge>{a.owner}</Badge></td><td className="right mono">{a.due_hours}h</td></tr>)}</tbody>
                  </table></div>
                </Card>

                <div className="grid g-2">
                  <Card title="Verification" icon={<CircleCheck size={15} />} actions={<Badge tone={r.verification.status === 'verified' ? 'b-ok' : 'b-warn'}>{fmt.label(r.verification.status)}</Badge>}>
                    <div className="small row between"><span className="muted">Completeness</span><b>{r.verification.completeness_score}%</b></div>
                    <div className="meter mt-4"><span style={{ width: `${r.verification.completeness_score}%` }} /></div>
                    <div className="small row between mt-12"><span className="muted">Duplicate risk</span><b>{r.verification.duplicate_score}%</b></div>
                    <div className="meter mt-4"><span style={{ width: `${r.verification.duplicate_score}%`, background: 'var(--warn)' }} /></div>
                    <p className="small muted mt-8">{r.verification.notes}</p>
                  </Card>
                  <Card title="Reviewer (reflection)" icon={<ShieldCheck size={15} />} sub="ADK critic reviews CrewAI plan">
                    {r.review.adjustments.length + r.review.issues.length === 0
                      ? <div className="alert ok small"><CircleCheck size={13} />No issues. Plan is consistent with context.</div>
                      : null}
                    {r.review.adjustments.map((x) => <div key={x} className="alert info small mt-8"><Sparkles size={13} />{x}</div>)}
                    {r.review.issues.map((x) => <div key={x} className="alert warn small mt-8"><TriangleAlert size={13} />{x}</div>)}
                    <div className="small row between mt-8"><span className="muted">Human approval required</span><b>{r.review.human_approval_required ? 'Yes' : 'No'}</b></div>
                  </Card>
                </div>
              </div>
            )}
            {tab === 'markdown' && d.markdown && <Card className="fade-in" actions={<a className="btn sm" href={`/api/incidents/${id}/report.md`} target="_blank" rel="noreferrer">Open .md</a>}><Markdown text={d.markdown} /></Card>}
            {tab === 'json' && <Card className="fade-in" title="IncidentResolutionReport" icon={<Braces size={15} />} sub="Pydantic-validated output"><JsonView data={r} maxHeight={600} /></Card>}
            {tab === 'state' && (
              <div className="stack fade-in">
                <div className="alert info small"><Database size={13} />ADK agents wrote these values to shared session state. They cross the A2A boundary to reach the CrewAI crew.</div>
                <div className="grid g-2">
                  {Object.entries(r.context).map(([k, v]) => <Card key={k} title={<span className="mono small">state.{k}</span>}><JsonView data={v} maxHeight={220} /></Card>)}
                </div>
                {d.agent_outputs && <Card title="Agent output_keys"><JsonView data={d.agent_outputs} maxHeight={260} /></Card>}
              </div>
            )}
            {tab === 'trace' && (
              <Card className="fade-in" title="Trace" icon={<Layers size={15} />} sub={`${spans?.length ?? '…'} spans`}>
                {spans ? <TraceWaterfall spans={spans} /> : <Skeleton h={280} />}
              </Card>
            )}
            {tab === 'tools' && (
              <div className="stack fade-in">
                <Card title="MCP tool calls" icon={<Database size={15} />} flush>
                  <div className="table-wrap"><table>
                    <thead><tr><th>Tool</th><th>Caller</th><th>Status</th><th className="right">Latency</th></tr></thead>
                    <tbody>{d.tool_calls.map((t, i) => <tr key={i}><td className="mono small">{t.tool}</td><td className="small muted">{t.caller}</td><td><Badge tone={t.status === 'ok' ? 'b-ok' : 'b-bad'}>{t.status}</Badge></td><td className="right mono">{t.duration_ms}ms</td></tr>)}</tbody>
                  </table></div>
                </Card>
                <Card title="Guardrail checks" icon={<ShieldCheck size={15} />} flush>
                  <div className="table-wrap"><table>
                    <thead><tr><th>Check</th><th>Stage</th><th>Result</th><th>Details</th></tr></thead>
                    <tbody>{d.guardrails.map((g, i) => <tr key={i}><td className="mono small">{g.check}</td><td className="small muted">{g.stage}</td><td>{g.passed ? <Badge tone="b-ok">passed</Badge> : <Badge tone="b-bad">blocked</Badge>}</td><td className="small muted ellipsis" style={{ maxWidth: 260 }} title={g.details}>{g.details}</td></tr>)}</tbody>
                  </table></div>
                </Card>
              </div>
            )}
            {tab === 'log' && d.monitoring && (
              <div className="grid g-2 fade-in">
                <Card title="ADK events" icon={<Bot size={15} />} sub={`${d.monitoring.adk_events.length} events`}>
                  <div className="timeline" style={{ maxHeight: 460, overflow: 'auto' }}>
                    {d.monitoring.adk_events.map((e, i) => (
                      <div key={i} className="tl-item" style={{ ['--tl' as any]: e.parts.some((p) => p.startsWith('call')) ? 'var(--teal)' : 'var(--accent)' }}>
                        <div className="row between"><b className="small">{e.author}</b><span className="when mono">+{e.t_ms}ms</span></div>
                        <div className="tiny muted">{e.parts.join(', ') || 'event'}{e.state_delta.length ? ` · state: ${e.state_delta.join(', ')}` : ''}</div>
                      </div>
                    ))}
                  </div>
                </Card>
                <Card title="CrewAI callbacks" icon={<Sparkles size={15} />} sub="step_callback + task_callback">
                  <div className="timeline" style={{ maxHeight: 460, overflow: 'auto' }}>
                    {d.monitoring.crew_monitor.map((m, i) => (
                      <div key={i} className="tl-item" style={{ ['--tl' as any]: m.type === 'task' ? 'var(--ok)' : 'var(--violet)' }}>
                        <b className="small">{m.type === 'task' ? m.agent : m.step}</b>
                        <div className="tiny muted ellipsis" title={m.thought || m.result || m.output}>{m.tool ? `tool: ${m.tool}` : ''} {(m.thought || m.result || m.output || m.task || '').slice(0, 100)}</div>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            )}
          </div>

          <div className="stack" style={{ minWidth: 0 }}>
            <Card title="Lifecycle" icon={<ListChecks size={15} />}>
              <div className="stack" style={{ gap: 6 }}>
                {LIFECYCLE.map((s, i) => (
                  <div key={s} className="row small" style={{ opacity: i <= stageIdx || inc.status === 'escalated' ? 1 : 0.4 }}>
                    {i < stageIdx ? <CircleCheck size={14} color="var(--ok)" /> : i === stageIdx ? <Badge tone="b-accent">now</Badge> : <span style={{ width: 14 }} />}
                    {fmt.label(s)}
                  </div>
                ))}
                {inc.status === 'escalated' && <div className="alert bad small"><ShieldAlert size={13} />Escalated</div>}
              </div>
            </Card>

            {d.plan && !d.plan.approved && inc.status !== 'closed' && (
              <Card title="Human approval" icon={<ThumbsUp size={15} />} className="glow" sub="Operator must approve before execution">
                <textarea className="textarea" style={{ minHeight: 60 }} placeholder="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
                <div className="row mt-8">
                  <button className="btn success grow" disabled={busy} onClick={() => act(() => api.approve(id, true, notes), 'Plan approved')}><ThumbsUp size={14} /> Approve</button>
                  <button className="btn danger" disabled={busy} onClick={() => act(() => api.approve(id, false, notes), 'Plan rejected')}><ThumbsDown size={14} /></button>
                </div>
              </Card>
            )}
            {d.plan?.approved && ['in_progress', 'escalated', 'assigned'].includes(inc.status) && (
              <Card title="Resolution evidence" icon={<Send size={15} />}>
                <textarea className="textarea" style={{ minHeight: 60 }} placeholder="What was done?" value={evidence} onChange={(e) => setEvidence(e.target.value)} />
                <button className="btn primary mt-8" style={{ width: '100%' }} disabled={busy || evidence.length < 5} onClick={() => act(() => api.evidence(id, evidence), 'Evidence submitted')}><Send size={14} /> Submit</button>
              </Card>
            )}
            {inc.status === 'awaiting_verification' && <button className="btn success lg" disabled={busy} onClick={() => act(() => api.verify(id), 'Verified')}><CircleCheck size={15} /> Verify resolution</button>}
            {inc.status === 'resolved' && <button className="btn primary lg" disabled={busy} onClick={() => act(() => api.close(id), 'Closed')}><CircleCheck size={15} /> Close incident</button>}

            <Timeline d={d} />
          </div>
        </div>
      )}
      {toast.node}
    </div>
  )
}

function Timeline({ d }: { d: Detail }) {
  const tone: Record<string, string> = { created: 'var(--accent)', workflow_ran: 'var(--teal)', escalated: 'var(--bad)', approval: 'var(--ok)', closed: 'var(--faint)', resolved: 'var(--ok)' }
  return (
    <Card title="Activity" icon={<Timer size={15} />}>
      <div className="timeline">
        {d.events.map((e, i) => (
          <div key={i} className="tl-item" style={{ ['--tl' as any]: tone[e.type] ?? 'var(--violet)' }}>
            <div className="small">{e.message}</div>
            <div className="when">{fmt.label(e.type)} · {fmt.ago(e.at)}</div>
          </div>
        ))}
      </div>
    </Card>
  )
}
