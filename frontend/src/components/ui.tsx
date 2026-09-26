/** Reusable presentational primitives. No data fetching, no global state. */

import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { copyText, reviewTone, riskTone, shortHash, statusTone, type Tone } from '../lib/format'

export function Panel({
  title,
  subtitle,
  actions,
  children,
  tight,
  scroll,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  tight?: boolean
  scroll?: boolean
}) {
  return (
    <section className="panel">
      {(title || actions) && (
        <header className="panel-head">
          <div className="panel-title">
            <span>{title}</span>
            {subtitle && <small>{subtitle}</small>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      <div className={`panel-body${tight ? ' tight' : ''}${scroll ? ' scroll' : ''}`}>{children}</div>
    </section>
  )
}

export function Badge({ tone = 'muted', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function ReviewBadge({ state }: { state: string }) {
  return <Badge tone={reviewTone(state)}>{state.replace(/_/g, ' ')}</Badge>
}

export function RiskBadge({ level }: { level: string }) {
  return <Badge tone={riskTone(level)}>{level}</Badge>
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTone(status)}>{status.replace(/_/g, ' ')}</Badge>
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: ReactNode
  children: ReactNode
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

export function Meter({ value, tone }: { value: number; tone?: Tone }) {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0))
  return (
    <div className="meter" role="progressbar" aria-valuenow={Math.round(clamped * 100)}>
      <div className={`meter-fill${tone && tone !== 'ok' ? ` ${tone}` : ''}`} style={{ width: `${clamped * 100}%` }} />
    </div>
  )
}

export function CopyButton({ value, label = 'copy' }: { value: string; label?: string }) {
  const [done, setDone] = useState(false)
  useEffect(() => {
    if (!done) return
    const timer = window.setTimeout(() => setDone(false), 1400)
    return () => window.clearTimeout(timer)
  }, [done])

  return (
    <button
      type="button"
      className="copy"
      onClick={async () => {
        if (await copyText(value)) setDone(true)
      }}
    >
      {done ? 'copied' : label}
    </button>
  )
}

export function Hash({ value, size = 10 }: { value: string | null | undefined; size?: number }) {
  if (!value) return <span className="muted">—</span>
  return (
    <span className="hash">
      <code title={value}>{shortHash(value, size)}</code>
      <CopyButton value={value} />
    </span>
  )
}

export function KeyValue({ rows }: { rows: Record<string, ReactNode> }) {
  return (
    <div className="kv">
      {Object.entries(rows).map(([key, value]) => (
        <div className="kv-row" key={key}>
          <span className="kv-key">{key}</span>
          <span className="kv-val">{value ?? '—'}</span>
        </div>
      ))}
    </div>
  )
}

export function Callout({
  tone = 'info',
  icon,
  children,
}: {
  tone?: 'ok' | 'warn' | 'danger' | 'info'
  icon?: string
  children: ReactNode
}) {
  return (
    <div className={`callout callout-${tone}`}>
      <span className="callout-icon" aria-hidden="true">
        {icon ?? (tone === 'ok' ? 'OK' : tone === 'warn' ? '!' : tone === 'danger' ? '!!' : 'i')}
      </span>
      <p>{children}</p>
    </div>
  )
}

export function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: Tone
}) {
  const colour =
    tone === 'ok'
      ? 'var(--ok)'
      : tone === 'warn'
        ? 'var(--warn)'
        : tone === 'danger'
          ? 'var(--danger)'
          : tone === 'accent'
            ? 'var(--accent)'
            : 'var(--violet)'
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value" style={{ color: colour }}>
        {value}
      </div>
      {hint && <div className="metric-hint">{hint}</div>}
    </div>
  )
}

export function Spinner({ large }: { large?: boolean }) {
  return <span className={`spinner${large ? ' lg' : ''}`} role="status" aria-label="Loading" />
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="loading-row">
      <Spinner />
      {label}
    </div>
  )
}

export function Empty({
  title,
  children,
  action,
}: {
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function Tabs<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T
  options: Array<{ id: T; label: string; count?: ReactNode; disabled?: boolean }>
  onChange: (next: T) => void
}) {
  return (
    <div className="tabs" role="tablist">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          role="tab"
          aria-selected={option.id === value}
          className={`tab${option.id === value ? ' active' : ''}`}
          disabled={option.disabled}
          onClick={() => onChange(option.id)}
        >
          {option.label}
          {option.count !== undefined && <span className="tab-count">{option.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function Json({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>
}
