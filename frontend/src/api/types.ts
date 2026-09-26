/**
 * TypeScript mirrors of the FastAPI schemas in `backend/app/schemas.py`.
 * Kept hand-written (no codegen) so the dashboard stays dependency-light;
 * the test suite on the backend is the contract guard.
 */

export type Role = 'viewer' | 'analyst' | 'approver' | 'admin'

export type ReviewState = 'draft' | 'pending_review' | 'approved' | 'rejected'

export type RiskLevel = 'none' | 'low' | 'medium' | 'high' | 'critical'

export type TransformationStatus =
  | 'queued'
  | 'analysing'
  | 'generating'
  | 'validating'
  | 'completed'
  | 'completed_with_warnings'
  | 'blocked'
  | 'failed'

export interface Capability {
  id: string
  label: string
  media: string
}

export interface Meta {
  app_name: string
  version: string
  pipeline_version: string
  prompt_version: string
  environment: string
  llm_configured: boolean
  llm_model: string | null
  llm_model_chain: string[]
  embedding_provider: string
  ocr_enabled: boolean
  speech_to_text_enabled: boolean
  web_ingestion_enabled: boolean
  generation_modes: string[]
  formats: Capability[]
  tones: Capability[]
  audiences: Capability[]
  objectives: Capability[]
  details: Capability[]
  languages: Record<string, string>
  demo_actors: Record<string, string>
}

export interface Health {
  status: string
  version: string
  environment: string
  database: string
  llm: string
  documents: number
  transformations: number
  audit_head: string | null
  server_time: string
}

export interface SystemConfig {
  [key: string]: unknown
}

export interface Stats {
  documents: number
  outputs: number
  audit_events: number
  avg_grounding_score: number
  status_breakdown: Record<string, number>
  completed: number
}

export interface SecurityFinding {
  category: string
  label: string
  severity: string
  evidence: string
  position: number
  redacted_value: string | null
}

export interface SecurityReport {
  injection_score: number
  injection_patterns: string[]
  pii_findings: SecurityFinding[]
  pii_count: number
  risk_level: string
  redactions_applied: number
  sanitised_text: string | null
  recommendations: string[]
}

export interface KeyFact {
  category: string
  text: string
  score?: number
  ordinal?: number
}

export interface Entity {
  name: string
  kind: string
  mentions?: number
  evidence?: string
}

export interface DocumentSummary {
  id: number
  public_id: string
  title: string
  filename: string
  media_type: string
  source_kind: string
  status: string
  status_detail: string | null
  byte_size: number
  file_hash: string
  text_hash: string | null
  char_count: number
  word_count: number
  chunk_count: number
  redaction_count: number
  injection_score: number
  risk_level: string
  pii_types: string[]
  meta: Record<string, unknown>
  created_by: string
  created_at: string
  indexed_at: string | null
}

export interface DocumentDetail extends DocumentSummary {
  preview: string
  security: SecurityReport | null
  topics: string[]
  key_facts: KeyFact[]
  entities: Entity[]
}

export interface Knowledge {
  summary: string
  subject: string
  topics: string[]
  key_facts: KeyFact[]
  entities: Entity[]
  indicators: string[]
  dates: string[]
  figures: string[]
  detected_objective: string
  reading_level: string
  build_mode: string
}

export interface EvidenceItem {
  chunk_id: number
  ordinal: number
  heading: string | null
  score: number
  quote: string
}

export interface Output {
  id: number
  format: string
  title: string
  body: string
  edited_body: string | null
  section_map: Array<Record<string, unknown>>
  output_hash: string
  char_count: number
  evidence: EvidenceItem[]
  grounding_score: number
  factuality: Record<string, unknown>
  security: Record<string, unknown>
  validation: Record<string, unknown>
  review_state: ReviewState
  reviewed_by: string | null
  review_note: string | null
  reviewed_at: string | null
  version: number
  created_at: string
}

export interface LlmAttempt {
  model?: string
  error?: string
  [key: string]: unknown
}

export interface Transformation {
  id: number
  transformation_id: string
  document_id: number
  status: TransformationStatus
  stage: string
  error: string | null
  requested_formats: string[]
  config: Record<string, unknown>
  source_hash: string
  model_version: string
  prompt_version: string
  pipeline_version: string
  generation_mode: string
  llm_attempts: LlmAttempt[]
  duration_ms: number
  warnings: string[]
  requested_by: string
  created_at: string
  completed_at: string | null
  document: DocumentSummary | null
  outputs: Output[]
}

export interface TransformationSummary {
  transformation_id: string
  document_id: string
  document_title: string | null
  status: TransformationStatus
  requested_formats: string[]
  generation_mode: string
  model_version: string
  duration_ms: number
  warnings: string[]
  output_count: number
  avg_grounding: number
  created_at: string
  requested_by: string
}

export interface AuditEvent {
  seq: number
  action: string
  actor: string
  actor_role: string
  document_id: string | null
  transformation_id: string | null
  summary: string
  detail: Record<string, unknown>
  prev_hash: string
  entry_hash: string
  verified: boolean
  created_at: string
}

export interface ChainVerification {
  valid: boolean
  length: number
  head_hash: string
  broken_at_seq: number | null
  message: string
}

export interface Provenance {
  transformation_id: string
  source_hash: string
  source_hash_algorithm: string
  outputs: Array<Record<string, unknown>>
  model_version: string
  prompt_version: string
  pipeline_version: string
  created_at: string
  manifest_hash: string
  manifest: Record<string, unknown>
}

export interface Comparison {
  transformation_id: string
  formats: string[]
  char_counts: Record<string, number>
  grounding_scores: Record<string, number>
  hashes: Record<string, string>
  shared_figures: string[]
  format_specific_figures: Record<string, string[]>
  consistency_note: string
}

export interface TransformRequest {
  formats: string[]
  audience: string
  tone: string
  language: string
  objective: string
  detail: string
  user_instruction: string
  include_pii: boolean
  auto_approve: boolean
}
