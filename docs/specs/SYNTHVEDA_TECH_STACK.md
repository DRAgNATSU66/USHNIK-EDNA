# SynthVeda — Suggested Tech Stack

Practical, staged recommendation. Bias throughout: ship a working product first, optimize 
only what profiling proves is actually slow. Don't front-load engineering effort (like a 
full Rust rewrite) before the product is validated.

---

## 1. Frontend

| Layer | Recommendation | Why |
|---|---|---|
| Framework | **React + Vite** | Fast dev loop, standard, works cleanly with Claude Code / agentic tooling |
| Styling | **Tailwind CSS**, configured with your exact token palette as custom theme values (not default Tailwind colors) | Prevents generic-Tailwind look; enforces the locked design system automatically |
| Component primitives | **shadcn/ui** | Accessible, unstyled-by-default components (dialogs, dropdowns, tables, tabs) you skin with your own tokens — avoids fighting a heavier library's default look |
| Charts | **Recharts** for most charts (line/area/bar/radar/pie); **Visx** if you want fully bespoke chart work (radial gauges, custom rarefaction curve, custom co-occurrence layout) | Recharts = fast to restyle for the spline/gradient-fill treatment; Visx = more control when a chart needs to look truly custom |
| 3D / WebGL | **Three.js** | Needed for the Species Co-occurrence Network (thousands of nodes) and doubles as the DNA helix hero visual — one library, two uses |
| Animation / micro-interactions | **Framer Motion** | Hover states, tab transitions, loading pulses — this is the actual difference between "prototype" and "premium product" |
| Maps | **Mapbox GL JS** or **Leaflet** (Mapbox has better built-in support for heatmap/probability-radius rendering, which you need for the Legislative hotspot map) | Diffused heat-zone rendering (not pin markers) is easier with Mapbox's heatmap layer |
| State management | **Zustand** (lightweight) or React Query for server state | Avoid Redux unless the app genuinely grows complex enough to need it — likely overkill here |
| Forms | **React Hook Form** + **Zod** for validation | Handles the Upload Analysis metadata form, Species Correction override form, etc. cleanly with schema validation |

---

## 2. Backend

| Layer | Recommendation | Why |
|---|---|---|
| Language/framework (MVP) | **Python + FastAPI** | Fast to build, async support, auto-generated OpenAPI docs, huge bioinformatics library ecosystem (Biopython, pyfastx) — best fit for getting the product working end-to-end quickly |
| Alternative if you're faster in JS | **Node + Express/Fastify** | Viable if you genuinely prefer it — but you lose direct access to Biopython, would rely more on calling external CLI tools |
| API style | **REST**, OpenAPI-documented | Simple, well-understood, easy for the frontend team (you) to consume; GraphQL is unnecessary complexity here |
| Async/background jobs | **Celery** + Redis, or FastAPI's built-in background tasks for lighter loads | File parsing/pipeline runs are long-running — don't block the request thread; this also unlocks the "live streaming progress" pattern discussed for Upload Analysis |
| Auth | **Auth0** or **Clerk** (managed) rather than building your own | Saves real time; both have solid free tiers for early-stage products |

---

## 3. DNA Parsing & Bioinformatics Pipeline

**Do not reimplement alignment/matching algorithms yourself.** Use existing, battle-tested 
compiled tools as subprocesses or services — they're already fast (C/C++), and rebuilding 
this logic is a huge time sink with no real product benefit.

| Task | Recommended tool |
|---|---|
| FASTA/FASTQ parsing | **pyfastx** (fast, C-backed Python library) or **Biopython** for more general-purpose needs |
| Sequence alignment / species matching | **BLAST+** (NCBI) or **DIAMOND** (much faster for large-scale protein/nucleotide searches) |
| OTU/ASV clustering | **VSEARCH** or **DADA2** (DADA2 is R-based, common in the metabarcoding world — call via subprocess if needed) |
| Reference databases | SILVA, NCBI NT/NR, BOLD — pick per the earlier "open decision" on which DB(s) you're actually matching against |
| Quality control / trimming | **fastp** or **Trimmomatic** |

