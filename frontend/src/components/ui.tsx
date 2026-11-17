import { CircleCheck, Inbox, LoaderCircle, TriangleAlert, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { fmt, type Severity } from '../api'

export function Card({ title, icon, sub, actions, children, className = '', flush }: {
  title?: ReactNode; icon?: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; flush?: boolean
}) {
  return (
    <section className={`card ${flush ? 'flush' : ''} ${className}`}>
      {(title || actions) && (
        <div className="card-head" style={flush ? { padding: '12px 14px 0' } : undefined}>
          <div>
            {title && <h3>{icon}{title}</h3>}
            {sub && <div className="sub mt-4">{sub}</div>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

export function SevBadge({ level }: { level: Severity | string }) {
  return <span className={`badge sev-${level}`}><span className="dot" />{level}</span>
}

const STATUS_TONE: Record<string, string> = {
  open: 'b-accent', in_review: 'b-warn', assigned: 'b-teal', in_progress: 'b-teal', awaiting_verification: 'b-violet',
  escalated: 'b-bad', resolved: 'b-ok', closed: 'b-neutral', completed: 'b-ok', failed: 'b-bad', working: 'b-warn', running: 'b-warn',
}
export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${STATUS_TONE[status] ?? 'b-neutral'}`}>{fmt.label(status)}</span>
}

export function Badge({ tone = 'b-neutral', children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>
}

export function Kpi({ label, value, hint, icon, tone = 'var(--accent)' }: { label: string; value: ReactNode; hint?: ReactNode; icon: ReactNode; tone?: string }) {
  return (
    <div className="card kpi fade-in">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
      <div className="icon" style={{ background: `color-mix(in srgb, ${tone} 12%, transparent)`, color: tone }}>{icon}</div>
    </div>
  )
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <LoaderCircle size={size} className="spin" />
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon ?? <Inbox size={24} />}
      <div className="bold">{title}</div>
      {children && <div className="small">{children}</div>}
    </div>
  )
}

export function Skeleton({ h = 18, w = '100%' }: { h?: number; w?: number | string }) {
  return <div className="skeleton" style={{ height: h, width: w }} />
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" className={`tab ${t.id === value ? 'active' : ''}`} onClick={() => onChange(t.id)}>{t.label}</button>
      ))}
    </div>
  )
}

export function Modal({ title, onClose, children, footer }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true">
        <div className="modal-head"><h3 style={{ fontSize: 15 }}>{title}</h3><button className="btn ghost sm" onClick={onClose} aria-label="Close"><X size={15} /></button></div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

export function Toast({ kind, message, onDone }: { kind: 'ok' | 'bad'; message: string; onDone: () => void }) {
  useEffect(() => { const t = setTimeout(onDone, 4000); return () => clearTimeout(t) }, [onDone])
  return (
    <div className="toast">
      {kind === 'ok' ? <CircleCheck size={16} color="var(--ok)" /> : <TriangleAlert size={16} color="var(--bad)" />}
      <span className="small">{message}</span>
    </div>
  )
}

export function useToast() {
  const [toast, setToast] = useState<{ kind: 'ok' | 'bad'; message: string } | null>(null)
  const node = toast ? <Toast {...toast} onDone={() => setToast(null)} /> : null
  return { node, ok: (m: string) => setToast({ kind: 'ok', message: m }), bad: (m: string) => setToast({ kind: 'bad', message: m }) }
}

function highlight(json: string) {
  const esc = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return esc.replace(/("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g, (m) => {
    let cls = 'n'
    if (m.startsWith('"')) cls = m.endsWith(':') ? 'k' : 's'
    else if (/true|false|null/.test(m)) cls = 'b'
    return `<span class="${cls}">${m}</span>`
  })
}
export function JsonView({ data, maxHeight }: { data: unknown; maxHeight?: number }) {
  return <pre className="json" style={maxHeight ? { maxHeight } : undefined} dangerouslySetInnerHTML={{ __html: highlight(JSON.stringify(data, null, 2) ?? 'null') }} />
}

function inline(s: string): ReactNode[] {
  const parts = s.split(/(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) return <strong key={i}>{p.slice(2, -2)}</strong>
    if (p.startsWith('`') && p.endsWith('`')) return <code key={i}>{p.slice(1, -1)}</code>
    if (p.startsWith('_') && p.endsWith('_') && p.length > 2) return <em key={i}>{p.slice(1, -1)}</em>
    return p
  })
}
export function Markdown({ text }: { text: string }) {
  const lines = text.split('\n')
  const out: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const l = lines[i]
    if (l.startsWith('# ')) out.push(<h1 key={i}>{inline(l.slice(2))}</h1>)
    else if (l.startsWith('## ')) out.push(<h2 key={i}>{inline(l.slice(3))}</h2>)
    else if (l.startsWith('|')) {
      const rows: string[][] = []
      while (i < lines.length && lines[i].startsWith('|')) {
        if (!/^\|[-| ]+\|$/.test(lines[i])) rows.push(lines[i].slice(1, -1).split('|').map((c) => c.trim()))
        i++
      }
      out.push(
        <div className="table-wrap" key={`t${i}`}><table><thead><tr>{rows[0].map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead>
          <tbody>{rows.slice(1).map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>)}</tbody></table></div>)
      continue
    } else if (l.startsWith('- ')) {
      const items: string[] = []
      while (i < lines.length && lines[i].startsWith('- ')) { items.push(lines[i].slice(2)); i++ }
      out.push(<ul key={`u${i}`}>{items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ul>)
      continue
    } else if (l.trim()) out.push(<p key={i}>{inline(l)}</p>)
    i++
  }
  return <div className="md">{out}</div>
}

const SEV_COLOR: Record<string, string> = { low: '#16a34a', medium: '#ca8a04', high: '#ea580c', critical: '#dc2626' }
export function SeverityGauge({ score, level }: { score: number; level: string }) {
  const r = 62, c = Math.PI * r
  const dash = (Math.max(0, Math.min(100, score)) / 100) * c
  return (
    <div className="gauge-wrap">
      <svg width="170" height="100" viewBox="0 0 170 100" aria-label={`Severity score ${score}`}>
        <defs>
          <linearGradient id="gg" x1="0" x2="1"><stop offset="0" stopColor="#16a34a" /><stop offset=".45" stopColor="#ca8a04" /><stop offset=".7" stopColor="#ea580c" /><stop offset="1" stopColor="#dc2626" /></linearGradient>
        </defs>
        <path d="M 23 88 A 62 62 0 0 1 147 88" fill="none" stroke="#e2e8f0" strokeWidth="12" strokeLinecap="round" />
        <path d="M 23 88 A 62 62 0 0 1 147 88" fill="none" stroke="url(#gg)" strokeWidth="12" strokeLinecap="round" strokeDasharray={`${dash} ${c}`} style={{ transition: 'stroke-dasharray .6s ease' }} />
      </svg>
      <div className="gauge-label" style={{ top: 38 }}>
        <b style={{ color: SEV_COLOR[level] }}>{score}</b>
        <span className="tiny muted">/ 100</span>
      </div>
    </div>
  )
}
export { SEV_COLOR }
