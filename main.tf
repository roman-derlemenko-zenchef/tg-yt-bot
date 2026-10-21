# One App Platform app with a single Functions component. Functions bill per
# GiB-second with 90,000 GiB-seconds free each month and no per-request or
# idle cost, so personal use stays at $0.

locals {
  app_name = "tg-yt-bot"
  # Must match the package and function names in functions/project.yml.
  webhook_url = "${digitalocean_app.bot.live_url}/api/tg/bot"
}

# Telegram sends this in the X-Telegram-Bot-Api-Secret-Token header of every
# webhook call; the function rejects calls without it. Telegram only allows
# letters, digits, "_" and "-".
resource "random_password" "webhook_secret" {
  length  = 48
  special = false
}

resource "digitalocean_app" "bot" {
  project_id = var.project_id

  spec {
    name   = local.app_name
    region = var.region

    function {
      name       = "bot"
      source_dir = "functions"

      github {
        repo           = var.github_repo
        branch         = var.github_branch
        deploy_on_push = true
      }

      # project.yml substitutes these at build time, so they are needed in
      # both phases.
      env {
        key   = "TELEGRAM_BOT_TOKEN"
        value = var.telegram_bot_token
        type  = "SECRET"
        scope = "RUN_AND_BUILD_TIME"
      }
      env {
        key   = "WEBHOOK_SECRET"
        value = random_password.webhook_secret.result
        type  = "SECRET"
        scope = "RUN_AND_BUILD_TIME"
      }
    }

    ingress {
      rule {
        component {
          name = "bot"
        }
        match {
          path {
            prefix = "/api"
          }
        }
      }
    }
  }
}

# Points the bot's webhook at the function. Re-runs when the URL, secret or
# token changes; removes the webhook again on destroy.
resource "terraform_data" "telegram_webhook" {
  triggers_replace = [local.webhook_url, random_password.webhook_secret.result, sha256(var.telegram_bot_token)]

  input = {
    token = var.telegram_bot_token
  }

  provisioner "local-exec" {
    command = <<-EOT
      curl -sS --fail-with-body "https://api.telegram.org/bot$TOKEN/setWebhook" \
        --data-urlencode "url=$URL" \
        --data-urlencode "secret_token=$SECRET" \
        --data-urlencode 'allowed_updates=["message"]' \
        --data-urlencode "drop_pending_updates=true"
    EOT
    environment = {
      TOKEN  = var.telegram_bot_token
      URL    = local.webhook_url
      SECRET = random_password.webhook_secret.result
    }
  }

  provisioner "local-exec" {
    when    = destroy
    command = "curl -sS --fail-with-body \"https://api.telegram.org/bot$TOKEN/deleteWebhook\""
    environment = {
      TOKEN = self.input.token
    }
  }
}
