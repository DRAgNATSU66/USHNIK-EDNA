# Synth Veda — Theory & Concepts Reference

A running Q&A record of the theoretical/conceptual questions asked while
building Synth Veda's ML pipeline — kept for verifying understanding and as
a source when writing up the methodology for a paper or conference
submission. Each entry is a real question asked during development, answered
in the context of what this specific system actually does (not generic
textbook definitions).

Updated automatically whenever a "how/what/why/if" conceptual question comes
up in conversation. See `models/README.md`, `models/registry/README.md`, and
`SYNTH_VEDA_PHASE_PLAN.md` for architecture/ops docs — this file is theory
and reasoning, not setup instructions.

---

## 1. Model architecture

### What ML models are we using / what's our neural schema?

Three distinct layers, only one of which is a trained neural network:

1. **Heuristic router** (`services/worker/app/model_router/`) — decides
   *which* of the 6 taxonomic routes (fish, plant, bacteria_pathogen,
   animal_general, human_domestic_contamination, misc_unknown) a sequence
   belongs to, *before* any deep model runs. Two signals combine:
   marker-gene pattern matching (known primer/barcode regions) and a
   Gaussian-kernel likelihood score from GC content, CpG observed/expected
   ratio, and sequence length against hand-set per-route statistical
   profiles (`reference.py`). No learned weights — pure statistics.

2. **The neural network** — [DNABERT-2](https://huggingface.co/zhihan1996/DNABERT-2-117M)
   (117M params, Zhou et al., ICLR 2024), a pretrained genomic foundation
   model we did **not** build from scratch. We fine-tuned **6 separate
   copies** of it — one full backbone + one classification head per route —
   each specialized on that route's labeled data. Architecture:
   - 12-layer transformer (MosaicBERT-style attention), 768 hidden dim
   - Custom BPE tokenizer (~4096 vocab, multi-base chunks per token, not
     one-token-per-base)
   - Classification head we did build (`app/inference/heads.py`):
     `Dropout(0.1) → Linear(768 → num_classes) → softmax`, `num_classes`
     being 2–4 depending on the route's label set

3. **Novelty/contamination scorer** (`app/novelty/scorer.py`) — a
   hand-tuned weighted sum (`result_class` 35%, model uncertainty 25%,
   quality 20%, contamination-gate 10%, label entropy 7%, embedding
   isolation 3%) that turns the neural model's raw outputs into a final
   novelty score. Explicitly a placeholder formula pending a future
   learned-weights phase — not itself trained.

**Not yet built**: species-level identification (`predicted_taxon` is
`null` everywhere). Today's model outputs a confidence *category*
(`known_species` / `likely_taxonomic_group` / `possible_novelty` /
`possible_contamination` / etc.), not an actual species name like
*Salmo salar*. That needs a taxonomy-lookup layer over the embedding space
— explicitly deferred, not implemented.

### DNABERT-2 is 117M params — is the fallback (DNABERT-S) also 117M? And the model we trained today — different parameter count, or purely fine-tuned with nothing else changed?

Both backbones are 117M — DNABERT-S is a DNABERT-2 variant (same
architecture, trained with a species-differentiation objective originally),
not a different size. **DNABERT-S has not been trained yet** — only
DNABERT-2 (main) has actually been fine-tuned, across all 6 routes.

And yes — "just fine-tune it, nothing else" is exactly what happened, per
route:

1. The full 117M-parameter DNABERT-2 backbone had its *existing* weights
   updated via backprop on that route's data (not frozen, not replaced,
   no architecture change).
2. The only genuinely new parameters are the tiny classification head:
   `Dropout → Linear(768 → num_classes)`, ~1,500–3,100 parameters for
   `num_classes` 2–4 — negligible next to 117M.

No new architecture was invented and the backbone's parameter count didn't
change. Each of the 6 trained checkpoints is still accurately described as
"a 117M-parameter model" — the backbone does essentially all the work; what
we actually built from scratch is the small head sitting on top of it.

### Why DNABERT-2 specifically, over the alternatives?

Considered and rejected, with reasons:

| Model | Why not (for this system, now) |
|---|---|
| Nucleotide Transformer (500M–2.5B) | Stronger benchmarks, but heavier than needed for short eDNA amplicons; one experimental fish-route registry stub exists for a future A/B comparison, untrained |
| HyenaDNA | Optimized for very long context (up to 1M tokens) — our amplicon reads are 100–1000bp, so this capability is wasted here |
| Caduceus | Tiny (8M params), reverse-complement equivariant — a genuinely relevant inductive bias, but not tried yet; a real future lever if DNABERT-2 plateaus |
| Evo / Evo 2 (7B/40B) | Built for genome-scale generation/design, not amplicon classification; needs GPU infrastructure beyond a single 8GB card |
| ESM-2/ESM-3 (Meta) | Operates on **protein** sequences (amino acids), not raw DNA — wrong input modality entirely for this task |
| AlphaGenome (Google DeepMind) | API-only preview, non-commercial license, no fine-tunable weights, trained only on human+mouse |
| Gemma | No genomics specialization at all — general-purpose text LLM |

DNABERT-2 won on: right input modality (DNA nucleotides), small enough
(117M) to fully fine-tune on a single consumer 8GB GPU, proven multi-species
pretraining, and it's what the project's own registry scaffolding had
already been set up to expect.

---

## 2. Training mechanics

### What is a loss function?

A single number expressing "how wrong was the prediction?" — the entire
training loop exists only to make this number smaller. Concretely here: for
each sequence, the model outputs a probability per label (e.g.
`known_species: 70%, likely_taxonomic_group: 10%, ...`); **cross-entropy
loss** compares that distribution against the true label and produces a
penalty (small if the model was confidently right, large if confidently
wrong). That per-batch loss value is what backpropagation uses to decide how
to adjust every weight in the model.

