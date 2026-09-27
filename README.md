# ODYSSEY TRANSFORM CORE

**Transform Information. Preserve Trust. Accelerate Action.**

A source-grounded Generative AI platform that turns **one verified source** into **nine
consistent, audience-specific artefacts** — with cryptographic provenance, security
screening and human sign-off built into the pipeline rather than bolted on afterwards.

* Smart India Hackathon 2026 — Problem Statement **SIH26154**
* Team **ODYSSEY NEXUS** · Theme: Blockchain & Cybersecurity
* Runs with **zero API keys**: the default engine is a deterministic extractive
  pipeline that needs no network at all.

---

## The problem it solves

An organisation that publishes a threat advisory, a policy change or an incident notice has
to rewrite the same verified content for a dozen audiences — an executive summary, a public
advisory, a LinkedIn post, an infographic, a slide deck, a video script. Doing that by hand
is slow and inconsistent. Doing it with a generic LLM is fast but untrustworthy: it invents
figures, drops caveats, leaks personal data, and leaves no record of where a claim came from.

This platform takes the second path seriously. Every sentence it emits is checked against
retrieved source evidence, every number is traced to the document, every artefact is hashed,
and a human must approve before release.

## What makes it different

| Capability | How it works |
| --- | --- |
| **Source grounding** | Two independent signals per claim: semantic support against retrieved chunks, and a hard numeric check. A number absent from the source fails the claim regardless of how fluent the sentence reads. |
| **Honest gaps** | When the source does not say something, the artefact says `Not stated in source` instead of inventing it. |
| **Prompt-injection defence** | Uploaded content is treated as untrusted data: injection patterns are scored, offending lines are replaced with `[UNTRUSTED_INSTRUCTION_SUPPRESSED]`, and content is fenced before it ever reaches a model. |
| **PII redaction** | A rules engine finds national IDs, credentials, contact details and more, then redacts them before storage. `include_pii=false` is the default. |
| **Cryptographic provenance** | Source hash, per-output hash and a provenance manifest (model, prompt and pipeline versions) for every run. Editing an output changes its hash and voids approval. |
| **Tamper-evident audit** | Every action is appended to a SHA-256 hash chain. `/api/audit/verify` re-walks it; altering a historical row invalidates the chain. |
| **Human review gate** | Analysts draft, approvers sign off. An analyst cannot approve their own work — enforced server-side, not in the UI. |
| **Zero-key operation** | With no LLM configured, a deterministic extractive engine composes all nine formats from parsed knowledge. Same endpoints, same guarantees, no network. |
| **Multimodal intake** | Text, PDF, DOCX, PPTX, HTML, images (OCR) and URLs, plus optional audio transcription. |

## Architecture

```
                    ┌──────────────────────────────────────────┐
  browser  ────────▶│  FastAPI  ·  /api  ·  serves the SPA      │
                    └────────────────────┬─────────────────────┘
                                         │
     ┌───────────────┬───────────────────┼────────────────────┬──────────────────┐
     ▼               ▼                   ▼                    ▼                  ▼
  documents      security          knowledge +            generation         outputs
  intake         scan              retrieval              9 formats          review +
  (text/PDF/     (injection,       (facts, figures,       (extractive or    provenance
   DOCX/URL/     PII, redaction,   entities, evidence     LLM + guardrails)  + export
   OCR)          SSRF guard)       ranking)                                 + audit
     └───────────────┴───────────────────┴────────────────────┴──────────────────┘
                                         │
                            SQLite (default) · PostgreSQL-ready schema
```

The dashboard is a React + TypeScript SPA. In development Vite proxies `/api` to the
backend, so both halves keep the same origin shape they have in production, where FastAPI
serves the built bundle itself.

### Pipeline stages

1. **Ingest** — normalise whitespace, detect the media type, extract text, compute the
   source SHA-256, then scan, sanitise and chunk.
2. **Scan** — score prompt injection, detect and redact PII, assign a risk level.
   URL ingestion refuses private and loopback address space (SSRF guard).
3. **Understand** — split sentences on real boundaries, strip list numbering and heading
   noise, and pull out the subject, key facts, figures, entities and recommendations.
4. **Retrieve** — embed chunks and rank them against the requested audience and objective.
5. **Generate** — compose one artefact per requested format, with audience guidance, tone
   and character budgets applied.
