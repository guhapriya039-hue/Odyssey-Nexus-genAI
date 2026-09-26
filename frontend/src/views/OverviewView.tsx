import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ChainVerification, SystemConfig } from '../api/types'
import {
  Badge,
  Callout,
  Empty,
  Hash,
  Json,
  KeyValue,
  Loading,
  Metric,
  Panel,
} from '../components/ui'
import { bytes, duration, percent, relativeTime, riskTone, statusTone } from '../lib/format'
import { useWorkspace } from '../state/workspace'
import { toast } from '../state/toast'

export function OverviewView({
  onOpenSources,
  onOpenRun,
  onOpenStudio,
  onOpenAudit,
}: {
  onOpenSources: () => void
  onOpenRun: (id: string) => void
  onOpenStudio: () => void
  onOpenAudit: () => void
}) {
  const meta = useWorkspace((s) => s.meta)
  const documents = useWorkspace((s) => s.documents)
  const runs = useWorkspace((s) => s.runs)
  const transformation = useWorkspace((s) => s.transformation)

  const [summary, setSummary] = useState<Awaited<ReturnType<typeof api.stats>> | null>(null)
  const [chain, setChain] = useState<ChainVerification | null>(null)
  const [config, setConfig] = useState<SystemConfig | null>(null)
  const [verifying, setVerifying] = useState(false)

  useEffect(() => {
    void (async () => {
      try {
        const [nextStats, nextChain, nextConfig] = await Promise.all([
          api.stats(),
          api.verifyChain(),
          api.config(),
        ])
        setSummary(nextStats)
        setChain(nextChain)
        setConfig(nextConfig)
      } catch (error) {
        toast.error(error instanceof Error ? error.message : String(error))
      }
    })()
  }, [])

  const reverify = async () => {
    setVerifying(true)
    try {
      const next = await api.verifyChain()
      setChain(next)
      if (next.valid) toast.ok(`Audit chain intact across ${next.length} entries`)
      else toast.error(`Chain broken at entry ${next.broken_at_seq}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setVerifying(false)
    }
  }

  return (
    <div className="stack">
      <div className="view-head">
        <div>
          <h1>Mission control</h1>
          <p>
            One verified source becomes nine audience-ready artefacts. Every claim is traced to a
            chunk, every edit to a human, every run to a tamper-evident hash.
          </p>
        </div>
        <div className="view-actions">
          <button type="button" className="btn btn-primary" onClick={onOpenSources}>
            Ingest source
          </button>
          {transformation && (
            <button type="button" className="btn" onClick={onOpenStudio}>
              Open latest run
            </button>
          )}
          <button type="button" className="btn btn-ghost" onClick={onOpenAudit}>
            Audit trail
          </button>
        </div>
      </div>

      <div className="grid grid-4">
        <Metric
          label="Sources indexed"
          value={summary?.documents ?? documents.length}
          hint={`${bytes(documents.reduce((sum, doc) => sum + doc.byte_size, 0))} ingested`}
          tone="accent"
        />
        <Metric
          label="Artefacts produced"
          value={summary?.outputs ?? 0}
          hint={`across ${summary?.completed ?? 0} completed runs`}
          tone="violet"
        />
        <Metric
          label="Mean grounding"
          value={percent(summary?.avg_grounding_score ?? 0, 1)}
          hint="share of sentences tied to source chunks"
          tone={(summary?.avg_grounding_score ?? 0) >= 0.6 ? 'ok' : 'warn'}
        />
        <Metric
          label="Audit entries"
          value={summary?.audit_events ?? 0}
          hint={chain ? (chain.valid ? 'chain verified' : `broken @ ${chain.broken_at_seq}`) : 'verifying…'}
          tone={chain?.valid ? 'ok' : chain ? 'danger' : 'muted'}
        />
      </div>

      {chain && !chain.valid && (
        <Callout tone="danger">
          <strong>Audit chain integrity failure.</strong> {chain.message}
        </Callout>
      )}

      <div className="grid grid-sidebar">
        <div className="stack">
          <Panel
            title="Recent transformation runs"
            subtitle={`${runs.length} shown`}
            actions={
              <button type="button" className="btn btn-sm btn-ghost" onClick={onOpenSources}>
                New source
              </button>
            }
            tight
          >
            {runs.length === 0 ? (
              <Empty title="No runs yet" action={<button type="button" className="btn btn-primary" onClick={onOpenSources}>Ingest your first source</button>}>
                Start by ingesting a PDF, DOCX, PPTX, image, subtitle file, audio clip or a public
                URL. The platform extracts text, scans it for prompt injection and PII, then
                builds a shared knowledge layer.
              </Empty>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Source</th>
                      <th>Status</th>
                      <th className="num">Artefacts</th>
                      <th className="num">Grounding</th>
                      <th>Mode</th>
                      <th className="num">Took</th>
                      <th>When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((run) => (
                      <tr
                        key={run.transformation_id}
                        className="clickable"
                        onClick={() => onOpenRun(run.transformation_id)}
                      >
                        <td className="mono">{run.transformation_id}</td>
                        <td>{run.document_title ?? run.document_id}</td>
                        <td>
                          <Badge tone={statusTone(run.status)}>{run.status.replace(/_/g, ' ')}</Badge>
                          {run.warnings.length > 0 && (
                            <div className="label-inline" style={{ marginTop: 3 }}>
                              {run.warnings.length} warning{run.warnings.length === 1 ? '' : 's'}
                            </div>
                          )}
                        </td>
                        <td className="num">{run.output_count}</td>
                        <td className="num tnum">{percent(run.avg_grounding, 0)}</td>
                        <td>
                          <Badge tone={run.generation_mode === 'llm' ? 'accent' : 'muted'}>
                            {run.generation_mode}
                          </Badge>
                        </td>
                        <td className="num">{duration(run.duration_ms)}</td>
                        <td className="nowrap muted">{relativeTime(run.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel title="Source library" subtitle={`${documents.length} indexed`} tight>
            {documents.length === 0 ? (
              <Empty title="Library is empty" />
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Kind</th>
                      <th>Status</th>
                      <th>Risk</th>
                      <th className="num">Words</th>
                      <th className="num">Chunks</th>
                      <th>Source hash</th>
                      <th>When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((doc) => (
                      <tr key={doc.public_id}>
                        <td>
                          <div style={{ fontWeight: 560 }}>{doc.title}</div>
                          <div className="label-inline">{doc.filename}</div>
                        </td>
                        <td>
                          <Badge tone="muted">{doc.source_kind}</Badge>
                        </td>
                        <td>
                          <Badge tone={statusTone(doc.status)}>{doc.status}</Badge>
                        </td>
                        <td>
                          <Badge tone={riskTone(doc.risk_level)}>{doc.risk_level}</Badge>
                          {doc.redaction_count > 0 && (
                            <div className="label-inline" style={{ marginTop: 3 }}>
                              {doc.redaction_count} redactions
                            </div>
                          )}
                        </td>
                        <td className="num tnum">{doc.word_count.toLocaleString()}</td>
                        <td className="num tnum">{doc.chunk_count}</td>
                        <td>
                          <Hash value={doc.file_hash} size={6} />
                        </td>
                        <td className="nowrap muted">{relativeTime(doc.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>

        <div className="stack">
          <Panel
            title="Integrity chain"
            actions={
              <button type="button" className="btn btn-sm" onClick={reverify} disabled={verifying}>
                {verifying ? 'Verifying…' : 'Re-verify'}
              </button>
            }
          >
            {!chain ? (
              <Loading label="Walking the chain…" />
            ) : (
              <KeyValue
                rows={{
                  Status: <Badge tone={chain.valid ? 'ok' : 'danger'}>{chain.valid ? 'Intact' : 'Broken'}</Badge>,
                  Entries: chain.length,
                  Head: <Hash value={chain.head_hash} size={8} />,
                  Algorithm: 'SHA-256',
                  Verdict: chain.message,
                }}
              />
            )}
          </Panel>

          <Panel title="Engine capability" subtitle={meta ? `v${meta.version}` : undefined}>
            {!meta ? (
              <Loading />
            ) : (
              <KeyValue
                rows={{
                  Environment: <Badge tone="muted">{meta.environment}</Badge>,
                  Generation: meta.llm_configured ? (
                    <Badge tone="ok">LLM · {meta.llm_model}</Badge>
                  ) : (
                    <Badge tone="warn">Extractive fallback</Badge>
                  ),
                  'Model chain': meta.llm_model_chain.join(' → ') || '—',
                  Embeddings: meta.embedding_provider,
                  OCR: meta.ocr_enabled ? 'enabled' : 'unavailable',
                  'Speech to text': meta.speech_to_text_enabled ? 'enabled' : 'unavailable',
                  'Web ingestion': meta.web_ingestion_enabled ? 'enabled' : 'disabled',
                  'Output formats': `${meta.formats.length} formats`,
                  Languages: String(Object.keys(meta.languages).length),
                  'Prompt set': meta.prompt_version,
                }}
              />
            )}
          </Panel>

          <Panel title="Runtime configuration" subtitle="live from the engine">
            {config ? <Json value={config} /> : <Loading />}
          </Panel>

          <Panel title="How trust is enforced">
            <div className="stack" style={{ gap: 10 }}>
              <Callout tone="info" icon="1">
                <strong>Scan before trust.</strong> Every source is scanned for prompt injection and
                PII; matches are redacted and the document is risk-rated.
              </Callout>
              <Callout tone="info" icon="2">
                <strong>One knowledge layer.</strong> All formats read from the same extracted facts,
                so numbers cannot drift between a deck and a tweet.
              </Callout>
              <Callout tone="info" icon="3">
                <strong>Human gate.</strong> Outputs land in <em>pending review</em>; only an
                approver can sign them off, and every edit re-hashes the artefact.
              </Callout>
              <Callout tone="info" icon="4">
                <strong>Tamper evidence.</strong> Audit entries are hash-chained, so a rewritten row
                breaks verification immediately.
              </Callout>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
