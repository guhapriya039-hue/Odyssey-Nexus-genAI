import { useMemo, useState } from 'react'
import { api } from '../api/client'
import type { Output } from '../api/types'
import {
  Badge,
  Callout,
  Empty,
  Hash,
  Json,
  KeyValue,
  Meter,
  Panel,
  ReviewBadge,
  Tabs,
} from '../components/ui'
import {
  dateTime,
  duration,
  humanise,
  percent,
  reviewTone,
  riskTone,
  score,
  statusTone,
} from '../lib/format'
import { toast } from '../state/toast'
import { useWorkspace, workspace } from '../state/workspace'

type StudioTab = 'preview' | 'evidence' | 'assurance' | 'activity'

export function StudioView({
  onOpenAudit,
  onConfigure,
}: {
  onOpenAudit: () => void
  onConfigure: () => void
}) {
  const transformation = useWorkspace((s) => s.transformation)
  const runs = useWorkspace((s) => s.runs)
  const document = useWorkspace((s) => s.document)

  const [format, setFormat] = useState<string | null>(null)

  const outputs = useMemo(
    () => transformation?.outputs ?? [],
    [transformation?.outputs],
  )
  const active = useMemo(
    () => outputs.find((output) => output.format === format) ?? outputs[0] ?? null,
    [outputs, format],
  )

  if (!transformation) {
    return (
      <div className="stack">
        <div className="view-head">
          <div>
            <h1>Output studio</h1>
            <p>Review, edit, approve and export grounded artefacts.</p>
          </div>
        </div>

        {runs.length === 0 ? (
          <Panel>
            <Empty
              title="No transformation to review"
              action={
                <button type="button" className="btn btn-primary" onClick={onConfigure}>
                  Configure a run
                </button>
              }
            >
              Ingest a source, choose the formats you need, then run the pipeline. Generated
              artefacts appear here for human review.
            </Empty>
          </Panel>
        ) : (
          <Panel title="Open a run" subtitle={`${runs.length} available`} tight>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Source</th>
                    <th>Status</th>
                    <th className="num">Artefacts</th>
                    <th className="num">Grounding</th>
                    <th>When</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.transformation_id}>
                      <td className="mono">{run.transformation_id}</td>
                      <td>{run.document_title ?? run.document_id}</td>
                      <td>
                        <Badge tone={statusTone(run.status)}>{run.status.replace(/_/g, ' ')}</Badge>
                      </td>
                      <td className="num">{run.output_count}</td>
                      <td className="num tnum">{percent(run.avg_grounding, 0)}</td>
                      <td className="nowrap muted">{dateTime(run.created_at)}</td>
                      <td className="end">
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => void workspace.openTransformation(run.transformation_id)}
                        >
                          Open
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        )}
      </div>
    )
  }

  return (
    <div className="stack">
      <div className="view-head">
        <div>
          <h1>Output studio</h1>
          <p>
            Artefacts are grounded in retrieved source chunks, checked for numeric hallucination and
            held at <em>pending review</em> until a human signs off.
          </p>
        </div>
        <div className="view-actions">
          <Badge tone="muted">run {transformation.transformation_id}</Badge>
          <Badge tone={statusTone(transformation.status)}>
            {transformation.status.replace(/_/g, ' ')}
          </Badge>
          <Badge tone={transformation.generation_mode === 'llm' ? 'accent' : 'muted'}>
            {transformation.generation_mode} mode
          </Badge>
          <button type="button" className="btn btn-ghost" onClick={onConfigure}>
            New configuration
          </button>
          <button type="button" className="btn" onClick={onOpenAudit}>
            Provenance
          </button>
        </div>
      </div>

      {transformation.error && <Callout tone="danger">{transformation.error}</Callout>}
      {transformation.warnings.map((warning) => (
        <Callout tone="warn" key={warning}>
          {warning}
        </Callout>
      ))}

      <Tabs
        value={active?.format ?? ''}
        onChange={setFormat}
        options={outputs.map((output) => ({
          id: output.format,
          label: labelFor(output),
          count: output.review_state === 'approved' ? '✓' : undefined,
        }))}
      />

      {active ? (
        <ArtefactPanel
          key={`${active.id}-${active.version}`}
          output={active}
          documentText={document?.preview ?? ''}
        />
      ) : (
        <Panel>
          <Empty title="This run produced no artefacts" />
        </Panel>
      )}


      <Panel title="Run record" subtitle={`stage: ${transformation.stage}`}>
        <div className="grid grid-3">
              <KeyValue
                rows={{
                  'Requested by': transformation.requested_by,
                  Created: dateTime(transformation.created_at),
                  Completed: dateTime(transformation.completed_at),
                  Duration: duration(transformation.duration_ms),
                }}
              />
              <KeyValue
                rows={{
                  Model: transformation.model_version,
                  'Prompt set': transformation.prompt_version,
                  Pipeline: transformation.pipeline_version,
                  Generation: transformation.generation_mode,
                }}
              />
              <KeyValue
                rows={{
                  'Source hash': <Hash value={transformation.source_hash} size={8} />,
                  'Requested formats': transformation.requested_formats.join(', '),
                  Artefacts: outputs.length,
                  Configuration:
                    Object.entries(transformation.config)
                      .filter(([, value]) => value !== '' && value !== false)
                      .map(([key, value]) => `${key}=${String(value)}`)
                      .join(' · ') || 'defaults',
                }}
              />

        </div>
      </Panel>
    </div>
  )
}