6. **Validate** — the factuality gate scores each claim and reports unsupported ones,
   invented numbers and coverage.
7. **Record** — hash the outputs, write the provenance manifest, append to the audit chain.

## Quick start

### Docker (recommended)

```bash
docker compose up --build
```

Open <http://localhost:8000>. That is the whole product: API, dashboard and database. The
database lives in a named volume, so it survives a rebuild.

To add a local model:

```bash
docker compose --profile llm up --build
docker exec -it odyssey-ollama ollama pull llama3.1
```

Then set `LLM_ENABLED=true` and `LLM_BASE_URL=http://ollama:11434/v1` in
`docker-compose.yml` and restart.

### Render (free tier)

`render.yaml` is a blueprint: one free web service that builds the same Dockerfile, so the
public URL serves the dashboard and the API from one origin.

1. Push the repository, then open <https://dashboard.render.com/blueprint/new>.
2. Connect `guhapriya039-hue/Odyssey-Nexus-genAI` and apply the blueprint as-is.

The Free plan has 512 MB of RAM, 0.1 CPU, no persistent disk and a 15-minute idle
spin-down, so the blueprint does three things the Compose file does not: it puts the SQLite
ledger under `/tmp` (ephemeral — lost on every deploy, restart and spin-down), lowers
`MAX_UPLOAD_BYTES` to 10 MB, and leaves `LLM_ENABLED=false` so no model is downloaded into
512 MB. Everything else — the guardrails, the audit chain, the human review gate — runs
unchanged. Treat it as a demo URL, not as a system of record.

### Local development

