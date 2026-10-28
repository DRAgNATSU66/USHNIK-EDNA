-- B9: the API now writes review_evidence, curation_decisions and
-- training_batch_items (services/api/app/reviews/records.py), mirroring the
-- MongoDB collections of the same names. Three columns of the original schema
-- (20260526000001) cannot hold what those writes carry:
--
-- 1. expert_reviews.submitted_by: reviews auto-queued by the worker for a
--    novelty/contamination flag have submitted_by "system" in MongoDB, which
--    has no user_profiles row. Null means "auto-queued by the pipeline".
-- 2. review_evidence: the analysis result a review is about is stored as
--    evidence (type 'result_snapshot', the result as jsonb in `payload`,
--    including the orchestrator's decision/decision_trace when present).
-- 3. training_batch_items.split: assembly assigns no split;
--    scripts/training/train.py draws its train/val split at training time.
--    Null means "not assigned"; the check still limits non-null values.

alter table expert_reviews alter column submitted_by drop not null;

alter table review_evidence drop constraint if exists review_evidence_evidence_type_check;
alter table review_evidence
  add constraint review_evidence_evidence_type_check
  check (evidence_type in ('file', 'reference', 'url', 'text', 'result_snapshot'));
alter table review_evidence add column if not exists payload jsonb;

alter table training_batch_items alter column split drop not null;
