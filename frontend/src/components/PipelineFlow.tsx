import { ArrowRight, Calculator, CircleCheck, CloudSun, FileText, Package, ScanSearch, ShieldCheck, Sparkles, Truck, Waypoints, Circle } from 'lucide-react'
import type { ReactNode } from 'react'
import { Spinner } from './ui'

export const STAGES = ['intake', 'gather', 'a2a', 'crew', 'review', 'report'] as const
type Stage = typeof STAGES[number]

function Node({ title, sub, icon, fw, state }: { title: string; sub: string; icon: ReactNode; fw: 'adk' | 'crew' | 'mcp'; state: 'idle' | 'active' | 'done' }) {
  return (
    <div className={`node ${state}`}>
      <span className={`n-fw fw-${fw}`}>{fw === 'adk' ? 'ADK' : fw === 'crew' ? 'CrewAI' : 'MCP'}</span>
      <div className="n-title">
        {state === 'active' ? <Spinner size={13} /> : state === 'done' ? <CircleCheck size={13} className="state" /> : <Circle size={13} className="faint" />}
        {icon}{title}
      </div>
      <div className="n-sub">{sub}</div>
    </div>
  )
}

/** progress: index into STAGES currently running (STAGES.length = all done, -1 = idle). */
export function PipelineFlow({ progress }: { progress: number }) {
  const st = (s: Stage): 'idle' | 'active' | 'done' => {
    const i = STAGES.indexOf(s)
    return progress < 0 ? 'idle' : i < progress ? 'done' : i === progress ? 'active' : 'idle'
  }
  const arrow = (s: Stage) => <div className={`flow-arrow ${STAGES.indexOf(s) <= progress ? 'on' : ''}`}><ArrowRight size={16} /></div>
  return (
    <div className="flow">
      <div className="flow-col"><Node fw="adk" title="Intake" sub="document_parser (MCP)" icon={<FileText size={13} />} state={st('intake')} /></div>
      {arrow('gather')}
      <div className="flow-group"><span className="g-label">ParallelAgent</span>
        <Node fw="adk" title="Supplier" sub="supplier_shipment_lookup" icon={<Truck size={13} />} state={st('gather')} />
        <Node fw="adk" title="Inventory" sub="inventory_lookup" icon={<Package size={13} />} state={st('gather')} />
        <Node fw="adk" title="Weather" sub="Open-Meteo (external)" icon={<CloudSun size={13} />} state={st('gather')} />
      </div>
      {arrow('a2a')}
      <div className="flow-col"><Node fw="adk" title="Crew liaison" sub="A2A message/send" icon={<Waypoints size={13} />} state={st('a2a')} /></div>
      {arrow('crew')}
      <div className="flow-group"><span className="g-label">CrewAI · sequential</span>
        <Node fw="crew" title="Verification" sub="historical_incident_search" icon={<ScanSearch size={13} />} state={st('crew')} />
        <Node fw="crew" title="Severity & impact" sub="impact_calculator" icon={<Calculator size={13} />} state={st('crew')} />
        <Node fw="crew" title="Resolution planner" sub="routing + action plan" icon={<Sparkles size={13} />} state={st('crew')} />
      </div>
      {arrow('review')}
      <div className="flow-col"><Node fw="adk" title="Reviewer" sub="reflection / critic" icon={<ShieldCheck size={13} />} state={st('review')} /></div>
      {arrow('report')}
      <div className="flow-col"><Node fw="adk" title="Report" sub="Pydantic · JSON + Markdown" icon={<FileText size={13} />} state={st('report')} /></div>
    </div>
  )
}