Requires Python 3.11+ and Node 20.19+ (22.12+ recommended — Vite 8's floor).

```bash
# --- backend -------------------------------------------------------------
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows   (. .venv/bin/activate on macOS/Linux)
pip install -e ".[dev]"
uvicorn app.main:app --reload

# --- frontend (second terminal) -----------------------------------------
cd frontend
npm install
npm run dev                       # http://localhost:5173, proxies /api to :8000
```

Every setting has a working default, so that is enough to run. To use a `.env` file, copy
the annotated template and pass it to Uvicorn, which loads it via `python-dotenv`
(installed by the `dev` extra):

```bash
cp .env.example .env              # Windows: copy .env.example .env
uvicorn app.main:app --reload --env-file .env
```

To serve the dashboard from the backend on a single port, build the frontend first
(`npm run build`); `app/main.py` mounts `frontend/dist` automatically when it exists. With
the bundle present, `/` serves the dashboard and the service banner moves to `/api/info`.

### Verify the install

```bash
cd backend
python -m pytest tests             # 73 unit and API tests
python -m ruff check app tests scripts
python scripts/smoke_e2e.py        # 115 end-to-end checks; starts its own server
python scripts/validate_image.py   # 76 image-contract checks; needs no container runtime
```

`smoke_e2e.py` boots Uvicorn on port 8123 against a throwaway SQLite database, walks the
same endpoint sequence the dashboard uses, and tears everything down — it never touches
your development data. Pass `--external` to point it at an instance you already started,
for example the one Compose brings up:

```bash
python scripts/smoke_e2e.py --external --base http://127.0.0.1:8000
```

`validate_image.py` is the part of the Docker review that does not need a runtime: it
verifies that every `COPY` source exists, that the image's paths agree with what the
application resolves at startup, that `requirements.txt` matches `pyproject.toml`, and that
Compose's environment is understood by `Settings`. It complements `docker build`, and does
not replace it.

## Configuration

Every setting is an environment variable with a working default; the platform runs with no
configuration at all. See `backend/.env.example` for the annotated list.

### Storage

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./odyssey.db` | SQLAlchemy URL. PostgreSQL: `postgresql+psycopg://user:pass@host/db`. |
| `UPLOAD_DIR` | `./storage/uploads` | Where uploaded originals are written. |
| `MAX_UPLOAD_BYTES` | `41943040` | Upload ceiling (40 MB). |
| `RETENTION_DAYS` | `90` | Retention window for stored sources. |
| `CORS_ORIGINS` | localhost dev origins | Comma-separated allowed dashboard origins. Only needs changing if the dashboard is on a different origin from the API. |

### Optional LLM

Leave these unset for the deterministic extractive engine.

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_ENABLED` | `true` | Master switch; the engine is used only when a base URL **and** model are set. |
| `LLM_BASE_URL` | *(empty)* | Any OpenAI-compatible endpoint. |
| `LLM_API_KEY` | *(empty)* | Bearer token, if the endpoint needs one. |
| `LLM_MODEL` | *(empty)* | Primary model. |
| `LLM_FALLBACK_MODELS` | *(empty)* | Comma-separated fallbacks tried in order. |
| `LLM_TEMPERATURE` | `0.2` | Low by design: consistency over creativity. |
| `LLM_MAX_OUTPUT_TOKENS` | `1400` | Per-artefact ceiling. |
| `LLM_TIMEOUT_SECONDS` | `60` | Per-request timeout. |
| `LLM_MAX_RETRIES` | `3` | Retries before falling back to extraction. |

### Guardrails

| Variable | Default | Purpose |
| --- | --- | --- |
| `GROUNDING_MIN_SCORE` | `0.55` | Support a claim needs to count as grounded. |
| `NUMERIC_GROUNDING` | `true` | Reject any number absent from the source. Leave on. |
| `PII_REDACTION` | `true` | Redact detected identifiers before storage. |
| `INJECTION_BLOCK_THRESHOLD` | `0.45` | Score at which content is treated as instruction-like. |
| `ALLOW_PRIVATE_NETWORK_FETCH` | `false` | **Keep false** in any shared deployment (SSRF guard). |
| `ALLOW_WEB_INGESTION` | `true` | Allow URL ingestion. |
| `RETRIEVAL_TOP_K` | `6` | Evidence chunks per artefact. |
| `CHUNK_TARGET_CHARS` | `1100` | Chunk size, with 180 characters of overlap. |
| `EMBEDDING_PROVIDER` | `auto` | `auto`, `local` (sentence-transformers), `st`, or `api`. Falls back to a local hashed-n-gram embedder so the platform never hard-depends on a model download. |

## API

Interactive docs at `/docs`, ReDoc at `/redoc`, OpenAPI at `/openapi.json`.

### Identity

Every request carries the acting user and role:

```
X-Odyssey-User: analyst@odyssey.team
X-Odyssey-Role: analyst
```

| Role | May do |
| --- | --- |
| `viewer` | Read documents, outputs and the audit trail. |
| `analyst` | Ingest, transform, edit, regenerate. Cannot approve or delete. |
| `approver` | Everything an analyst can, plus approve or reject. |
| `admin` | Everything, including document deletion. |

A missing user falls back to the demo actor for the declared role; a missing role defaults to
`analyst`, and an unrecognised role is rejected with `400`.

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness, database status, pipeline version. |
| `GET` | `/api/info` | Service banner: team, problem statement, whether the dashboard is bundled. |
| `GET` | `/api/meta` | Formats, audiences, tones, objectives, languages, demo actors. |
| `GET` | `/api/config` | Effective configuration and capability flags. |
| `GET` | `/api/stats` | Dashboard counters. |
| `POST` | `/api/security/scan` | Scan text without storing it. |
| `POST` | `/api/documents/preview` | Scan and summarise before committing. |
| `POST` | `/api/documents/text` | Ingest pasted text. |
| `POST` | `/api/documents/upload` | Ingest a file (multipart). |
| `POST` | `/api/documents/url` | Ingest a URL, with the SSRF guard applied. |
| `GET` | `/api/documents` | List sources. |
| `GET` | `/api/documents/{public_id}` | Source detail and preview. |
| `GET` | `/api/documents/{public_id}/knowledge` | Extracted subject, facts, figures, entities. |
| `DELETE` | `/api/documents/{public_id}` | Delete a source (admin). |
| `POST` | `/api/transformations/document/{public_id}` | Run a transformation over a source. |
| `GET` | `/api/transformations` | List runs, optionally filtered by `document_id`. |
| `GET` | `/api/transformations/{transformation_id}` | Run detail with all artefacts. |
| `GET` | `/api/transformations/{transformation_id}/outputs` | Artefacts for a run. |
| `GET` | `/api/transformations/{transformation_id}/provenance` | Provenance manifest. |
| `GET` | `/api/transformations/{transformation_id}/compare` | Cross-format figure consistency. |
| `GET` | `/api/outputs/{output_id}` | Artefact detail. |
| `PUT` | `/api/outputs/{output_id}` | Edit an artefact; rehashes and resets approval. |
| `POST` | `/api/outputs/{output_id}/regenerate` | Rebuild from the source. |
| `POST` | `/api/outputs/{output_id}/review` | Approve or reject. |
| `POST` | `/api/outputs/{output_id}/verify` | Re-verify against the source. |
| `GET` | `/api/outputs/{output_id}/export` | Markdown export with a provenance footer. |
| `GET` | `/api/audit` | Audit events, optionally scoped by `transformation_id`. |
| `GET` | `/api/audit/chain` | Chain status. |
| `GET` | `/api/audit/verify` | Re-walk the chain and report validity. |

### Example

```bash
curl -X POST http://localhost:8000/api/documents/text \
  -H 'Content-Type: application/json' \
  -H 'X-Odyssey-User: analyst@odyssey.team' \
  -H 'X-Odyssey-Role: analyst' \
  -d '{"title":"Meridian Q1 Threat Intel","text":"..."}'

curl -X POST http://localhost:8000/api/transformations/document/DOC-XXXXXXXX \
  -H 'Content-Type: application/json' \
  -H 'X-Odyssey-User: analyst@odyssey.team' \
  -H 'X-Odyssey-Role: analyst' \
  -d '{"formats":["executive_summary","linkedin","infographic"],
       "audience":"executive","tone":"neutral","objective":"inform",
       "detail":"balanced","include_pii":false,"auto_approve":false}'
