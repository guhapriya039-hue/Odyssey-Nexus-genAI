import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { DocumentSummary, Knowledge, SecurityReport } from '../api/types'
import {
  Badge,
  Callout,
  Empty,
  Hash,
  KeyValue,
  Loading,
  Metric,
  Panel,
  RiskBadge,
  StatusBadge,
  Tabs,
} from '../components/ui'
import { bytes, humanise, percent, relativeTime, riskTone } from '../lib/format'
import { toast } from '../state/toast'
import { useWorkspace, workspace } from '../state/workspace'

type IntakeTab = 'upload' | 'text' | 'url'

const ACCEPT = '.pdf,.docx,.pptx,.txt,.md,.csv,.json,.srt,.vtt,.png,.jpg,.jpeg,.webp,.mp3,.wav,.m4a'

export function SourcesView({ onContinue }: { onContinue: () => void }) {
  const documents = useWorkspace((s) => s.documents)
  const selected = useWorkspace((s) => s.document)
  const documentId = useWorkspace((s) => s.documentId)
  const meta = useWorkspace((s) => s.meta)

  const [tab, setTab] = useState<IntakeTab>('upload')
  const [query, setQuery] = useState('')
  const [loaded, setLoaded] = useState<{ id: string; record: Knowledge } | null>(null)
  const [busy, setBusy] = useState(false)

  // --- upload
  const [file, setFile] = useState<File | null>(null)
  const [fileTitle, setFileTitle] = useState('')
  // --- paste
  const [pasteTitle, setPasteTitle] = useState('Pasted source')
  const [pasteText, setPasteText] = useState('')
  // --- url
  const [url, setUrl] = useState('')
  const [urlTitle, setUrlTitle] = useState('')

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return documents
    return documents.filter(
      (doc) =>
        doc.title.toLowerCase().includes(needle) ||
        doc.filename.toLowerCase().includes(needle) ||
        doc.source_kind.includes(needle),
    )
  }, [documents, query])

  useEffect(() => {
    if (!documentId) return
    let cancelled = false
    void (async () => {
      try {
        const record = await api.knowledge(documentId)
        if (!cancelled) setLoaded({ id: documentId, record })
      } catch {
        if (!cancelled) setLoaded(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [documentId])

  // Only show a knowledge record that belongs to the currently selected source.
  const knowledge = loaded && loaded.id === documentId ? loaded.record : null

  const adopt = async (publicId: string) => {
    const document = await workspace.openDocument(publicId)
    toast.ok(`Loaded “${document.title}” — risk ${document.risk_level}`)
  }

  const submit = async (action: () => Promise<{ public_id: string; title: string }>) => {
    setBusy(true)
    const progress = toast.begin('Extracting, scanning and indexing source…')
    try {
      const created = await action()
      await workspace.refreshDocuments()
      await adopt(created.public_id)
      progress.done(`Indexed “${created.title}”`)
    } catch (error) {
      progress.fail(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (doc: DocumentSummary) => {
    if (!window.confirm(`Delete “${doc.title}” and its run history? The audit chain keeps the hashes.`)) {
      return
    }
    try {
      await api.deleteDocument(doc.public_id)
      if (doc.public_id === documentId) await workspace.closeDocument()
      await workspace.refreshDocuments()
      toast.ok('Source deleted; provenance hashes retained in the audit chain')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  const security = selected?.security ?? null

  return (
    <div className="stack">
      <div className="view-head">
        <div>
          <h1>Source intake</h1>
          <p>
            Bring one document in any supported medium. It is text-extracted, scanned for prompt
            injection and PII, hashed, chunked and turned into a single shared knowledge layer that
            every output format will read from.
          </p>
        </div>
        <div className="view-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={onContinue}
            disabled={!documentId}
            title={documentId ? '' : 'Select a source first'}
          >
            Continue to configure →
          </button>
        </div>
      </div>

      <div className="grid grid-sidebar">
        <div className="stack">
          <Panel title="Ingest a source" subtitle={meta?.web_ingestion_enabled ? undefined : 'web ingestion disabled by policy'}>
            <Tabs
              value={tab}
              onChange={setTab}
              options={[
                { id: 'upload', label: 'File upload' },
                { id: 'text', label: 'Paste text' },
                { id: 'url', label: 'Public URL' },
              ]}
            />

            <div className="divider" />

            {tab === 'upload' && (
              <div className="stack">
                <div className="field">
                  <span className="field-label">Document</span>
                  <input
                    className="input"
                    type="file"
                    accept={ACCEPT}
                    onChange={(event) => {
                      const picked = event.target.files?.[0] ?? null
                      setFile(picked)
                      if (picked && !fileTitle) setFileTitle(picked.name)
                    }}
                  />
                  <span className="field-hint">
                    PDF · DOCX · PPTX · Markdown · CSV · JSON · SRT/VTT · images (OCR) · MP3/WAV/M4A
                    (transcription)
                  </span>
                </div>
                <div className="field">
                  <span className="field-label">Title override</span>
                  <input
                    className="input"
                    value={fileTitle}
                    placeholder="Optional — detected from the file otherwise"
                    onChange={(event) => setFileTitle(event.target.value)}
                  />
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!file || busy}
                  onClick={() => {
                    if (file) void submit(() => api.uploadDocument(file, fileTitle))
                  }}
                >
                  {busy ? 'Processing…' : 'Upload and index'}
                </button>
              </div>
            )}

            {tab === 'text' && (
              <div className="stack">
                <div className="field">
                  <span className="field-label">Title</span>
                  <input
                    className="input"
                    value={pasteTitle}
                    onChange={(event) => setPasteTitle(event.target.value)}
                  />
                </div>
                <div className="field">
                  <span className="field-label">Source text</span>
                  <textarea
                    className="textarea"
                    style={{ minHeight: 200 }}
                    value={pasteText}
                    placeholder="Paste an incident note, report, transcript or policy here…"
                    onChange={(event) => setPasteText(event.target.value)}
                  />
                  <span className="field-hint">
                    {pasteText.trim() ? `${pasteText.trim().split(/\s+/).length} words` : 'Up to 400,000 characters'}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!pasteText.trim() || busy}
                  onClick={() => void submit(() => api.ingestText(pasteTitle, pasteText))}
                >
                  {busy ? 'Processing…' : 'Index pasted text'}
                </button>
              </div>
            )}

            {tab === 'url' && (
              <div className="stack">
                <Callout tone="info">
                  Private and loopback addresses are refused, redirects are re-validated, and the
                  fetch is size-capped — this is the SSRF guard from the security layer.
                </Callout>
                <div className="field">
                  <span className="field-label">Source URL</span>
                  <input
                    className="input"
                    value={url}
                    placeholder="https://example.org/report"
                    onChange={(event) => setUrl(event.target.value)}
                  />
                </div>
                <div className="field">
                  <span className="field-label">Title override</span>
                  <input
                    className="input"
                    value={urlTitle}
                    placeholder="Optional"
                    onChange={(event) => setUrlTitle(event.target.value)}
                  />
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!url.trim() || busy || !meta?.web_ingestion_enabled}
                  onClick={() => void submit(() => api.ingestUrl(url.trim(), urlTitle))}
                >
                  {busy ? 'Fetching…' : 'Fetch and index'}
                </button>
              </div>
            )}
          </Panel>

          <Panel title="Library" subtitle={`${filtered.length} of ${documents.length}`}>
            <div className="field" style={{ marginBottom: 12 }}>
              <input
                className="input"
                value={query}
                placeholder="Filter by title, filename or kind…"
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>

            {filtered.length === 0 ? (
              <Empty title={documents.length ? 'No match' : 'No sources ingested yet'}>
                {documents.length
                  ? 'Try a different filter term.'
                  : 'Use the intake panel above to add your first document.'}
              </Empty>
            ) : (
              <div className="list-pick">
                {filtered.map((doc) => (
                  <div
                    key={doc.public_id}
                    className={`doc-card${doc.public_id === documentId ? ' selected' : ''}`}
                    onClick={() => void adopt(doc.public_id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') void adopt(doc.public_id)
                    }}
                  >
                    <div className="row spread" style={{ gap: 6 }}>
                      <span className="doc-card-title">{doc.title}</span>
                      <StatusBadge status={doc.status} />
                    </div>
                    <div className="doc-card-meta">
                      <Badge tone="muted">{doc.source_kind}</Badge>
                      <RiskBadge level={doc.risk_level} />
                      {doc.redaction_count > 0 && (
                        <Badge tone="warn">{doc.redaction_count} PII redactions</Badge>
                      )}
                      {doc.injection_score > 0 && (
                        <Badge tone="danger">injection {percent(doc.injection_score)}</Badge>
                      )}
                    </div>
                    <div className="row spread label-inline">
                      <span>
                        {doc.word_count.toLocaleString()} words · {doc.chunk_count} chunks ·{' '}
                        {bytes(doc.byte_size)}
                      </span>
                      <span>{relativeTime(doc.created_at)}</span>
                    </div>
                    <div className="row spread">
                      <Hash value={doc.file_hash} size={6} />
                      <span className="row row-tight">
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={(event) => {
                            event.stopPropagation()
                            void adopt(doc.public_id)
                          }}
                        >
                          Open
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={(event) => {
                            event.stopPropagation()
                            void remove(doc)
                          }}
                        >
                          Delete
                        </button>
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>

        <div className="stack">
          {!selected ? (
            <Panel title="Source detail">
              <Empty title="Nothing selected">
                Pick a document to inspect its extracted text, security posture and knowledge layer.
              </Empty>
            </Panel>
          ) : (
            <>
              <Panel
                title={selected.title}
                subtitle={selected.public_id}
                actions={
                  <button type="button" className="btn btn-sm btn-primary" onClick={onContinue}>
                    Configure →
                  </button>
                }
              >
                <div className="grid grid-2" style={{ gap: 10, marginBottom: 12 }}>
                  <Metric label="Words" value={selected.word_count.toLocaleString()} tone="accent" />
                  <Metric label="Chunks" value={selected.chunk_count} tone="violet" />
                  <Metric
                    label="Risk"
                    value={selected.risk_level}
                    tone={riskTone(selected.risk_level)}
                    hint={`injection score ${percent(selected.injection_score)}`}
                  />
                  <Metric
                    label="Redactions"
                    value={selected.redaction_count}
                    tone={selected.redaction_count ? 'warn' : 'ok'}
                    hint={selected.pii_types.join(', ') || 'no PII matched'}
                  />
                </div>
                <KeyValue
                  rows={{
                    Filename: selected.filename,
                    'Media type': selected.media_type,
                    'Source kind': selected.source_kind,
                    Size: bytes(selected.byte_size),
                    'Ingested by': selected.created_by,
                    'Ingested at': relativeTime(selected.created_at),
                    'File hash (SHA-256)': <Hash value={selected.file_hash} size={8} />,
                    'Text hash (SHA-256)': <Hash value={selected.text_hash} size={8} />,
                    'Status detail': selected.status_detail,
                  }}
                />
              </Panel>

              <SecurityPanel report={security} />

              <Panel title="Knowledge layer" subtitle="shared by every output format">
                {knowledge ? (
                  <div className="stack">
                    <div>
                      <div className="field-label">Subject</div>
                      <div style={{ fontSize: 13.5, fontWeight: 560 }}>{knowledge.subject}</div>
                    </div>
                    <div>
                      <div className="field-label">Summary</div>
                      <p className="dim" style={{ marginTop: 4, fontSize: 12.5 }}>
                        {knowledge.summary}
                      </p>
                    </div>
                    {knowledge.topics.length > 0 && (
                      <div>
                        <div className="field-label">Topics</div>
                        <div className="chip-row" style={{ marginTop: 5 }}>
                          {knowledge.topics.map((topic) => (
                            <span className="chip" key={topic}>
                              {topic}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    <div>
                      <div className="field-label">Key facts ({knowledge.key_facts.length})</div>
                      <div className="stack" style={{ gap: 6, marginTop: 5 }}>
                        {knowledge.key_facts.slice(0, 8).map((fact, index) => (
                          <div className="quote" key={`${fact.category}-${index}`}>
                            <span className="quote-score">{fact.category}</span>
                            <span className="quote-text">{fact.text}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="grid grid-2" style={{ gap: 10 }}>
                      <KeyValue
                        rows={{
                          Figures: knowledge.figures.join(', ') || 'none',
                          Dates: knowledge.dates.join(', ') || 'none',
                          Indicators: knowledge.indicators.join(', ') || 'none',
                          Entities: knowledge.entities.map((e) => e.name).join(', ') || 'none',
                          'Detected objective': humanise(knowledge.detected_objective),
                          'Reading level': humanise(knowledge.reading_level),
                          'Build mode': knowledge.build_mode,
                        }}
                      />
                    </div>
                  </div>
                ) : (
                  <Loading label="Loading knowledge layer…" />
                )}
              </Panel>

              <Panel title="Extracted text preview" subtitle={`${selected.char_count.toLocaleString()} chars`}>
                <pre className="json">{selected.preview}</pre>
              </Panel>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function SecurityPanel({ report }: { report: SecurityReport | null }) {
  if (!report) {
    return (
      <Panel title="Security scan">
        <Callout tone="info">No scan report is stored for this source.</Callout>
      </Panel>
    )
  }

  const tone = riskTone(report.risk_level)
  return (
    <Panel
      title="Security scan"
      subtitle="pre-generation gate"
      actions={<RiskBadge level={report.risk_level} />}
    >
      <div className="stack">
        <KeyValue
          rows={{
            'Prompt-injection score': (
              <Badge tone={report.injection_score > 0.4 ? 'danger' : report.injection_score > 0 ? 'warn' : 'ok'}>
                {percent(report.injection_score)}
              </Badge>
            ),
            'Injection patterns':
              report.injection_patterns.length ? report.injection_patterns.join(', ') : 'none matched',
            'PII findings': report.pii_count,
            'Redactions applied': report.redactions_applied,
          }}
        />

        {report.pii_findings.length > 0 && (
          <div className="stack" style={{ gap: 6 }}>
            <div className="field-label">PII detail</div>
            {report.pii_findings.slice(0, 10).map((finding, index) => (
              <div className="quote" key={`${finding.category}-${index}`} style={{ borderLeftColor: tone === 'danger' ? 'var(--danger)' : 'var(--warn)' }}>
                <span className="quote-score">{finding.severity}</span>
                <span className="quote-text">
                  <strong>{finding.label}</strong> ({humanise(finding.category)}) — evidence “{finding.evidence}”
                  {finding.redacted_value ? (
                    <>
                      {' '}
                      <span className="chip chip-mono">{finding.redacted_value}</span>
                    </>
                  ) : null}
                </span>
              </div>
            ))}
          </div>
        )}

        {report.recommendations.length > 0 && (
          <div className="stack" style={{ gap: 6 }}>
            <div className="field-label">Recommendations</div>
            {report.recommendations.map((line) => (
              <Callout tone={report.risk_level === 'none' ? 'ok' : 'warn'} key={line}>
                {line}
              </Callout>
            ))}
          </div>
        )}

        {report.injection_score > 0.4 && (
          <Callout tone="danger">
            <strong>Hostile instruction detected.</strong> Matching lines were replaced with a
            suppression marker before indexing, so they can never steer generation.
          </Callout>
        )}
      </div>
    </Panel>
  )
}