### What does "fine-tuning" mean here, concretely?

Loading DNABERT-2's pretrained weights, then continuing training (backward
passes + weight updates) on our own labeled route-specific data — as opposed
to (a) using it frozen as a fixed feature extractor, or (b) training a
transformer from random initialization. We chose **full fine-tuning**
(backbone + head both trainable) rather than freezing the backbone, since
117M parameters fits comfortably in 8GB VRAM and full fine-tuning generally
outperforms a frozen-backbone linear probe.

### How does gradient accumulation work, and why do we need it?

The technique for training with an effectively large batch size on a GPU
that can't hold a large batch in memory at once: process a small
"micro-batch" (e.g. 8 sequences — the piece that actually has to fit in
VRAM), compute its gradients, but don't apply them yet — just add them to a
running total. Repeat for N micro-batches (e.g. 16), *then* apply the
accumulated gradient to the weights. Mathematically equivalent to training
on one batch of 8×16=128 at once; the GPU memory footprint at any instant is
only ever the 8-sequence slice.

### What is an epoch?

One complete pass through the *entire* training dataset — every example
seen exactly once. Concretely, for `bacteria_pathogen`'s 37,832 training
examples at batch size 8: one epoch = 37,832 ÷ 8 ≈ 4,729 steps. We train
for multiple epochs (e.g. 8) so the model refines its weights across
several full passes, not just one — but more epochs isn't automatically
better: past some point the model starts fitting noise in the training
set rather than learning generalizable patterns (overfitting), which is
exactly why `dev_loss`/`dev_acc` are tracked *every* epoch and the
best-scoring epoch's weights are what actually gets saved, not just
whatever the last epoch happened to produce.

### What do train/dev/test actually mean, separately?

(2026-08-04.) Three splits of the same labeled dataset, each with a
different job:

- **`train`** — the only split that changes the model. Every sequence in
  it is fed through the model, compared against its true label, and the
  resulting error is backpropagated to update the weights. This is "the
  model learning," full stop.
- **`dev`** (validation set) — the model never trains on this (zero weight
  updates from it), but it's evaluated after *every* epoch. Its job:
  catch overfitting early (train accuracy climbing while dev accuracy
  stalls/drops means the model is starting to memorize training-specific
  noise instead of real patterns — see the epoch entry above), and decide
  *which* epoch's weights actually get saved as the final model.
- **`test`** — also never trained on, but unlike `dev`, not used to make
  *any* decisions during training either. Touched exactly once, at the
  very end, after everything else is already decided, to produce the
  honest final number.

**Why three splits instead of two**: if `test` were used to make any
decisions during training (the way `dev` is — e.g. picking the best
epoch), those decisions would start unconsciously fitting to that
specific set, and the final "test accuracy" would become an inflated
estimate rather than an honest one. `dev` exists specifically to absorb
all the decision-making, so `test` stays untouched until the one real,
unbiased check that has to clear the 85% target.

### What do the fields in a live training progress line actually mean?

(2026-08-04.) Reading a real line from a `bacteria_pathogen` run:

```text
train=37832 dev=4729 test=4729
progress epoch=1/8 step=2187/18916 elapsed=395s rate=5.5it/s
```

- **`train=37832 dev=4729 test=4729`** — the sizes of the three dataset
  splits, printed once at startup — see the train/dev/test entry above.
- **`step=2187/18916`** — which micro-batch the loop is currently on, out
  of the total for this epoch. The denominator is `train size ÷
  batch_size` (37,832 ÷ 2 = 18,916 here) — this is *not* the same as the
  number of optimizer updates, which only happen every `grad_accum`
  micro-steps (see the gradient-accumulation entry above).
- **`elapsed=395s`** — wall-clock time spent in *this* epoch specifically;
  resets to 0 at the start of each new epoch.
- **`rate=5.5it/s`** — micro-batches processed per second right now. Not
  directly comparable across runs with different `batch_size` values —
  see the "why did it/s look the same after raising batch_size" entry
  further up, where this exact confusion came up for real.
- **`epoch=1/8 in progress`** — which full pass through the dataset this
  is, out of the total configured.

From these, a live ETA is just arithmetic: `(steps_remaining_this_epoch ÷
rate) + (epochs_remaining × steps_per_epoch ÷ rate)`.

### What's a class-weighted loss, and why did bacteria_pathogen need one?

Normally every training example contributes equally to the loss. If one
label has 16,000 examples and another has only 4,565 (a real, measured
imbalance in `bacteria_pathogen`'s `likely_taxonomic_group` class — not a
sampling bug), the loss is dominated by the majority classes and the model
has little pressure to learn the rare one well. Inverse-frequency
weighting (`weight_i = total_examples / (num_classes × count_i)`) multiplies
the rare class's contribution to the loss (2.07× for
`likely_taxonomic_group`, 7.36× for `possible_contamination` in our case) so
mistakes on it count for more, giving the optimizer real pressure to fix
them — without needing more data than actually exists for that class.

**Result, measured**: it didn't actually help overall accuracy. Three
`bacteria_pathogen` runs: baseline 80.06% acc / 0.847 macro F1 → more data
(20K cap) 84.56% / 0.837 → more data + class weighting 82.87% / 0.832.
Weighting raised `likely_taxonomic_group`'s recall (0.64→0.79) but at the
cost of its precision (0.57→0.50) and `known_species`' recall (0.83→0.79) —
net negative on overall accuracy. **Conclusion**: the weak class wasn't
primarily a data-volume or imbalance problem — see next entry.

### When more data and class weighting both fail to fix a weak class, what's actually wrong — and how do you tell the difference?