```

## The nine formats

| Format | Media | Notes |
| --- | --- | --- |
| `executive_summary` | document | Impact and decisions first, jargon expanded. |
| `advisory` | document | Structured, sectioned, action-oriented. |
| `linkedin` | social | Within a professional-post character budget. |
| `x_post` | social | Hard character budget; the most compressed. |
| `infographic` | visual | Panels. A statistic is printed only when it appears in the source, otherwise `Not stated in source`. |
| `presentation` | slides | One idea per slide, with a title slide. |
| `video_script` | video | Timed scenes with narration and on-screen text. |
| `storyboard` | visual | Numbered frames with shot types and a takeaway card. |
| `narration_subtitles` | video | Timed subtitle cues. |

Six audiences (executive, technical, operations, security analyst, media/public, partner),
six tones, seven objectives, three detail levels and fifteen languages shape the output.
Audience guidance is explicit, so a `media_public` artefact drops raw indicators while a
`security_analyst` one keeps them.

## How grounding is judged

This is the part worth understanding, because it is where a source-grounded platform is
either real or a wrapper.

1. **Claims are extracted from the artefact, not from the layout.** A line is reduced to its
   assertion: bracketed scene tags (`[Frame 2 | Wide shot | …]`), field labels (`Body:`,
   `Narration:`, `Stat:`) and clip markers are stripped, while the content behind them is
   kept. Production metadata such as `Total narration: approximately 87 seconds` is not a
   claim about the subject and is not scored as one.
2. **Numeric grounding is absolute.** Every number in a claim is normalised and looked up in
   the source evidence. A missing number fails the claim outright — no amount of fluency
   rescues it. This is checked independently of meaning, which is why a fluent, well-written
   fabrication still scores zero.
3. **Semantic support is scored, and verbatim text wins.** Each claim is embedded and
   compared against the retrieved chunks, blended with token overlap. If every content word
   of a claim appears in a single chunk, it counts as fully supported — otherwise formats
   that clip lines to a character budget would be punished for the clipping.
4. **Explicit gaps are honoured.** `Not stated in source` is treated as a truthful signal,
   not a failure, and rewards the model for admitting a gap.
5. **Statistics are verified on the numeric signal.** A `Stat:` line asserts a figure and
   nothing else, so it is checked against the source's numbers directly. An invented
   headline figure is reported exactly like an invented number in prose.

The result is a per-output `grounding_score`, a `verdict`
(`grounded`, `partially_grounded`, `weakly_grounded`, `ungrounded`, `numeric_drift`), the
list of unsupported claims with reasons, and any invented numbers — all surfaced in the
dashboard's evidence panel.

## Security model

| Layer | Control |
| --- | --- |
| **Untrusted input** | Injection scoring, `[UNTRUSTED_INSTRUCTION_SUPPRESSED]` substitution, and `<<SOURCE>>` fencing so a document is data, never instructions. |
| **Data minimisation** | PII detection and redaction before storage; `include_pii` is opt-in; retention window is configurable. |
| **Network** | URL ingestion blocks loopback, link-local and private ranges, and resolves DNS before fetching to close rebinding gaps. |
| **Authorisation** | Role checks on every write, approval and delete; separation of duties between analyst and approver. |
| **Integrity** | SHA-256 over sources, artefacts and a chained audit ledger; `verify` re-walks the chain. |
| **Disclosure** | Markdown export carries a provenance footer; partner and public audiences are shaped to avoid leaking internal detail. |

### Honest limitations

* Identity is header-based demo auth. It demonstrates the authorisation model and RBAC
  enforcement but is not a substitute for real authentication — put it behind an identity
  proxy before exposing it to a network.
* The SQLite default is right for a prototype and a single-node demo. The schema is
  PostgreSQL-ready, but the deployment has not been load-tested at scale. Because SQLite
  writes to local disk, a deployment must attach a persistent volume at `/srv/app/data`; on an
  ephemeral filesystem the ledger and every uploaded source are lost on each deploy. It also
  means exactly one writer — running more than one replica against the same database is not a
  supported configuration.
* The local hashed-n-gram embedder is a deterministic fallback, not a semantic model. It
  keeps the platform dependency-free; set `EMBEDDING_PROVIDER=local` with
  `sentence-transformers` installed for noticeably better retrieval on large corpora.
* `Stat:` panels deliberately print `Not stated in source` over a guessed figure. That is
  the intended behaviour, not a bug.

## Project layout

```
.
├── docker-compose.yml         # one-command deployment
├── Dockerfile                 # multi-stage: builds the SPA, serves it from FastAPI
├── backend/
│   ├── app/
│   │   ├── main.py            # app factory, CORS, static SPA mount
│   │   ├── config.py          # environment-driven settings
│   │   ├── models.py          # Document, Chunk, Knowledge, Transformation, Output, AuditEvent
│   │   ├── schemas.py         # request/response contracts
│   │   ├── rbac.py            # role resolution and permission checks
│   │   ├── constants.py       # formats, audiences, tones, objectives, roles
│   │   ├── routers/           # system, documents, transformations, outputs, audit
│   │   └── services/
│   │       ├── ingestion.py   # text, PDF, DOCX, PPTX, HTML, image OCR, URL, audio
│   │       ├── security.py    # injection, PII, redaction, SSRF, risk
│   │       ├── textutils.py   # sentence splitting, headings, numbers
│   │       ├── chunking.py    # heading-aware segmentation with overlap
│   │       ├── knowledge.py   # subject, facts, figures, entities, recommendations
│   │       ├── embeddings.py  # provider abstraction with local fallback
│   │       ├── retrieval.py   # hybrid vector + keyword ranking
│   │       ├── generation.py  # the nine composers
│   │       ├── factuality.py  # claim extraction, grounding, numeric drift
│   │       ├── provenance.py  # hashing, manifests, audit chain
│   │       ├── pipeline.py    # stage orchestration
│   │       ├── llm.py         # optional LLM client with fallback
│   │       └── prompts.py     # grounded prompt construction
│   ├── scripts/
│   │   ├── smoke_e2e.py        # self-contained end-to-end harness
│   │   └── validate_image.py   # static Dockerfile/compose contract checks
│   ├── tests/                  # 73 tests
│   └── .env.example
└── frontend/
    └── src/
        ├── api/               # typed client and models
        ├── state/             # workspace store, toasts
        ├── components/        # shared UI primitives
        ├── views/             # overview, sources, transform, studio, audit
        └── App.tsx            # shell, navigation, identity switcher
```

## Design decisions worth defending

**Why a deterministic engine by default.** A demo that needs an API key cannot be verified
by a judge on a plane. The extractive path makes every guarantee in this README testable
offline, and the LLM path is an accelerator rather than a dependency.

**Why the factuality gate scores the claim, not the document.** A cosine similarity over a
whole artefact is dominated by boilerplate — a footer can make an unsupported claim look
supported. Scoring line by line, after stripping layout, is what makes the number
meaningful.

**Why editing voids approval.** If a human changes the text, the hash changes, and the
signature that approved the old text no longer applies. The pipeline enforces this rather
than trusting the UI to remember.

**Why the audit chain is a chain.** A per-row hash only proves a row was not edited in
isolation. Chaining each entry to the hash of its predecessor means any change to history
invalidates everything after it, which is the property an auditor actually needs.

## Licence

Built for Smart India Hackathon 2026 by Team ODYSSEY NEXUS.
