# Synth Veda Phase Plan

This document is the execution roadmap for turning the current prototype into
Synth Veda: a backend-first eDNA biodiversity analysis platform with online
full analysis, offline Synth Veda Abyss Mode, human-in-the-loop learning, and a
fast sequence-processing core.

The order is intentional:

1. Clean and stabilize the repository.
2. Build the backend, data model, auth, and hosting foundation.
3. Build the fast parser and AI routing pipeline.
4. Build curation and monthly training workflows.
5. Build the frontend after the backend contracts are real.

The final success state is:

```text
User uploads FASTA or JSON
-> FASTA is converted to structured JSONL batches
-> backend analyzes sequences through routed specialist DNA models
-> biodiversity results are shown
-> novelty/contamination/low-quality signals are explained
-> expert/admin review can correct results
-> curated corrections enter monthly training batches
```

---

## Product Identity

Project name: **Synth Veda**

Offline mode name: **Synth Veda Abyss Mode**

Core product promise:

```text
Fast eDNA biodiversity triage in remote field conditions, followed by deeper
online reanalysis when full compute and connectivity are available.
```

Abyss Mode must be described as field triage, not final scientific
confirmation. It helps researchers decide whether to continue sampling,
preserve samples, resample, or return for full analysis.

---

## Target Architecture

```text
apps/
  web/                         React/Vite frontend

services/
  api/                         FastAPI backend
  worker/                      background analysis worker

packages/
  fastx_parser/                Rust FASTA/FASTQ parser and batcher
  edna_core/                   shared Python domain logic
  model_router/                routing, QC, novelty scoring

models/
  registry/                    model metadata only, not large binaries

data/
  samples/                     small local sample fixtures only
  manifests/                   dataset manifests, checksums, source notes

infra/
  docker/                      local Docker Compose and service Dockerfiles
  deployment/                  cloud deploy notes/scripts

docs/
  architecture/
  api/
  ml/
  security/
```

Current repo does not need to be fully reorganized on day one. First build the
new backend contracts, then move files into the new layout.

---

## Phase 0: Repository Weight Reset

### Goal

Reduce the repo from a large prototype folder into a clean development base.
The current folder size is mostly local environments, Node dependencies, Git
history, and model binaries.

### Why

Large repos slow down everything: search, Git, backup, deployment, onboarding,
and experimentation. It also hides the real code structure.

### What To Remove Locally

These are generated or restorable and should not live in the project folder:

```powershell
Remove-Item -Recurse -Force .\gpu_env, .\venv, .\node_modules, .\web_frontend\node_modules, .\backup_frontend, .\.pytest_cache, .\__pycache__ -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
```

Review and remove if not needed:

```text
src/web_api/models.py.bak
train_output.txt
nt_load_error.txt
sample_as_json.json
root package.json and package-lock.json if only web_frontend is used
old Vite/React starter assets
```

### Model Artifact Decision

The repo currently tracks large model files. Do not keep production model
binaries in Git.

Move model artifacts to one of:

```text
Hugging Face Hub private model repos
S3/GCS object storage
Git LFS only if the repo workflow truly needs it
local artifact folder ignored by Git
```

Keep only:

```text
model registry metadata
checksums
download instructions
small test fixtures
```

### Git History Problem

Deleting model files from the working tree will not shrink `.git`. The `.git`
folder is already large because big files exist in history.

Choices:

1. Start a fresh clean `synth-veda` repo and copy only wanted source files.
2. Rewrite history later with a tool like `git filter-repo`.

Recommendation: create a fresh repo once the new structure is ready. It is
cleaner and safer for a project that is changing identity.

### Done Criteria

- Local folder size drops substantially.
- Only source, docs, configs, small fixtures, and manifests remain.
- `.env` stays ignored.
- Model binaries are no longer treated as normal source files.

---

## Phase 1: Backend Foundation

### Goal

