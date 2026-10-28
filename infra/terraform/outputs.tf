output "api_url" {
  description = "Public URL of the Cloud Run API service"
  value       = google_cloud_run_v2_service.api.uri
}

output "frontend_url" {
  description = "Public URL of the Cloud Run frontend service"
  value       = google_cloud_run_v2_service.frontend.uri
}

output "worker_name" {
  description = "Cloud Run service name for the worker (internal only)"
  value       = google_cloud_run_v2_service.worker.name
}

output "artifact_registry_url" {
  description = "Artifact Registry URL for pushing Docker images"
  value       = "us-docker.pkg.dev/${var.project_id}/synthveda"
}

output "api_service_account" {
  description = "Service account email for the API Cloud Run service"
  value       = google_service_account.synthveda_api.email
}

output "worker_service_account" {
  description = "Service account email for the worker Cloud Run service"
  value       = google_service_account.synthveda_worker.email
}

output "cloud_armor_policy" {
  description = "Cloud Armor security policy name (attach to Load Balancer backend)"
  value       = google_compute_security_policy.synthveda_api.name
}
