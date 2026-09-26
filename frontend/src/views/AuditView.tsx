import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AuditEvent, ChainVerification, Comparison, Provenance } from '../api/types'
import {
  Badge,
  Callout,
  CopyButton,
  Empty,
  Hash,
  Json,
  KeyValue,
  Loading,
  Panel,
  Tabs,
} from '../components/ui'
import { dateTime, humanise, percent, shortHash } from '../lib/format'
import { toast } from '../state/toast'
import { useWorkspace } from '../state/workspace'

type AuditTab = 'chain' | 'events' | 'manifest' | 'consistency'

export function AuditView() {
  const transformation = useWorkspace((s) => s.transformation)
  const transformationId = useWorkspace((s) => s.transformationId)
  const documentId = useWorkspace((s) => s.documentId)
  const liveHead = useWorkspace((s) => s.health?.audit_head)

  const [tab, setTab] = useState<AuditTab>('chain')
  const [chain, setChain] = useState<ChainVerification | null>(null)
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [provenance, setProvenance] = useState<Provenance | null>(null)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [scope, setScope] = useState<'run' | 'all'>('all')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void (async () => {
      try {
        setEvents(await api.auditEvents({ limit: scope === 'run' ? 40 : 120, transformationId: scope === 'run' ? transformationId ?? undefined : undefined }))
      } catch (error) {
        toast.error(error instanceof Error ? error.message : String(error))
      }
    })()
  }, [scope, transformationId])

  useEffect(() => {
    void (async () => {
      setChain(null)
      setProvenance(null)
      setComparison(null)
      try {
        setChain(await api.auditChain())
      } catch (error) {
        toast.error(error instanceof Error ? error.message : String(error))
      }
      if (!transformationId) return
      try {
        const [manifest, compare] = await Promise.all([
          api.provenance(transformationId),
          api.compare(transformationId),
        ])
        setProvenance(manifest)
        setComparison(compare)
      } catch {
        /* the run may have been deleted; the chain view still applies */
      }
    })()
  }, [transformationId])

  const reverify = async () => {
    setBusy(true)
    try {
      const next = await api.verifyChain()
      setChain(next)
      if (next.valid) toast.ok(`Chain intact across ${next.length} entries`)
      else toast.error(`Chain broken at entry ${next.broken_at_seq}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="view-head">
        <div>
          <h1>Provenance &amp; audit</h1>
          <p>
            Every action is an entry in a hash-chained ledger: rewriting any row breaks
            verification. Artefacts are bound to the exact source bytes and model configuration
            that produced them.
          </p>
        </div>
        <div className="view-actions">
          <div className="segmented">
            <button
              type="button"
              className={scope === 'all' ? 'active' : ''}
              onClick={() => setScope('all')}
            >
              All activity
            </button>
            <button
              type="button"
              className={scope === 'run' ? 'active' : ''}
              disabled={!transformationId}
              onClick={() => setScope('run')}
            >
              This run
            </button>
          </div>
          <button type="button" className="btn" onClick={reverify} disabled={busy}>
            {busy ? 'Verifying…' : 'Verify chain'}
          </button>
        </div>
      </div>

      <Tabs
        value={tab}
        onChange={setTab}
        options={[
          { id: 'chain', label: 'Integrity chain' },
          { id: 'events', label: 'Audit events', count: events.length },
          { id: 'manifest', label: 'Manifest', disabled: !provenance },
          { id: 'consistency', label: 'Cross-format', disabled: !comparison },
        ]}
      />

      {tab === 'chain' && (
        <div className="grid grid-sidebar">
          <Panel title="Chain verification" subtitle={chain ? `${chain.length} entries` : undefined}>
            {!chain ? (
              <Loading label="Recomputing hashes…" />
            ) : (
              <div className="stack">
                <Callout tone={chain.valid ? 'ok' : 'danger'}>
                  <strong>{chain.valid ? 'Chain intact.' : 'Chain broken.'}</strong> {chain.message}
                  {chain.broken_at_seq ? ` First mismatch at sequence ${chain.broken_at_seq}.` : ''}
                </Callout>
                <KeyValue
                  rows={{
                    Algorithm: 'SHA-256 over (seq, timestamp, action, actor, payload, previous hash)',
                    Entries: chain.length,
                    'Head hash': <Hash value={chain.head_hash} size={16} />,
                    Verdict: <Badge tone={chain.valid ? 'ok' : 'danger'}>{chain.valid ? 'valid' : 'invalid'}</Badge>,
                    'Live head': liveHead,
                  }}
                />
                <Callout tone="info">
                  Deleting a document does not erase the chain: the entry keeps the source hash, so a
                  removed artefact can still be shown to have existed and to have been unaltered.
                </Callout>
              </div>
            )}
          </Panel>

          <Panel title="Current scope">
            <KeyValue
              rows={{
                Run: transformationId ?? 'none selected',
                Source: documentId ?? 'none selected',
                Artefacts: transformation ? `${transformation.outputs.length} generated` : '—',
                'Prompt set': transformation?.prompt_version,
                Pipeline: transformation?.pipeline_version,
              }}
            />
          </Panel>
        </div>
      )}

      {tab === 'events' && (
        <Panel title="Audit ledger" subtitle="newest first" tight>
          {events.length === 0 ? (
            <Empty title="No audit events" />
          ) : (
            <div className="panel-body">
              {events.map((event) => (
                <div className="event" key={event.seq}>
                  <span className="event-seq">#{event.seq}</span>
                  <div className="event-body">
                    <div className="row spread" style={{ alignItems: 'flex-start' }}>
                      <div className="grow">
                        <div className="event-summary">{event.summary}</div>
                        <div className="event-meta">
                          <Badge tone={event.action.includes('approved') ? 'ok' : event.action.includes('rejected') || event.action.includes('deleted') ? 'danger' : event.action.includes('failed') || event.action.includes('blocked') ? 'warn' : 'muted'}>
                            {event.action}
                          </Badge>
                          <span>
                            {event.actor} · {event.actor_role}
                          </span>
                          <span>{dateTime(event.created_at)}</span>
                          {event.transformation_id && (
                            <span className="mono">{event.transformation_id}</span>
                          )}
                        </div>
                        <div className="event-meta">
                          <span className="hash">
                            <code title="Previous entry hash">{shortHash(event.prev_hash, 8)}</code>
                            <CopyButton value={event.prev_hash} />
                          </span>
                          <span className="hash">
                            <code title="This entry hash">{shortHash(event.entry_hash, 8)}</code>
                            <CopyButton value={event.entry_hash} />
                          </span>
                          <Badge tone={event.verified ? 'ok' : 'danger'}>
                            {event.verified ? 'verified' : 'unverified'}
                          </Badge>
                        </div>
                      </div>
                    </div>
                    {Object.keys(event.detail).length > 0 && (
                      <details>
                        <summary className="label-inline" style={{ cursor: 'pointer', marginTop: 4 }}>
                          payload
                        </summary>
                        <div style={{ marginTop: 6 }}>
                          <Json value={event.detail} />
                        </div>
                      </details>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      )}

      {tab === 'manifest' && (
        <div className="stack">
          {provenance ? (
            <>
              <div className="grid grid-2">
                <Panel title="Source binding">
                  <KeyValue
                    rows={{
                      Transformation: <span className="mono">{provenance.transformation_id}</span>,
                      Algorithm: provenance.source_hash_algorithm,
                      'Source hash': <Hash value={provenance.source_hash} size={16} />,
                      'Manifest hash': <Hash value={provenance.manifest_hash} size={16} />,
                      Created: dateTime(provenance.created_at),
                    }}
                  />
                </Panel>
                <Panel title="Generation configuration">
                  <KeyValue
                    rows={{
                      Model: provenance.model_version,
                      'Prompt set': provenance.prompt_version,
                      Pipeline: provenance.pipeline_version,
                      Artefacts: provenance.outputs.length,
                    }}
                  />
                </Panel>
              </div>

              <Panel title="Artefact manifest" tight>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Format</th>
                        <th>Review state</th>
                        <th className="num">Grounding</th>
                        <th>Output hash</th>
                      </tr>
                    </thead>
                    <tbody>
                      {provenance.outputs.map((row) => (
                        <tr key={String(row.format)}>
                          <td>{humanise(String(row.format))}</td>
                          <td>{humanise(String(row.review_state))}</td>
                          <td className="num tnum">{percent(Number(row.grounding_score ?? 0), 0)}</td>
                          <td>
                            <Hash value={String(row.output_hash)} size={10} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>

              <Panel title="Raw manifest" subtitle="signed structure">
                <Json value={provenance.manifest} />
              </Panel>
            </>
          ) : (
            <Panel>
              <Empty title="Select a run to see its manifest" />
            </Panel>
          )}
        </div>
      )}

      {tab === 'consistency' && (
        <div className="stack">
          {comparison ? (
            <>
              <Panel title="Cross-format consistency" subtitle="do the numbers agree?">
                <div className="stack">
                  <Callout tone={comparison.shared_figures.length ? 'ok' : 'warn'}>
                    {comparison.consistency_note}
                  </Callout>
                  <KeyValue
                    rows={{
                      Formats: comparison.formats.map((f) => humanise(f)).join(', '),
                      'Shared figures': comparison.shared_figures.length
                        ? comparison.shared_figures.join(', ')
                        : 'none — verify before release',
                    }}
                  />
                </div>
              </Panel>

              <Panel title="Per-format profile" tight>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Format</th>
                        <th className="num">Characters</th>
                        <th className="num">Grounding</th>
                        <th>Format-specific figures</th>
                        <th>Hash</th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparison.formats.map((format) => (
                        <tr key={format}>
                          <td>{humanise(format)}</td>
                          <td className="num tnum">{(comparison.char_counts[format] ?? 0).toLocaleString()}</td>
                          <td className="num tnum">{percent(comparison.grounding_scores[format] ?? 0, 0)}</td>
                          <td className="mono muted">
                            {(comparison.format_specific_figures[format] ?? []).join(', ') || '—'}
                          </td>
                          <td>
                            <Hash value={comparison.hashes[format]} size={8} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </>
          ) : (
            <Panel>
              <Empty title="Select a run to compare its formats" />
            </Panel>
          )}
        </div>
      )}

      <p className="label-inline">
        Ledger scoped to {scope === 'run' ? `run ${transformationId}` : 'all activity'} · chain head{' '}
        <span className="mono">{shortHash(chain?.head_hash, 10)}</span>
      </p>
    </div>
  )
}
