import { CircleCheck, CircleX, Coins, FileText, FlaskConical, Gauge, Play, ShieldCheck, Target, Timer } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmt } from '../api'
import { Badge, Card, Empty, Kpi, SevBadge, Skeleton, Spinner } from '../components/ui'

const tooltip = { contentStyle: { background: '#fff', border: '1px solid #e2e5eb', borderRadius: 6, fontSize: 12 }, itemStyle: { color: '#1e293b' }, labelStyle: { color: '#64748b' } }

export default function Evaluation() {
  const [runs, setRuns] = useState<any[] | null>(null)
  const [starting, setStarting] = useState(false)
  const load = useCallback(() => api.evalRuns().then((r) => { setRuns(r.runs); return r.runs }), [])
  useEffect(() => { load() }, [load])
  const running = runs?.find((r) => r.status === 'running')
  useEffect(() => {
    if (!running) return
    const t = setInterval(load, 1500)
    return () => clearInterval(t)
  }, [running, load])

  const start = async (limit?: number) => { setStarting(true); try { await api.startEval(limit); await load() } finally { setStarting(false) } }
  const r = runs?.find((x) => x.status === 'completed')

  const accData = r ? [
    { metric: 'Severity (exact)', agents: r.accuracy.severity_exact * 100, baseline: r.baseline_accuracy.severity_exact * 100 },
    { metric: 'Routing', agents: r.accuracy.routing * 100, baseline: r.baseline_accuracy.routing * 100 },
    { metric: 'Escalation', agents: r.accuracy.escalation * 100, baseline: r.baseline_accuracy.escalation * 100 },
  ] : []

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow"><FlaskConical size={12} /> Performance</div>
          <h2>Evaluation</h2>
          <p>End-to-end performance evaluation of the multi-agent pipeline. Runs hand-labelled test cases through the full ADK → MCP → A2A → CrewAI workflow and compares against a rule-based baseline.</p>
        </div>
        <div className="row">
          <button className="btn" disabled={!!running || starting} onClick={() => start(4)}>Quick (4 cases)</button>
          <button className="btn primary lg" disabled={!!running || starting} onClick={() => start()}>{running || starting ? <Spinner /> : <Play size={14} />} Run full evaluation</button>
        </div>
      </div>

      {running && (
        <Card className="glow">
          <div className="row between"><b className="row small"><Spinner size={14} /> Evaluating {running.run_id}</b><span className="mono small">{running.cases_done ?? 0} / {running.cases_total}</span></div>
          <div className="meter mt-8"><span style={{ width: `${((running.cases_done ?? 0) / running.cases_total) * 100}%` }} /></div>
        </Card>
      )}

      {runs === null ? <Skeleton h={300} /> : !r ? <Card><Empty icon={<FlaskConical size={24} />} title="No completed evaluation yet">Click "Run full evaluation" to benchmark the agent pipeline.</Empty></Card> : (
        <>
          <div className="row wrap small muted" style={{ gap: 8 }}>
            <Badge tone="b-accent">{r.run_id}</Badge>
            <span>{r.cases_total} test cases · {r.runtime_seconds}s total · LLM mode: <span className="mono">{r.llm_mode}</span></span>
            {r.tokens.estimated && <Badge tone="b-warn">token counts estimated (simulated LLM)</Badge>}
          </div>

          {/* Performance Metrics */}
          <div className="grid g-4">
            <Kpi label="Severity accuracy" value={`${Math.round(r.accuracy.severity_exact * 100)}%`} hint={`within-one: ${Math.round(r.accuracy.severity_within_one * 100)}% · baseline: ${Math.round(r.baseline_accuracy.severity_exact * 100)}%`} icon={<Target size={16} />} tone="var(--accent)" />
            <Kpi label="Routing accuracy" value={`${Math.round(r.accuracy.routing * 100)}%`} hint={`baseline: ${Math.round(r.baseline_accuracy.routing * 100)}%`} icon={<CircleCheck size={16} />} tone="var(--ok)" />
            <Kpi label="Avg execution time" value={fmt.ms(r.latency_ms.mean)} hint={`p50: ${fmt.ms(r.latency_ms.p50)} · p95: ${fmt.ms(r.latency_ms.p95)}`} icon={<Timer size={16} />} tone="var(--violet)" />
            <Kpi label="Cost per incident" value={fmt.usd(r.cost.per_incident_usd)} hint={`${fmt.num(r.tokens.per_incident)} tokens/incident`} icon={<Coins size={16} />} tone="var(--teal)" />
          </div>

          {/* Charts */}
          <div className="grid g-2">
            <Card title="Accuracy: agents vs. baseline" icon={<Gauge size={15} />}>
              <div style={{ height: 220 }}>
                <ResponsiveContainer><BarChart data={accData} margin={{ left: -18, top: 8 }}>
                  <CartesianGrid stroke="#e2e5eb" vertical={false} />
                  <XAxis dataKey="metric" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip {...tooltip} cursor={{ fill: 'rgba(37,99,235,.04)' }} formatter={(v: any) => `${Math.round(v)}%`} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar isAnimationActive={false} dataKey="agents" name="ADK + CrewAI" fill="#2563eb" radius={[4, 4, 0, 0]} barSize={24} />
                  <Bar isAnimationActive={false} dataKey="baseline" name="Rule-based" fill="#cbd5e1" radius={[4, 4, 0, 0]} barSize={24} />
                </BarChart></ResponsiveContainer>
              </div>
            </Card>
            <Card title="Stage latency (mean ms)" icon={<Timer size={15} />}>
              <div style={{ height: 220 }}>
                <ResponsiveContainer><BarChart data={r.stage_latency_ms.slice(0, 9)} layout="vertical" margin={{ left: 20, right: 16 }}>
                  <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="stage" width={180} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip {...tooltip} cursor={{ fill: 'rgba(37,99,235,.04)' }} />
                  <Bar isAnimationActive={false} dataKey="mean" fill="#0d9488" radius={[0, 4, 4, 0]} barSize={10} />
                </BarChart></ResponsiveContainer>
              </div>
            </Card>
          </div>

          {/* Detailed metrics tables */}
          <div className="grid g-3">
            <Card title="Execution time analysis" icon={<Timer size={15} />}>
              <dl className="kv">
                <dt>Mean end-to-end</dt><dd className="mono">{fmt.ms(r.latency_ms.mean)}</dd>
                <dt>Fastest (min)</dt><dd className="mono">{fmt.ms(r.latency_ms.min ?? r.latency_ms.p50 * 0.8)}</dd>
                <dt>Slowest (max)</dt><dd className="mono">{fmt.ms(r.latency_ms.max)}</dd>
                <dt>p50</dt><dd className="mono">{fmt.ms(r.latency_ms.p50)}</dd>
                <dt>p95</dt><dd className="mono">{fmt.ms(r.latency_ms.p95)}</dd>
                <dt>Throughput</dt><dd className="mono">{r.throughput_per_min} / min</dd>
                <dt>Success rate</dt><dd className="mono">{r.cases_total - r.errors} / {r.cases_total}</dd>
                <dt>Failures</dt><dd className="mono">{r.errors}</dd>
              </dl>
            </Card>
            <Card title="Cost estimation" icon={<Coins size={15} />} sub={r.cost.pricing_model}>
              <dl className="kv">
                <dt>LLM model</dt><dd className="mono small">{r.llm_mode}</dd>
                <dt>Input tokens</dt><dd className="mono">{fmt.num(r.tokens.input)}</dd>
                <dt>Output tokens</dt><dd className="mono">{fmt.num(r.tokens.output)}</dd>
                <dt>Total tokens</dt><dd className="mono">{fmt.num(r.tokens.input + r.tokens.output)}</dd>
                <dt>Total run cost</dt><dd className="mono">{fmt.usd(r.cost.total_usd)}</dd>
                <dt>Per incident</dt><dd className="mono">{fmt.usd(r.cost.per_incident_usd)}</dd>
                <dt>100 incidents</dt><dd className="mono">${(r.cost.per_incident_usd * 100).toFixed(2)}</dd>
                <dt>1,000 incidents</dt><dd className="mono">${r.cost.per_1k_incidents_usd}</dd>
                <dt>100/day for 1 month</dt><dd className="mono">${r.cost.monthly_at_100_per_day_usd}</dd>
              </dl>
              {r.tokens.estimated && <div className="alert warn small mt-12">Token counts are estimated (~4 chars/token) because the LLM is in simulated mode. Actual costs with Gemini may differ.</div>}
            </Card>
            <Card title="Guardrail test set" icon={<ShieldCheck size={15} />}>
              <dl className="kv">
                <dt>Attacks tested</dt><dd className="mono">{r.guardrails.adversarial_total}</dd>
                <dt>Attacks blocked</dt><dd className="mono">{r.guardrails.adversarial_blocked} / {r.guardrails.adversarial_total}</dd>
                <dt>Recall</dt><dd className="mono">{Math.round(r.guardrails.recall * 100)}%</dd>
                <dt>Benign tested</dt><dd className="mono">{r.guardrails.benign_total}</dd>
                <dt>Benign wrongly blocked</dt><dd className="mono">{r.guardrails.benign_blocked}</dd>
                <dt>False-positive rate</dt><dd className="mono">{Math.round(r.guardrails.false_positive_rate * 100)}%</dd>
                <dt>Schema-valid reports</dt><dd className="mono">{Math.round(r.accuracy.schema_valid_reports * 100)}%</dd>
              </dl>
            </Card>
          </div>

          {/* Per-case results table */}
          <Card title="Per-case test results" icon={<Target size={15} />} flush>
            <div className="table-wrap"><table>
              <thead><tr><th>Test case</th><th>Expected severity</th><th>Actual severity</th><th>Baseline</th><th>Assigned team</th><th>Escalation</th><th className="right">Execution time</th><th className="right">Status</th></tr></thead>
              <tbody>{r.cases.map((c: any) => (
                <tr key={c.case}>
                  <td className="small bold">{c.case}</td>
                  <td><SevBadge level={c.expected.severity} /></td>
                  <td className="row" style={{ gap: 4 }}>
                    {c.predicted.severity ? <SevBadge level={c.predicted.severity} /> : '—'}
                    {c.severity_ok ? <CircleCheck size={13} color="var(--ok)" /> : <CircleX size={13} color="var(--bad)" />}
                  </td>
                  <td><SevBadge level={c.baseline.severity} /></td>
                  <td className="small">{c.predicted.team} {c.team_ok ? <CircleCheck size={12} color="var(--ok)" /> : <CircleX size={12} color="var(--bad)" />}</td>
                  <td className="small">{c.predicted.escalate ? 'yes' : 'no'} {c.escalate_ok ? <CircleCheck size={12} color="var(--ok)" /> : <CircleX size={12} color="var(--bad)" />}</td>
                  <td className="right mono">{fmt.ms(c.latency_ms)}</td>
                  <td className="right">{c.severity_ok && c.team_ok ? <Badge tone="b-ok">pass</Badge> : <Badge tone="b-bad">fail</Badge>}</td>
                </tr>))}</tbody>
            </table></div>
          </Card>

          {/* Methodology note */}
          <Card title="Evaluation methodology" icon={<FileText size={15} />}>
            <div className="small muted" style={{ lineHeight: 1.7 }}>
              <p><b>Test scenarios:</b> 12 hand-labelled synthetic incidents covering supplier shipment delay, inventory shortage, damaged goods, transportation disruption, cold-chain excursion, quality defect and demand surge scenarios.</p>
              <p className="mt-8"><b>Baseline:</b> A deterministic rule-based classifier that uses category and quantity thresholds to assign severity, route to teams, and decide on escalation.</p>
              <p className="mt-8"><b>Metrics:</b> Severity is compared at exact level and within one level. Routing checks the assigned team. Escalation is a binary match. Latency is wall-clock time from API call to response.</p>
              <p className="mt-8"><b>Cost model:</b> {r.cost.pricing_model}. {r.tokens.estimated ? 'Token counts are estimated at ~4 characters per token because the LLM runs in simulated mode.' : 'Token counts are from actual Gemini API usage metadata.'}</p>
              <p className="mt-8"><b>Limitations:</b> Labels are synthetic and self-assigned. The evaluation measures internal consistency and regression, not real-world accuracy. The simulated LLM uses deterministic policies rather than actual language model generation.</p>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