If a class's F1 stays stuck despite (a) increasing its training volume and
(b) reweighting the loss to penalize mistakes on it more — both tried here,
neither fixed `likely_taxonomic_group` — the next suspect is the **label
definition itself**, not the model or the data volume. Traced it back to
`training/labeling.py`'s `is_higher_rank_only()`: it flagged a record as
`likely_taxonomic_group` whenever NCBI's taxonomy tree lacked a
species-rank node for that organism's taxid — which for bacteria is
extremely common for administrative/curatorial reasons (many
well-characterized organisms simply aren't formally assigned a
species-rank NCBI entry) and has nothing to do with whether the *sequence*
is actually identifiable. That fallback was silently mixing "NCBI's
taxonomy is incomplete here" into the same bucket as "this genuinely reads
as an unresolved species from the DNA," which is why more data/reweighting
couldn't fix it — you can't statistically learn your way out of a
label that's measuring the wrong thing. Fix: dropped that fallback,
keeping only the explicit naming-convention signal ("Genus sp.", "cf.
species") — an actual human curatorial judgment call, not a taxonomy-tree
completeness artifact.

**Result, measured — and this hypothesis turned out wrong**: 82.39% acc /
0.832 macro F1, essentially tied with the class-weighting attempt (82.87%)
and *worse* than "more data, unchanged heuristic" (84.56%). The tell:
`likely_taxonomic_group`'s class size came out **exactly identical**
(5,690) before and after removing the "species not in lineage" trigger —
meaning in this data, almost every record with that taxonomy gap *also* has
"sp."/"cf." in its name. The two signals I assumed were separable turned
out to be nearly the same population, so this wasn't really an independent
test of the label-definition theory.

**Correction to the record**: re-running this exact config a second time
(attempting to regenerate a checkpoint) reproduced **82.39% / 0.8316 to the
decimal, identical per-class breakdown** — confirming training here is
fully deterministic given a fixed dataset + seed, not run-to-run noise as
first assumed. The 84.56% number came from a genuinely different dataset
(the old-heuristic build) and was never reproduced — recovering it exactly
would require reverting `labeling.py` and rebuilding, which wasn't judged
worth doing since 84.56% still doesn't clear the actual target (see
target note below).

**Target**: `bacteria_pathogen` must exceed **85%** test accuracy — a hard
project requirement, not "higher is better." No attempt so far has cleared
it (best real, reproducible result: 84.56%, old-heuristic dataset).

**Standing conclusion after four attempts (baseline → more data → class
weighting → relabeled), best remains "more data alone" at 84.56%**: this
may genuinely be a hard, close decision boundary at this amplicon length —
distinguishing congeneric species (same genus, different species) from
short marker-gene reads is a known-hard problem in real DNA barcoding
literature, not necessarily a fixable artifact of this pipeline. 90%+
accuracy on this exact 4-class split may not be realistic for a 117M model
on short reads without a materially different lever (bigger backbone,
longer sequences/full genes instead of amplicon fragments, or accepting
`known_species` vs `likely_taxonomic_group` as an inherently fuzzy
boundary worth reporting with a confidence range rather than forcing a hard
class label). Worth stating plainly in any writeup: this is a documented
negative result, not a hidden one — the attempts and their reasoning are
preserved above.

### Why fp32 instead of fp16 for inference, if training used mixed precision?

Two different things: **training** used `torch.autocast`, which safely
mixes fp16/fp32 per-operation while keeping master weights in fp32 — PyTorch
decides case-by-case which ops are safe to run in fp16. **Loading a model
directly with `torch_dtype=torch.float16`** forces the *entire* model,
including newly-initialized layers (DNABERT-2's pooler weights, which don't
come from the pretrained checkpoint), into fp16 with no such safety net —
this crashed with a dtype mismatch. Since a 117M model in fp32 is a
non-issue for single-sequence inference on an 8GB GPU, the fix was to always
load in fp32 rather than try to make blanket fp16 loading safe for
custom/hand-written model code that wasn't written with that guarantee.

### Why does `trust_remote_code=True` matter, and how is it handled safely?

DNABERT-2 ships its own custom attention implementation (not a standard
`transformers` architecture), so loading it at all requires
`trust_remote_code=True` — which executes that repo's Python code locally.
This is a real trust decision, not a formality. Handled via a **per-model
allowlist**: `ModelRegistryEntry.trusted_remote_code` defaults to `False`
and must be explicitly set per registry entry — so trusting DNABERT-2's code
never silently extends to any other model the system might load later.

### What is a smoke test, and why run one before a full training run?

A smoke test is a deliberately cheap, minimal run whose only job is to
answer "does this catastrophically break?" — not "is it accurate?" For us
that means 1 epoch instead of the full 8, taking a couple of minutes
instead of ~8-9. The name comes from hardware testing: power on the device,
see if smoke comes out; if it does, stop immediately rather than run the
full test suite on something already broken.

Why it mattered here, concretely: getting DNABERT-2 fine-tuning working at
all took **four** real bugs in a row — a missing `einops` dependency, a
`transformers` version incompatibility with DNABERT-2's unmaintained custom
code, a `torch` version too old for a `transformers` security check on
non-safetensors checkpoints, and a tuple-vs-object output-format mismatch
in DNABERT-2's forward pass. Every one of those surfaced within the first
few seconds-to-minutes of a smoke test. Had we skipped straight to full
8-epoch runs each time, discovering each bug would have cost the full ~8-9
minutes per attempt instead of under a minute — four full-run cycles
wasted instead of four fast ones. The rule going forward: any new
model/config combination gets a 1-epoch smoke test first, full run only
once that's clean. **This exact pattern repeated with Nucleotide
Transformer 500M** (see the next two entries) — two more real bugs, both
caught by the smoke test within seconds/minutes rather than after a full run.