**Your actual backend code's job:** orchestrate these tools (run them as subprocesses or 
via a job queue), parse their output into structured data, apply your own business logic 
(novelty thresholding, route/triage bucketing, contamination flagging), and serve it via 
the API. This orchestration layer is where most of your real engineering time goes — not 
in writing a custom aligner.

---

## 4. Data Storage

| Need | Recommendation |
|---|---|
| Primary database | **PostgreSQL** — handles structured taxonomic/sample data well, has solid JSON support for flexible fields (reason codes, metadata) |
| Geospatial queries | **PostGIS** extension on Postgres — needed for the hotspot map, EEZ/maritime boundary checks, spatial radius queries |
| File storage (raw FASTA uploads, PDFs, attachments) | **S3-compatible object storage** (AWS S3, or Cloudflare R2 for lower cost) |
| Caching / job queue backing | **Redis** |
| Vector/network data (co-occurrence network, phylogenetic tree) | Store as structured JSON in Postgres initially — only reach for a dedicated graph DB (Neo4j) if the co-occurrence network genuinely outgrows relational storage |

---

## 5. Where Rust Actually Fits (Later, Not Now)

Per our earlier discussion — Rust is not required to ship. Recommended path:

1. Build the MVP pipeline orchestration in Python (FastAPI + pyfastx + subprocess calls to 
   BLAST/DIAMOND/VSEARCH).
2. Get real usage and real file sizes through it.
3. Profile. Find the actual bottleneck — it's often not where you'd assume.
4. If a specific hot path is proven slow (e.g. raw read filtering/QC on very large files, 
   not the alignment step which is already compiled-tool-fast), port *that one function* to 
   Rust and expose it via **PyO3** (callable from Python) rather than rewriting the whole 
   backend.
5. This keeps the investor-facing "Rust-optimized hot path" claim true without spending 
   months rewriting a backend before the product is validated.

---

## 6. Infrastructure & Deployment

| Need | Recommendation |
|---|---|
| Frontend hosting | **Vercel** |
| Backend hosting | **Railway** or **Render** for early stage (simple, fast to deploy FastAPI + Celery + Redis + Postgres); move to AWS/GCP only once you need finer infra control or hit their limits |
| Heavy compute (bioinformatics jobs) | Consider a separate worker/queue setup that can scale independently from the API — this is where multi-GB file processing actually happens, keep it isolated from your request-handling servers |
| CI/CD | GitHub Actions — standard, free tier is generous |
| Error monitoring | **Sentry** (frontend + backend) |
| Env/secrets | **Doppler** or simple `.env` + platform secret manager for MVP stage |

---

## 7. Suggested Build Sequence

1. Set up Postgres schema (samples, sequences, taxonomic calls, corrections, metadata, 
   users) + FastAPI skeleton + auth
2. Build the pipeline orchestration layer: upload → pyfastx parse → fastp QC → 
   BLAST/DIAMOND/VSEARCH → structured output → stored in Postgres
3. Wire the frontend (per the Master Frontend doc) against real API endpoints, page by page 
   in the previously established build order
4. Add background job handling (Celery) once synchronous processing starts feeling slow in 
   real use — don't build this speculatively on day one if it adds friction to shipping v1
5. Profile real bioinformatics runs; only then consider a Rust hot-path port if genuinely 
   warranted

---

## 8. What NOT to over-invest in early

- Full Rust backend rewrite (see Section 5)
- GraphQL (REST is sufficient)
- Kubernetes / complex container orchestration (Railway/Render abstracts this away until 
  you have real scale pressure)
- A custom-built auth system (use Auth0/Clerk)
- A dedicated graph database (Postgres JSON is enough until proven otherwise)
