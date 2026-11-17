import { Activity, ArrowRight, Gauge, ShieldAlert, Siren, Timer, TriangleAlert, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmt } from '../api'
import { Card, Empty, Kpi, SevBadge, Skeleton, StatusBadge } from '../components/ui'

const SEV_FILL: Record<string, string> = { low: '#16a34a', medium: '#ca8a04', high: '#ea580c', critical: '#dc2626' }
const tooltip = { contentStyle: { background: '#fff', border: '1px solid #e2e5eb', borderRadius: 6, fontSize: 12 }, itemStyle: { color: '#1e293b' }, labelStyle: { color: '#64748b' } }

export default function Dashboard() {
  const [a, setA] = useState<any>(null)
  const [err, setErr] = useState('')
  const nav = useNavigate()
  useEffect(() => {
    const load = () => api.analytics().then(setA).catch((e) => setErr(e.message))
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])

  if (err) return <div className="alert bad"><TriangleAlert size={15} />Backend unreachable: {err}</div>
  const sevData = (a?.severity_distribution ?? []).filter((d: any) => d.value > 0)

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow"><Activity size={12} /> Overview</div>
          <h2>Dashboard</h2>
          <p>Supply chain incident management. ADK coordinates intake and context gathering; CrewAI specialists analyse each incident over A2A.</p>
        </div>
        <Link to="/incidents?new=1" className="btn primary lg"><Siren size={15} /> Report incident</Link>
      </div>

      <div className="grid g-4">
        {a ? <>
          <Kpi label="Total incidents" value={a.total_incidents} hint={`${a.open_incidents} open`} icon={<Siren size={16} />} tone="var(--accent)" />
          <Kpi label="Critical" value={a.critical_incidents} hint={`${a.escalated_incidents} escalated`} icon={<ShieldAlert size={16} />} tone="var(--critical)" />
          <Kpi label="Pending verification" value={a.awaiting_approval} hint="awaiting human review" icon={<Users size={16} />} tone="var(--warn)" />
          <Kpi label="Resolved" value={a.resolved_incidents} hint={`avg ${fmt.ms(a.avg_pipeline_ms)} pipeline`} icon={<Gauge size={16} />} tone="var(--ok)" />
        </> : [0, 1, 2, 3].map((i) => <div key={i} className="card"><Skeleton h={14} w="50%" /><div className="mt-12"><Skeleton h={28} w="40%" /></div></div>)}
      </div>

      <div className="grid g-main">
        <Card title="Recent incidents" icon={<Siren size={15} />} actions={<Link className="btn sm" to="/incidents">View all <ArrowRight size={12} /></Link>} flush>
          {a?.recent_incidents?.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>ID</th><th>Incident</th><th>Severity</th><th>Status</th></tr></thead>
              <tbody>{a.recent_incidents.map((r: any) => (
                <tr key={r.id} className="click" onClick={() => nav(`/incidents/${r.id}`)}>
                  <td className="id">{r.incident_id}</td><td className="bold">{r.title}</td><td><SevBadge level={r.severity} /></td><td><StatusBadge status={r.status} /></td>
                </tr>))}</tbody>
            </table></div>
          ) : <Empty title="No incidents yet" />}
        </Card>

        <Card title="Severity distribution" icon={<ShieldAlert size={15} />}>
          {sevData.length ? (
            <div className="row" style={{ gap: 12 }}>
              <div style={{ width: 160, height: 160, flexShrink: 0 }}>
                <ResponsiveContainer width="100%" height="100%"><PieChart>
                  <Pie data={sevData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={42} outerRadius={68} paddingAngle={2} stroke="none" isAnimationActive={false}>
                    {sevData.map((d: any) => <Cell key={d.name} fill={SEV_FILL[d.name]} />)}
                  </Pie><Tooltip {...tooltip} />
                </PieChart></ResponsiveContainer>
              </div>
              <div className="stack grow" style={{ gap: 8 }}>
                {a.severity_distribution.map((d: any) => (
                  <div key={d.name} className="row between small"><SevBadge level={d.name} /><b>{d.value}</b></div>
                ))}
              </div>
            </div>
          ) : <Skeleton h={160} />}
        </Card>
      </div>

      <div className="grid g-2">
        <Card title="Categories" icon={<Activity size={15} />}>
          <div style={{ height: 180 }}>
            <ResponsiveContainer><BarChart data={a?.category_distribution ?? []} layout="vertical" margin={{ left: 10, right: 10 }}>
              <XAxis type="number" hide allowDecimals={false} />
              <YAxis type="category" dataKey="name" width={130} tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={fmt.label} axisLine={false} tickLine={false} />
              <Tooltip {...tooltip} cursor={{ fill: 'rgba(37,99,235,.04)' }} />
              <Bar isAnimationActive={false} dataKey="value" fill="var(--accent)" radius={[0, 4, 4, 0]} barSize={12} />
            </BarChart></ResponsiveContainer>
          </div>
        </Card>
        <Card title="Team workload" icon={<Users size={15} />} sub="Open incidents by team">
          <div className="stack" style={{ gap: 10 }}>
            {(a?.team_workload ?? []).map((t: any) => {
              const max = Math.max(1, ...a.team_workload.map((x: any) => x.value))
              return (
                <div key={t.team}>
                  <div className="row between small"><span>{t.team}</span><b>{t.value}</b></div>
                  <div className="meter mt-4"><span style={{ width: `${(t.value / max) * 100}%` }} /></div>
                </div>
              )
            })}
          </div>
        </Card>
      </div>

      {a && <div className="row small muted"><Timer size={12} /> {a.pipeline_runs} pipeline runs · avg {fmt.ms(a.avg_pipeline_ms)} · {fmt.usd(a.total_cost_usd)} total estimated LLM cost</div>}
    </div>
  )
}