### Why did `AutoModel.from_pretrained(..., trust_remote_code=True)` load the *wrong* architecture for Nucleotide Transformer 500M?

(2026-08-04.) Smoke-testing NT-500M as a `bacteria_pathogen` candidate (see
§4's decision log) failed immediately with
`RuntimeError: size mismatch for weight: copying a param with shape
torch.Size([8192, 1024]) from checkpoint, the shape in current model is
torch.Size([4096, 1024])` — during model *loading*, before any training
step. Root cause: this repo's `config.json` declares `auto_map` entries for
`AutoModelForMaskedLM` / `AutoModelForTokenClassification` /
`AutoModelForSequenceClassification`, but **not for plain `AutoModel`**.
`model_type: "esm"` is also a natively-registered architecture inside
`transformers` itself. So `AutoModel.from_pretrained(..., trust_remote_code=True)`
— with no `AutoModel` entry to dispatch through — silently resolves to
`transformers`' own **built-in, vanilla-FFN** `EsmModel`, not this repo's
own `modeling_esm.py`, even though that file defines its own `EsmModel` and
even though `trust_remote_code=True` was passed. The repo's actual encoder
uses a SwiGLU-style **gated** FFN (`EsmIntermediate`, a single fused
`Linear(hidden, 2×intermediate)` projection later split into gate/value
halves) — hence the checkpoint's `8192 = 2×4096` output dim, which the
built-in non-gated `EsmModel` (expecting a plain `4096`) can't load.

**Fix**: load through the class that *is* mapped —
`AutoModelForMaskedLM.from_pretrained(..., trust_remote_code=True)` — and
take its `.esm` submodule as the encoder backbone, rather than calling
`AutoModel` directly. Applied generically (any ESM-family checkpoint whose
`auto_map` lacks an `AutoModel` key falls back to this path), in both
`training/finetune.py` and the production `app/inference/loader.py`, so the
same bug can't resurface silently if NT ever becomes the deployed model.

### Why did NT-500M still run out of memory after the loading bug was fixed, on hardware that fine-tunes DNABERT-2 fine?

(2026-08-04.) NT-500M is ~4.3× DNABERT-2's parameter count (500M vs 117M).
Standard `AdamW` keeps **two extra fp32 buffers per trainable parameter**
(first and second moment estimates) on top of the parameters themselves and
their gradients — so full fine-tuning's static memory floor is roughly
params (fp32, 2GB) + gradients (fp32, 2GB) + Adam state (fp32 ×2, 4GB) ≈
8GB, before a single activation tensor exists and before any of the actual
8GB card's CUDA/driver overhead. DNABERT-2 at 117M never got close to this
ceiling; NT-500M hit it exactly, crashing inside `optimizer.step()` on the
very first update.

**Fix, in two parts**:

1. Swapped `torch.optim.AdamW` for `bitsandbytes.optim.AdamW8bit` (CUDA
   only) — quantizes the two moment buffers to ~1 byte/param instead of 4,
   cutting that 4GB down to roughly 1GB. Installed cleanly via a native
   Windows wheel (`pip install bitsandbytes`, unlike Triton, which has no
   official Windows build at all — see the DNABERT-S entry in §4).
2. Still OOM'd afterward (crashed mid-backward with 7.29GB already
   resident) — the remaining pressure was activation memory: no
   Triton/FlashAttention on Windows means attention runs through the plain
   PyTorch fallback, materializing full `batch × heads × seq × seq`
   matrices, and the gated FFN's fused projection is 2× wider than a normal
   one. Reduced `--batch-size` from 4 to 1 (raising `--grad-accum` from 8 to
   32 to hold the *effective* batch size at 32 — same optimizer-step
   semantics, smaller peak memory per micro-step) and set
   `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` to reduce allocator
   fragmentation (the OOM messages explicitly named fragmentation:
   "reserved but unallocated memory is large"). That combination finally
   trained cleanly.

Once running, GPU compute read 100% utilization but only ~6.6/8GB VRAM was
in use — expected, not a bug: at batch_size=1, memory is dominated by the
parts that don't scale with batch (weights, gradients, 8-bit optimizer
state, CUDA context), while activations — the part that *does* scale with
batch — are small at batch=1, leaving real headroom on the table. "100%
compute" just means the GPU is never idle between kernel launches; it says
nothing about how much work each launch does. Since fragmentation was
already addressed by `expandable_segments`, batch_size was raised to 2
(`--grad-accum` correspondingly lowered to 16, keeping the same effective
batch of 32) to use more of that headroom and roughly double per-step
throughput — without changing what the model actually learns, since the
effective batch size (and therefore the gradient each optimizer step sees)
is unchanged.

### After raising batch_size (and VRAM use) 1→2, the printed `it/s` looked the same — so was the extra VRAM just wasted, no real speedup?

(2026-08-04.) No — the printed `rate=X it/s` isn't comparable across the two
runs, because an "it" means a different amount of work in each: it's
**micro-batches per second**, not sequences per second, and a micro-batch
holds `batch_size` sequences. Measured:

- batch_size=1 run: `total_steps=37832` (one step per sequence, since the
  dataset has 37,832 training rows), rate ≈6.9 it/s → **6.9 sequences/sec**
  real throughput → projected epoch time ≈ 37832 ÷ 6.9 ≈ **91 minutes**.
- batch_size=2 run: `total_steps=18916` (half as many steps — 2 sequences
  per step now), rate ≈6.4 it/s → **12.8 sequences/sec** real throughput →
  projected epoch time ≈ 18916 ÷ 6.4 ≈ **49 minutes**.

So real throughput went 6.9 → 12.8 sequences/sec, roughly **1.85×**, even
though the printed "it/s" number stayed flat (in fact dipped slightly,
because each larger step now does genuinely more matrix-multiply work per
launch, not because anything got slower). The reliable read is the
**step-count halving** (37832 → 18916 for the same dataset), not the raw
`it/s` figure by itself — same unit label, different meaning per run.

