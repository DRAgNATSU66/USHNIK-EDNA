variable "project_id" {
  description = "Google Cloud project ID"
  type        = string
}

variable "region" {
  description = "Primary GCP region for Cloud Run services"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment: staging or production"
  type        = string
  default     = "production"

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production"
  }
}

variable "image_tag" {
  description = "Docker image tag (git SHA). Passed at deploy time."
  type        = string
}

variable "api_min_instances" {
  description = "Minimum Cloud Run instances for the API (0 = cold starts allowed)"
  type        = number
  default     = 1
}

variable "api_max_instances" {
  description = "Maximum Cloud Run instances for the API"
  type        = number
  default     = 50
}

variable "worker_min_instances" {
  description = "Minimum always-on worker instances"
  type        = number
  default     = 2
}

variable "worker_max_instances" {
  description = "Maximum worker instances"
  type        = number
  default     = 20
}

variable "allowed_origins" {
  description = "Comma-separated list of allowed CORS origins"
  type        = string
  default     = ""
}

variable "rate_limit_requests_per_minute" {
  description = "Cloud Armor rate limit: max requests per minute per IP"
  type        = number
  default     = 300
}

variable "alert_notification_email" {
  description = "Email address for Cloud Monitoring alert notifications"
  type        = string
  default     = ""
}

variable "vpc_connector_name" {
  description = "Serverless VPC Access connector name (for private MongoDB/Redis)"
  type        = string
  default     = "synthveda-vpc-connector"
}
