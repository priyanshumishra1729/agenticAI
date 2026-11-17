import { FlaskConical, GitBranch, LayoutDashboard, ListChecks, Menu, Network, ShieldCheck, Siren, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api'
import Architecture from './pages/Architecture'
import Dashboard from './pages/Dashboard'
import Evaluation from './pages/Evaluation'
import ExecutionLogs from './pages/ExecutionLogs'
import Guardrails from './pages/Guardrails'
import IncidentDetail from './pages/IncidentDetail'
import Incidents from './pages/Incidents'
import Workflow from './pages/Workflow'

function Sidebar({ open, onNav }: { open: boolean; onNav: () => void }) {
  const [sys, setSys] = useState<any>(null)
  useEffect(() => { api.system().then(setSys).catch(() => setSys(null)) }, [])
  const link = (to: string, icon: React.ReactNode, label: string) => (
    <NavLink to={to} end={to === '/'} onClick={onNav}>{icon}{label}</NavLink>
  )
  return (
    <aside className={`sidebar ${open ? 'open' : ''}`}>
      <div className="brand">
        <div className="brand-mark"><Zap size={18} strokeWidth={2.4} /></div>
        <div><h1>SignalChain</h1><small>Crisis Management</small></div>
      </div>
      <nav className="nav">
        {link('/', <LayoutDashboard size={16} />, 'Dashboard')}
        {link('/incidents', <Siren size={16} />, 'Incidents')}
        {link('/workflow', <GitBranch size={16} />, 'Agent Workflow')}
        {link('/architecture', <Network size={16} />, 'Architecture')}
        {link('/logs', <ListChecks size={16} />, 'Execution Logs')}
        {link('/guardrails', <ShieldCheck size={16} />, 'Guardrails')}
        {link('/evaluation', <FlaskConical size={16} />, 'Evaluation')}
      </nav>
      <div className="side-foot">
        <div className="row between"><span className={sys ? 'live' : 'muted small'}>{sys ? 'Online' : 'Connecting…'}</span></div>
        <div className="row"><span>LLM</span><b>{sys?.llm_mode?.split(':')[0] ?? '—'}</b></div>
        <div className="row"><span>Frameworks</span><b>ADK + CrewAI</b></div>
      </div>
    </aside>
  )
}

function Layout() {
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => { window.scrollTo(0, 0) }, [loc.pathname])
  return (
    <div className="shell">
      <Sidebar open={open} onNav={() => setOpen(false)} />
      <div style={{ minWidth: 0 }}>
        <div className="mobile-bar">
          <button className="btn ghost sm" onClick={() => setOpen(!open)} aria-label="Menu"><Menu size={16} /></button>
          <b>SignalChain</b>
        </div>
        <main className="main" onClick={() => open && setOpen(false)}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/incidents" element={<Incidents />} />
            <Route path="/incidents/:id" element={<IncidentDetail />} />
            <Route path="/workflow" element={<Workflow />} />
            <Route path="/architecture" element={<Architecture />} />
            <Route path="/logs" element={<ExecutionLogs />} />
            <Route path="/guardrails" element={<Guardrails />} />
            <Route path="/evaluation" element={<Evaluation />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return <BrowserRouter><Layout /></BrowserRouter>
}