Why the extra VRAM bought real speed rather than nothing: model weights,
gradients, and 8-bit optimizer state are **fixed-size regardless of batch**
— they don't grow when batch_size grows. Only activations scale with batch.
So going from batch=1 to batch=2 adds a small, mostly-fixed amount of extra
memory but lets each GPU kernel launch process twice the data, amortizing
per-launch overhead (Python dispatch, CUDA kernel-launch latency) over more
actual computation. That's also *why* GPU compute read "100%" even at
batch=1, despite being genuinely slower in real terms: "100% utilization"
means the GPU was never sitting idle between launches, not that each launch
was doing peak useful work — at batch=1 a larger fraction of each launch's
time was fixed overhead rather than math, exactly the inefficiency the
batch-size increase targeted.

### If the GPU does "the learning," what do the CPU and RAM actually do during training — and what did we change to use them better?

(2026-08-04.) The GPU runs the actual learning math (matmuls, attention,
backprop). CPU and RAM do everything that feeds and orchestrates that math,
concretely in `training/finetune.py`:

**CPU**: (1) **tokenization** —
`SequenceDataset.__getitem__` turns each raw DNA string into token IDs via
the tokenizer, once per sequence, every batch; (2) **the training loop
itself** — Python issuing `loss.backward()`, `optimizer.step()`, scheduler
steps, progress printing (orchestration, not math — it tells the GPU what
to do, asynchronously, but the instructions themselves are CPU-bound); (3)
**metric computation** — `sklearn`'s `accuracy_score`/`f1_score` in
`run_eval()` run on CPU/numpy, not GPU; (4) **file I/O** — reading CSVs at
startup, writing checkpoints/`metrics.json`.

**RAM**: (1) **holding the dataset** — `SequenceDataset.__init__` loads
every row (raw sequence string + label) into a Python list up front, for
all of train/dev/test; (2) **DataLoader worker buffers** — each parallel
worker is its own OS process with its own memory and a prefetch queue, so
more workers/deeper prefetch directly costs more RAM; (3) **pinned
memory** — a page-locked RAM region that lets CPU→GPU transfer over PCIe
happen via direct memory access instead of an extra copy step; (4) **the
model itself, transiently** — `from_pretrained` first materializes weights
in system RAM before `.to(device)` moves them to VRAM.

**The bug this surfaced**: Task Manager showed CPU at ~9% and RAM
comfortably under budget while the GPU sat at 90%+ during an NT-500M
run — because `DataLoader(...)` never set `num_workers`, defaulting to
`0`: all tokenization ran serially on a single thread, blocking between
GPU steps, while the other 15 CPU threads and most of the RAM sat idle.
**Fix**: added `--num-workers` (default 10, sized for this machine's
8-core/16-thread CPU — see [[max-resource-utilization-preference]]),
`persistent_workers=True` (avoids re-spawning worker processes and
re-initializing the tokenizer every epoch), `prefetch_factor=4`, and
`pin_memory=True` when on CUDA. Validated in isolation (no GPU/model
involved, so zero risk to the live NT-500M run already in progress at the
time) — 10 parallel workers iterated cleanly on Windows `spawn`-based
multiprocessing with no crash or hang. Applied for future runs; the
already-running experiment was deliberately left alone rather than
restarted, to avoid losing its progress for a CPU-utilization gain.

---

## 3. Pipeline / system architecture

### Do we test on real data?

(2026-08-05.) Yes, with an important nuance. Every split (train/dev/test)
is built from genuine, curated biological reference databases, not
synthetic or generated sequences — for `bacteria_pathogen` specifically:
BOLD (COI/rbcL/matK barcodes), SILVA (16S/18S/28S rRNA), MIDORI2
(mitochondrial genes, real NCBI taxids), and real NCBI BLAST databases
(`16S_ribosomal_RNA`, `ref_prok_rep_genomes`, `env_nt`, `nt_viruses`, etc.).
No fabricated sequences anywhere in the pipeline.

The nuance: these are **curated reference database entries**, not **raw
field-collected eDNA samples**. A reference entry is a clean sequence tied
to a confirmed species ID — meaningfully different from what a real water/
soil sample yields (degraded DNA, mixed communities, PCR bias, sequencing
errors, chimeric reads). The one deliberate exception is `possible_novelty`,
which pulls specifically from NCBI's `env_nt` — real *uncultured/
environmental* sequences, chosen precisely because they're the closest real
proxy to genuine eDNA conditions available in a reference database, not a
synthetic stand-in for it.

