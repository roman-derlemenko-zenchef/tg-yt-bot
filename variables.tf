variable "project_id" {
  description = "DigitalOcean project the app is assigned to."
  type        = string
  default     = "9a0395e2-1f89-45c4-a3b3-1e1a14a6c909"
}

variable "region" {
  description = "App Platform region slug."
  type        = string
  default     = "fra"
}

variable "github_repo" {
  description = "Public GitHub repository holding this folder, as \"owner/name\"."
  type        = string

  validation {
    condition     = can(regex("^[\\w.-]+/[\\w.-]+$", var.github_repo))
    error_message = "Use the form \"owner/name\"."
  }
}

variable "github_branch" {
  description = "Branch to deploy."
  type        = string
  default     = "main"
}

variable "telegram_bot_token" {
  description = "Token of the Telegram bot, from @BotFather."
  type        = string
  sensitive   = true
}
