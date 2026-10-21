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
  description = "GitHub repository holding this folder, as \"owner/name\". DigitalOcean's GitHub app must have access to it."
  type        = string

  validation {
    condition     = can(regex("^[\\w.-]+/[\\w.-]+$", var.github_repo))
    error_message = "Use the form \"owner/name\"."
  }
}

variable "github_branch" {
  description = "Branch to deploy. Every push to it redeploys the function."
  type        = string
  default     = "main"
}

variable "telegram_bot_token" {
  description = "Token of the Telegram bot, from @BotFather."
  type        = string
  sensitive   = true
}
