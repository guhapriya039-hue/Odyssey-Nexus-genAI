/**
 * Single fetch wrapper for the ODYSSEY API.
 *
 * Identity travels in two headers (see `backend/app/rbac.py`); the client
 * holds them in module state so every view shares one identity without a
 * React context provider.
 */

import type {
  AuditEvent,
  ChainVerification,
  Comparison,
  DocumentDetail,
  DocumentSummary,
  Health,
  Knowledge,
  Meta,
  Output,
  Provenance,
  ReviewState,
  SecurityReport,
  Stats,
  SystemConfig,
  TransformRequest,
  Transformation,
  TransformationSummary,
} from './types'

export const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type Identity = { user: string; role: string }

let identity: Identity = { user: 'analyst@odyssey.team', role: 'analyst' }

export function setIdentity(next: Identity): void {
  identity = next
}

export function getIdentity(): Identity {
  return identity
}

function detailFromPayload(payload: unknown, status: number): string {
  if (typeof payload === 'string' && payload.trim()) return payload
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === 'object' && 'msg' in item) {
            return String((item as { msg: unknown }).msg)
          }
          return JSON.stringify(item)
        })
        .join('; ')
    }
  }
  return `Request failed (${status})`
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        'X-Odyssey-User': identity.user,
        'X-Odyssey-Role': identity.role,
        ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...init.headers,
      },
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the API. Is the backend running on port 8000?')
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, detailFromPayload(payload, response.status))
  }
  return payload as T
}

const json = (body: unknown): string => JSON.stringify(body)

export const api = {
  // ---- system ---------------------------------------------------------
  health: () => request<Health>('/health'),
  meta: () => request<Meta>('/meta'),
  config: () => request<SystemConfig>('/config'),
  stats: () => request<Stats>('/stats'),
  scan: (text: string) =>
    request<{ report: SecurityReport }>('/security/scan', {
      method: 'POST',
      body: json({ text }),
    }),
  verifyChain: () => request<ChainVerification>('/audit/verify'),

  // ---- documents ------------------------------------------------------
  documents: () => request<DocumentSummary[]>('/documents'),
  document: (publicId: string) => request<DocumentDetail>(`/documents/${publicId}`),
  knowledge: (publicId: string) => request<Knowledge>(`/documents/${publicId}/knowledge`),
  deleteDocument: (publicId: string) =>
    request<void>(`/documents/${publicId}`, { method: 'DELETE' }),

  uploadDocument: (file: File, title: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('title', title)
    return request<DocumentDetail>('/documents/upload', { method: 'POST', body: form })
  },

  ingestText: (title: string, text: string) =>
    request<DocumentDetail>('/documents/text', {
      method: 'POST',
      body: json({ title, text }),
    }),

  ingestUrl: (url: string, title: string) =>
    request<DocumentDetail>('/documents/url', {
      method: 'POST',
      body: json({ url, title }),
    }),

  // ---- transformations ------------------------------------------------
  transformations: (documentId?: string) =>
    request<TransformationSummary[]>(
      `/transformations${documentId ? `?document_id=${encodeURIComponent(documentId)}` : ''}`,
    ),
  transform: (documentPublicId: string, payload: TransformRequest) =>
    request<Transformation>(`/transformations/document/${documentPublicId}`, {
      method: 'POST',
      body: json(payload),
    }),
  transformation: (id: string) => request<Transformation>(`/transformations/${id}`),
  provenance: (id: string) => request<Provenance>(`/transformations/${id}/provenance`),
  compare: (id: string) => request<Comparison>(`/transformations/${id}/compare`),

  // ---- outputs --------------------------------------------------------
  output: (id: number) => request<Output>(`/outputs/${id}`),
  editOutput: (id: number, body: string, note: string) =>
    request<Output>(`/outputs/${id}`, {
      method: 'PUT',
      body: json({ body, note }),
    }),
  regenerateOutput: (id: number) =>
    request<Output>(`/outputs/${id}/regenerate`, { method: 'POST' }),
  reviewOutput: (id: number, state: ReviewState, note: string) =>
    request<Output>(`/outputs/${id}/review`, {
      method: 'POST',
      body: json({ state, note }),
    }),
  verifyOutput: (id: number, sourceText: string) =>
    request<Record<string, unknown>>(`/outputs/${id}/verify`, {
      method: 'POST',
      body: json({ source_text: sourceText }),
    }),

  exportUrl: (id: number) => `${API_BASE}/outputs/${id}/export`,

  // ---- audit ----------------------------------------------------------
  auditEvents: (params: { limit?: number; transformationId?: string; documentId?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.limit) query.set('limit', String(params.limit))
    if (params.transformationId) query.set('transformation_id', params.transformationId)
    if (params.documentId) query.set('document_id', params.documentId)
    const suffix = query.toString() ? `?${query}` : ''
    return request<AuditEvent[]>(`/audit${suffix}`)
  },
  auditChain: () => request<ChainVerification>('/audit/chain'),
}