Build the real backend contract before changing the frontend. The backend
should become the source of truth for uploads, analysis jobs, model status,
review workflows, and user permissions.

### Why

The current frontend has mock/demo behavior and calls routes that do not exist.
If the frontend is built first, it will keep inventing fake contracts. Build
the backend first, then make the UI consume it.

### Technology

```text
FastAPI
Python 3.11+
Pydantic v2
Uvicorn/Gunicorn for API serving
Docker for reproducible local/dev deployment
```

### Core Backend Modules

```text
services/api/app/main.py
services/api/app/config.py
services/api/app/auth/
services/api/app/uploads/
services/api/app/analysis/
services/api/app/models/
services/api/app/reviews/
services/api/app/reports/
services/api/app/abyss/
services/api/app/db/
```

### Core API Endpoints

```text
GET  /health
GET  /version

POST /auth/google/exchange
POST /auth/admin-key/redeem
GET  /auth/me

POST /uploads
GET  /uploads/{upload_id}

POST /analysis/jobs
GET  /analysis/jobs/{job_id}
GET  /analysis/{analysis_id}
GET  /analysis/{analysis_id}/report

GET  /models/status
GET  /models/registry

POST /reviews
GET  /reviews/queue
POST /reviews/{review_id}/decision

POST /abyss/expeditions
POST /abyss/sync
GET  /abyss/expeditions/{id}
```

### Analysis Job Contract

Do not make `/analyze` a slow blocking endpoint long term. Use a job model:

```text
upload file
-> create analysis job
-> worker processes job
-> frontend polls or subscribes to job status
-> results appear when ready
```

Basic job states:

```text
queued
parsing
qc
routing
inferencing
novelty_scoring
reporting
completed
failed
needs_review
```

### How To Implement

1. Create a new backend package structure.
2. Add typed settings from environment variables.
3. Add API response models before frontend work.
4. Add job records in MongoDB.
5. Add placeholders for parser/model workers.
6. Add tests for every endpoint contract.

### Done Criteria

- Backend starts locally with one command.
- `/health`, `/version`, `/auth/me`, `/models/status` work.
- Upload/job lifecycle works with mock analysis output.
- Tests cover the API contracts.
- No frontend is needed to verify backend behavior.

---

## Phase 2: Database Architecture

### Goal

Use the right database for the right type of data:

```text
MongoDB = raw/flexible analysis documents
Supabase Postgres = structured auth roles, review, curation, training batches
Object storage = files and large artifacts
```

### Why

eDNA results are nested and variable, so MongoDB is useful for raw analysis.
Human review, admin keys, monthly training, audit logs, and model versions need
relational integrity, so Postgres/Supabase is better.

### MongoDB Collections

```text
uploads
analysis_jobs
analysis_results
sequence_batches
abyss_expedition_logs
raw_model_outputs
reports
```

Example analysis result:

```json
{
  "analysis_id": "ana_...",
  "upload_id": "upl_...",
  "mode": "online_full",
  "model_version_set": "2026-05",
  "summary": {
    "known_species": 12,
    "possible_novelty": 2,
    "contamination_flags": 1
  },
  "routes": {
    "fish": 400,
    "plant": 80,
    "bacteria": 1200,
    "human_domestic": 14,
    "misc_unknown": 30
  },
  "results": []
}
```

### Supabase/Postgres Tables

```text
user_profiles
admin_invite_keys
role_assignments
expert_reviews
review_evidence
curation_decisions
curated_sequences
training_batches
training_batch_items
model_versions
model_eval_metrics
audit_logs
```

### Admin Invite Key Rules

Admin/contributor access requires:

```text
Google account + company-issued 8-character alphanumeric key
```

Rules:

```text
keys are random
keys are stored hashed, never plaintext
keys are one-time use or limited-use
keys expire
failed attempts are rate-limited
redeemed keys bind to a Google account
every admin action is audited
```

