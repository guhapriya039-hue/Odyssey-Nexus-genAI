import { useMemo, useState } from 'react'
import type { TransformRequest, Transformation } from '../api/types'
import { Badge, Callout, Empty, Field, Panel, RiskBadge, StatusBadge } from '../components/ui'
import { duration, humanise, MEDIA_GLYPH, percent } from '../lib/format'
import { useWorkspace, workspace } from '../state/workspace'

const DEFAULTS = {
  audience: 'executive',
  tone: 'neutral',
  language: 'en',
  objective: 'inform',
  detail: 'balanced',
} satisfies Omit<TransformRequest, 'formats' | 'user_instruction' | 'include_pii' | 'auto_approve'>

export function TransformView({
  onDone,
  hasDocument,
  onOpenSources,
}: {
  onDone: () => void
  hasDocument: boolean
  onOpenSources: () => void
}) {
  const meta = useWorkspace((s) => s.meta)
  const document = useWorkspace((s) => s.document)

  const [formats, setFormats] = useState<string[]>(['executive_summary', 'linkedin'])
  const [audience, setAudience] = useState(DEFAULTS.audience)
  const [tone, setTone] = useState(DEFAULTS.tone)
  const [language, setLanguage] = useState(DEFAULTS.language)
  const [objective, setObjective] = useState(DEFAULTS.objective)
  const [detail, setDetail] = useState(DEFAULTS.detail)
  const [instruction, setInstruction] = useState('')
  const [includePii, setIncludePii] = useState(false)
  const [autoApprove, setAutoApprove] = useState(false)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<Transformation | null>(null)

  const available = meta?.formats ?? []
  const toggled = useMemo(
    () => (id: string) => {
      setFormats((current) =>
        current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
      )
    },
    [],
  )

  const allSelected = available.length > 0 && formats.length === available.length
  const selectAll = () => setFormats(allSelected ? [] : available.map((item) => item.id))

  const submit = async () => {
    if (!document) return
    setRunning(true)
    try {
      const transformation = await workspace.run(document.public_id, {
        formats,
        audience,
        tone,
        language,
        objective,
        detail,
        user_instruction: instruction.trim(),
        include_pii: includePii,
        auto_approve: autoApprove,
      })
      setResult(transformation)
      if (transformation.status === 'completed' || transformation.status === 'completed_with_warnings') {
        onDone()
      }
    } catch {
      setResult(null)
    } finally {
      setRunning(false)
    }
  }

  if (!hasDocument || !document) {
    return (
      <div className="stack">
        <div className="view-head">
          <div>
            <h1>Configure transformation</h1>
            <p>Choose the audience, register and output formats for the selected source.</p>
          </div>
        </div>
        <Panel>
          <Empty
            title="No source selected"
            action={
              <button type="button" className="btn btn-primary" onClick={onOpenSources}>
                Go to source intake
              </button>
            }
          >
            The configuration below applies to one verified source. Ingest a document first and the
            control panel will unlock.
          </Empty>
        </Panel>
      </div>
    )
  }

  return (
    <div className="stack">
      <div className="view-head">
        <div>
          <h1>Configure transformation</h1>
          <p>
            Every format below is generated from the same knowledge layer, so figures and dates stay
            consistent across the whole set.
          </p>
        </div>
        <div className="view-actions">
          <span className="label-inline">
            {formats.length} of {available.length} formats selected
          </span>
          <button
            type="button"
            className="btn btn-primary"
            disabled={running || formats.length === 0}
            onClick={() => void submit()}
          >
            {running ? 'Running pipeline…' : `Generate ${formats.length} artefact${formats.length === 1 ? '' : 's'}`}
          </button>
        </div>
      </div>

      <div className="grid grid-sidebar">
        <div className="stack">
          <Panel
            title="Output formats"
            subtitle="the eight communication categories from the problem statement"
            actions={
              <button type="button" className="btn btn-sm btn-ghost" onClick={selectAll}>
                {allSelected ? 'Clear all' : 'Select all'}
              </button>
            }
          >
            <div className="format-grid">
              {available.map((format) => {
                const selected = formats.includes(format.id)
                return (
                  <button
                    key={format.id}
                    type="button"
                    className={`format-card${selected ? ' selected' : ''}`}
                    onClick={() => toggled(format.id)}
                    aria-pressed={selected}
                  >
                    <div className="format-card-top">
                      <span className="format-card-name">{format.label}</span>
                      {selected ? <span className="tick">✓</span> : null}
                    </div>
                    <span className="format-card-media">
                      {MEDIA_GLYPH[format.media] ?? format.media}
                    </span>
                  </button>
                )
              })}
            </div>
          </Panel>

          <Panel title="Source under transformation">
            <div className="row spread" style={{ alignItems: 'flex-start' }}>
              <div className="grow">
                <h3>{document.title}</h3>
                <p className="dim" style={{ marginTop: 4, fontSize: 12.5 }}>
                  {document.word_count.toLocaleString()} words · {document.chunk_count} chunks ·{' '}
                  {document.source_kind}
                </p>
              </div>
              <div className="row row-tight">
                <RiskBadge level={document.risk_level} />
                <StatusBadge status={document.status} />
              </div>
            </div>
            {document.security && document.security.injection_score > 0.4 && (
              <div style={{ marginTop: 12 }}>
                <Callout tone="warn">
                  This source scored {percent(document.security.injection_score)} for prompt
                  injection. Hostile lines were suppressed, so the run will report warnings — review
                  the artefacts before approving.
                </Callout>
              </div>
            )}
          </Panel>

          {result && (
            <Panel title="Last run" subtitle={result.transformation_id}>
              <div className="stack">
                <div className="row">
                  <StatusBadge status={result.status} />
                  <Badge tone={result.generation_mode === 'llm' ? 'accent' : 'muted'}>
                    {result.generation_mode} mode
                  </Badge>
                  <Badge tone="muted">{result.outputs.length} artefacts</Badge>
                  <Badge tone="muted">{duration(result.duration_ms)}</Badge>
                </div>
                {result.error && <Callout tone="danger">{result.error}</Callout>}
                {result.warnings.length > 0 && (
                  <div className="stack" style={{ gap: 6 }}>
                    {result.warnings.map((warning) => (
                      <Callout tone="warn" key={warning}>
                        {warning}
                      </Callout>
                    ))}
                  </div>
                )}
                {result.llm_attempts.length > 0 && (
                  <details>
                    <summary className="label-inline" style={{ cursor: 'pointer' }}>
                      {result.llm_attempts.length} LLM attempt(s)
                    </summary>
                    <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                      {result.llm_attempts.map((attempt, index) => (
                        <li key={index} className="dim" style={{ fontSize: 12 }}>
                          {humanise(String(attempt.model ?? 'unknown'))}:{' '}
                          {String(attempt.error ?? 'ok')}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
                <button type="button" className="btn btn-primary" onClick={onDone}>
                  Open in output studio →
                </button>
              </div>
            </Panel>
          )}
        </div>

        <div className="stack">
          <Panel title="Communication controls">
            <div className="stack">
              <Field label="Audience" hint={AUDIENCE_NOTES[audience] ?? 'Tailors vocabulary and depth.'}>
                <select className="select" value={audience} onChange={(e) => setAudience(e.target.value)}>
                  {(meta?.audiences ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Register / tone">
                <select className="select" value={tone} onChange={(e) => setTone(e.target.value)}>
                  {(meta?.tones ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Primary objective">
                <select className="select" value={objective} onChange={(e) => setObjective(e.target.value)}>
                  {(meta?.objectives ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Detail level" hint="Controls how many sourced facts each artefact carries.">
                <div className="segmented" style={{ width: '100%' }}>
                  {(meta?.details ?? []).map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={detail === item.id ? 'active' : ''}
                      style={{ flex: 1 }}
                      onClick={() => setDetail(item.id)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </Field>

              <Field label="Output language">
                <select className="select" value={language} onChange={(e) => setLanguage(e.target.value)}>
                  {Object.entries(meta?.languages ?? { en: 'English' }).map(([code, label]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </Panel>

          <Panel title="Operator guidance" subtitle="optional, appended to the grounded prompt">
            <div className="stack">
              <textarea
                className="textarea"
                value={instruction}
                maxLength={2000}
                placeholder="e.g. Lead with the regulatory deadline and keep the LinkedIn version under 900 characters."
                onChange={(e) => setInstruction(e.target.value)}
              />
              <span className="field-hint">
                Guidance can steer emphasis and length. It cannot introduce facts: the factuality
                gate rejects any number that is not in the source.
              </span>
            </div>
          </Panel>

          <Panel title="Governance">
            <div className="stack">
              <label className="check">
                <input
                  type="checkbox"
                  checked={autoApprove}
                  onChange={(e) => setAutoApprove(e.target.checked)}
                />
                <span>
                  <strong>Auto-approve outputs</strong>
                  Skips the human review gate. Requires the approver or admin role; the audit trail
                  still records the automatic sign-off.
                </span>
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={includePii}
                  onChange={(e) => setIncludePii(e.target.checked)}
                />
                <span>
                  <strong>Allow personal data in output</strong>
                  Off by default. Personal data is redacted at ingestion; enabling this re-admits
                  it for audiences such as internal incident response.
                </span>
              </label>
            </div>
          </Panel>

          <Panel title="Pipeline" subtitle="what will run">
            <div className="stack" style={{ gap: 8 }}>
              {[
                'Extract and normalise text',
                'Neutralise injected instructions',
                'Redact personal data',
                'Chunk by document structure',
                'Build the shared knowledge layer',
                'Retrieve evidence per artefact',
                'Generate with grounded prompts',
                'Factuality and numeric checks',
                'Hash artefacts and chain the audit log',
              ].map((step, index) => (
                <div className="row" key={step} style={{ gap: 9 }}>
                  <span className="nav-step">{index + 1}</span>
                  <span className="dim" style={{ fontSize: 12.5 }}>
                    {step}
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}

const AUDIENCE_NOTES: Record<string, string> = {
  executive: 'Decision-makers with little time. Lead with impact and decisions required.',
  technical: 'Keep precise terminology, indicators and enough evidence to reproduce findings.',
  operations: 'Emphasise action sequence, ownership, dependencies and rollback.',
  security_analyst: 'Preserve IOCs, CVEs, confidence levels and attribution caveats.',
  media_public: 'Plain language, no jargon, no sensitive identifiers or personal data.',
  partner: 'Share only what is safe to disclose; avoid internal-only detail.',
}
