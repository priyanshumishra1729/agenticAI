import { useMemo, useState } from 'react'
import { fmt, type Span } from '../api'
import { Badge, JsonView } from './ui'

const KINDS = ['workflow', 'agent', 'llm', 'tool', 'a2a', 'guardrail', 'callback']

export function TraceWaterfall({ spans, showCallbacks = false }: { spans: Span[]; showCallbacks?: boolean }) {
  const [sel, setSel] = useState<Span | null>(null)
  const [cb, setCb] = useState(showCallbacks)

  const rows = useMemo(() => {
    const visible = spans.filter((s) => cb || s.kind !== 'callback')
    const ids = new Set(visible.map((s) => s.span_id))
    const kids = new Map<string | null, Span[]>()
    for (const s of visible) {
      let p = s.parent_span_id
      // re-attach to nearest visible ancestor
      while (p && !ids.has(p)) p = spans.find((x) => x.span_id === p)?.parent_span_id ?? null
      const arr = kids.get(p) ?? []
      arr.push(s)
      kids.set(p, arr)
    }
    const out: { s: Span; depth: number }[] = []
    const walk = (p: string | null, d: number) => {
      for (const s of (kids.get(p) ?? []).sort((a, b) => a.start_ms - b.start_ms)) { out.push({ s, depth: d }); walk(s.span_id, d + 1) }
    }
    walk(null, 0)
    return out
  }, [spans, cb])

  const total = Math.max(1, ...spans.map((s) => s.start_ms + s.duration_ms))
  const current = sel ?? rows[0]?.s

  return (
    <div className="grid g-side">
      <div className="wf" style={{ minWidth: 0 }}>
        <div className="row wrap between" style={{ marginBottom: 10 }}>
          <div className="row wrap" style={{ gap: 12 }}>
            {KINDS.map((k) => <span key={k} className="row tiny muted" style={{ gap: 5 }}><span className={`kdot k-${k}`} />{k}</span>)}
          </div>
          <label className="row tiny muted" style={{ cursor: 'pointer' }}>
            <input type="checkbox" checked={cb} onChange={(e) => setCb(e.target.checked)} /> show callback events
          </label>
        </div>
        <div style={{ maxHeight: 560, overflow: 'auto' }}>
          {rows.map(({ s, depth }) => (
            <div key={s.span_id} className={`wf-row ${current?.span_id === s.span_id ? 'sel' : ''}`} onClick={() => setSel(s)}>
              <div className="wf-name" style={{ paddingLeft: depth * 14 }} title={s.name}>
                <span className={`kdot k-${s.kind}`} />
                <span className={s.status === 'ok' ? '' : 'bold'} style={{ color: s.status === 'ok' ? undefined : 'var(--bad)' }}>{s.name}</span>
              </div>
              <div className="wf-track">
                <div className={`wf-bar k-${s.kind}`} style={{ left: `${(s.start_ms / total) * 100}%`, width: `${Math.max(0.4, (s.duration_ms / total) * 100)}%` }} />
              </div>
              <div className="right mono faint">{fmt.ms(s.duration_ms)}</div>
            </div>
          ))}
        </div>
      </div>
      {current && (
        <div className="card fade-in" style={{ padding: 14, alignSelf: 'start', position: 'sticky', top: 16 }}>
          <div className="row between"><b className="ellipsis">{current.name}</b><Badge tone={current.status === 'ok' ? 'b-ok' : 'b-bad'}>{current.status}</Badge></div>
          <dl className="kv mt-12">
            <dt>Kind</dt><dd>{current.kind}</dd>
            <dt>Framework</dt><dd>{current.framework || '—'}</dd>
            <dt>Start / duration</dt><dd className="mono">+{current.start_ms}ms · {fmt.ms(current.duration_ms)}</dd>
            {(current.tokens_in > 0 || current.tokens_out > 0) && <><dt>Tokens</dt><dd className="mono">{current.tokens_in} in · {current.tokens_out} out</dd></>}
            <dt>Span id</dt><dd className="mono">{current.span_id}</dd>
          </dl>
          {current.error && <div className="alert bad mt-12 small">{current.error}</div>}
          {current.input != null && <><div className="tiny faint mt-12">INPUT</div><JsonView data={current.input} maxHeight={170} /></>}
          {current.output != null && <><div className="tiny faint mt-12">OUTPUT</div><JsonView data={current.output} maxHeight={220} /></>}
          {current.attributes && Object.keys(current.attributes).length > 0 && <><div className="tiny faint mt-12">ATTRIBUTES</div><JsonView data={current.attributes} maxHeight={120} /></>}
        </div>
      )}
    </div>
  )
}