### Supabase Security Notes

Use Row Level Security on exposed tables. Do not use user-editable metadata for
authorization decisions. Store roles in controlled server-managed tables or app
metadata, and keep service-role credentials out of frontend code.

### How To Implement

1. Create MongoDB connection layer.
2. Create Supabase/Postgres schema migrations.
3. Add RLS policies after roles are defined.
4. Add audit logging for every privileged mutation.
5. Create seed scripts for local development.

### Done Criteria

- Mongo stores uploads/jobs/results.
- Supabase stores users, roles, reviews, curation, and training metadata.
- Admin key redemption works.
- No admin-only write path is exposed to normal users.
- DB schema is documented and migration-based.

---

## Phase 3: Auth And Roles

### Goal

Use Google OAuth for normal online login, plus company-issued keys for expert,
curator, and admin access.

### Why

Anyone can sign in, but not everyone should be allowed to influence scientific
curation or model learning.

### Roles

```text
viewer
researcher
expert_contributor
curator
admin
company_owner
expedition_operator
```

### Permissions

```text
viewer:
  view own analyses

researcher:
  upload samples
  submit basic feedback

expert_contributor:
  submit corrections and evidence
  comment on novelty flags

curator:
  approve/reject suggestions
  mark novelty as accepted/rejected/needs evidence

admin:
  issue/revoke invite keys
  manage model releases
  manage monthly training batches

expedition_operator:
  create/use Abyss Mode expedition sessions
```

### Online Auth Flow

```text
custom Synth Veda login page
-> Continue with Google
-> backend verifies OAuth/session
-> backend creates/reads user profile
-> frontend receives app session
```

Supabase can support Google social login. Confirm exact setup against current
Supabase docs before implementation because auth provider setup changes over
time.

### Abyss Mode Offline Auth Flow

Google OAuth cannot work underwater/offline. Abyss Mode needs a pre-authorized
offline expedition session.

```text
before voyage:
  user logs in online
  company/admin creates expedition
  app downloads offline license/session
  app downloads model pack and reference pack

underwater:
  local PIN/device unlock
  expedition session validates offline
  all actions are locally logged

after voyage:
  reconnect
  sync logs, samples, notes, and decisions
  cloud reanalysis runs
```

### Done Criteria

- Google login works in online app.
- Admin/contributor key redemption works.
- Role-protected endpoints reject unauthorized users.
- Abyss Mode has a planned offline auth format and sync path.

---

## Phase 4: Hosting And Runtime Strategy

### Goal

Choose a deployment path that works for MVP without pretending to be scaled
before funding.

### Why

The project needs to run reliably for demos, testing, and early users. It does
not need expensive large-scale infrastructure yet.

### Recommended MVP Hosting

```text
Frontend:
  Vercel

Backend API:
  Google Cloud Run or similar container host

Worker:
  same platform as backend at first

MongoDB:
  MongoDB Atlas or local dev Mongo

Structured DB/Auth:
  Supabase Postgres/Auth

Model artifacts:
  Hugging Face Hub private repos or object storage

Training:
  local RTX 3070 for small runs
  Google Colab for larger fine-tuning
```

Vercel environment variables apply per deployment and need redeployment after
changes. Cloud Run is container-based and supports autoscaling behavior for
stateless services. Hugging Face Spaces is best treated as a model/demo host,
not the core production API. Verify current pricing, GPU availability, and
limits before committing to a paid plan.

### Local Dev Stack

Use Docker Compose:

```text
api
worker
mongo
redis or simple local queue
```

Supabase can be managed cloud during MVP, or local Supabase can be added later
when schema development needs it.

### Why Not Host Everything On One Platform

The system has different workloads:

```text
frontend = static web app
api = request/response
worker = long-running jobs
models = heavy compute/artifacts
databases = managed storage
```

Keeping them separate avoids forcing one platform to do everything badly.

### Done Criteria