A genuinely realistic external validation set already exists but is unused:
`E:\synthveda-data\Project\` contains real Monterey Bay eDNA data (sample
metadata + an ASV taxonomic abundance table) from a published field study
(Djurhuus et al. 2020, *Nature Communications*) — actual water samples,
actual sequencing runs, actual taxonomic assignments, not reference-database
entries. Worth using as a true field-realism check once the model clears
85%, and worth naming explicitly as a limitation in any writeup before
then: reported accuracy reflects performance on reference-quality sequences,
not yet validated against raw field samples.

### Train/test data leakage: why every accuracy number before 2026-08-05 was inflated

**The most consequential bug found in this project.** `build_dataset.py`'s
`write_splits()` shuffled raw rows and sliced them into test/dev/train
**without deduplicating first**. Reference databases legitimately contain the
same sequence many times (the same marker gene deposited under multiple
accessions; overlapping coverage between BOLD/SILVA/MIDORI2/NCBI), so
duplicate copies of one sequence scattered randomly across all three splits.
The model was therefore evaluated partly on sequences it had memorised
during training.

Measured on `bacteria_pathogen` (47,290 rows):

- **13.1%** of all rows were duplicates (47,290 rows → 41,093 unique).
- **~11%** of the test set also appeared in train (483 unique sequences,
  720 test rows once test's own internal duplicates are counted).

Quantified directly by evaluating the trained NT-500M checkpoint on the
leaked and clean portions of the test set separately:

| Subset | n | Accuracy |
|---|---|---|
| Full test (the reported headline) | 4,729 | **84.88%** |
| Leaked (also present in train) | 720 | **98.61%** |
| Clean (genuinely held out) | 4,009 | **82.41%** |

The 98.61%-vs-82.41% split is memorisation made visible: on sequences it had
seen, the model was almost perfect; on unseen ones, ~16 points worse. **True
generalisation accuracy was 82.41%, not 84.88% — the headline was inflated
by ~2.5 points.** This applies retroactively to *every* earlier number in
this document (DNABERT-2's 80.06%/84.56%/82.87%/82.39% all used the same
leaky splits), so the whole experiment series was measuring partly-memorised
performance. The distance to the 85% target was never 0.12 points; it was
~2.6 points.

**Fix**: deduplicate by sequence *before* splitting, so a sequence appears in
exactly one split exactly once. Sequences carrying conflicting labels across
sources (14 of them, 0.03%) are dropped rather than arbitrarily assigned —
ambiguous supervision is worse than less supervision. Post-fix verification
on the re-split data: `train/test overlap = 0, train/dev = 0, dev/test = 0`.

**Secondary benefit**: the 12.3% duplicate rows *within* train were also
active overfitting pressure — the model saw the same sequence several times
per epoch, which is direct memorisation incentive. Deduplicating should
therefore reduce the overfitting documented in §4, not merely make the
numbers honest.

**Confirmed by an actual retrain, not just post-hoc re-evaluation** (2026-08-05):
the 82.41% above was estimated by evaluating the *old* (leakage-trained)
checkpoint on a clean subset. A full fresh 8-epoch run on the properly
deduplicated splits (plus the eval-loss fix below, weight_decay 0.01→0.05,
lr 2e-5→1e-5) produced **83.64% test accuracy** — close to that estimate and,
notably, *higher* than the naive post-hoc estimate, consistent with training
on clean data from the start being better than training on leaky data and
only cleaning up the evaluation. See §4 for the full run's numbers and the
dev_loss-vs-dev_acc selection-criterion comparison it settled.

**Side effect worth noting in any writeup**: deduplication shifted the class
balance (`known_species` 42.4% → 33.5%, `possible_novelty` 42.2% → 48.9%),
because duplicates were concentrated in well-characterised species — exactly
the organisms most often deposited repeatedly in reference databases. The
pre-dedup class distribution was itself an artefact of database redundancy,
not of the underlying biology.

### Why is the eval loss computed by weight-sum rather than example count?

`nn.CrossEntropyLoss(weight=...)` with the default `reduction="mean"`
divides by the **sum of the batch's class weights**, not by the batch size.
The original `run_eval` accumulated `loss.item() * batch_size` and divided by
N, mixing two different denominators — verified concretely: for one batch,
PyTorch returned 2.013 (= weighted sum / weight sum) while the code's implied
formula gives 3.636 (= weighted sum / batch size). The resulting `dev_loss`
drifted with each batch's class composition.

This mattered more than a cosmetic metric error, because `dev_loss` is what
selects the saved checkpoint — a distorted value can select the wrong epoch,
which is directly relevant to the observed case where the highest-`dev_acc`
epoch (7, 86.7%) was passed over in favour of epoch 3. Fixed by accumulating
the true weighted sum and dividing by total weight.

### Training uses max_length=256, inference uses 512 — does that train/serve skew matter?

Empirically tested rather than assumed, since the two paths genuinely
disagree (`finetune.py --max-length 256` vs `predictor.py`'s
`tokenize_dna(..., max_length=512)`):

| Subset | acc @256 (train-matched) | acc @512 (production) | delta |
|---|---|---|---|
| sequences ≤256 tokens (n=1108) | 0.8330 | 0.8330 | **+0.0000** |
| sequences >256 tokens (n=92) | 0.8478 | 0.8587 | **+0.0109** |

For sequences within the training window the results are **bit-identical** —
attention masking fully neutralises the extra padding, so the longer window
costs only wasted compute, not accuracy. For sequences *exceeding* it, the
512 window is actually **better**, because it stops truncating real signal.
Conclusion: a real inconsistency, but benign-to-beneficial in the serving
direction, so it was deliberately left alone rather than "fixed" into
truncating more. The more interesting implication is the reverse one —
**7.7% of sequences are truncated during training** at 256 tokens (NT's
6-mer tokeniser gives median 233 / p90 255 / max 437 tokens on this data),
so raising the *training* window is a plausible future accuracy lever,
bounded by the O(n²) attention memory cost on an 8GB card.

Note also that the code comment justifying `--max-length 256` cites
empirical token lengths measured with **DNABERT-2's BPE tokeniser**
(median ~133, p90 ~241), which do not transfer to NT's 6-mer tokeniser. The
value happens to remain defensible for NT; the stated reasoning does not.

### How does the system analyze a DNA sequence end to end?

1. **Parse** (`fastx_parser.py`) — raw FASTA/FASTQ text → structured
   records; computes GC ratio, N-ratio, invalid-character flags, SHA256.
   Pure text processing, no biology yet.
2. **Quality gate** — sequences failing basic thresholds (too short, too
   many ambiguous bases) are stamped `low_quality` and skipped from
   everything downstream.
3. **Heuristic routing** — marker-gene matching + biophysical scoring (see
   §1) assigns a route and a confidence tier (high/medium/low).
4. **Neural classification** — tokenize (DNABERT-2 BPE) → transformer
   forward pass → extract the `[CLS]` token's 768-dim embedding (first
   token of the last hidden state) → route-specific linear head → softmax
   over that route's label set.
5. **Novelty/contamination scoring** — weighted-sum formula over the neural
   output plus embedding-space signals.
6. **Report assembly** (`reports/builder.py`) — aggregates into the
   structured report (QC summary, route distribution, Shannon diversity
   index, novelty table, contamination warnings, review status).

### Why build the reference training data from many small sources instead of one big one?

Each source covers a different, mostly non-overlapping slice of the problem:
BOLD (curated COI/rbcL/matK barcodes, strong species-level ID), SILVA (16S/
18S/28S rRNA, strongest for bacteria/archaea), MIDORI2 (mitochondrial genes,
broad eukaryote coverage with real NCBI taxids per record), UNITE (fungal
ITS), NCBI's `env_nt` (real uncultured/environmental sequences — the closest
direct match to genuine eDNA reads, used specifically as the `possible_novelty`
signal since it's real unresolved data, not a synthetic proxy), plus GRCh38/
UniVec for the human/contamination route. No single source has clean,
abundant coverage of all 6 routes' full label sets.

### Why does checkpoint selection use dev_loss instead of dev_acc, and is that actually the right call?

(2026-08-05.) `finetune.py` selects the "best" epoch via `if dev_loss <
best_dev_loss`, not by highest `dev_acc` — inherited unchanged from the
original DNABERT-2 script used across all 5 other routes, where it never
mattered enough to question. The NT-500M full run made the gap concrete:
epoch 3 had the lowest dev_loss (0.385) and got saved/tested; epoch 7 had
higher raw dev_acc (86.7% vs epoch 3's 86.4%) but much worse dev_loss
(0.765) and was never saved at all.

The reasoning for preferring loss: it's a richer signal than accuracy —
accuracy is binary right/wrong per example, while loss captures *how
confidently* right or wrong, so it's generally a more statistically stable
generalization proxy on a dev set this size (4,729 examples), where a
fraction of a point of accuracy can just be noise from a handful of
examples flipping. Epoch 7's much higher loss despite similar accuracy
suggests it was making more confidently-wrong predictions elsewhere even
while narrowly matching epoch 3 on raw hit-rate for that one snapshot.

**The real gap**: this can't actually be verified either way with the
current setup. Because only the loss-criterion "best" epoch ever gets
saved, epoch 7's weights are simply gone — there's no way to go back and
test whether accuracy-based selection would have scored higher or lower on
the real held-out test set. The selection criterion is committed to
up-front with no way to compare against the alternative after the fact.
**Fix identified, not yet built**: save a best-by-loss *and* a
best-by-accuracy checkpoint separately (not replacing either), so a future
run can directly test both against the real test set instead of assuming
one criterion is right.

### Retrospective: was the NT-500M attempt actually worth the time it took?

(2026-08-05.) Honest accounting, not just "it was a long day." Final
result: NT-500M's full 8-epoch run scored 84.88% test accuracy, beating
DNABERT-2's best (84.56%) by **+0.32 points** — for ~4.3× the parameters
(500M vs 117M), real added engineering cost, and roughly 6-7× longer
training time. Breaking down where the elapsed time actually went, not
just the training itself:

- **Necessary infrastructure debugging** (silent wrong-architecture model
  load via `AutoModel` vs `AutoModelForMaskedLM`, an `optimizer.step()` OOM
  needing 8-bit AdamW, a worker-pileup bug causing a real "paging file too
  small" crash, and the checkpoint-durability fix it exposed) — real,
  unavoidable for *any* NT-500M attempt on this hardware, and the fixes
  carry forward to future runs regardless of this route's outcome.
- **GPU overclock exploration** — opportunistic, not accuracy-motivated,
  and it directly caused one of the crashes (an untested-for-backward-pass
  overclock crashing `loss.backward()` mid-run) while delivering no
  measured throughput benefit worth the risk (see §2's OC/VRAM entries).
- **Pagefile debugging** — a real rabbit hole that never fully resolved
  (E:'s pagefile never activated despite correct configuration and two
  reboots). In hindsight, lower value than it seemed at the time: the
  actual root cause of the crash (worker pileup) was already fixed in code
  *before* most of this detour started, making the pagefile chase mostly
  redundant safety margin on an already-fixed problem.
- **Malware scan** — a legitimate one-off check once a real (blocked,
  never-executed) threat surfaced in Defender's history, unrelated to the
  actual modeling work.
- **The training run itself** — ~6.4 hours of real GPU compute, the
  genuine cost of the modeling attempt.

**Conclusion, stated plainly for the record**: a meaningful share of the
total elapsed time was side-quests that didn't move the accuracy number,
not the model genuinely requiring that long to earn +0.32 points. The
infrastructure fixes were worth it (durable, reusable); the OC and
pagefile detours were lower-value in retrospect and should be treated as
optional/separate from the core modeling work next time, not entangled
with a live, time-sensitive training run.

---

## 4. Decision log

Open decisions and the reasoning behind them at the time — updated with the
actual result once measured, so the reasoning is checkable against what
really happened, not just the prediction.

### Decision: try DNABERT-S before Nucleotide Transformer 500M/2.5B for `bacteria_pathogen`

**Status (as of this entry): decided, not yet run.**

Context: four attempts on `bacteria_pathogen` (baseline, more data, class
weighting, relabeled heuristic) all landed in the 80-85% range, best
84.56%, short of the 90% target — see §2's class-weighting and
label-definition entries. `known_species` vs `likely_taxonomic_group`
looks like a genuinely hard, close decision boundary rather than a fixable
bug.

**Options considered**:

- **Nucleotide Transformer 2.5B** — rejected. Can't be fully fine-tuned on
  an 8GB GPU (optimizer state alone ≈30GB in fp32); would need a frozen
  backbone, and a frozen bigger model can underperform a smaller *fully*
  fine-tuned one. More theoretical capacity doesn't help if hardware forces
  a worse training regime to use it.
- **Nucleotide Transformer 500M** — feasible (full fine-tuning fits, tightly)
  but its pretraining objective is generic masked-language-modeling across
  species, with no specific mechanism aimed at separating closely related
  species from each other. Real engineering risk too: new tokenizer family
  (6-mer, not BPE), untested dependency combination — DNABERT-2 needed 4
  rounds of real fixes before it worked, no reason to assume a clean first
  run here.
- **DNABERT-S** (chosen) — same 117M size already proven to run cleanly on
  this hardware (known-working batch size, no new tokenizer/memory tuning),
  and — the actual reason, not just cost — it was pretrained with a
  **species-aware contrastive objective specifically designed to push
  genetically similar-but-different species apart in embedding space**.
  That is mechanistically the exact problem `known_species` vs
  `likely_taxonomic_group` is testing. It's not a bigger hammer, it's a
  differently-shaped one aimed at this specific failure mode.

**Prediction**: higher probability of improvement than NT-500M, for lower
engineering cost and lower risk, precisely because the intervention targets
the diagnosed failure mode rather than just adding generic capacity. If
DNABERT-S doesn't move the needle, NT-500M becomes better justified as a
next experiment (a genuinely different mechanism), rather than a first move.

**Actual result**: **Ruled out, never got to a training run — a Windows
toolchain dead end, not a modeling result.** DNABERT-S's attention
implementation *hard-requires* Triton at import time (unlike DNABERT-2,
which falls back to plain PyTorch attention when Triton is unavailable).
Triton has no official Windows build at all (`pip install triton` simply
has no matching wheel); the community `triton-windows` package installs
fine, but the actual forward pass then tries to JIT-compile a Triton kernel
and fails with `RuntimeError: Failed to find C compiler` — Triton's JIT
needs a real C compiler on `PATH`/`CC`, which this machine doesn't have
without installing a full toolchain (MSVC Build Tools or similar). Judged
not worth that setup cost given the standing instruction that model choice
is irrelevant, only clearing 85% is — pivoted straight to Nucleotide
Transformer 500M instead (see next entry).

### Decision: proceed with Nucleotide Transformer 500M after DNABERT-S was ruled out

**Status (2026-08-05): complete — full 8-epoch run finished.**

With DNABERT-S ruled out on toolchain grounds (not a modeling result — it
never actually ran), NT-500M is the next real option per the original
comparison in this file's decision log: feasible to fully fine-tune on 8GB
(tightly — see §2's OOM entry for exactly how tightly), same "more generic
capacity, no failure-mode-specific mechanism" tradeoff already noted when
NT-500M was first considered. Required two real bug fixes before a smoke
test could even complete cleanly — a silent wrong-architecture load (auto_map
missing `AutoModel`) and an OOM in `optimizer.step()` — both written up in
§2.

**Actual accuracy result**: **84.88% test accuracy, 0.8438 macro F1** — the
best real result across every attempt this project has run
(baseline DNABERT-2 80.06% → best DNABERT-2 config 84.56% → NT-500M 1-epoch
smoke test 84.18% → **NT-500M full 8-epoch run: 84.88%**), and still short
of the 85% target by 0.12 points. Best checkpoint was epoch 3 of 8
(dev_acc 86.36%, dev_loss 0.385) — epochs 4-8 all overfit progressively
worse (train_loss fell to 0.0038 by epoch 8 while dev_loss rose to 0.786),
confirming the checkpoint-select-by-dev-loss logic mattered here: the run
would have scored worse using epoch 8's weights outright. The ~1.5-point
gap between epoch 3's dev_acc (86.36%) and the final test_acc (84.88%) is a
real dev/test generalization gap, not a selection bug — a legitimate
signal that NT-500M's extra capacity over DNABERT-2 bought a real but
modest improvement (+0.32 points over DNABERT-2's best), not the
qualitative jump the species-aware-contrastive mechanism (DNABERT-S) was
predicted to offer if it had been testable. Reinforces the standing
hypothesis from §2: `known_species` vs `likely_taxonomic_group` may be a
genuinely hard, close boundary at this amplicon length regardless of
backbone size.

**Correction to the record (2026-08-05)**: the 84.88% above, and every
number in this document before it, was measured on leaky train/test splits
(see §3's leakage entry) — inflated by ~2.5 points from duplicate sequences
crossing splits. After fixing deduplication, the eval-loss weighting bug,
and adding weight_decay=0.05/lr=1e-5 to fight the overfitting documented
above, a fresh 8-epoch run on clean data produced two checkpoints (dual
selection-criterion tracking added specifically to settle whether
dev_loss-based selection was picking the right epoch — see §2):

| Checkpoint | Selected by | Test accuracy | Macro F1 |
|---|---|---|---|
| Epoch 2 of 8 | lowest dev_loss | 83.10% | 0.8347 |
| Epoch 6 of 8 | highest dev_acc | **83.64%** | 0.8287 |

**dev_acc-based selection won this time** (83.64% > 83.10%) — a real,
measured answer to the open methodology question, not an assumption either
way could have been argued from first principles. The honest gap to the 85%
target is now **1.36 points** (using the better checkpoint), not the 0.12
points the leaky number implied. This is worse news in absolute terms but
better epistemically: every number from here on is trustworthy, which
84.88% never was.

---

*This file grows automatically whenever a theoretical question like this is
asked in conversation — see the "how it's kept up to date" note in project
memory.*
