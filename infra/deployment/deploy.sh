#!/usr/bin/env bash
# deploy.sh — Build, push, and deploy Synth Veda to Google Cloud Run.
#
# Usage:
#   ./infra/deployment/deploy.sh <project-id> [region] [--staging]
#
# Options:
#   --staging    Deploy to the staging Cloud Run services instead of production.
#   --no-frontend  Skip building/deploying the frontend container.
#
# Prerequisites:
#   gcloud auth login && gcloud auth configure-docker us-docker.pkg.dev
#   All secrets already created in Google Secret Manager.
#
# Image tags:
#   Images are tagged with the git commit SHA so every build is traceable and
#   rollback is a one-line gcloud command.

set -euo pipefail

# ── Parse arguments ───────────────────────────────────────────────────────────
PROJECT_ID="${1:?Usage: deploy.sh <project-id> [region] [--staging] [--no-frontend]}"
REGION="${2:-us-central1}"
ENVIRONMENT="production"
DEPLOY_FRONTEND=true

for arg in "$@"; do
  case "$arg" in
    --staging)      ENVIRONMENT="staging" ;;
    --no-frontend)  DEPLOY_FRONTEND=false ;;
  esac
done

# Git SHA tag — every build is uniquely identified and traceable.
IMAGE_TAG="$(git rev-parse --short HEAD)"
REGISTRY="us-docker.pkg.dev/${PROJECT_ID}/synthveda"
API_IMAGE="${REGISTRY}/api:${IMAGE_TAG}"
WORKER_IMAGE="${REGISTRY}/worker:${IMAGE_TAG}"
FRONTEND_IMAGE="${REGISTRY}/frontend:${IMAGE_TAG}"

API_SERVICE="synthveda-${ENVIRONMENT}-api"
WORKER_SERVICE="synthveda-${ENVIRONMENT}-worker"
FRONTEND_SERVICE="synthveda-${ENVIRONMENT}-frontend"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Synth Veda — Deploy to Google Cloud Run                 ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Project    : ${PROJECT_ID}"
echo "║  Region     : ${REGION}"
echo "║  Environment: ${ENVIRONMENT}"
echo "║  Image tag  : ${IMAGE_TAG}"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Confirm production deploy
if [[ "$ENVIRONMENT" == "production" ]]; then
  read -rp "  Deploying to PRODUCTION. Continue? [y/N] " CONFIRM
  [[ "$CONFIRM" == "y" || "$CONFIRM" == "Y" ]] || { echo "Aborted."; exit 0; }
fi

# ── Build and push images ─────────────────────────────────────────────────────

echo "▶ Building API image → ${API_IMAGE}"
docker build \
  --tag "${API_IMAGE}" \
  --tag "${REGISTRY}/api:${ENVIRONMENT}-latest" \
  --cache-from "${REGISTRY}/api:${ENVIRONMENT}-latest" \
  services/api/
docker push "${API_IMAGE}"
docker push "${REGISTRY}/api:${ENVIRONMENT}-latest"
echo "  ✓ API image pushed"

echo "▶ Building Worker image → ${WORKER_IMAGE}"
docker build \
  --tag "${WORKER_IMAGE}" \
  --tag "${REGISTRY}/worker:${ENVIRONMENT}-latest" \
  --cache-from "${REGISTRY}/worker:${ENVIRONMENT}-latest" \
  services/worker/
docker push "${WORKER_IMAGE}"
docker push "${REGISTRY}/worker:${ENVIRONMENT}-latest"
echo "  ✓ Worker image pushed"

if [[ "$DEPLOY_FRONTEND" == "true" ]]; then
  # Frontend requires API URL to embed at build time.
  # Get the current API URL from Cloud Run before building.
  API_URL="$(gcloud run services describe "${API_SERVICE}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --format='value(status.url)' 2>/dev/null || echo "")"

  echo "▶ Building Frontend image → ${FRONTEND_IMAGE} (API_URL=${API_URL:-not yet deployed})"
  docker build \
    --tag "${FRONTEND_IMAGE}" \
    --tag "${REGISTRY}/frontend:${ENVIRONMENT}-latest" \
    --cache-from "${REGISTRY}/frontend:${ENVIRONMENT}-latest" \
    --build-arg "VITE_API_URL=${API_URL}" \
    --build-arg "VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID:-}" \
    web_frontend/
  docker push "${FRONTEND_IMAGE}"
  docker push "${REGISTRY}/frontend:${ENVIRONMENT}-latest"
  echo "  ✓ Frontend image pushed"
