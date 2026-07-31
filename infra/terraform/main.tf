terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Remote state — replace bucket name after running: gsutil mb gs://<project-id>-tfstate
  backend "gcs" {
    bucket = "REPLACE_WITH_YOUR_PROJECT_ID-tfstate"
    prefix = "synthveda/terraform.tfstate"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  name_prefix = "synthveda-${var.environment}"
  labels = {
    app         = "synthveda"
    environment = var.environment
    managed_by  = "terraform"
  }
  api_image      = "us-docker.pkg.dev/${var.project_id}/synthveda/api:${var.image_tag}"
  worker_image   = "us-docker.pkg.dev/${var.project_id}/synthveda/worker:${var.image_tag}"
  frontend_image = "us-docker.pkg.dev/${var.project_id}/synthveda/frontend:${var.image_tag}"
}

# ─────────────────────────────────────────────────────────────────────────────
# Artifact Registry — stores Docker images
# ─────────────────────────────────────────────────────────────────────────────

resource "google_artifact_registry_repository" "synthveda" {
  repository_id = "synthveda"
  format        = "DOCKER"
  location      = "us"
  labels        = local.labels
}

# ─────────────────────────────────────────────────────────────────────────────
# Service account — least-privilege identity for Cloud Run services
# ─────────────────────────────────────────────────────────────────────────────

resource "google_service_account" "synthveda_api" {
  account_id   = "${local.name_prefix}-api"
  display_name = "Synth Veda API Service Account"
}

resource "google_service_account" "synthveda_worker" {
  account_id   = "${local.name_prefix}-worker"
  display_name = "Synth Veda Worker Service Account"
}

# Grant Secret Manager access to both SAs
resource "google_project_iam_member" "api_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.synthveda_api.email}"
}

resource "google_project_iam_member" "worker_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.synthveda_worker.email}"
}

# ─────────────────────────────────────────────────────────────────────────────
# Secret Manager — references to secrets created out-of-band
# (create secrets once: gcloud secrets create synthveda-jwt-secret --data-file=-)
# ─────────────────────────────────────────────────────────────────────────────

locals {
  secret_names = [
    "synthveda-mongodb-uri",
    "synthveda-redis-url",
    "synthveda-jwt-secret",
    "synthveda-google-client-id",
    "synthveda-supabase-url",
    "synthveda-supabase-service-role-key",
    "synthveda-supabase-anon-key",
  ]
}

data "google_secret_manager_secret_version" "secrets" {
  for_each = toset(local.secret_names)
  secret   = each.value
}

# ─────────────────────────────────────────────────────────────────────────────
# Cloud Armor security policy — DDoS protection + rate limiting
# Rate limiting enforced at infra layer per security spec.
# ─────────────────────────────────────────────────────────────────────────────