- Local Docker stack starts.
- Backend can be deployed as a container.
- Frontend can be deployed separately.
- Environment variables are documented.
- No secrets are committed.

---

## Phase 5: Fast FASTA/JSON Parser And Batching Engine

### Goal

Build Synth Veda's speed advantage: a Rust parser and batching engine for FASTA
and FASTQ-like input.

### Why

Fast analysis starts before AI. If parsing is slow, memory-heavy, or blocking,
the model pipeline will never feel fast. Abyss Mode also needs lightweight
offline processing.

### Language Decision

Use Rust for:

```text
FASTA/FASTQ parsing
sequence chunking
batch generation
QC metrics
k-mer/minimizer signatures
deduplication
optional compressed binary index
```

Use Python for:

```text
API orchestration
ML model calls
training scripts
report generation
database workflows
```

Do not add Go unless a later service specifically needs it. Do not use C++
unless a required existing bioinformatics library forces that decision.

### Parser Output

Internal JSONL batch format:

```json
{
  "batch_id": "bat_001",
  "sequence_id": "seq_001",
  "sequence": "ATCG...",
  "length": 420,
  "gc_ratio": 0.47,
  "n_ratio": 0.01,
  "sha256": "...",
  "source_file": "sample.fasta"
}
```

### Roll-Number Analogy Applied Correctly

Your roll-number idea is useful as a routing concept:

```text
roll number:
  college prefix -> stream -> student id

DNA sequence:
  cheap sequence features -> likely taxonomic route -> specialist model
```

Important limitation:

DNA does not have a fixed prefix that safely means "fish" or "plant". We should
not sort by first bases alone. Instead we compute cheap features:

```text
k-mer counts
minimizer sketches
GC ratio
length distribution
marker hints
reference pre-hit
low-quality flags
contamination hints
```

Then we route.

### Implementation Path

1. Build Rust CLI:

```text
synthveda-parse input.fasta --out batches.jsonl
```

2. Add parser benchmark:

```text
Python Bio.SeqIO baseline
Rust parser
Rust parser with parallel batching
```

3. Add QC:

```text
length
GC ratio
N ratio
invalid characters
duplicate hash
sequence count
```

4. Add batch modes:

```text
fixed sequence count
fixed total bases
route-aware batches
offline low-memory batches
```

5. Expose to Python later through PyO3/maturin.

### Done Criteria

- Rust parser can parse sample FASTA into JSONL.
- Benchmark report exists.
- Parser supports low-memory streaming.
- Backend can call parser and ingest batches.

---

## Phase 6: Taxonomic Router

### Goal

Build a fast router that sends sequence batches to the right specialist model:
fish, plants, bacteria, animals, human/domestic contamination, or misc unknown.

### Why

One model for all species is tedious, expensive, and likely weaker. Routing
makes the system faster and more explainable.

### Routes

```text
fish
plant
bacteria_pathogen
animal_general
human_domestic_contamination
misc_unknown
low_quality
```

Animal route can later split into:

```text
mammal
reptile
turtle_tortoise
bird
marine_invertebrate
```

### Router Inputs

```text
parser QC output
k-mer/minimizer signature
reference pre-hit result
sequence length
marker hints
previous sample context
geography/depth metadata when available
```

### Router Output

```json
{
  "sequence_id": "seq_001",
  "route": "fish",
  "route_confidence": 0.81,
  "fallback_routes": ["animal_general", "misc_unknown"],
  "reason_codes": ["kmer_fish_like", "length_marker_compatible"]
}
```

### Loophole Control

If the router is uncertain, do not force one model. Use fallback:

```text
route_confidence high:
  specialist model only

route_confidence medium:
  specialist + fallback

route_confidence low:
  general/misc model + reference search
```

### Done Criteria

- Router produces a route and reason codes.
- Uncertain routing uses fallback.
- Route distribution appears in analysis report.
- Router errors can be corrected in admin review.

