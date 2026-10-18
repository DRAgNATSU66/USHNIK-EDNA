-- B8: POST /models/register and POST /models/{id}/promote mirror into
-- model_versions and model_eval_metrics (services/api/app/models/router.py).
--
-- 1. "candidate" is the status a registered-but-not-promoted model has in
--    models/registry/*.json; the worker never serves it. Mirror it as-is.
-- 2. The registry reports test_accuracy and test_size for every model; the
--    original table had no column for either.

alter type model_status add value if not exists 'candidate' before 'experimental';

alter table model_eval_metrics
  add column if not exists accuracy     float,
  add column if not exists sample_count integer;
