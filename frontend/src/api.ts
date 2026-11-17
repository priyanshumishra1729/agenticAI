/* Typed API client for the SignalChain backend. */

export type Severity = 'low' | 'medium' | 'high' | 'critical'

export interface Incident {
  id: number
  incident_id: string
  title: string
  description: string
  category: string
  location: string
  supplier: string | null
  shipment_id: string | null
  product_sku: string | null
  quantity_affected: number
  reported_time: string
  severity: Severity
  status: string
  verification_status: string
  approval_status: string
  escalation_count: number
  duplicate_of: string | null
  created_at: string
  assigned_team: { id: number; name: string } | null
}

export interface ActionStep { title: string; owner: string; due_hours: number }

export interface Report {
  report_id: string
  incident_id: string
  title: string
  generated_at: string
  llm_mode: string
  category: string
  location: string
  verification: {
    status: string; completeness_score: number; duplicate_score: number; duplicate_of: string | null
    missing_fields: string[]; data_conflicts: string[]; notes: string
  }
  severity: {
    level: Severity; score: number; drivers: string[]; confidence: number
    impact: { shortage_units: number; days_of_cover: number; revenue_at_risk_usd: number; expedite_cost_usd: number; sla_breach_risk: string }
  }
  plan: { owner_team: string; priority: string; deadline_hours: number; summary: string; actions: ActionStep[]; escalate: boolean; escalation_reason: string }
  review: { approved_by_reviewer: boolean; issues: string[]; adjustments: string[]; human_approval_required: boolean }
  context: Record<string, any>
  provenance: Record<string, any>
  metrics: { duration_ms: number; tokens_in: number; tokens_out: number; llm_calls: number; estimated_cost_usd: number }
}

export interface AdkEvent { author: string; t_ms: number; parts: string[]; state_delta: string[] }

export interface IncidentDetail {
  incident: Incident
  report: Report | null
  markdown: string | null
  trace_id: string | null
  monitoring: { adk_events: AdkEvent[]; crew_monitor: any[] } | null
  agent_outputs: Record<string, string> | null
  plan: { id: number; approved: boolean; rejected: boolean; items: ActionStep[] } | null
  events: { type: string; message: string; at: string }[]
  tool_calls: { tool: string; caller: string; status: string; duration_ms: number; arguments: any; result: any }[]
  guardrails: { check: string; stage: string; passed: boolean; details: string; at: string }[]
}

export interface Span {
  span_id: string; parent_span_id: string | null; name: string; kind: string; framework: string; status: string
  input: any; output: any; attributes: any; error: string; tokens_in: number; tokens_out: number; start_ms: number; duration_ms: number
}

export class ApiError extends Error {
  status: number
  details: string[]
  constructor(status: number, message: string, details: string[] = []) {
    super(message)
    this.status = status
    this.details = details
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { 'content-type': 'application/json' }, ...init })
  if (!res.ok) {
    let details: string[] = []
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      const d = body.detail
      if (typeof d === 'string') message = d
      else if (d?.errors) details = d.errors
      else if (Array.isArray(d)) details = d.map((e: any) => `${(e.loc || []).slice(1).join('.')}: ${e.msg}`)
      if (details.length) message = details.join(' · ')
    } catch { /* ignore */ }
    throw new ApiError(res.status, message, details)
  }
  const type = res.headers.get('content-type') || ''
  return (type.includes('json') ? res.json() : res.text()) as Promise<T>
}

const post = <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  system: () => request<any>('/api/system'),
  analytics: () => request<any>('/api/analytics/summary'),
  incidents: (params: Record<string, string> = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString()
    return request<Incident[]>(`/api/incidents${qs ? `?${qs}` : ''}`)
  },
  createIncident: (body: Record<string, unknown>) => post<Incident>('/api/incidents', body),
  detail: (id: number) => request<IncidentDetail>(`/api/incidents/${id}/detail`),
  runWorkflow: (id: number) => post<{ report: Report; markdown: string; trace_id: string; adk_events: AdkEvent[]; crew_monitor: any[] }>(`/api/incidents/${id}/workflow`),
  approve: (id: number, approved: boolean, notes = '') => post(`/api/incidents/${id}/approve`, { approved, notes }),
  evidence: (id: number, summary: string) => post(`/api/incidents/${id}/evidence`, { summary }),
  verify: (id: number) => post(`/api/incidents/${id}/verify-resolution`),
  close: (id: number) => post(`/api/incidents/${id}/close`),
  escalate: (id: number, reason: string) => post(`/api/incidents/${id}/escalate?reason=${encodeURIComponent(reason)}`),
  traces: () => request<{ traces: any[]; langfuse_enabled: boolean }>('/api/traces'),
  trace: (id: string) => request<{ trace_id: string; spans: Span[] }>(`/api/traces/${id}`),
  guardrailCheck: (text: string) => post<{ allowed: boolean; violations: string[]; redactions: Record<string, number>; redacted_text: string }>('/api/guardrails/check', { text }),
  guardrailEvents: () => request<{ total: number; blocked: number; events: any[] }>('/api/guardrails/events'),
  mcpTools: () => request<{ server: string; transport: string; tools: { name: string; description: string; input_schema: any }[] }>('/api/mcp/tools'),
  callTool: (name: string, args: Record<string, unknown>) => post<{ result: any }>(`/api/mcp/tools/${name}`, args),
  a2aTasks: () => request<{ tasks: any[] }>('/api/a2a/tasks'),
  agentCard: (agent: string) => request<any>(`/a2a/${agent}/.well-known/agent.json`),
  startEval: (limit?: number) => post<{ run_id: string }>(`/api/evaluation/run${limit ? `?limit=${limit}` : ''}`),
  evalRuns: () => request<{ runs: any[] }>('/api/evaluation/runs'),
}

export const fmt = {
  ago(iso: string) {
    const s = (Date.now() - new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z').getTime()) / 1000
    if (s < 60) return 'just now'
    if (s < 3600) return `${Math.floor(s / 60)}m ago`
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`
    return `${Math.floor(s / 86400)}d ago`
  },
  label(s: string) { return (s || '').replace(/_/g, ' ') },
  usd(n: number) { return n >= 1 ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : `$${n.toFixed(4)}` },
  ms(n: number) { return n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms` },
  num(n: number) { return n.toLocaleString() },
}