fi

# ── Deploy to Cloud Run ───────────────────────────────────────────────────────

_deploy_service() {
  local service="$1"
  local image="$2"
  local yaml_template="$3"

  # Substitute IMAGE_TAG and YOUR_PROJECT_ID in the YAML
  local tmp_yaml
  tmp_yaml="$(mktemp)"
  sed \
    -e "s|IMAGE_TAG|${IMAGE_TAG}|g" \
    -e "s|YOUR_PROJECT_ID|${PROJECT_ID}|g" \
    -e "s|YOUR_REGION|${REGION}|g" \
    -e "s|synthveda-production-|synthveda-${ENVIRONMENT}-|g" \
    -e "s|name: synthveda-api|name: ${service}|" \
    -e "s|name: synthveda-worker|name: ${service}|" \
    -e "s|name: synthveda-frontend|name: ${service}|" \
    "$yaml_template" > "$tmp_yaml"

  gcloud run services replace "$tmp_yaml" \
    --region="${REGION}" \
    --project="${PROJECT_ID}"

  rm -f "$tmp_yaml"
}

echo "▶ Deploying API to Cloud Run (${REGION})"
_deploy_service "${API_SERVICE}" "${API_IMAGE}" "infra/deployment/cloud-run-api.yml"
echo "  ✓ API deployed"

echo "▶ Deploying Worker to Cloud Run (${REGION})"
_deploy_service "${WORKER_SERVICE}" "${WORKER_IMAGE}" "infra/deployment/cloud-run-worker.yml"
echo "  ✓ Worker deployed"

if [[ "$DEPLOY_FRONTEND" == "true" ]]; then
  echo "▶ Deploying Frontend to Cloud Run (${REGION})"
  _deploy_service "${FRONTEND_SERVICE}" "${FRONTEND_IMAGE}" "infra/deployment/cloud-run-frontend.yml"
  echo "  ✓ Frontend deployed"
fi

# ── Health check — wait for API to be healthy ─────────────────────────────────

API_URL="$(gcloud run services describe "${API_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --format='value(status.url)')"

echo ""
echo "▶ Waiting for API health check at ${API_URL}/health …"
MAX_RETRIES=20
RETRY=0
until curl -sf "${API_URL}/health" > /dev/null 2>&1; do
  RETRY=$((RETRY + 1))
  if [[ $RETRY -ge $MAX_RETRIES ]]; then
    echo "  ✗ API failed health check after ${MAX_RETRIES} attempts."
    echo "    Run: gcloud run services logs read ${API_SERVICE} --region=${REGION}"
    echo "    Rollback: gcloud run services update-traffic ${API_SERVICE} --to-revisions=PREV=100 --region=${REGION}"
    exit 1
  fi
  echo "    Attempt ${RETRY}/${MAX_RETRIES} — waiting 10s …"
  sleep 10
done
echo "  ✓ API is healthy"

# ── Print summary ─────────────────────────────────────────────────────────────

FRONTEND_URL=""
if [[ "$DEPLOY_FRONTEND" == "true" ]]; then
  FRONTEND_URL="$(gcloud run services describe "${FRONTEND_SERVICE}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --format='value(status.url)' 2>/dev/null || echo "(not deployed)")"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Deployment complete                                     ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Image tag  : ${IMAGE_TAG}"
echo "║  API        : ${API_URL}"
if [[ "$DEPLOY_FRONTEND" == "true" ]]; then
  echo "║  Frontend   : ${FRONTEND_URL}"
fi
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  To rollback:"
echo "║    gcloud run services update-traffic ${API_SERVICE} \\"
echo "║      --to-revisions=PREV=100 --region=${REGION}"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