function ArtefactPanel({ output, documentText }: { output: Output; documentText: string }) {
  const meta = useWorkspace((s) => s.meta)
  const [tab, setTab] = useState<StudioTab>('preview')
  // The parent keys this component on id+version, so an edit or regeneration
  // remounts it and the draft always starts from the stored body.
  const [draft, setDraft] = useState(output.edited_body ?? output.body)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)

  const formatLabel =
    meta?.formats.find((item) => item.id === output.format)?.label ?? humanise(output.format)

  const save = async () => {
    setBusy('save')
    try {
      const next = await api.editOutput(output.id, draft, note.trim())
      workspace.patchOutput(next)
      setDirty(false)
      setNote('')
      toast.ok('Artefact re-hashed; approval reset to pending review')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  const regenerate = async () => {
    setBusy('regen')
    const progress = toast.begin(`Regenerating ${formatLabel} from source evidence…`)
    try {
      const next = await api.regenerateOutput(output.id)
      workspace.patchOutput(next)
      progress.done('Regenerated with a fresh evidence retrieval')
    } catch (error) {
      progress.fail(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  const review = async (state: 'approved' | 'rejected' | 'pending_review') => {
    setBusy(state)
    try {
      const next = await api.reviewOutput(output.id, state, note.trim())
      workspace.patchOutput(next)
      toast.ok(
        state === 'approved'
          ? `${formatLabel} approved and sealed into the audit chain`
          : `${formatLabel} marked ${state.replace(/_/g, ' ')}`,
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  const verify = async () => {
    setBusy('verify')
    try {
      const result = await api.verifyOutput(output.id, documentText)
      const matched = result.matched ?? result.valid ?? result.verified
      if (matched) toast.ok('Artefact re-derives from the supplied source text')
      else toast.error('Source binding check failed — do not release this artefact')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  const factuality = output.factuality as {
    score?: number
    supported_claims?: number
    total_claims?: number
    unsupported?: string[]
    numbers?: string[]
  }
  const validation = output.validation as { errors?: string[]; warnings?: string[] }
  const security = output.security as { risk_level?: string; notes?: string[] }

  return (
    <div className="grid grid-sidebar">
      <div className="stack">
        <Panel
          title={output.title || formatLabel}
          subtitle={`v${output.version} · ${output.char_count.toLocaleString()} chars`}
          actions={
            <>
              <ReviewBadge state={output.review_state} />
              <a
                className="btn btn-sm"
                href={api.exportUrl(output.id)}
                target="_blank"
                rel="noreferrer"
                download
              >
                Export .md
              </a>
            </>
          }
        >
          <Tabs
            value={tab}
            onChange={setTab}
            options={[
              { id: 'preview', label: dirty ? 'Preview (edited)' : 'Preview' },
              { id: 'evidence', label: 'Evidence', count: output.evidence.length },
              { id: 'assurance', label: 'Assurance' },
              { id: 'activity', label: 'Activity' },
            ]}
          />
          <div className="divider" />

          {tab === 'preview' && (
            <div className="stack">
              <div className="artefact">{draft}</div>
              <div className="divider" />
              <div className="field">
                <span className="field-label">Edit artefact</span>
                <textarea
                  className="artefact-editor"
                  value={draft}
                  onChange={(event) => {
                    setDraft(event.target.value)
                    setDirty(event.target.value !== (output.edited_body ?? output.body))
                  }}
                />
                <span className="field-hint">
                  Edits are hashed, attributed and send the artefact back to{' '}
                  <em>pending review</em>. Nothing is released without a signature.
                </span>
              </div>
              <div className="field">
                <span className="field-label">Change note</span>
                <input
                  className="input"
                  value={note}
                  maxLength={1000}
                  placeholder="Why this edit? Recorded in the audit chain."
                  onChange={(event) => setNote(event.target.value)}
                />
              </div>
              <div className="row">
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!dirty || busy === 'save'}
                  onClick={() => void save()}
                >
                  {busy === 'save' ? 'Saving…' : 'Save edit & re-hash'}
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={dirty}
                  title={dirty ? 'Save or discard your edit first' : ''}
                  onClick={() => {
                    setDraft(output.edited_body ?? output.body)
                    setDirty(false)
                  }}
                >
                  Discard changes
                </button>
              </div>
            </div>
          )}

          {tab === 'evidence' && (
            <div className="stack">
              <Callout tone="info">
                Each quote is the source chunk that backed a sentence in this artefact, with its
                retrieval score and the section it came from.
              </Callout>
              {output.evidence.length === 0 ? (
                <Empty title="No evidence attached" />
              ) : (
                output.evidence.map((item) => (
                  <div className="quote" key={item.chunk_id}>
                    <span className="quote-score">#{item.ordinal}</span>
                    <span className="quote-text">
                      {item.heading && <div className="quote-heading">{item.heading}</div>}
                      {item.quote}
                      <div className="label-inline" style={{ marginTop: 4 }}>
                        retrieval {score(item.score)} · chunk {item.chunk_id}
                      </div>
                    </span>
                  </div>
                ))
              )}
            </div>
          )}

          {tab === 'assurance' && (
            <div className="stack">
              <div className="grid grid-3">
                <div className="metric">
                  <div className="metric-label">Grounding</div>
                  <div className="metric-value" style={{ color: 'var(--accent)' }}>
                    {percent(output.grounding_score, 0)}
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <Meter value={output.grounding_score} tone="accent" />
                  </div>
                </div>
                <div className="metric">
                  <div className="metric-label">Factuality</div>
                  <div
                    className="metric-value"
                    style={{
                      color:
                        (factuality.score ?? 0) >= 0.8
                          ? 'var(--ok)'
                          : (factuality.score ?? 0) >= 0.5
                            ? 'var(--warn)'
                            : 'var(--danger)',
                    }}
                  >
                    {percent(factuality.score, 0)}
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <Meter value={factuality.score ?? 0} />
                  </div>
                </div>
                <div className="metric">
                  <div className="metric-label">Risk carried</div>
                  <div
                    className="metric-value"
                    style={{
                      fontSize: 20,
                      color: RISK_COLOUR[riskTone(security.risk_level ?? 'none')] ?? 'var(--text-dim)',
                    }}
                  >
                    {humanise(security.risk_level ?? 'none')}
                  </div>
                  <div className="metric-hint">{output.evidence.length} evidence chunks</div>
                </div>
              </div>

              {validation.errors && validation.errors.length > 0 && (
                <div className="stack" style={{ gap: 6 }}>
                  <div className="field-label">Validation errors</div>
                  {validation.errors.map((line) => (
                    <Callout tone="danger" key={line}>
                      {line}
                    </Callout>
                  ))}
                </div>
              )}
              {validation.warnings && validation.warnings.length > 0 && (
                <div className="stack" style={{ gap: 6 }}>
                  <div className="field-label">Validation warnings</div>
                  {validation.warnings.map((line) => (
                    <Callout tone="warn" key={line}>
                      {line}
                    </Callout>
                  ))}
                </div>
              )}
              {factuality.unsupported && factuality.unsupported.length > 0 && (
                <div className="stack" style={{ gap: 6 }}>
                  <div className="field-label">Claims without direct support</div>
                  {factuality.unsupported.map((line) => (
                    <Callout tone="warn" key={line}>
                      {line}
                    </Callout>
                  ))}
                </div>
              )}
              <details>
                <summary className="label-inline" style={{ cursor: 'pointer' }}>
                  Raw assurance payload
                </summary>
                <div style={{ marginTop: 8 }}>
                  <Json value={{ factuality: output.factuality, security: output.security, validation: output.validation }} />
                </div>
              </details>
            </div>
          )}

          {tab === 'activity' && (
            <div className="stack">
              <KeyValue
                rows={{
                  'Review state': <ReviewBadge state={output.review_state} />,
                  'Reviewed by': output.reviewed_by,
                  'Review note': output.review_note,
                  'Reviewed at': dateTime(output.reviewed_at),
                  Version: `v${output.version}`,
                  Created: dateTime(output.created_at),
                  'Sections mapped': output.section_map.length,
                  'Output hash (SHA-256)': <Hash value={output.output_hash} size={12} />,
                }}
              />
              {output.section_map.length > 0 && (
                <details>
                  <summary className="label-inline" style={{ cursor: 'pointer' }}>
                    Section map
                  </summary>
                  <div style={{ marginTop: 8 }}>
                    <Json value={output.section_map} />
                  </div>
                </details>
              )}
            </div>
          )}
        </Panel>
      </div>

      <div className="stack">
        <Panel title="Release gate" subtitle="human in the loop">
          <div className="stack">
            {output.review_state === 'approved' ? (
              <Callout tone="ok">
                <strong>Approved</strong> by {output.reviewed_by} on {dateTime(output.reviewed_at)}.
                The signed hash is in the audit chain.
              </Callout>
            ) : (
              <Callout tone="warn">
                <strong>{humanise(output.review_state)}.</strong> Requires the approver or admin role
                before this artefact can be released.
              </Callout>
            )}

            <div className="field">
              <span className="field-label">Review note</span>
              <textarea
                className="textarea"
                style={{ minHeight: 70 }}
                value={note}
                maxLength={1000}
                placeholder="Sign-off rationale, e.g. figures cross-checked against the source annexure."
                onChange={(event) => setNote(event.target.value)}
              />
            </div>

            <div className="stack" style={{ gap: 8 }}>
              <button
                type="button"
                className="btn btn-ok btn-block"
                disabled={busy !== null || output.review_state === 'approved'}
                onClick={() => void review('approved')}
              >
                {busy === 'approved' ? 'Approving…' : 'Approve for release'}
              </button>
              <button
                type="button"
                className="btn btn-danger btn-block"
                disabled={busy !== null}
                onClick={() => void review('rejected')}
              >
                Reject and return
              </button>
              <button
                type="button"
                className="btn btn-block"
                disabled={busy !== null}
                onClick={() => void review('pending_review')}
              >
                Move back to review
              </button>
            </div>
          </div>
        </Panel>

        <Panel title="Regenerate" subtitle="fresh retrieval, same source">
          <div className="stack">
            <p className="dim" style={{ fontSize: 12.5 }}>
              Re-runs retrieval and generation for this format only. The source, configuration and
              knowledge layer are unchanged, so the new hash can be compared against the old one.
            </p>
            <button
              type="button"
              className="btn btn-block"
              disabled={busy !== null}
              onClick={() => void regenerate()}
            >
              {busy === 'regen' ? 'Regenerating…' : 'Regenerate this format'}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-block"
              disabled={busy !== null || !documentText}
              title={documentText ? '' : 'Open a source to enable this check'}
              onClick={() => void verify()}
            >
              {busy === 'verify' ? 'Verifying…' : 'Verify source binding'}
            </button>
          </div>
        </Panel>

        <Panel title="Integrity">
          <KeyValue
            rows={{
              'Output hash': <Hash value={output.output_hash} size={10} />,
              Version: `v${output.version}`,
              Review: (
                <Badge tone={reviewTone(output.review_state)}>{output.review_state.replace(/_/g, ' ')}</Badge>
              ),
              Grounding: percent(output.grounding_score, 1),
              Claims: factuality.total_claims
                ? `${factuality.supported_claims ?? 0} of ${factuality.total_claims} supported`
                : 'not measured',
            }}
          />
        </Panel>
      </div>
    </div>
  )
}

const RISK_COLOUR: Record<string, string> = {
  ok: 'var(--ok)',
  info: 'var(--info)',
  warn: 'var(--warn)',
  danger: 'var(--danger)',
  muted: 'var(--text-dim)',
}

function labelFor(output: Output): string {
  return humanise(output.format)
}
