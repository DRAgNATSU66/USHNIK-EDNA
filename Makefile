# Synth Veda — common dev commands
# Usage: make <target>
# Requires: Docker, Python 3.11+, cargo (Phase 5+)
# For deploy targets: gcloud CLI, Docker logged in to Artifact Registry.

COMPOSE     = docker compose -f infra/docker/docker-compose.yml
API_DIR     = services/api
WORKER_DIR  = services/worker
PYTHON      = python
PROJECT_ID ?= YOUR_PROJECT_ID
REGION     ?= us-central1

# -------------------------------------------------------------------------
# Docker stack
# -------------------------------------------------------------------------
.PHONY: up down logs ps

up:
	$(COMPOSE) up --build -d
	@echo "API:    http://localhost:8000/docs"
	@echo "Mongo:  mongodb://localhost:27017"
	@echo "Redis:  redis://localhost:6379"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

# -------------------------------------------------------------------------
# API dev (without Docker)
# -------------------------------------------------------------------------
.PHONY: api-install api-run api-test api-test-cov

api-install:
	cd $(API_DIR) && pip install -r requirements-dev.txt

api-run:
	cd $(API_DIR) && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

api-test:
	cd $(API_DIR) && python -m pytest tests/ -v

api-test-cov:
	cd $(API_DIR) && python -m pytest tests/ --cov=app --cov-report=term-missing

# -------------------------------------------------------------------------
# Worker dev (without Docker)
# -------------------------------------------------------------------------
.PHONY: worker-install worker-run worker-test

worker-install:
	cd $(WORKER_DIR) && pip install -r requirements-dev.txt

worker-run:
	cd $(WORKER_DIR) && python -m app.dispatcher

worker-test:
	cd $(WORKER_DIR) && python -m pytest tests/ -v

# -------------------------------------------------------------------------
# Seed / database
# -------------------------------------------------------------------------
.PHONY: seed-dev

seed-dev:
	$(PYTHON) scripts/seed_dev.py

# -------------------------------------------------------------------------
# Model training (Phase 14) — requires training virtualenv
# Set BATCH_ID, ROUTE, and RUN_ID before calling these targets.
# Example:
#   make train-export BATCH_ID=tbatch_202606_fish_abc ROUTE=fish RUN_ID=dnabert2_fish_v2
# -------------------------------------------------------------------------
.PHONY: train-install train-export train-run train-eval train-promote train-pipeline

BATCH_ID   ?= tbatch_YYYYMM_route_id
ROUTE      ?= fish
RUN_ID     ?= dnabert2_$(ROUTE)_vX
BATCH_DIR  ?= data/batches/$(BATCH_ID)
EPOCHS     ?= 3
BATCH_SIZE ?= 8

train-install:
	pip install -r scripts/training/requirements.txt

train-export:
	$(PYTHON) scripts/training/export_batch.py \
		--batch-id $(BATCH_ID) \
		--out-dir  $(BATCH_DIR)

train-run:
	$(PYTHON) scripts/training/train.py \
		--route      $(ROUTE) \
		--batch-dir  $(BATCH_DIR) \
		--run-id     $(RUN_ID) \
		--epochs     $(EPOCHS) \
		--batch-size $(BATCH_SIZE)

train-eval:
	$(PYTHON) scripts/training/evaluate.py \
		--run-id    $(RUN_ID) \
		--batch-dir $(BATCH_DIR)

train-promote:
	$(PYTHON) scripts/training/promote.py \
		--run-id $(RUN_ID) \
		--approve

# Runs the full pipeline interactively (asks for human sign-off before promote)
train-pipeline:
	bash scripts/training/monthly_release.sh \
		--batch-id   $(BATCH_ID) \
		--route      $(ROUTE) \
		--run-id     $(RUN_ID) \
		--epochs     $(EPOCHS) \
		--batch-size $(BATCH_SIZE)

# -------------------------------------------------------------------------
# Rust parser (Phase 5)
# -------------------------------------------------------------------------
.PHONY: parser-build parser-test parser-bench

parser-build:
	cd packages/fastx_parser && cargo build --release

parser-test:
	cd packages/fastx_parser && cargo test

parser-bench:
	cd packages/fastx_parser && cargo bench

# -------------------------------------------------------------------------
# Supabase
# -------------------------------------------------------------------------
.PHONY: db-push db-reset

db-push:
	supabase db push

db-reset:
	supabase db reset

# -------------------------------------------------------------------------
# Frontend (without Docker)
# -------------------------------------------------------------------------
.PHONY: frontend-install frontend-dev frontend-build

frontend-install:
	cd web_frontend && npm install

frontend-dev:
	cd web_frontend && npm run dev

frontend-build:
	cd web_frontend && npm run build

# -------------------------------------------------------------------------
# Security
# -------------------------------------------------------------------------
.PHONY: security-scan

security-scan:
	@echo "=== Scanning services/api/app ==="
	bandit -r $(API_DIR)/app -ll --quiet
	@echo "=== Scanning services/worker/app ==="
	bandit -r $(WORKER_DIR)/app -ll --quiet
	@echo "=== Checking for committed .env files ==="
	@if git ls-files | grep -E '(^|/)\.env$$' | grep -v '\.env\.example'; then \
		echo "ERROR: .env file tracked in git"; exit 1; \
	fi
	@echo "Security scan complete."

# -------------------------------------------------------------------------
# Scale testing (Phase 15) — docker-compose horizontal scale
# -------------------------------------------------------------------------
.PHONY: up-scale down-scale

up-scale:
	$(COMPOSE) -f infra/docker/docker-compose.scale.yml \
		up --build --scale worker=4 --scale api=2 -d
	@echo "Load balancer: http://localhost:8080"
	@echo "Workers: 4  |  API instances: 2"

down-scale:
	$(COMPOSE) -f infra/docker/docker-compose.scale.yml down

# -------------------------------------------------------------------------
# Terraform IaC (Phase 15)
# -------------------------------------------------------------------------
.PHONY: infra-init infra-plan infra-apply infra-destroy

TERRAFORM_DIR = infra/terraform

infra-init:
	cd $(TERRAFORM_DIR) && terraform init

infra-plan:
	cd $(TERRAFORM_DIR) && terraform plan \
		-var="project_id=$(PROJECT_ID)" \
		-var="region=$(REGION)" \
		-var="image_tag=$(shell git rev-parse --short HEAD)"

infra-apply:
	cd $(TERRAFORM_DIR) && terraform apply \
		-var="project_id=$(PROJECT_ID)" \
		-var="region=$(REGION)" \
		-var="image_tag=$(shell git rev-parse --short HEAD)"

infra-destroy:
	@echo "WARNING: This will destroy all managed GCP resources."
	@read -p "Type 'destroy' to confirm: " c; [ "$$c" = "destroy" ] || exit 1
	cd $(TERRAFORM_DIR) && terraform destroy \
		-var="project_id=$(PROJECT_ID)" \
		-var="region=$(REGION)" \
		-var="image_tag=$(shell git rev-parse --short HEAD)"

# -------------------------------------------------------------------------
# Deploy to Cloud Run (Phase 15)
# -------------------------------------------------------------------------
.PHONY: deploy-staging deploy-prod

deploy-staging:
	bash infra/deployment/deploy.sh $(PROJECT_ID) $(REGION) --staging

deploy-prod:
	bash infra/deployment/deploy.sh $(PROJECT_ID) $(REGION)

# -------------------------------------------------------------------------
# Cleanup
# -------------------------------------------------------------------------
.PHONY: clean

clean:
	$(COMPOSE) down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
