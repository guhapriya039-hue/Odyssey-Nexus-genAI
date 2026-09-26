/** Small presentation helpers shared by every view. */

export function shortHash(hash: string | null | undefined, size = 10): string {
  if (!hash) return '—'
  return hash.length <= size * 2 + 1 ? hash : `${hash.slice(0, size)}…${hash.slice(-size)}`
}

export function bytes(value: number): string {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let index = 0
  let size = value
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return '—'
  const then = new Date(value.endsWith('Z') || value.includes('+') ? value : `${value}Z`).getTime()
  if (Number.isNaN(then)) return '—'
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(then).toLocaleDateString()
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value.endsWith('Z') || value.includes('+') ? value : `${value}Z`)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function duration(ms: number): string {
  if (!ms && ms !== 0) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

export function score(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(3)
}

export type Tone = 'ok' | 'warn' | 'danger' | 'info' | 'accent' | 'violet' | 'muted'

const RISK_TONES: Record<string, Tone> = {
  none: 'ok',
  low: 'info',
  medium: 'warn',
  high: 'danger',
  critical: 'danger',
}

const REVIEW_TONES: Record<string, Tone> = {
  draft: 'muted',
  pending_review: 'warn',
  approved: 'ok',
  rejected: 'danger',
}

const STATUS_TONES: Record<string, Tone> = {
  queued: 'muted',
  analysing: 'info',
  generating: 'accent',
  validating: 'violet',
  completed: 'ok',
  completed_with_warnings: 'warn',
  blocked: 'danger',
  failed: 'danger',
  indexed: 'ok',
  uploaded: 'info',
  extracting: 'info',
  rejected: 'danger',
}

export const riskTone = (level: string): Tone => RISK_TONES[level] ?? 'muted'
export const reviewTone = (state: string): Tone => REVIEW_TONES[state] ?? 'muted'
export const statusTone = (status: string): Tone => STATUS_TONES[status] ?? 'muted'

export const humanise = (value: string): string =>
  value.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

export const MEDIA_GLYPH: Record<string, string> = {
  document: 'DOC',
  social: 'SOC',
  visual: 'VIS',
  slides: 'SLD',
  video: 'VID',
}

export async function copyText(value: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value)
      return true
    }
  } catch {
    /* fall through to the legacy path */
  }
  try {
    const area = document.createElement('textarea')
    area.value = value
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(area)
    return ok
  } catch {
    return false
  }
}