---

## Phase 7: Foundation DNA Model Strategy

### Goal

Replace `bert-base-uncased` with DNA foundation models and specialist heads.

### Why

General English BERT is not a biology model. It can smoke-test code but should
not be used for scientific claims.

### Model Direction

Use raw DNA models only. ESM/protein branch is removed from scope.

Candidate model families:

```text
DNABERT-2 / MultiMolecule DNABERT-2
Nucleotide Transformer
other DNA-specific HF models after compatibility testing
```

### Windows Development Rule

Build the system on Windows, but avoid depending on custom Linux-only model
code. Use Windows-friendly models first. For tricky models requiring custom
Triton/FlashAttention stacks, train/test in Colab or WSL2 and export stable
artifacts.

### Training Strategy

RTX 3070 local:

```text
frozen embeddings
small classifier heads
small LoRA experiments
router training
offline model tests
benchmarking
```

Google Colab:

```text
larger fine-tuning
route-specific specialist models
monthly training batches
heavier Nucleotide Transformer experiments
```

Do not train a foundation model from scratch at this stage.

### Model Registry

Every model must have metadata:

```text
model_id
route
base_model
training_dataset_version
label_set_version
metrics
thresholds
artifact_uri
checksum
created_at
promoted_by
status: experimental/staging/production/retired
```

### Done Criteria

- Old BERT fallback is removed or clearly marked as smoke-test only.
- At least one DNA foundation model can run inference.
- Model registry exists.
- Route-specific classifier head plan is documented.

---

## Phase 8: Novelty And Contamination Scoring

### Goal

Flag possible novelty responsibly and detect contamination.

### Why

Novelty claims are high-stakes. Low confidence alone is not enough. The system
must explain why something might be novel or why it is likely contamination.

### Novelty Signals

```text
low model confidence
low reference similarity
stable unknown cluster across reads/samples
high sequence quality
not likely human/domestic contamination
not a known local species
not obvious sequencing artifact
route/model disagreement
```

### Contamination Signals

```text
human DNA
dog/cat/cattle/domestic animal DNA
lab reagent/control patterns
beach/swimmer contamination context
low abundance but common contaminant profile
```

### Output Classes

```text
known_species
likely_taxonomic_group
possible_novelty
known_species_not_novelty
possible_contamination
low_quality_unusable
unknown_needs_online_confirmation
```

### Abyss Mode Difference

Abyss Mode can say:

```text
novelty suspicion: low/medium/high
requires cloud confirmation: yes
recommended action: preserve sample / resample / continue / return
```

It should not make final new-species claims offline.

### Done Criteria

- Novelty score uses multiple signals.
- Contamination has separate flags.
- Results include reason codes.
- Admin can mark "not novelty, known species" and explain why.

---

## Phase 9: Human-In-The-Loop Review

### Goal

Build controlled expert review that improves the system over time without
allowing random users to poison training data.

### Why

Species identification and novelty detection require expert correction. But
corrections must be trusted, audited, and curated before training.

### Review Inputs

Users/experts can:

```text
confirm predicted species
reject prediction
choose corrected species
mark possible novelty
mark not novelty
mark human/domestic contamination
mark low-quality sequence
add depth/location/source/habitat/salinity/temperature notes
upload supporting lab/reference evidence
comment on route/model error
```

### Review States

```text
submitted
triaged
needs_evidence
accepted
rejected
duplicate
company_verified
included_in_training_batch
```

### Admin Review Sections

```text
novelty correction queue
species correction queue
contamination queue
low-quality queue
route-error queue
supporting evidence queue
comments and discussion
```

### Monthly Training Loop

```text
all accepted suggestions for month
-> clean and deduplicate
-> company review
-> taxonomic grouping
-> train/eval split
-> fine-tune route-specific heads/models
-> compare new vs previous model
-> promote only if metrics improve
-> record model version
```