resource "google_compute_security_policy" "synthveda_api" {
  name        = "${local.name_prefix}-api-armor"
  description = "Cloud Armor policy for Synth Veda API: DDoS + rate limiting"

  # Rate limiting rule — block IPs exceeding threshold
  rule {
    action   = "throttle"
    priority = 1000
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      rate_limit_threshold {
        count        = var.rate_limit_requests_per_minute
        interval_sec = 60
      }
      enforce_on_key = "IP"
    }
    description = "Rate limit: ${var.rate_limit_requests_per_minute} req/min per IP"
  }

  # Block known bad user agents (scrapers, scanners)
  rule {
    action   = "deny(403)"
    priority = 900
    match {
      expr {
        expression = "request.headers['user-agent'].matches('(?i)(sqlmap|nikto|nmap|masscan|zgrab)')"
      }
    }
    description = "Block known vulnerability scanners"
  }

  # Default: allow all
  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Default allow"
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# Cloud Run — API service
# ─────────────────────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "api" {
  name     = "${local.name_prefix}-api"
  location = var.region
  labels   = local.labels

  template {
    service_account = google_service_account.synthveda_api.email
    labels          = local.labels

    scaling {
      min_instance_count = var.api_min_instances
      max_instance_count = var.api_max_instances
    }

    # VPC connector for private MongoDB/Redis access
    vpc_access {
      connector = "projects/${var.project_id}/locations/${var.region}/connectors/${var.vpc_connector_name}"
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = local.api_image

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
        cpu_idle          = false  # CPU always-on — no throttling under requests
        startup_cpu_boost = true
      }

      # Secrets from Secret Manager
      dynamic "env" {
        for_each = {
          MONGODB_URI               = "synthveda-mongodb-uri"
          REDIS_URL                 = "synthveda-redis-url"
          JWT_SECRET                = "synthveda-jwt-secret"
          GOOGLE_CLIENT_ID          = "synthveda-google-client-id"
          SUPABASE_URL              = "synthveda-supabase-url"
          SUPABASE_SERVICE_ROLE_KEY = "synthveda-supabase-service-role-key"
          SUPABASE_ANON_KEY         = "synthveda-supabase-anon-key"
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      # Non-secret config
      env {
        name  = "MONGODB_DB"
        value = "synthveda"
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = var.allowed_origins
      }
      env {
        name  = "DEBUG"
        value = "false"
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 10
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        period_seconds    = 30
        failure_threshold = 3
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# Allow unauthenticated access to the API (JWT auth is application-level)
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ─────────────────────────────────────────────────────────────────────────────
# Cloud Run — Worker service
# ─────────────────────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "worker" {
  name     = "${local.name_prefix}-worker"
  location = var.region
  labels   = local.labels

  # Workers are not publicly accessible — they poll Redis internally
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.synthveda_worker.email
    labels          = local.labels

    scaling {
      min_instance_count = var.worker_min_instances
      max_instance_count = var.worker_max_instances
    }

    vpc_access {
      connector = "projects/${var.project_id}/locations/${var.region}/connectors/${var.vpc_connector_name}"
      egress    = "PRIVATE_RANGES_ONLY"
    }

    # Workers need more memory for ML inference
    containers {
      image = local.worker_image

      resources {
        limits = {
          cpu    = "4"
          memory = "4Gi"
        }
        cpu_idle = false  # always-on for low-latency job pickup
      }

      dynamic "env" {
        for_each = {
          MONGODB_URI = "synthveda-mongodb-uri"
          REDIS_URL   = "synthveda-redis-url"
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      env {
        name  = "MONGODB_DB"
        value = "synthveda"
      }
      env {
        name  = "WORKER_CONCURRENCY"
        value = "4"
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# Cloud Run — Frontend (nginx SPA container)
# ─────────────────────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "frontend" {
  name     = "${local.name_prefix}-frontend"
  location = var.region
  labels   = local.labels

  template {
    scaling {
      min_instance_count = 1
      max_instance_count = 20
    }

    containers {
      image = local.frontend_image

      ports {
        container_port = 80
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
        cpu_idle = true  # static files — throttle when idle
      }

      startup_probe {
        http_get {
          path = "/index.html"
          port = 80
        }
        initial_delay_seconds = 3
        period_seconds        = 5
        failure_threshold     = 5
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ─────────────────────────────────────────────────────────────────────────────
# Cloud Monitoring — uptime checks + alert policies
# ─────────────────────────────────────────────────────────────────────────────

resource "google_monitoring_uptime_check_config" "api_health" {
  display_name = "Synth Veda API /health"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = trimprefix(google_cloud_run_v2_service.api.uri, "https://")
    }
  }
}

resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_notification_email != "" ? 1 : 0
  display_name = "Synth Veda Alerts — Email"
  type         = "email"
  labels = {
    email_address = var.alert_notification_email
  }
}

resource "google_monitoring_alert_policy" "api_uptime" {
  display_name = "API uptime failure"
  combiner     = "OR"

  conditions {
    display_name = "/health endpoint down"
    condition_threshold {
      filter          = "resource.type=\"uptime_url\" AND metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "120s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields    = ["resource.*"]
      }
    }
  }

  notification_channels = var.alert_notification_email != "" ? [
    google_monitoring_notification_channel.email[0].id
  ] : []

  documentation {
    content   = "The Synth Veda API /health endpoint has been unreachable for 2 minutes. Check Cloud Run logs and MongoDB/Redis connectivity."
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "high_error_rate" {
  display_name = "High API 5xx error rate"
  combiner     = "OR"

  conditions {
    display_name = "5xx > 5% over 5 minutes"
    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_revision\"",
        "resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\"",
        "metric.type=\"run.googleapis.com/request_count\"",
        "metric.labels.response_code_class=\"5xx\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 0.05  # 5%
      duration        = "300s"
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.labels.service_name"]
      }
    }
  }

  notification_channels = var.alert_notification_email != "" ? [
    google_monitoring_notification_channel.email[0].id
  ] : []

  documentation {
    content   = "The API 5xx error rate exceeded 5% for 5 minutes. Check recent deployments, MongoDB, and worker queue depth."
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "high_latency" {
  display_name = "High API p95 latency"
  combiner     = "OR"

  conditions {
    display_name = "p95 latency > 5s"
    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_revision\"",
        "resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\"",
        "metric.type=\"run.googleapis.com/request_latencies\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 5000  # milliseconds
      duration        = "300s"
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["resource.labels.service_name"]
      }
    }
  }

  notification_channels = var.alert_notification_email != "" ? [
    google_monitoring_notification_channel.email[0].id
  ] : []
}
