import { useEffect, useState } from 'react'
import { getIdentity, setIdentity } from './api/client'
import { toast } from './state/toast'
import { workspace, useWorkspace } from './state/workspace'
import { Badge, Loading } from './components/ui'
import { Toaster } from './components/Toaster'
import { humanise, shortHash } from './lib/format'
import { AuditView } from './views/AuditView'
import { OverviewView } from './views/OverviewView'
import { SourcesView } from './views/SourcesView'
import { StudioView } from './views/StudioView'
import { TransformView } from './views/TransformView'

type ViewId = 'overview' | 'sources' | 'transform' | 'studio' | 'audit'

interface NavEntry {
  id: ViewId
  step: string
  label: string
  blurb: string
}

const NAV: NavEntry[] = [
  {
    id: 'overview',
    step: '00',
    label: 'Mission control',
    blurb: 'Pipeline health, integrity chain and recent runs',
  },
  {
    id: 'sources',
    step: '01',
    label: 'Source intake',
    blurb: 'Ingest and scan multimodal evidence',
  },
  {
    id: 'transform',
    step: '02',
    label: 'Configure',
    blurb: 'Audience, tone and target output formats',
  },
  {
    id: 'studio',
    step: '03',
    label: 'Output studio',
    blurb: 'Review, edit, approve and export grounded artefacts',
  },
  { id: 'audit', step: '04', label: 'Provenance', blurb: 'Hash-chained audit trail and manifests' },
]

const ROLES = ['viewer', 'analyst', 'approver', 'admin'] as const

/** Validate the `?view=` parameter so a hand-edited URL cannot break the shell. */
function viewFromLocation(): ViewId {
  const requested = new URLSearchParams(window.location.search).get('view')
  return NAV.some((entry) => entry.id === requested) ? (requested as ViewId) : 'overview'
}

export default function App() {
  const booting = useWorkspace((s) => s.booting)
  const offline = useWorkspace((s) => s.offline)
  const meta = useWorkspace((s) => s.meta)
  const health = useWorkspace((s) => s.health)
  const documentId = useWorkspace((s) => s.documentId)
  const document = useWorkspace((s) => s.document)
  const transformation = useWorkspace((s) => s.transformation)

  // The view comes from the URL so a run link can be shared. Reading it during
  // the initial render avoids a second pass just to pick the starting view.
  const [view, setView] = useState<ViewId>(viewFromLocation)
  const [role, setRole] = useState<string>(getIdentity().role)

  useEffect(() => {
    void workspace.boot()
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => void workspace.refreshHealth(), 45_000)
    return () => window.clearInterval(timer)
  }, [])

  const go = (next: ViewId) => {
    setView(next)
    const url = new URL(window.location.href)
    url.searchParams.set('view', next)
    window.history.replaceState(null, '', url)
  }

  const changeRole = (next: string) => {
    setRole(next)
    setIdentity({ user: meta?.demo_actors[next] ?? getIdentity().user, role: next })
    void workspace.boot()
    toast.info(`Acting as ${humanise(next)}`)
  }

  const entry = NAV.find((item) => item.id === view) ?? NAV[0]
  const documentCount = useWorkspace((s) => s.documents.length)
  const artefactCount = transformation?.outputs.length ?? 0
  const counts: Partial<Record<ViewId, number>> = {
    sources: documentCount,
    studio: artefactCount,
  }

  const dbTone = health?.database === 'ok' ? 'ok' : 'danger'

  if (booting) {
    return (
      <div className="shell">
        <aside className="rail">
          <div className="rail-brand">
            <div className="rail-mark">OT</div>
            <div className="rail-brand-text">
              <h1>ODYSSEY</h1>
              <p>Transform Core</p>
            </div>
          </div>
        </aside>
        <main className="main">
          <Loading label="Negotiating secure link with transformation engine…" />
        </main>
      </div>
    )
  }

  return (
    <div className="shell">
      <aside className="rail">
        <div className="rail-brand">
          <div className="rail-mark">OT</div>
          <div className="rail-brand-text">
            <h1>ODYSSEY</h1>
            <p>Transform Core</p>
          </div>
        </div>

        <div className="rail-section">Workflow</div>
        <nav className="rail-nav">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item${view === item.id ? ' active' : ''}`}
              onClick={() => go(item.id)}
              title={item.blurb}
            >
              <span className="nav-step">{item.step}</span>
              <span className="nav-label">{item.label}</span>
              {counts[item.id] ? <span className="nav-badge">{counts[item.id]}</span> : null}
            </button>
          ))}
        </nav>

        <div className="rail-foot">
          <div className="rail-section">Runtime</div>
          <div className="rail-status">
            <span className={`dot ${offline ? 'danger' : dbTone}`} />
            Database {offline ? 'unreachable' : (health?.database ?? 'unknown')}
          </div>
          <div className="rail-status">
            <span className={`dot ${meta?.llm_configured ? 'ok' : 'warn'}`} />
            {meta?.llm_configured ? `LLM · ${meta.llm_model}` : 'Extractive mode (no LLM key)'}
          </div>
          <div className="rail-status">
            <span className="dot accent" />
            Pipeline v{meta?.pipeline_version ?? '—'}
          </div>
          <div className="divider" />
          <div className="label-inline">SIH26154</div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar-titles">
            <h2>{entry.label}</h2>
            <p>
              {entry.blurb}
              {document ? ` · Source: ${document.title}` : ''}
              {transformation ? ` · Run ${transformation.transformation_id}` : ''}
            </p>
          </div>

          {transformation && (
            <Badge tone="accent">
              {transformation.outputs.length} artefacts · v{transformation.pipeline_version}
            </Badge>
          )}
          {health?.audit_head && (
            <span className="label-inline mono" title="Audit chain head hash">
              head {shortHash(health.audit_head, 6)}
            </span>
          )}

          <div className="identity">
            <span className="label-inline nowrap">Role</span>
            <select
              className="select"
              value={role}
              onChange={(event) => changeRole(event.target.value)}
              aria-label="Acting role"
            >
              {ROLES.map((item) => (
                <option key={item} value={item}>
                  {humanise(item)}
                </option>
              ))}
            </select>
          </div>
        </header>

        <div className="view">
          {offline && (
            <div className="callout callout-danger" style={{ marginBottom: 16 }}>
              <span className="callout-icon">!!</span>
              <p>
                <strong>API unreachable.</strong> {offline} Start the backend with{' '}
                <code>uvicorn app.main:app --reload</code> in <code>backend/</code>, then reload.
              </p>
            </div>
          )}

          {view === 'overview' && (
            <OverviewView
              onOpenSources={() => go('sources')}
              onOpenRun={(id) => {
                void workspace.openTransformation(id)
                go('studio')
              }}
              onOpenStudio={() => go('studio')}
              onOpenAudit={() => go('audit')}
            />
          )}
          {view === 'sources' && <SourcesView onContinue={() => go('transform')} />}
          {view === 'transform' && (
            <TransformView
              onDone={() => go('studio')}
              hasDocument={Boolean(documentId)}
              onOpenSources={() => go('sources')}
            />
          )}
          {view === 'studio' && <StudioView onOpenAudit={() => go('audit')} onConfigure={() => go('transform')} />}
          {view === 'audit' && <AuditView />}
        </div>
      </main>

      <Toaster />
    </div>
  )
}