### Anti-Poisoning Rule

Never update live models instantly from user suggestions.

```text
feedback updates database immediately
models update only after curated monthly retraining
```

### Done Criteria

- Expert/admin review works.
- All review actions are stored in Supabase/Postgres.
- Admin decisions are audited.
- Monthly batch creation can be run manually.

---

## Phase 10: Abyss Mode

### Goal

Create offline field-triage mode for submarine/deep-sea/remote expeditions.

### Why

Voyages are expensive and time-sensitive. Researchers need immediate local
assessment to decide whether to keep exploring, resample, preserve material, or
return for deeper analysis.

### Abyss Mode Capabilities

```text
offline login/session
local FASTA parsing
low-memory batching
small reference pack
compressed/quantized specialist models
basic novelty suspicion
contamination flags
decision recommendation
local audit log
sync when online
```

### Abyss Mode Limitations

Must show disclaimer:

```text
Abyss Mode is a field-triage system. Results are preliminary and must be
confirmed by full online analysis after reconnecting.
```

### Offline Pack

```text
expedition license/session
model pack
reference pack
known contaminant pack
species metadata pack
Ollama/reporting model if enabled
```

### Ollama Role

Ollama can be used for local explanation and decision-support summaries only.
It should not classify species.

```text
model evidence JSON
-> Ollama local summary
-> structured recommendation
```

Example recommendation:

```json
{
  "decision": "preserve_and_continue_sampling",
  "risk_level": "medium",
  "requires_cloud_confirmation": true,
  "reason": "High-quality unknown cluster with low contamination evidence."
}
```

### Done Criteria

- Offline mode can run without internet.
- Offline mode produces preliminary decision report.
- All offline actions sync to backend later.
- Online full analysis reruns after sync.

---

## Phase 11: Backend Reports And Export

### Goal

Create structured reports that support both scientific review and product demo.

### Report Sections

```text
sample metadata
processing summary
quality control
route distribution
known species table
possible novelty table
contamination warnings
biodiversity summary
model versions used
limitations/disclaimer
admin review status
downloadable JSON/PDF
```

### Why

Reports are the end product. The model output is only useful if researchers can
act on it and defend it.

### Done Criteria

- JSON report export works.
- PDF/HTML report can be generated later.
- Every result includes model version and reason codes.

---

## Phase 12: Frontend Rebuild

### Goal

Rebuild frontend around real backend contracts.

### Why

Current frontend has hardcoded local URLs, mock admin data, and demo auth. Once
backend contracts are real, frontend work becomes straightforward and less
fragile.

### Frontend Pages

```text
Landing/Login
Dashboard
Upload
Job Progress
Analysis Results
Species Detail
Novelty Review
Admin Review
Training Batch Admin
Model Status
Abyss Mode Expedition Setup
Abyss Sync History
```

### Landing/Auth

Keep the custom Synth Veda landing/login style, but wire it to real Google
OAuth.

```text
Continue with Google
Admin/contributor key redemption
role-aware navigation
```

### Upload Page

Features:

```text
FASTA/JSON upload
drag and drop
server-side upload ID
metadata form: depth, location, source, habitat, salinity, temperature
mode selection: online full / Abyss synced upload
```

### Results Page

Features:

```text
known species
possible novelty
contamination
low quality
route distribution
confidence/reason codes
download report
submit correction
```

### Admin Page

Features:

```text
review queue
novelty correction
species correction
contamination marking
evidence viewer
company decision controls
audit history
training-batch inclusion
```

### Done Criteria

- No mock axios.
- No hardcoded localhost except dev config.
- Frontend consumes typed backend API.
- Admin page requires real role.
- User corrections are saved to Supabase/Postgres.

---

## Phase 13: Testing, Security, And CI

### Goal

Make the system trustworthy enough for demos and early serious use.

### Backend Tests

