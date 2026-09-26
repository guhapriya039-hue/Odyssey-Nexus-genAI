/**
 * Shared workspace store: capability metadata, source documents and the
 * currently open transformation.
 *
 * A module store (rather than nested contexts) keeps the whole dashboard
 * consistent — a document selected in Sources is immediately the subject of
 * the Transform view and the Provenance trail.
 */

import { useSyncExternalStore } from 'react'
import { api, setIdentity } from '../api/client'
import type {
  DocumentDetail,
  DocumentSummary,
  Health,
  Meta,
  Output,
  Transformation,
  TransformationSummary,
  TransformRequest,
} from '../api/types'
import { toast } from './toast'

export interface WorkspaceState {
  meta: Meta | null
  health: Health | null
  documents: DocumentSummary[]
  runs: TransformationSummary[]
  document: DocumentDetail | null
  documentId: string | null
  transformation: Transformation | null
  transformationId: string | null
  booting: boolean
  offline: string | null
}

let state: WorkspaceState = {
  meta: null,
  health: null,
  documents: [],
  runs: [],
  document: null,
  documentId: null,
  transformation: null,
  transformationId: null,
  booting: true,
  offline: null,
}

let listeners: Array<() => void> = []

function set(patch: Partial<WorkspaceState>): void {
  state = { ...state, ...patch }
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.push(listener)
  return () => {
    listeners = listeners.filter((candidate) => candidate !== listener)
  }
}

export function useWorkspace<T>(select: (value: WorkspaceState) => T): T {
  return useSyncExternalStore(
    subscribe,
    () => select(state),
    () => select(state),
  )
}

export const workspace = {
  get: (): WorkspaceState => state,

  async boot(): Promise<void> {
    set({ booting: true })
    try {
      const [meta, health, documents, runs] = await Promise.all([
        api.meta(),
        api.health(),
        api.documents(),
        api.transformations(),
      ])
      setIdentity({ user: meta.demo_actors.analyst ?? 'analyst@odyssey.team', role: 'analyst' })
      set({ meta, health, documents, runs, offline: null, booting: false })
    } catch (error) {
      set({ booting: false, offline: error instanceof Error ? error.message : String(error) })
    }
  },

  async refreshHealth(): Promise<void> {
    try {
      set({ health: await api.health(), offline: null })
    } catch (error) {
      set({ offline: error instanceof Error ? error.message : String(error) })
    }
  },

  async refreshDocuments(): Promise<DocumentSummary[]> {
    const documents = await api.documents()
    set({ documents })
    return documents
  },

  async refreshRuns(documentId?: string): Promise<void> {
    set({ runs: await api.transformations(documentId) })
  },

  async openDocument(publicId: string): Promise<DocumentDetail> {
    const document = await api.document(publicId)
    set({ document, documentId: publicId })
    return document
  },

  async closeDocument(): Promise<void> {
    set({ document: null, documentId: null })
  },

  async run(documentPublicId: string, payload: TransformRequest): Promise<Transformation> {
    const progress = toast.begin('Running transformation pipeline…')
    try {
      const transformation = await api.transform(documentPublicId, payload)
      await Promise.all([workspace.refreshDocuments(), workspace.refreshRuns(documentPublicId)])
      set({ transformation, transformationId: transformation.transformation_id })
      const produced = transformation.outputs.length
      if (transformation.status === 'failed' || transformation.status === 'blocked') {
        progress.fail(
          transformation.error ??
            `Pipeline ${transformation.status.replace(/_/g, ' ')}. Check the run detail.`,
        )
      } else {
        progress.done(
          `${produced} artefact${produced === 1 ? '' : 's'} generated in ${transformation.generation_mode} mode`,
        )
      }
      return transformation
    } catch (error) {
      progress.fail(error instanceof Error ? error.message : String(error))
      throw error
    }
  },

  async openTransformation(transformationId: string): Promise<void> {
    const transformation = await api.transformation(transformationId)
    set({ transformation, transformationId })
    if (transformation.document?.public_id && transformation.document.public_id !== state.documentId) {
      try {
        const document = await api.document(transformation.document.public_id)
        set({ document, documentId: document.public_id })
      } catch {
        /* the source may have been deleted; the run is still viewable */
      }
    }
  },

  closeTransformation(): void {
    set({ transformation: null, transformationId: null })
  },

  /** Replace one output in place after an edit, regenerate or review. */
  patchOutput(output: Output): void {
    if (!state.transformation) return
    const outputs = state.transformation.outputs.map((candidate) =>
      candidate.id === output.id ? output : candidate,
    )
    set({ transformation: { ...state.transformation, outputs } })
  },
}