```text
auth tests
upload tests
parser integration tests
job lifecycle tests
review permission tests
model registry tests
report generation tests
```

### Frontend Tests

```text
build test
lint
basic route render
upload flow
admin auth guard
```

### Security Checklist

```text
restrict CORS
server-side file size limits
rate limit auth/admin key attempts
hash admin invite keys
never expose service-role keys
RLS on Supabase exposed tables
audit admin decisions
scan npm dependencies
pin Python dependencies
avoid trust_remote_code unless isolated
do not accept arbitrary model paths from users
```

### CI

```text
backend unit tests
frontend build
frontend lint
Rust parser tests
npm audit
dependency scan
Docker build
```

### Done Criteria

- CI catches broken backend/frontend/parser changes.
- Security-sensitive flows have tests.
- Dependency vulnerabilities are tracked.

---

## Phase 14: Model Training And Monthly Release Process

### Goal

Turn curated human feedback into better model versions every month.

### Monthly Process

```text
1. freeze monthly accepted curation set
2. export route-specific datasets
3. clean/deduplicate sequences
4. create train/val/test split
5. train route-specific heads/models
6. evaluate against previous model
7. run regression tests on known cases
8. create model version record
9. promote or reject model
10. archive artifacts and metrics
```

### Promotion Criteria

New model must improve or preserve:

```text
overall F1
route-specific recall
novelty false-positive rate
contamination detection
known regression samples
latency budget
offline memory budget for Abyss Mode
```

### Done Criteria

- Monthly batch can be exported.
- Training script can run locally/Colab.
- Model version is recorded.
- Bad model releases can be rolled back.

---

## Phase 15: Planned Scaling After Funding

### Goal

Know how the system will scale later without overbuilding now.

### Future Scaling Plan

```text
API:
  stateless containers behind managed load balancer

Workers:
  queue-based workers
  GPU worker pool for model inference

Parser:
  Rust parser service or binary inside worker

Storage:
  object storage for uploads/reports
  Mongo for analysis documents
  Postgres for structured curation/training

Models:
  model registry
  dedicated inference service
  quantized offline packs

Observability:
  structured logs
  metrics
  tracing
  model drift monitoring
```

### Competitor Differentiation To Preserve

```text
edge/offline Abyss Mode
fast parser and routing engine
transparent route-specific models
human-curated monthly model improvement
contamination-aware coastal/deep-sea analysis
explainable novelty suspicion instead of black-box novelty claims
```

---

## Immediate Next Actions

### Step 1: Cleanup

Remove local generated folders and prepare a clean repo base.

### Step 2: Backend Skeleton

Create the new FastAPI structure and define endpoint contracts.

### Step 3: Database Schema

Design Supabase/Postgres tables for users, roles, reviews, curation, model
versions, and training batches.

### Step 4: Mongo Analysis Model

Define upload, job, sequence batch, and analysis result document shapes.

### Step 5: Parser Prototype

Build a Rust parser CLI and benchmark it against Python parsing.

### Step 6: Router Prototype

Implement QC + cheap route features before any heavy model work.

### Step 7: Frontend Wiring

Only after backend contracts exist, rebuild frontend pages around real APIs.

---

## External Docs To Verify Before Implementation

These areas change over time. Verify the official docs before coding/deploying:

```text
Supabase Google OAuth setup
Supabase RLS and auth best practices
Vercel environment variable behavior
Google Cloud Run deployment and autoscaling limits
Hugging Face Spaces hardware/pricing if used for demos
Hugging Face model compatibility on Windows/Colab
```

Official references checked during planning:

- Supabase Auth and Google login docs: https://supabase.com/docs/guides/auth
- Vercel environment variables docs: https://vercel.com/docs/environment-variables
- Google Cloud Run autoscaling docs: https://cloud.google.com/run/docs/about-instance-autoscaling
- Hugging Face Spaces docs: https://huggingface.co/docs/hub/spaces

